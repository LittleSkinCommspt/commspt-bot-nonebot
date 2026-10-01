"""跨群消息发送工具

受 avilla 版 `ctx.scene.into(f"::group({g})").send_message(...)` 启发，
NoneBot 下使用 `UniMessage.send(Target.group(...))` 实现向指定群发送消息。

主要接口：
- send_to_group: 向指定群号主动推送文本或 UniMessage 消息
- send_to_group_with_at: 向指定群号发送带 @ 目标用户的消息
"""

from nonebot import logger
from nonebot_plugin_alconna.uniseg import At, Target, UniMessage
from nonebot_plugin_alconna.uniseg.constraint import SupportScope


async def send_to_group(group_id: int, message: str | UniMessage):
    """向指定群发送消息"""
    if not group_id:
        logger.warning("目标群号未配置，跳过发送")
        return
    if isinstance(message, str):
        message = UniMessage(message)
    # 使用 Target.group 构造群聊目标，并通过 scope=SupportScope.qq_client 限定在 QQ 客户端适配器范围内寻址发送
    await message.send(Target.group(str(group_id), scope=SupportScope.qq_client))


async def send_to_group_with_at(group_id: int, user_id: int | str, message: str | UniMessage):
    """向指定群发送带 @ 的消息"""
    if isinstance(message, str):
        message = UniMessage(message)
    await send_to_group(group_id, UniMessage(At("user", str(user_id))) + " " + message)
