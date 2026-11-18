"""回复入群申请提示消息以通过或拒绝加群请求。

对应 Avilla 原版 modules/do_action_join.py。
使用 NoneBot 原生 ``on_regex`` + OneBot V11 API 实现，不依赖 Alconna / UniMessage。
通过回复机器人发送的「新的入群申请」通知消息，解析出 sub_type 与 flag，
调用入群审批公共执行核心 ``execute_join_action`` 批准或拒绝入群。

执行核心与表情回应审批（贴 👍/👎）共用，保证两条入口行为一致；
同一条申请被任一入口处理后再由另一入口处理，会得到「已过期/已处理」提示。

命令（裸命令，不受全局 COMMAND_START 影响）：
- do <accept|reject> [reason]   通过或拒绝入群申请   (in_preset_cafe; admin_only)
- 拒绝 [理由]                   do reject 的中文快捷写法，理由可含空格
                                (in_preset_cafe; admin_only; 需 JOIN_REPLY_REJECT_ENABLED=true，默认关闭)
"""

import re
from typing import Literal

from nonebot import logger, on_regex
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.params import RegexDict
from nonebot.rule import Rule

from plugins.commspt_bot.config import S_
from plugins.commspt_bot.utils.adv_filter import admin_only, in_preset_cafe
from plugins.commspt_bot.utils.join_action import (
    DEFAULT_REJECT_REASON,
    describe_result,
    execute_join_action,
)
from plugins.commspt_bot.utils.join_request_notice import (
    JoinRequestNotice,
    JoinRequestNoticeError,
    parse_join_request_notice,
)
from plugins.commspt_bot.utils.onebot_message import reply_to

# 裸命令匹配模式：以「do」开头，不接受任何 COMMAND_START 前缀；
# reject 的原因仅取单个不含空白的原因词，多词原因不匹配（沿用原行为）。
DO_ACTION_PATTERN = r"^do (?P<action>accept|reject)(?: (?P<reason>\S+))?$"

# 使用 on_regex 而非 on_command：on_command 始终读取全局 command_start 命令前缀，
# 而 on_regex 基于正则规则，可保证 do 为前缀无关的裸命令。
do_action = on_regex(
    DO_ACTION_PATTERN,
    re.UNICODE,
    rule=in_preset_cafe,
    permission=admin_only,
    priority=1,
    block=False,
)


# 中文快捷拒绝：引用申请通知直接回复「拒绝 理由」。与 do 命令的区别：
# - 理由取「拒绝」之后的整段文字（允许空格，含全角空格分隔）；只回复「拒绝」时用默认理由；
# - 默认关闭（JOIN_REPLY_REJECT_ENABLED），开关只影响这个写法，do 命令始终可用。
REPLY_REJECT_PATTERN = r"^拒绝(?:\s+(?P<reason>\S.*?))?\s*$"


def _reply_reject_enabled() -> bool:
    """快捷拒绝开关（默认关闭）。"""
    return S_.join_reply_reject_enabled


reply_reject = on_regex(
    REPLY_REJECT_PATTERN,
    re.UNICODE,
    rule=in_preset_cafe & Rule(_reply_reject_enabled),
    permission=admin_only,
    priority=1,
    block=False,
)


def _notice_from_reply(bot: Bot, event: MessageEvent) -> tuple[JoinRequestNotice | None, str]:
    """从被引用的消息解析入群申请通知。

    返回 ``(通知, "")``；无法解析时返回 ``(None, 给管理员的说明)``。
    只接受引用 Bot 自己发出的通知，避免伪造通知文本触发审批。
    """
    if not event.reply:
        return None, "需要回复一条申请提示消息以进行处理"

    try:
        reply_sender_id = int(event.reply.sender.user_id)
    except (TypeError, ValueError):
        reply_sender_id = None
    if reply_sender_id != int(bot.self_id):
        return None, "无法验证通知来源"

    try:
        return parse_join_request_notice(str(event.reply.message)), ""
    except JoinRequestNoticeError:
        return None, "无法识别申请通知"


@do_action.handle()
async def do_action_join(bot: Bot, event: MessageEvent, groups: dict = RegexDict()):
    """处理回复加群申请提示的审批指令。"""
    logger.info("received do action (join group request)")

    action: Literal["accept", "reject"] = groups["action"]
    reason: str = groups.get("reason") or DEFAULT_REJECT_REASON

    notice, problem = _notice_from_reply(bot, event)
    if notice is None:
        await do_action.send(reply_to(event) + problem)
        return

    result = await execute_join_action(
        bot,
        notice,
        approve=(action == "accept"),
        reason=reason,  # 仅 reject 时生效
        operator_id=int(event.user_id),
        source="command",
    )

    await do_action.send(reply_to(event) + describe_result(result, action))


@reply_reject.handle()
async def reply_reject_join(bot: Bot, event: MessageEvent, groups: dict = RegexDict()):
    """处理引用入群申请通知回复「拒绝 理由」的快捷拒绝。"""
    notice, problem = _notice_from_reply(bot, event)
    if notice is None:
        # 「拒绝」是日常用语：不是在引用 Bot 的申请通知时一律静默忽略，不在群里回任何提示
        logger.debug(f"reply reject ignored: {problem}")
        return

    logger.info("received reply reject (join group request)")
    reason = (groups.get("reason") or "").strip() or DEFAULT_REJECT_REASON
    result = await execute_join_action(
        bot,
        notice,
        approve=False,
        reason=reason,
        operator_id=int(event.user_id),
        source="reply-reject",
    )

    await reply_reject.send(reply_to(event) + describe_result(result, "reject"))
