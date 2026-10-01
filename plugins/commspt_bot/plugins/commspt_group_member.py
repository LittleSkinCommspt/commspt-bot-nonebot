"""查询群成员/指定 QQ 所绑定的 LittleSkin UID 映射信息。

对应 Avilla 原版 modules/group_member.py。
从 MongoDB 数据库 (UIDMapping) 中检索 QQ 对应的 LittleSkin UID 及 QMail 验证状态。

命令：
- &uid <target>   查询指定用户 (@或QQ号) 绑定的 UID 与 QMail 状态   (in_preset_cafe; admin_only)
"""

from arclet.alconna import Alconna, Args, CommandMeta
from nonebot import logger
from nonebot_plugin_alconna import At, Match, on_alconna
from nonebot_plugin_alconna.uniseg import UniMessage

from plugins.commspt_bot.models.mongodb_data import UIDMapping
from plugins.commspt_bot.utils.adv_filter import admin_only, in_preset_cafe
from plugins.commspt_bot.utils.random_sleep import random_sleep

uid_cmd = on_alconna(
    Alconna(
        "uid",
        Args["target#目标", At | int],  # 目标用户，支持 @提及 (At) 或输入纯数字 QQ 号 (int)
        meta=CommandMeta(
            description="查询用户 UID (commspt only)",
            usage=r"&uid <target / qq>",
            example=r"&uid @user",
        ),
    ),
    rule=in_preset_cafe,
    permission=admin_only,
)


@uid_cmd.handle()
async def cmd_uid(target: Match[At | int]):
    """处理 UID 查询指令，输出用户 UID 及邮箱验证标识。"""
    target_qq = int(target.result.target) if isinstance(target.result, At) else target.result  # 提取目标 QQ 号
    logger.info(f"UID search: {target_qq}")
    uid_mapping = await UIDMapping.fetch(qq=target_qq)  # 从数据库检索 QQ 对应的 UIDMapping 缓存
    logger.success(f"UID search: {target_qq} -> {uid_mapping}")
    await random_sleep()
    if uid_mapping:
        await uid_cmd.send(
            UniMessage(f"QQ {target_qq} UID {uid_mapping.uid} QMAIL {'✅' if uid_mapping.qmail_verified else '❌'}"),
            reply_to=True,
        )
    else:
        await uid_cmd.send(UniMessage(f"找不到 {target_qq} 在缓存中的 UID"), reply_to=True)
