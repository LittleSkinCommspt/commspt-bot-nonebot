"""回复入群申请提示消息以通过或拒绝加群请求。

对应 Avilla 原版 modules/do_action_join.py。
通过回复机器人发送的「新的入群申请」通知消息，解析出 sub_type 与 flag，
调用 OneBot V11 的 set_group_add_request API 执行批准或拒绝入群。

命令：
- do <accept|reject> [reason]   通过或拒绝入群申请   (in_preset_cafe; admin_only)
"""

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
        # action: 操作类型 (accept 同意 / reject 拒绝)
        # reason: 拒绝原因，默认为 "答案错误，再仔细看看"
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
    """处理回复加群申请提示的审批指令。"""
    logger.info("received do action (join group request)")

    # check origin message
    if not event.reply:
        await do_action.send(UniMessage("需要回复一条申请提示消息以进行处理"), reply_to=True)
        return
    origin_raw_text = str(event.reply.message)
    req_match = re.search(r"^id=(.*)$", origin_raw_text, re.MULTILINE)  # 从被回复的提示消息中提取 id=<sub_type>_<flag>
    applicant_match = re.search(r"申请人\s*(.*)$", origin_raw_text, re.MULTILINE)  # 从被回复的提示消息中提取申请人 QQ 号

    # if check failed then kill
    # 仅处理由机器人发出的标准加群申请提示消息
    if not (origin_raw_text.startswith("新的入群申请") and req_match and applicant_match):
        return

    reqid = req_match.group(1)
    applicant = applicant_match.group(1)
    logger.info(f"do action (join group request): {action.result=}, {reason.result=}, {applicant=}, {reqid=}")

    sub_type, flag = reqid.split("_", 1)  # 拆分得到 OneBot V11 加群子类型与请求 flag

    # Fn action
    await random_sleep(3)
    match action.result:
        case "accept":
            await bot.set_group_add_request(flag=flag, sub_type=sub_type, approve=True)  # 调用 OneBot V11 API 同意入群
            logger.info("accepted")
        case "reject":
            # 调用 OneBot V11 API 拒绝入群并附带原因
            await bot.set_group_add_request(flag=flag, sub_type=sub_type, approve=False, reason=reason.result)
            logger.info("rejected")
    await do_action.send(UniMessage(f"{action.result}ed {applicant}"), reply_to=True)


# endregion
