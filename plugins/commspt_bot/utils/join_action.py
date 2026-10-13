"""入群审批的公共执行核心与表情审批凭证索引

`do accept|reject` 文字命令（回复通知消息）与表情回应（贴 👍/👎）
共用同一个 ``execute_join_action`` 执行核心，保证两条入口的审批行为、
错误处理与日志完全一致；两者唯一区别在于「如何拿到 JoinRequestNotice」：

- do 命令        : parse_join_request_notice(reply.message)
- 表情回应       : pop_approval(message_id) 从凭证索引取出

凭证索引（``message_id -> JoinRequestNotice``）供表情审批使用：
表情事件只带 message_id，不含 flag/sub_type，故发送通知时先行登记，
收到表情回应时再取回对应凭证。

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

from plugins.commspt_bot.utils.join_request_notice import JoinRequestNotice

# ---- 审批表情常量（emoji_id 必须为字符串）----
EMOJI_APPROVE = "128077"  # 👍
EMOJI_REJECT = "128078"  # 👎
APPROVAL_EMOJIS = (EMOJI_APPROVE, EMOJI_REJECT)  # 审批引导表情（👍 批准 / 👎 拒绝）

# 拒绝原因默认值（沿用原 commspt_do_action_join 文案）
DEFAULT_REJECT_REASON = "答案错误，再仔细看看"

# 凭证保留时长（秒），默认 24 小时
_APPROVAL_TTL = 24 * 60 * 60

# 审批结果状态
SUCCESS = "success"
ALREADY_HANDLED = "already_handled"
ERROR = "error"

# 反馈文案用的动作过去式，避免依赖英文动词变形规则
_ACTION_VERBS = {"accept": "accepted", "reject": "rejected"}


@dataclass(frozen=True, slots=True)
class JoinActionResult:
    """审批执行结果

    - outcome: SUCCESS / ALREADY_HANDLED / ERROR
    - approve: 本次为批准（True）还是拒绝（False）
    - notice: 对应的入群申请凭证
    - exception: 发生异常时的异常对象（否则为 None）
    """

    outcome: str
    approve: bool
    notice: JoinRequestNotice
    exception: Exception | None = None


def describe_result(result: JoinActionResult, action: str) -> str:
    """按执行结果生成统一的用户反馈文案（do 命令与表情回应共用）。

    ``action`` 为 ``"accept"`` 或 ``"reject"``。
    """
    if result.outcome == SUCCESS:
        return f"{_ACTION_VERBS.get(action, action)} {result.notice.applicant}"
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
) -> JoinActionResult:
    """统一执行入群审批：批准或拒绝 ``notice`` 对应的入群申请。

    两条入口（``do`` 命令 / 表情回应）共用本函数，确保行为一致。
    异常归类：``OneBotV11AdapterException``（已过期/已处理/被平台拒绝）→ ALREADY_HANDLED，其它 → ERROR。

    注意：OneBot 适配器会把 ``params`` 原样 ``json.dumps``（不剔除 ``None``），
    而 SnowLuma 的 ``reason`` 声明为 string（默认 ""），传 ``null`` 会被协议端拒绝
    （表现为 ``ActionFailed``）。故 ``approve=True`` 时**不携带** ``reason`` 字段。
    """
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
        return JoinActionResult(ALREADY_HANDLED, approve, notice, e)
    except Exception as e:
        logger.exception(e)
        return JoinActionResult(ERROR, approve, notice, e)

    logger.info(
        "join action done: source={source} action={action} kind={kind} applicant={applicant} operator={operator}",
        source=source,
        action="accept" if approve else "reject",
        kind=notice.kind,
        applicant=notice.applicant,
        operator=operator_id,
    )
    return JoinActionResult(SUCCESS, approve, notice)


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
