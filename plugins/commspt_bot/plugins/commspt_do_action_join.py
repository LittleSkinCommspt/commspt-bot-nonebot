"""回复入群申请提示消息以通过或拒绝加群请求。

对应 Avilla 原版 modules/do_action_join.py。
通过回复机器人发送的「新的入群申请」通知消息，解析出 sub_type 与 flag，
调用 OneBot V11 的 set_group_add_request API 执行批准或拒绝入群。

命令：
- do <accept|reject> [reason]   通过或拒绝入群申请   (in_preset_cafe; admin_only)
"""

import re
from typing import Literal, assert_never

from arclet.alconna import Alconna, Args, CommandMeta
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, OneBotV11AdapterException
from nonebot.rule import Rule
from nonebot_plugin_alconna import Match, on_alconna
from nonebot_plugin_alconna.uniseg import UniMessage

from plugins.commspt_bot.utils.adv_filter import admin_only, in_preset_cafe
from plugins.commspt_bot.utils.join_request_notice import JoinRequestNoticeError, parse_join_request_notice
from plugins.commspt_bot.utils.random_sleep import random_sleep


def is_bare_do_action(event: MessageEvent) -> bool:
    return re.fullmatch(r"do (?:accept|reject(?: \S+)?)", event.raw_message) is not None


# region do join action
do_action = on_alconna(
    Alconna(
        r"do",
        # action: 操作类型 (accept 同意 / reject 拒绝)
        # reason: 拒绝原因，默认为 "答案错误，再仔细看看"
        Args["action#操作", Literal["accept", "reject"]]["reason#原因", str, "答案错误，再仔细看看"],
        meta=CommandMeta(
            description="处理入群请求 (commspt only)",
            usage="do <accept|reject> [reason]",
            example="do accept",
        ),
    ),
    rule=in_preset_cafe & Rule(is_bare_do_action),
    permission=admin_only,
    use_cmd_start=False,
)


@do_action.handle()
async def do_action_join(
    bot: Bot,
    event: MessageEvent,
    action: Match[Literal["accept", "reject"]],
    reason: Match[str],
):
    """处理回复加群申请提示的审批指令。"""
    logger.info("received do action (join group request)")

    if not event.reply:
        await do_action.send(UniMessage("需要回复一条申请提示消息以进行处理"), reply_to=True)
        return

    try:
        reply_sender_id = int(event.reply.sender.user_id)
    except (TypeError, ValueError):
        await do_action.send(UniMessage("无法验证通知来源"), reply_to=True)
        return
    if reply_sender_id != int(bot.self_id):
        await do_action.send(UniMessage("无法验证通知来源"), reply_to=True)
        return

    try:
        notice = parse_join_request_notice(str(event.reply.message))
    except JoinRequestNoticeError:
        await do_action.send(UniMessage("无法识别申请通知"), reply_to=True)
        return

    await random_sleep(3)
    try:
        match action.result:
            case "accept":
                await bot.set_group_add_request(flag=notice.flag, sub_type=notice.sub_type, approve=True)
                logger.info("accepted")
            case "reject":
                await bot.set_group_add_request(
                    flag=notice.flag,
                    sub_type=notice.sub_type,
                    approve=False,
                    reason=reason.result,
                )
                logger.info("rejected")
            case unreachable:
                assert_never(unreachable)
    except OneBotV11AdapterException as exception:
        logger.error(
            "join moderation action failed: action={action} group={group} subtype={subtype} exception={exception}",
            action=action.result,
            group=event.group_id,
            subtype=notice.sub_type,
            exception=type(exception).__name__,
        )
        await do_action.send(UniMessage("处理失败：请求可能已过期、已处理，或被平台拒绝"), reply_to=True)
        return

    try:
        await do_action.send(UniMessage(f"{action.result}ed {notice.applicant}"), reply_to=True)
    except OneBotV11AdapterException as exception:
        logger.error(
            "join moderation action succeeded, notification failed: "
            "action={action} group={group} subtype={subtype} exception={exception}",
            action=action.result,
            group=event.group_id,
            subtype=notice.sub_type,
            exception=type(exception).__name__,
        )
        return


# endregion
