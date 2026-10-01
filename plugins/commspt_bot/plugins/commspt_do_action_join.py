import re
from typing import Literal

from arclet.alconna import Alconna, Args, CommandMeta
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot_plugin_alconna import Match, on_alconna
from nonebot_plugin_alconna.uniseg import UniMessage

from plugins.commspt_bot.utils.adv_filter import admin_only, in_preset_cafe
from plugins.commspt_bot.utils.random_sleep import random_sleep

# region do join action
do_action = on_alconna(
    Alconna(
        r"do",
        Args["action#操作", Literal["accept", "reject"]]["reason#原因", str, "答案错误，再仔细看看"],
        meta=CommandMeta(
            description="处理入群请求 (commspt only)",
            usage="do <accept|reject> [reason]",
            example="do accept",
        ),
    ),
    rule=in_preset_cafe,
    permission=admin_only,
)


@do_action.handle()
async def do_action_join(
    bot: Bot,
    event: MessageEvent,
    action: Match[Literal["accept", "reject"]],
    reason: Match[str],
):
    logger.info("received do action (join group request)")

    # check origin message
    if not event.reply:
        await do_action.send(UniMessage("需要回复一条申请提示消息以进行处理"), reply_to=True)
        return
    origin_raw_text = str(event.reply.message)
    req_match = re.search(r"^id=(.*)$", origin_raw_text, re.MULTILINE)
    applicant_match = re.search(r"申请人\s*(.*)$", origin_raw_text, re.MULTILINE)

    # if check failed then kill
    if not (origin_raw_text.startswith("新的入群申请") and req_match and applicant_match):
        return

    reqid = req_match.group(1)
    applicant = applicant_match.group(1)
    logger.info(f"do action (join group request): {action.result=}, {reason.result=}, {applicant=}, {reqid=}")

    sub_type, flag = reqid.split("_", 1)

    # Fn action
    await random_sleep(3)
    match action.result:
        case "accept":
            await bot.set_group_add_request(flag=flag, sub_type=sub_type, approve=True)
            logger.info("accepted")
        case "reject":
            await bot.set_group_add_request(flag=flag, sub_type=sub_type, approve=False, reason=reason.result)
            logger.info("rejected")
    await do_action.send(UniMessage(f"{action.result}ed {applicant}"), reply_to=True)


# endregion
