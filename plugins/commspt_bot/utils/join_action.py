"""入群审批的公共执行核心与表情审批凭证索引

`do accept|reject` 文字命令（回复通知消息）与表情回应（贴 👍/👎）
共用同一个 ``execute_join_action`` 执行核心，保证两条入口的审批行为、
错误处理与日志完全一致；两者唯一区别在于「如何拿到 JoinRequestNotice」：

- do 命令        : parse_join_request_notice(reply.message)
- 表情回应       : pop_approval(message_id) 从凭证索引取出

凭证索引（``message_id -> JoinRequestNotice``）供表情审批使用：
表情事件只带 message_id，不含 flag/sub_type，故发送通知时先行登记，
收到表情回应时再取回对应凭证。

批准顺序约定（唯一 choke point）
--------------------------------
所有批准动作都汇聚到 ``execute_join_action``，因此「先写数据库/登记，再放人」的
顺序约束集中实现在这里，两条入口自动获得同一保证：

1. 从申请答案解析 UID（非纯数字则不落账，也不猜测）；
2. 登记到进程内 UID 表（``utils.join_ledger``），供欢迎通知直接读取；
3. 主群把映射 upsert 到 MongoDB（best-effort + 超时上限，失败不阻止放人）；
4. 最后才调用 ``set_group_add_request`` 放人。

原因：放人会立刻触发 ``group_increase``，欢迎处理器在同一秒内就读 UID；写入若
排在审批之后，欢迎侧必然读到空。拒绝入群与审批调用失败时会撤销内存登记，避免
残留登记污染下一次欢迎通知。

主要接口：
- execute_join_action: 统一执行入群审批（批准/拒绝），返回 JoinActionResult
- remember_approval: 登记一条审批消息的凭证
- pop_approval: 取出并终结凭证（弹出即消费，防重复处理）
- purge_expired_approvals: 惰性清理超过保留时限的凭证，避免内存累积
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, OneBotV11AdapterException

from plugins.commspt_bot.utils.command_prefix import display_command
from plugins.commspt_bot.utils.join_ledger import forget_join_uid, remember_join_uid, uid_from_answer
from plugins.commspt_bot.utils.join_request_notice import JoinRequestNotice
from plugins.commspt_bot.utils.mongodb_manager import upsert_uid_mapping

# ---- 审批表情常量（emoji_id 必须为字符串）----
EMOJI_APPROVE = "128077"  # 👍
EMOJI_REJECT = "128078"  # 👎
APPROVAL_EMOJIS = (EMOJI_APPROVE, EMOJI_REJECT)  # 审批引导表情（👍 批准 / 👎 拒绝）

# 未指定拒绝原因时的默认提示
DEFAULT_REJECT_REASON = "请正确填写UID"

# 凭证保留时长（秒），默认 24 小时
_APPROVAL_TTL = 24 * 60 * 60

# 审批结果状态
SUCCESS = "success"
ALREADY_HANDLED = "already_handled"
ERROR = "error"

# 会写入 MongoDB 台账的申请类型：茶馆群只校验 UID 是否存在，不构成身份校验，
# 若把茶馆群的自报 UID 也落库，就会用未经验证的值覆盖主群已核实的正确映射。
_PERSISTED_KINDS = frozenset({"Main"})

# 反馈文案用的动作过去式，避免依赖英文动词变形规则
_ACTION_VERBS = {"accept": "accepted", "reject": "rejected"}

# 映射写入失败时的补写提示（命令展示前缀跟随 COMMAND_START）
_MAPPING_WRITE_HINT = f"⚠️ 映射写入失败，请用 {display_command('setuid')} 补写"


async def _persist_mapping(uid: int, qq: int, *, qmail_verified: bool) -> bool:
    """落库映射台账；任何异常都按「未写入」处理，绝不阻断放人。

    ``upsert_uid_mapping`` 本身已经是「永不抛异常」的 best-effort 实现，这层
    额外兜底是为了防它内部出现未预期的编程错误（例如模型字段变更）把审批搞挂：
    台账是辅助记录，不能成为放人的单点故障。
    """
    try:
        return await upsert_uid_mapping(uid, qq, qmail_verified=qmail_verified)
    except Exception as e:
        logger.exception(e)
        return False


@dataclass(frozen=True, slots=True)
class JoinActionResult:
    """审批执行结果

    - outcome: SUCCESS / ALREADY_HANDLED / ERROR
    - approve: 本次为批准（True）还是拒绝（False）
    - notice: 对应的入群申请凭证
    - exception: 发生异常时的异常对象（否则为 None）
    - uid: 本次放行使用的 UID（答案非有效 UID、或本次为拒绝时是 ``None``）
    - mapping_written: 是否已写入 MongoDB 台账；``None`` 表示本次无需落账
      （拒绝入群、答案非有效 UID、茶馆群不落账）
    """

    outcome: str
    approve: bool
    notice: JoinRequestNotice
    exception: Exception | None = None
    uid: int | None = None
    mapping_written: bool | None = None


def describe_result(result: JoinActionResult, action: str) -> str:
    """按执行结果生成统一的用户反馈文案（do 命令与表情回应共用）。

    ``action`` 为 ``"accept"`` 或 ``"reject"``。
    """
    if result.outcome == SUCCESS:
        text = f"{_ACTION_VERBS.get(action, action)} {result.notice.applicant}"
        if result.mapping_written is False:
            # 放人已成功，只是台账没写进去：明确告知补写方式，避免管理员误以为全成功
            text = f"{text}（{_MAPPING_WRITE_HINT}）"
        return text
    if result.outcome == ALREADY_HANDLED:
        return "处理失败：请求可能已过期、已处理，或被平台拒绝"
    return "处理失败：内部错误，请稍后重试"


def _describe_exception(exc: Exception) -> str:
    """尽量提取 OneBot 异常的详细信息（code/message/info），便于排查协议端拒绝原因。"""
    parts: list[str] = []
    for attr in ("code", "message", "msg"):
        val = getattr(exc, attr, None)
        if val not in (None, ""):
            parts.append(f"{attr}={val}")
    info = getattr(exc, "info", None)
    if info:
        parts.append(f"info={info}")
    return " ".join(parts) if parts else str(exc)


async def execute_join_action(
    bot: Bot,
    notice: JoinRequestNotice,
    *,
    approve: bool,
    reason: str | None = None,
    operator_id: int | None = None,
    source: str = "command",
    qmail_verified: bool = False,
) -> JoinActionResult:
    """统一执行入群审批：批准或拒绝 ``notice`` 对应的入群申请。

    两条入口（``do`` 命令 / 表情回应）共用本函数，确保行为一致。
    异常归类：``OneBotV11AdapterException``（已过期/已处理/被平台拒绝）→ ALREADY_HANDLED，其它 → ERROR。

    批准时严格执行「先写库/登记，再放人」：

    1. 答案解析出 UID（非纯数字则跳过落账，仍照常放人——管理员已明确批准）；
    2. 登记进程内 UID 表，欢迎通知据此展示 UID，不再回查映射库；
    3. 主群把映射 upsert 到 MongoDB（best-effort：超时或异常只记日志，不阻止放人）；
    4. 调用 ``set_group_add_request`` 放人。

    顺序不可调整：放人会立刻触发 ``group_increase``，欢迎侧紧接着读 UID。

    ``qmail_verified`` 表示调用方已完成 QMail 确定性校验（QQ 邮箱与 UID 归属一致），
    仅影响台账里记录的状态位，不参与是否放人的决策。

    注意：OneBot 适配器会把 ``params`` 原样 ``json.dumps``（不剔除 ``None``），
    而 SnowLuma 的 ``reason`` 声明为 string（默认 ""），传 ``null`` 会被协议端拒绝
    （表现为 ``ActionFailed``）。故 ``approve=True`` 时**不携带** ``reason`` 字段。
    """
    uid: int | None = None
    mapping_written: bool | None = None

    if approve:
        uid = uid_from_answer(notice.answer)
        if notice.applicant > 0 and uid is not None:
            # 顺序不可换：登记必须早于放人，欢迎通知在同一秒内就会读这张表
            remember_join_uid(notice.applicant, uid, qmail_verified=qmail_verified)
            if notice.kind in _PERSISTED_KINDS:
                mapping_written = await _persist_mapping(uid, notice.applicant, qmail_verified=qmail_verified)
            else:
                logger.debug(
                    "join ledger kept in memory only: kind={kind} applicant={applicant} (不写 MongoDB)",
                    kind=notice.kind,
                    applicant=notice.applicant,
                )
        else:
            # 答案不是有效 UID（占位符 / 申请人 user_id 为 0）：不猜、不落账，但仍放人
            logger.info(
                "join uid skipped: kind={kind} applicant={applicant} answer={answer} "
                "(答案非有效 UID，欢迎通知将不带 UID)",
                kind=notice.kind,
                applicant=notice.applicant,
                answer=notice.answer,
            )
    else:
        # 拒绝入群：撤销可能残留的登记，避免下一次欢迎通知误用旧 UID
        forget_join_uid(notice.applicant)

    params: dict[str, Any] = {
        "flag": notice.flag,
        "sub_type": notice.sub_type,
        "approve": approve,
    }
    if not approve:
        params["reason"] = reason or DEFAULT_REJECT_REASON
    try:
        await bot.call_api("set_group_add_request", **params)
    except OneBotV11AdapterException as e:
        # 请求可能已过期 / 已处理 / 被平台拒绝（含另一入口已先消费 flag 的情形）
        if approve:
            # 人没放进去，撤销刚登记/落库前的内存条目，避免污染后续欢迎通知
            forget_join_uid(notice.applicant)
        logger.error(
            "join action failed: source={source} action={action} subtype={subtype} "
            "applicant={applicant} operator={operator} flag={flag} "
            "exception={exc} detail={detail}",
            source=source,
            action="accept" if approve else "reject",
            subtype=notice.sub_type,
            applicant=notice.applicant,
            operator=operator_id,
            flag=notice.flag,
            exc=type(e).__name__,
            detail=_describe_exception(e),
        )
        return JoinActionResult(ALREADY_HANDLED, approve, notice, e, uid=uid, mapping_written=mapping_written)
    except Exception as e:
        if approve:
            forget_join_uid(notice.applicant)
        logger.exception(e)
        return JoinActionResult(ERROR, approve, notice, e, uid=uid, mapping_written=mapping_written)

    logger.info(
        "join action done: source={source} action={action} kind={kind} applicant={applicant} operator={operator}"
        " uid={uid} mapping_written={mapping_written}",
        source=source,
        action="accept" if approve else "reject",
        kind=notice.kind,
        applicant=notice.applicant,
        operator=operator_id,
        uid=uid,
        mapping_written=mapping_written,
    )
    return JoinActionResult(SUCCESS, approve, notice, uid=uid, mapping_written=mapping_written)


# ---- 表情审批凭证索引（message_id -> JoinRequestNotice）----
_INDEX: dict[int, JoinRequestNotice] = {}
_INDEX_CREATED_AT: dict[int, float] = {}
_INDEX_LOCK = asyncio.Lock()


async def remember_approval(message_id: int, notice: JoinRequestNotice) -> None:
    """登记一条审批消息的凭证，并顺带惰性清理过期条目。"""
    async with _INDEX_LOCK:
        _purge_locked()
        _INDEX[message_id] = notice
        _INDEX_CREATED_AT[message_id] = time.monotonic()


async def pop_approval(message_id: int) -> JoinRequestNotice | None:
    """取出并终结该审批消息的凭证（弹出即消费，防重复处理）。"""
    async with _INDEX_LOCK:
        _purge_locked()
        _INDEX_CREATED_AT.pop(message_id, None)
        return _INDEX.pop(message_id, None)


def _purge_locked() -> None:
    """清理超过保留时限的凭证（调用方须已持有 _INDEX_LOCK）。"""
    deadline = time.monotonic() - _APPROVAL_TTL
    expired = [mid for mid, ts in _INDEX_CREATED_AT.items() if ts < deadline]
    for mid in expired:
        _INDEX.pop(mid, None)
        _INDEX_CREATED_AT.pop(mid, None)
    if expired:
        logger.debug("purged {n} expired approval entries", n=len(expired))


async def purge_expired_approvals() -> int:
    """主动清理过期凭证，返回清理数量（可供后台定时任务调用）。"""
    async with _INDEX_LOCK:
        before = len(_INDEX)
        _purge_locked()
        return before - len(_INDEX)
