"""开发者环境与消息元数据调试工具。

对应 Avilla 原版 modules/dev.py。
原版通过 Avilla 上下文（Context/Scene）读取会话与引用消息；
此处适配 OneBot V11 协议，从 MessageEvent 及 event.reply 中提取群号、消息 ID 及消息内容。

命令：
- &id               获取当前群号、当前消息 ID/内容以及被回复消息的 ID/内容 (适用群: in_preset_commspt; 权限: 管理员 admin_only)
"""

from arclet.alconna import Alconna, CommandMeta
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot_plugin_alconna import on_alconna
from nonebot_plugin_alconna.uniseg import UniMessage

from plugins.commspt_bot.config import S_
from plugins.commspt_bot.utils.adv_filter import admin_only, in_preset_commspt

id_cmd = on_alconna(
    Alconna(
        f"{S_.command_prompt}id",
        meta=CommandMeta(
            description="获取环境 ID (commspt only)",
            usage=f"{S_.command_prompt}id",
            example=f"{S_.command_prompt}id",
        ),
    ),
    rule=in_preset_commspt,
    permission=admin_only,
)


@id_cmd.handle()
async def _(event: MessageEvent):
    """提取当前消息及被引用消息的元信息并格式化输出。"""
    origin_message = event.reply
    await id_cmd.send(
        UniMessage(
            f"""Channel ID: {getattr(event, "group_id", None)}
Message ID: {event.message_id}
Message Content: {event.message}
Reply Message ID: {origin_message.message_id if origin_message else None}
Reply Message Content: {origin_message.message if origin_message else None}""",
        ),
    )
