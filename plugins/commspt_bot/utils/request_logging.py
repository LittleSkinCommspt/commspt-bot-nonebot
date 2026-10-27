"""请求日志（排障用）：把外部服务调用失败按天追加写入文本文件

设计约束：
- 只追加：append 模式 + UTF-8 严格编解码，不覆盖 / 删除 / 轮转 / 改名；每日一个文件
  ``<directory>/YYYY-MM-DD.log``（北京时间）。
- 关闭（``request_logging.enabled=false``）时不建目录、不写任何字节。
- 进程内锁保证整条记录一次写入；**所有日志诊断路径 fail-safe**：格式化 / 脱敏 / 读取事件
  属性 / 写文件任一环节抛错都只打控制台告警，绝不替换或掩盖原业务异常。
- 全字段脱敏，不记录响应体 / 请求头 / Pydantic 原始输入；动态文本转义换行防伪造。

记录格式（单行，`` | `` 分隔）::

    2026-01-02 03:04:05.678 +08:00 | [失败] | 服务=飞书 API | 方法=POST | 尝试=3/3
        | 地址=https://... | 状态=500 | 原因=HTTP 500 响应错误 | 详情=...
        | 操作者=昵称 | QQ=10001 | 角色=管理员 | 群=123456 | 命令=&uid [CQ:at,qq=123]

公共接口：
- external_request: 网络调用作用域；``scope.response`` / ``scope.address`` 可变，
  ``scope.report_failure(exc)`` 可在业务继续执行时登记一次失败
- retry_log_scope: 重试尝试作用域；``mark_final(exc)`` 由重试层在最终失败时落盘一次
- write_startup_marker / register_startup_hook: 启动标记
- redact_text / redact_url: 脱敏工具
"""

from __future__ import annotations

import dataclasses
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, unquote_plus, urlsplit, urlunsplit

import httpx
import pytz
from nonebot import logger
from nonebot.matcher import current_event
from pydantic import ValidationError

from plugins.commspt_bot import config as app_config

_TIMEZONE = pytz.timezone("Asia/Shanghai")

_LOG_PREFIX = "[请求日志]"

_WRITE_LOCK = threading.Lock()
"""进程内写锁：保证整条记录一次性写入，不被并发写入打断。"""

_META_ATTR = "__commspt_request_log_failure__"
"""异常上的失败元数据（值为 ``(recorder, _Failure)``，按逻辑操作隔离）。"""

_WRITTEN_ATTR = "__commspt_request_log_written__"
"""已落盘标记（值为写下记录的 ``_Recorder``，避免复用异常对象时误抑制）。"""

_MAX_SERVICE = 120
_MAX_ADDRESS = 500
_MAX_DETAIL = 300
_MAX_COMMAND = 200
_MAX_NAME = 64

_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^\s\"'<>`]+")
_KV_RE = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z0-9_.\-]{0,40})[\"']?(?P<sep>\s*[=:]\s*)"
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^\s,;&\"')\]}]+)",
)
_BEARER_RE = re.compile(r"(?P<scheme>Bearer|Basic|Token)\s+(?P<value>[A-Za-z0-9._~+/=\-]{3,})", re.IGNORECASE)
_HEADER_RE = re.compile(r"\b(?P<name>cookie|authorization)\s*[:=]\s*[^\r\n]+", re.IGNORECASE)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x85\u2028\u2029]")

_TRAILING_PUNCTUATION = ".,;:)]}\"'"

_SENSITIVE_NAMES = frozenset(
    {
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "tenant_access_token",
        "app_token",
        "app_secret",
        "client_secret",
        "secret",
        "password",
        "passwd",
        "pwd",
        "sign",
        "sig",
        "signature",
        "hmac",
        "key",
        "apikey",
        "api_key",
        "access_key",
        "secret_key",
        "private_key",
        "credential",
        "credentials",
        "authorization",
        "auth",
        "cookie",
        "session",
        "session_id",
        "code_verifier",
    }
)
_SENSITIVE_SUFFIXES = (
    "token",
    "secret",
    "password",
    "passwd",
    "pwd",
    "signature",
    "apikey",
    "credential",
    "authorization",
    "cookie",
)

_FEISHU_HOSTS = ("feishu.cn", "larksuite.com", "feishu.net")

# 需要剥离 URL 中 userinfo 密码的配置端点
_ENDPOINT_ATTRS = (
    "api_skinrendermc",
    "api_mihari_svg",
    "api_browserless",
    "api_bingling_ipip",
    "api_littleskin_origin",
    "api_cloudconfig",
)

# 异常类名 -> 只记录 code / 安全提示（消息体可能来自响应文本，不能整段落盘）
_CODE_ONLY_ERRORS = frozenset({"FeishuAPIError"})


# MARK: 脱敏


def _is_sensitive_name(name: str) -> bool:
    """判断键名是否属于需要脱敏的敏感字段（token / 签名 / 密码等）。"""
    normalized = name.strip().lower().replace("-", "_")
    if not normalized:
        return False
    return normalized in _SENSITIVE_NAMES or normalized.endswith(_SENSITIVE_SUFFIXES)


def _userinfo_password(endpoint: str) -> str:
    """取 URL userinfo 中的密码（没有则空串）。"""
    text = (endpoint or "").strip()
    if "://" not in text or "@" not in text:
        return ""
    try:
        netloc = urlsplit(text).netloc
    except ValueError:
        return ""
    if "@" not in netloc:
        return ""
    userinfo = netloc.rsplit("@", 1)[0]
    return userinfo.split(":", 1)[1] if ":" in userinfo else ""


def _configured_secret_values(minimum: int = 1) -> list[str]:
    """配置里的秘密值（含 URL 编码形式），按长度降序，便于长值优先替换。

    短秘密在替换时使用单词边界，以免破坏主机名等普通词片段。
    整串连接串不进替换表——它由 URL 结构化脱敏处理，否则会把 Mongo 主机一并抹掉。
    """
    values: list[str] = []

    def _add(value: Any, floor: int = minimum) -> None:
        if isinstance(value, str):
            stripped = value.strip()
            if len(stripped) >= floor:
                values.append(stripped)

    settings = app_config.S_
    _add(settings.littleskin_admin_token)
    _add(settings.api_feishu.app_id)
    _add(settings.api_feishu.app_secret)
    _add(settings.api_cloudconfig.password)
    _add(settings.feishu_ban.app_token)
    for attr in _ENDPOINT_ATTRS:
        endpoint = _safe_getattr(_safe_getattr(settings, attr), "endpoint", "")
        _add(_userinfo_password(endpoint))
        try:
            parts = urlsplit(endpoint)
            for name, value in parse_qsl(parts.query) + parse_qsl(parts.fragment):
                if _is_sensitive_name(name):
                    _add(value)
        except ValueError:
            pass

    netloc = _safe_netloc(settings.db_mongo.url)
    if "@" in netloc:
        # 连接串凭证：整段 userinfo 及各分段单独加入（异常里常只带片段）
        userinfo = netloc.rsplit("@", 1)[0]
        _add(userinfo)
        for piece in userinfo.split(":", 1):
            _add(piece)

    expanded: list[str] = []
    for value in values:
        for decoded in (value, unquote(value)):
            expanded.extend((decoded, quote(decoded, safe=""), quote(decoded, safe="+/=")))
    return sorted(set(expanded), key=len, reverse=True)


def _safe_netloc(url: str) -> str:
    """安全读取 URL 的 netloc（解析失败返回空串）。"""
    text = (url or "").strip()
    if "://" not in text:
        return ""
    try:
        return urlsplit(text).netloc
    except ValueError:
        return ""


def _replace_secrets(text: str, minimum: int = 1) -> str:
    """把配置秘密值（含编码形式）替换为 ``***``。"""
    result = str(text)
    for secret in _configured_secret_values(minimum):
        if len(secret) < 4:
            result = re.sub(rf"(?<!\w){re.escape(secret)}(?!\w)", "***", result)
        else:
            result = result.replace(secret, "***")
    return result


def _redact_kv_match(match: re.Match[str]) -> str:
    """把 ``name=value`` / ``name: value`` 中的敏感值替换为 ``***``。"""
    if not _is_sensitive_name(match.group("name")):
        return match.group(0)
    return f"{match.group('name')}{match.group('sep')}***"


def _redact_query(query: str, depth: int = 0) -> str:
    """脱敏查询串 / OAuth fragment 中的敏感参数（按参数名）。"""
    if not query:
        return ""
    pairs: list[str] = []
    for pair in query.split("&"):
        if not pair:
            continue
        name, sep, value = pair.partition("=")
        if sep and _is_sensitive_name(unquote_plus(name)):
            pairs.append(f"{name}=***")
        elif sep and "://" in (decoded := unquote_plus(value)):
            # 渲染接口的 skinUrl / capeUrl 也可能带鉴权，不能只处理最外层参数。
            safe_value = redact_url(decoded, _depth=depth + 1) if depth < 3 else "***"
            pairs.append(f"{name}={quote(safe_value, safe='')}")
        else:
            pairs.append(pair)
    return "&".join(pairs)


def _redact_path_segments(host: str, path: str) -> str:
    """脱敏飞书多维表格路径里的 app_token（保留 table_id 便于排障）。"""
    if not any(host.endswith(feishu_host) for feishu_host in _FEISHU_HOSTS):
        return path
    return re.sub(r"(/apps/)[^/]+", r"\1***", re.sub(r"(/base/)[^/]+", r"\1***", path))


def redact_url(url: str, *, _depth: int = 0) -> str:
    """脱敏 URL：userinfo、敏感查询参数 / fragment、飞书 app_token 路径段、配置秘密值。

    结构化处理后再做一次配置秘密值替换，因此端点把 API Key 塞进路径或查询值、或秘密
    以 URL 编码形式出现时同样被脱敏；Mongo 连接串只抹凭据、保留主机便于排障。
    """
    text = str(url or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
    except ValueError:
        return _replace_secrets(text)
    if not parts.scheme:
        return _replace_secrets(text)

    netloc = parts.netloc
    if "@" in netloc:
        netloc = f"***@{netloc.rsplit('@', 1)[1]}"
    host = netloc.split("@")[-1].split(":")[0].lower()
    rebuilt = urlunsplit(
        (
            parts.scheme,
            netloc,
            _redact_path_segments(host, parts.path),
            _redact_query(parts.query, _depth),
            _redact_query(parts.fragment, _depth),
        )
    )
    return _replace_secrets(rebuilt)


def _redact_url_match(match: re.Match[str]) -> str:
    """脱敏文本中命中的 URL，并保留其后的标点。"""
    candidate = match.group(0)
    trailing = ""
    while candidate and candidate[-1] in _TRAILING_PUNCTUATION:
        trailing = candidate[-1] + trailing
        candidate = candidate[:-1]
    return f"{redact_url(candidate)}{trailing}"


def redact_text(text: str) -> str:
    """对任意动态文本做凭据脱敏（配置秘密 / URL / 键值 / Bearer）。"""
    if not text:
        return ""
    result = _HEADER_RE.sub(lambda match: f"{match.group('name')}=***", _replace_secrets(text))
    result = _URL_RE.sub(_redact_url_match, result)
    result = _KV_RE.sub(_redact_kv_match, result)
    return _BEARER_RE.sub(lambda match: f"{match.group('scheme')} ***", result)


def _escape_control(text: str) -> str:
    """转义换行等控制字符，避免动态文本伪造出额外的日志行。"""
    escaped = text.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
    return _CONTROL_RE.sub(lambda match: f"\\x{ord(match.group()):02x}", escaped)


def _sanitize(value: Any, limit: int = _MAX_DETAIL) -> str:
    """脱敏 + 转义控制字符 + 截断，供记录中的动态字段统一使用。"""
    text = _escape_control(redact_text(str(value or "")))
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _sanitize_address(value: Any) -> str:
    """地址字段：URL 走 URL 脱敏（含配置秘密值），其余按普通文本脱敏。

    地址用更低的秘密长度下限，避免短密码只出现在地址里时漏脱敏。
    """
    text = str(value or "").strip()
    if not text:
        return ""
    redacted = redact_url(text) if "://" in text else redact_text(text)
    escaped = _escape_control(redacted)
    return escaped if len(escaped) <= _MAX_ADDRESS else f"{escaped[: _MAX_ADDRESS - 3]}..."


# MARK: 时间


def _now() -> datetime:
    """当前北京时间（单独抽出便于测试注入固定时间）。"""
    return datetime.now(_TIMEZONE)


def _format_ts(moment: datetime) -> str:
    """格式化为 ``YYYY-MM-DD HH:mm:ss.SSS +08:00``。"""
    total_seconds = int((moment.utcoffset() or timedelta(0)).total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    hours, remainder = divmod(abs(total_seconds), 3600)
    return (
        f"{moment.strftime('%Y-%m-%d %H:%M:%S')}.{moment.microsecond // 1000:03d} "
        f"{sign}{hours:02d}:{remainder // 60:02d}"
    )


# MARK: 失败信息


@dataclass
class _Failure:
    """一次失败的原始信息（落盘时统一脱敏）。"""

    service: str
    address: str
    method: str
    status: int | None
    reason: str
    detail: str
    attempt: tuple[int, int] | None = None
    exc: BaseException | None = field(default=None, repr=False)


def _safe_getattr(obj: Any, name: str, default: Any = None) -> Any:
    """安全的属性读取（部分库的未设置属性会抛异常，例如 httpx 的 ``.request``）。"""
    if obj is None:
        return default
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _classify_reason(exc: BaseException) -> str:
    """把异常分类为面向日志的安全原因（不含响应体 / 请求头 / 原始输入）。"""
    if isinstance(exc, httpx.TimeoutException):
        return "请求超时"
    if isinstance(exc, httpx.ConnectError):
        return "无法建立连接"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code} 响应错误"
    if isinstance(exc, httpx.HTTPError):
        return "网络请求异常"
    if isinstance(exc, ValidationError):
        return "数据校验失败"
    if type(exc).__module__.startswith(("pymongo", "motor")):
        return "数据库操作异常"
    return type(exc).__name__


def _describe_validation_error(exc: ValidationError) -> str:
    """描述 Pydantic 校验错误：只取字段位置与错误类型，绝不带原始输入。"""
    try:
        errors = exc.errors(include_input=False, include_url=False, include_context=False)
    except TypeError:  # 兼容不支持这些关键字的老版本 pydantic
        errors = [{key: value for key, value in error.items() if key in {"loc", "type"}} for error in exc.errors()]
    summary = []
    for error in errors[:5]:
        location = ".".join(str(part) for part in error.get("loc", ()))
        kind = str(error.get("type", ""))
        summary.append(f"{location}:{kind}" if location else kind)
    return f"数据校验失败（{exc.error_count()} 处）：{', '.join(summary)}"


def _safe_detail(exc: BaseException) -> str:
    """异常的安全描述：脱敏、转义换行并截断。"""
    if isinstance(exc, ValidationError):
        return _sanitize(_describe_validation_error(exc), _MAX_DETAIL)
    if isinstance(exc, httpx.HTTPStatusError):
        safe = _sanitize(f"HTTP {exc.response.status_code} {exc.response.reason_phrase}".strip(), _MAX_DETAIL)
        return safe
    if type(exc).__name__ in _CODE_ONLY_ERRORS:
        # 这类异常的 message 可能来自响应文本，只保留 code 与内置安全提示
        code = _safe_getattr(exc, "code")
        hint = _safe_getattr(exc, "hint")
        detail = f"{type(exc).__name__}: code={code}"
        if isinstance(hint, str) and hint.strip():
            detail = f"{detail}（{hint.strip()}）"
        return _sanitize(detail, _MAX_DETAIL)
    return _sanitize(f"{type(exc).__name__}: {exc}", _MAX_DETAIL)


def _status_of(candidate: Any) -> int | None:
    """读取 HTTP 响应对象的状态码。"""
    status = _safe_getattr(candidate, "status_code")
    return status if isinstance(status, int) else None


def _address_of(candidate: Any) -> str:
    """读取 HTTP 响应对象实际请求的 URL。"""
    url = _safe_getattr(_safe_getattr(candidate, "request"), "url")
    return str(url) if url else ""


def _request_url(exc: BaseException) -> str:
    """读取异常自身携带的实际请求 URL（httpx 异常带 ``.request``）。"""
    url = _safe_getattr(_safe_getattr(exc, "request"), "url")
    return str(url) if url else _address_of(_safe_getattr(exc, "response"))


def _failure_meta(exc: BaseException, recorder: _Recorder) -> _Failure | None:
    """读取异常上的失败元数据（仅当属于**当前**逻辑操作时有效）。"""
    meta = _safe_getattr(exc, _META_ATTR, None)
    if isinstance(meta, tuple) and len(meta) == 2 and meta[0] is recorder and isinstance(meta[1], _Failure):
        return meta[1]
    return None


def _attach_failure_meta(exc: BaseException, recorder: _Recorder, failure: _Failure) -> None:
    """附加失败元数据（最内层优先；同一逻辑操作内不覆盖已有值）。"""
    if _failure_meta(exc, recorder) is not None:
        return
    try:
        setattr(exc, _META_ATTR, (recorder, failure))
    except (AttributeError, TypeError):
        # 少数异常禁止设置属性；元数据只是增强，缺失时由落盘时的请求 / 响应信息兜底
        return


def _is_written(exc: BaseException, recorder: _Recorder) -> bool:
    """该异常对应的失败是否已由**同一逻辑操作**落盘。"""
    return _safe_getattr(exc, _WRITTEN_ATTR, None) is recorder


def _mark_written(exc: BaseException, recorder: _Recorder) -> None:
    """标记该异常对应的失败已落盘。"""
    try:
        setattr(exc, _WRITTEN_ATTR, recorder)
    except (AttributeError, TypeError):
        return


# MARK: 上下文（操作者 / 触发事件）


def _as_int(value: Any) -> int | None:
    """尽量把事件字段转成整数（失败返回 None）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    return int(text) if text.isdecimal() else None


def _current_event() -> Any:
    """只读获取当前事件上下文；handler 之外（启动、后台任务）返回 None。"""
    try:
        return current_event.get()
    except LookupError:
        return None


def _display_name(sender: Any, user_id: int | None) -> str:
    """操作者显示名：card > nickname > QQ 号（不额外调用任何接口）。"""
    if sender is not None:
        for attr in ("card", "nickname"):
            value = _safe_getattr(sender, attr)
            if isinstance(value, str) and value.strip():
                return _sanitize(value.strip(), _MAX_NAME)
    return str(user_id) if user_id is not None else ""


def _event_command(event: Any) -> str:
    """命令原文：优先 ``raw_message``（保留 At 目标等 CQ 段），退回消息序列化 / 纯文本。

    ``get_plaintext`` 会丢掉 At 段目标（``&uid @123456`` 只剩 ``&uid``），因此放在最后兜底。
    ``raw_message`` 是 CQ 转义文本（``&`` -> ``&amp;``），需反转义还原用户实际输入。
    """
    raw = _safe_getattr(event, "raw_message")
    text = _unescape_cq(raw) if isinstance(raw, str) and raw.strip() else ""
    if text.strip():
        return text.strip()
    getter = _safe_getattr(event, "get_message")
    if callable(getter):
        try:
            text = _unescape_cq(str(getter() or ""))
        except Exception:
            text = ""
        if text.strip():
            return text.strip()
    getter = _safe_getattr(event, "get_plaintext")
    if callable(getter):
        try:
            return str(getter() or "").strip()
        except Exception:
            return ""
    return ""


def _unescape_cq(text: str) -> str:
    """反转义 OneBot CQ 文本里的实体（``&amp;`` / ``&#91;`` 等），失败时原样返回。"""
    try:
        from nonebot.adapters.onebot.v11.utils import unescape
    except Exception:  # 非 V11 适配器 / 版本差异：不做反转义
        return text
    try:
        return unescape(text)
    except Exception:
        return text


def _group_kind(group_id: int | None) -> str:
    """把群号翻译为预设群名称（主群 / 茶馆），未知群返回群号。"""
    if group_id is None:
        return "未知群"
    settings = app_config.S_
    if group_id == _as_int(settings.defined_qq.littleskin_main) and group_id:
        return "主群"
    if group_id == _as_int(settings.defined_qq.littleskin_cafe) and group_id:
        return "茶馆"
    return f"群{group_id}"


def _join_request_answer(event: Any) -> str:
    """从入群申请留言中取出用户填写的 UID 答案（与业务侧解析保持一致）。"""
    comment = _safe_getattr(event, "comment")
    if not isinstance(comment, str) or not comment.strip():
        return ""
    return _sanitize(comment.splitlines()[-1].removeprefix("答案：").strip(), _MAX_NAME)


def _context_fields() -> list[str]:
    """生成操作者 / 触发上下文字段（拿不到时统一标注为系统）。"""
    event = _current_event()
    if event is None:
        return ["操作者=系统"]

    fields: list[str] = []
    user_id = _as_int(_safe_getattr(event, "user_id"))
    if user_id is None:
        getter = _safe_getattr(event, "get_user_id")
        if callable(getter):
            try:
                user_id = _as_int(getter())
            except Exception:
                user_id = None

    fields.append(f"操作者={_display_name(_safe_getattr(event, 'sender'), user_id) or '系统'}")
    if user_id is not None:
        fields.append(f"QQ={user_id}")
        fields.append(f"角色={'管理员' if user_id in app_config.C_.admin_list else '普通用户'}")

    group_id = _as_int(_safe_getattr(event, "group_id"))
    post_type = str(_safe_getattr(event, "post_type") or "")
    message_type = str(_safe_getattr(event, "message_type") or "")

    if post_type == "message" or message_type:
        if group_id is not None:
            fields.append(f"群={group_id}")
        command = _event_command(event)
        if command:
            fields.append(f"命令={_sanitize(command, _MAX_COMMAND)}")
    elif str(_safe_getattr(event, "request_type") or "") == "group":
        fields.append(f"触发=入群申请({_group_kind(group_id)})")
        if user_id is not None:
            fields.append(f"申请人={user_id}")
        if group_id is not None:
            fields.append(f"群={group_id}")
        answer = _join_request_answer(event)
        if answer:
            fields.append(f"所填UID={answer}")
    elif str(_safe_getattr(event, "notice_type") or "") == "group_increase":
        fields.append("触发=入群通知")
        if user_id is not None:
            fields.append(f"新成员={user_id}")
        if group_id is not None:
            fields.append(f"群={group_id}")
    else:
        fields.append(f"触发={_sanitize(post_type or type(event).__name__, _MAX_NAME)}")

    return fields


# MARK: 落盘


def _enabled() -> bool:
    """请求日志是否启用（每次实时读取配置）。"""
    return bool(app_config.C_.request_logging.enabled)


def _format_failure_record(failure: _Failure, moment: datetime) -> str:
    """把失败信息格式化为单行记录。"""
    parts = [_format_ts(moment), "[失败]", f"服务={_sanitize(failure.service, _MAX_SERVICE)}"]
    if failure.method:
        parts.append(f"方法={_sanitize(failure.method, 16)}")
    if failure.attempt is not None:
        parts.append(f"尝试={failure.attempt[0]}/{failure.attempt[1]}")
    if failure.address:
        parts.append(f"地址={_sanitize_address(failure.address)}")
    if failure.status is not None:
        parts.append(f"状态={failure.status}")
    if failure.reason:
        parts.append(f"原因={_sanitize(failure.reason, _MAX_SERVICE)}")
    if failure.detail:
        parts.append(f"详情={failure.detail}")
    parts.extend(_context_fields())
    return " | ".join(parts)


def _append_line(text: str, moment: datetime) -> None:
    """以 UTF-8 严格模式追加一行到当日日志文件；任何失败都只告警，不抛出。"""
    config = app_config.C_.request_logging
    if not config.enabled:
        return
    try:
        directory = config.resolved_directory()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{moment.strftime('%Y-%m-%d')}.log"
        with _WRITE_LOCK, path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"{text}\n")
    except Exception as exc:  # 日志写入绝不能影响原业务
        _warn("写入", exc)


def _warn(action: str, exc: Exception) -> None:
    """诊断告警不回显异常内容，也不得因控制台日志故障影响业务。"""
    try:
        logger.warning(f"{_LOG_PREFIX} {action}失败（已忽略，不影响业务）：{type(exc).__name__}")
    except Exception:
        return  # 控制台本身失效时不能递归记录，也不能干扰原业务。


def _guard(action: str, func, *args) -> None:
    """执行一段日志诊断逻辑：任何异常都只打告警，绝不向外传播。"""
    try:
        func(*args)
    except Exception as exc:  # 诊断逻辑绝不能替换原业务异常
        _warn(action, exc)


def _persist_failure(failure: _Failure, recorder: _Recorder) -> None:
    """落盘一次失败记录（同一逻辑操作内同一异常只落盘一次）；全路径 fail-safe。"""
    try:
        if not _enabled():
            return
        exc = failure.exc
        if exc is not None:
            if _is_written(exc, recorder):
                return
            _mark_written(exc, recorder)
        moment = _now()
        _append_line(_format_failure_record(failure, moment), moment)
    except Exception as exc:  # 格式化 / 取事件属性 / 脱敏抛错也不得影响业务
        _warn("记录", exc)


def write_startup_marker() -> None:
    """向当日日志文件追加启动标记（配置关闭时不做任何事）；fail-safe。"""
    try:
        if not _enabled():
            return
        moment = _now()
        _append_line(f"\n--- {_format_ts(moment)} 启动 ---", moment)
    except Exception as exc:  # 启动标记绝不能中断进程启动
        _warn("启动标记写入", exc)


def register_startup_hook() -> None:
    """在 NoneBot 注册一次启动标记 hook（幂等，重复调用只会注册一次）。"""
    global _STARTUP_HOOK_REGISTERED
    if _STARTUP_HOOK_REGISTERED:
        return
    try:
        import nonebot

        nonebot.get_driver().on_startup(write_startup_marker)
    except Exception:  # NoneBot 尚未初始化（如直接导入模块）时跳过注册
        return
    _STARTUP_HOOK_REGISTERED = True


_STARTUP_HOOK_REGISTERED = False


# MARK: 网络调用作用域


@dataclass
class _Recorder:
    """一次「逻辑操作」内的记录状态（随 ContextVar 被同一操作的子任务共享）。"""

    failure: _Failure | None = None
    """待落盘的最内层失败（先写入者优先）。"""


_RECORDER: ContextVar[_Recorder | None] = ContextVar("commspt_request_log_recorder", default=None)

_DEPTH: ContextVar[int] = ContextVar("commspt_request_log_depth", default=0)
"""当前任务内的网络作用域层数（判定「最外层」用）。"""

_SUPPRESS_DEPTH: ContextVar[int] = ContextVar("commspt_request_log_suppress", default=0)
"""重试抑制层级：>0 表示当前不允许落盘。"""


def _acquire_recorder() -> tuple[_Recorder, Any]:
    """获取当前逻辑操作的记录状态；返回 ``(recorder, token)``，token 非 None 时需 reset。"""
    recorder = _RECORDER.get()
    if recorder is not None:
        return recorder, None
    recorder = _Recorder()
    return recorder, _RECORDER.set(recorder)


class RequestScope:
    """``external_request`` 产出的可变作用域对象。

    ``response`` 可赋值为 ``httpx.Response``（用于提取实际 URL 与 HTTP 状态），
    ``address`` 可在请求真正发出后更新为实际地址。
    """

    def __init__(
        self,
        service: str,
        address: str,
        method: str,
        non_failures: tuple[type[BaseException], ...],
        recorder: _Recorder,
    ) -> None:
        self.service = service
        self.address = address
        self.method = method
        self.non_failures = non_failures
        self.response: Any = None
        self._recorder = recorder

    def report_failure(self, exc: BaseException) -> None:
        """登记一次失败但不中断业务：在外层作用域结束时落盘一次（重试内被抑制）。

        适用于「响应 4xx / 5xx 但业务继续解析」的场景：在
        ``response.raise_for_status()`` 的 ``except`` 里调用本方法，再继续原有解析逻辑。
        成功后仍会记录这次 HTTP 失败；之后解析再出错也不会重复记录。
        """
        _guard("登记失败", _note_failure, self._recorder, self, exc)

    def report_http_status(self) -> None:
        """只登记 HTTP 4xx/5xx，不改变接口原有的继续解析行为。"""
        status = _status_of(self.response)
        if status is not None and status >= 400:
            self.report_failure(
                httpx.HTTPStatusError(
                    f"HTTP {status}",
                    request=_safe_getattr(self.response, "request"),
                    response=self.response,
                )
            )

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"RequestScope(service={self.service!r}, address={self.address!r}, method={self.method!r})"


def _is_non_failure(exc: BaseException, scope: RequestScope) -> bool:
    """是否为「不算失败」的业务结果（``non_failures``）。"""
    return bool(scope.non_failures) and isinstance(exc, scope.non_failures)


def _build_failure(recorder: _Recorder, scope: RequestScope, exc: BaseException) -> _Failure:
    """构造失败信息：优先沿用更内层网络点已记录的实际地址 / 服务。"""
    meta = _failure_meta(exc, recorder)
    if meta is not None:
        return dataclasses.replace(meta, exc=exc)
    exc_response = _safe_getattr(exc, "response")
    status = _status_of(scope.response)
    if status is None:
        status = _status_of(exc_response)
    address = _address_of(scope.response) or _address_of(exc_response) or _request_url(exc) or scope.address
    return _Failure(
        service=scope.service,
        address=address,
        method=scope.method,
        status=status,
        reason=_classify_reason(exc),
        detail=_safe_detail(exc),
        exc=exc,
    )


def _note_failure(recorder: _Recorder, scope: RequestScope, exc: BaseException) -> None:
    """记录一次作用域内失败：附加元数据，按需计入待落盘失败。"""
    if _is_non_failure(exc, scope) or _is_written(exc, recorder):
        return
    if not _enabled():
        return
    failure = _build_failure(recorder, scope, exc)
    _attach_failure_meta(exc, recorder, failure)
    if _SUPPRESS_DEPTH.get() > 0:
        return  # 重试尝试内：只留元数据，由 mark_final 统一落盘
    if recorder.failure is None:
        recorder.failure = failure


def _persist_pending(recorder: _Recorder) -> None:
    """最外层作用域退出时落盘（整条逻辑操作只记录一次）。"""
    failure = recorder.failure
    if failure is None:
        return
    recorder.failure = None
    _persist_failure(failure, recorder)


@contextmanager
def external_request(
    service: str,
    address: str,
    *,
    method: str = "GET",
    non_failures: tuple[type[BaseException], ...] = (),
) -> Iterator[RequestScope]:
    """外部网络调用作用域：``with`` 范围包含 await 请求与解析，异常时落盘一次失败记录。

    Args:
        service: 面向日志的服务名（如 ``"飞书 API"``）。
        address: 逻辑地址或 URL；请求发出后可通过 ``scope.address`` 更新为实际地址。
        method: HTTP 方法（仅用于记录）。
        non_failures: 属于业务结果、不记为失败（不落盘）的异常类型。

    说明：
    - 异常一律原样透传，不捕获取消等控制流（``BaseException`` 不被拦截）；
    - 允许嵌套：最外层作用域退出时只落盘一次，优先保留最内层失败网络点的实际地址 / 服务；
    - 与 ``retry_log_scope`` 配合时，尝试内失败只在控制台，最终失败由 ``mark_final`` 落盘一次。
    """
    recorder, token = _acquire_recorder()
    scope = RequestScope(service, address, method, non_failures, recorder)
    is_outer_frame = _DEPTH.get() == 0
    _DEPTH.set(_DEPTH.get() + 1)
    try:
        yield scope
    except Exception as exc:  # 仅拦截常规异常：取消等控制流原样透传
        _guard("登记失败", _note_failure, recorder, scope, exc)
        raise
    finally:
        _DEPTH.set(max(0, _DEPTH.get() - 1))
        try:
            if is_outer_frame:
                _guard("落盘", _persist_pending, recorder)
        finally:
            if token is not None:
                _RECORDER.reset(token)


class RetryLogScope:
    """一次重试尝试对应的日志范围（由 ``retry_log_scope`` 产出）。"""

    def __init__(
        self,
        recorder: _Recorder,
        attempt: int,
        attempts: int,
        service: str,
        address: str,
        method: str,
    ) -> None:
        self.recorder = recorder
        self.attempt = attempt
        self.attempts = attempts
        self.service = service
        self.address = address
        self.method = method

    def _fallback_failure(self, exc: BaseException) -> _Failure:
        """没有更内层网络点元数据时，用重试层自身的服务名兜底构造失败信息。"""
        return _Failure(
            service=self.service or "外部服务",
            address=_request_url(exc) or self.address,
            method=self.method,
            status=_status_of(_safe_getattr(exc, "response")),
            reason=_classify_reason(exc),
            detail=_safe_detail(exc),
            attempt=(self.attempt, self.attempts),
            exc=exc,
        )

    def mark_final(self, exc: BaseException) -> None:
        """标记该异常是「最终失败」：落盘一次（重复调用不会重复记录）。

        在重试层自己就能判定「不会再重试」时调用（不可重试的错误、重试次数耗尽）。
        尝试内的失败一律被抑制，因此本方法是这些场景的唯一落盘点；记录会带上实际尝试
        次数，并沿用更内层网络点记录的实际地址 / 服务。
        """
        _guard("落盘", self._write_final, exc)

    def mark_non_failure(self, exc: BaseException) -> None:
        """标记该异常属于业务结果（如查无此人）：不落盘，外层作用域也不再记录。"""
        _guard("标记业务结果", _mark_written, exc, self.recorder)

    def _write_final(self, exc: BaseException) -> None:
        if _is_written(exc, self.recorder):
            return
        failure = _failure_meta(exc, self.recorder)
        if failure is None:
            if not self.service:
                return
            failure = self._fallback_failure(exc)
            _attach_failure_meta(exc, self.recorder, failure)
        failure = dataclasses.replace(failure, attempt=(self.attempt, self.attempts), exc=exc)
        _persist_failure(failure, self.recorder)
        pending = self.recorder.failure
        if pending is not None and (pending.exc is exc or pending is failure):
            self.recorder.failure = None


@contextmanager
def retry_log_scope(
    attempt: int,
    attempts: int,
    *,
    service: str = "",
    address: str = "",
    method: str = "",
) -> Iterator[RetryLogScope]:
    """标记一次重试尝试：所有尝试内的失败都抑制落盘，最终失败由 ``mark_final`` 落盘一次。

    Args:
        attempt: 当前尝试序号（从 1 开始）。
        attempts: 总尝试次数。
        service: 兜底服务名（没有更内层网络点元数据时用于落盘）。
        address: 兜底地址。
        method: 兜底请求方法。

    配合 ``call_with_retry`` 使用：每次尝试进入本作用域，判定不会再重试时调用
    ``scope.mark_final(exc)``。即使中间尝试先退出，也不会抢先落盘导致最终记录缺少尝试次数。
    """
    recorder, token = _acquire_recorder()
    _SUPPRESS_DEPTH.set(_SUPPRESS_DEPTH.get() + 1)
    scope = RetryLogScope(
        recorder=recorder,
        attempt=attempt,
        attempts=attempts,
        service=service,
        address=address,
        method=method,
    )
    try:
        yield scope
    finally:
        try:
            _SUPPRESS_DEPTH.set(max(0, _SUPPRESS_DEPTH.get() - 1))
        finally:
            if token is not None:
                _RECORDER.reset(token)
