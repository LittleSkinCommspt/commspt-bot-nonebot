from arclet.alconna import Alconna, Args, CommandMeta
from nonebot import logger
from nonebot_plugin_alconna import At, Match, on_alconna
from nonebot_plugin_alconna.uniseg import UniMessage

from plugins.commspt_bot.config import S_
from plugins.commspt_bot.models.mongodb_data import UIDMapping
from plugins.commspt_bot.utils.adv_filter import admin_only, in_preset_cafe
from plugins.commspt_bot.utils.random_sleep import random_sleep

uid_cmd = on_alconna(
    Alconna(
        f"{S_.command_prompt}uid",
        Args["target#目标", At | int],
        meta=CommandMeta(
            description="查询用户 UID (commspt only)",
            usage=rf"{S_.command_prompt}uid <target / qq>",
            example=rf"{S_.command_prompt}uid @user",
        ),
    ),
    rule=in_preset_cafe,
    permission=admin_only,
)


@uid_cmd.handle()
async def cmd_uid(target: Match[At | int]):
    target_qq = int(target.result.target) if isinstance(target.result, At) else target.result
    logger.info(f"UID search: {target_qq}")
    uid_mapping = await UIDMapping.fetch(qq=target_qq)
    logger.success(f"UID search: {target_qq} -> {uid_mapping}")
    await random_sleep()
    if uid_mapping:
        await uid_cmd.send(
            UniMessage(f"QQ {target_qq} UID {uid_mapping.uid} QMAIL {'✅' if uid_mapping.qmail_verified else '❌'}"),
            reply_to=True,
        )
    else:
        await uid_cmd.send(UniMessage(f"找不到 {target_qq} 在缓存中的 UID"), reply_to=True)
