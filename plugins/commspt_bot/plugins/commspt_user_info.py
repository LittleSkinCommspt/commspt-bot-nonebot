from arclet.alconna import Alconna, Args, CommandMeta
from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot_plugin_alconna import At, Match, on_alconna
from nonebot_plugin_alconna.uniseg import UniMessage

from plugins.commspt_bot.config import S_
from plugins.commspt_bot.models.littleskin_api import LittleSkinUser
from plugins.commspt_bot.models.mongodb_data import UIDMapping
from plugins.commspt_bot.models.render_user_info import RenderUserInfo
from plugins.commspt_bot.utils.adv_filter import (
    admin_only,
    in_preset_cafe,
    in_preset_commspt,
)
from plugins.commspt_bot.utils.mongodb_manager import write_uid_db

user_info = on_alconna(
    Alconna(
        f"{S_.command_prompt}user",
        Args["uid#UID", int],
        meta=CommandMeta(
            description="查询用户信息 (commspt [group] only)",
            usage=rf"{S_.command_prompt}user <uid>",
            example=rf"{S_.command_prompt}user 123456",
        ),
    ),
    rule=in_preset_commspt,
    permission=admin_only,
)


@user_info.handle()
async def _user_info(uid: Match[int]):
    logger.info(f"Looking for user info uid={uid.result}")
    ltsk_user = await LittleSkinUser.uid_info(uid.result)
    mapping_qq = await UIDMapping.fetch(uid=uid.result)
    logger.info(f"UID Mapping: {uid.result} -> {mapping_qq}")
    if ltsk_user:
        logger.info(f"Ready to render {uid.result} ↓")
        logger.info(ltsk_user)
        render = RenderUserInfo(**ltsk_user.model_dump(), qq=mapping_qq.qq if mapping_qq else None)
        image = await render.get_image()
        await user_info.send(UniMessage.image(raw=image))
        logger.success("Image sent.")
    else:
        await user_info.send(UniMessage(f"未找到 UID 为 {uid.result} 的用户"))
        logger.error(f"UID {uid.result} not found.")


set_uid = on_alconna(
    Alconna(
        f"{S_.command_prompt}setuid",
        Args["target#目标", At | int]["uid#UID", int],
        meta=CommandMeta(
            description="设置用户记录的 UID (commspt only)",
            usage=rf"{S_.command_prompt}setuid <target> <uid>",
            example=rf"{S_.command_prompt}setuid @SerinaNya 15301",
        ),
    ),
    rule=in_preset_cafe,
    permission=admin_only,
)


@set_uid.handle()
async def _set_uid(target: Match[At | int], uid: Match[int], event: MessageEvent):
    target_qq = int(target.result.target) if isinstance(target.result, At) else target.result
    target_uid = uid.result
    await write_uid_db(uid=target_uid, qq=target_qq)
    await set_uid.send(UniMessage(f"RESULT ✅ > QQ {target_qq} <-> UID {target_uid}"))
