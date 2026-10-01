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
