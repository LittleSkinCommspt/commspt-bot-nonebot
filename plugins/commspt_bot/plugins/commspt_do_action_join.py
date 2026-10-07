"""回复入群申请提示消息以通过或拒绝加群请求。

对应 Avilla 原版 modules/do_action_join.py。
使用 NoneBot 原生 ``on_regex`` + OneBot V11 API 实现，不依赖 Alconna / UniMessage。
通过回复机器人发送的「新的入群申请」通知消息，解析出 sub_type 与 flag，
调用 OneBot V11 的 set_group_add_request API 执行批准或拒绝入群。

命令（裸命令，不受全局 COMMAND_START 影响）：
- do <accept|reject> [reason]   通过或拒绝入群申请   (in_preset_cafe; admin_only)
"""

import re
from typing import Literal, assert_never

from nonebot import logger, on_regex
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, OneBotV11AdapterException
from nonebot.params import RegexDict

from plugins.commspt_bot.utils.adv_filter import admin_only, in_preset_cafe
from plugins.commspt_bot.utils.join_request_notice import JoinRequestNoticeError, parse_join_request_notice
from plugins.commspt_bot.utils.onebot_message import reply_to
from plugins.commspt_bot.utils.random_sleep import random_sleep

# 拒绝原因默认值（与 Alconna 原实现保持一致）
_DEFAULT_REJECT_REASON = "答案错误，再仔细看看"

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


@do_action.handle()
async def do_action_join(bot: Bot, event: MessageEvent, groups: dict = RegexDict()):
    """处理回复加群申请提示的审批指令。"""
    logger.info("received do action (join group request)")

    action: Literal["accept", "reject"] = groups["action"]
    reason: str = groups.get("reason") or _DEFAULT_REJECT_REASON

    if not event.reply:
        await do_action.send(reply_to(event) + "需要回复一条申请提示消息以进行处理")
        return

    try:
        reply_sender_id = int(event.reply.sender.user_id)
    except (TypeError, ValueError):
        await do_action.send(reply_to(event) + "无法验证通知来源")
        return
    if reply_sender_id != int(bot.self_id):
        await do_action.send(reply_to(event) + "无法验证通知来源")
        return

    try:
        notice = parse_join_request_notice(str(event.reply.message))
    except JoinRequestNoticeError:
        await do_action.send(reply_to(event) + "无法识别申请通知")
        return

    await random_sleep(3)
    try:
        match action:
            case "accept":
                await bot.set_group_add_request(flag=notice.flag, sub_type=notice.sub_type, approve=True)
                logger.info("accepted")
            case "reject":
                await bot.set_group_add_request(
                    flag=notice.flag,
                    sub_type=notice.sub_type,
                    approve=False,
                    reason=reason,
                )
                logger.info("rejected")
            case unreachable:
                assert_never(unreachable)
    except OneBotV11AdapterException as exception:
        logger.error(
            "join moderation action failed: action={action} group={group} subtype={subtype} exception={exception}",
            action=action,
            group=event.group_id,
            subtype=notice.sub_type,
            exception=type(exception).__name__,
        )
        await do_action.send(reply_to(event) + "处理失败：请求可能已过期、已处理，或被平台拒绝")
        return

    try:
        await do_action.send(reply_to(event) + f"{action}ed {notice.applicant}")
    except OneBotV11AdapterException as exception:
        logger.error(
            "join moderation action succeeded, notification failed: "
            "action={action} group={group} subtype={subtype} exception={exception}",
            action=action,
            group=event.group_id,
            subtype=notice.sub_type,
            exception=type(exception).__name__,
        )
        return
