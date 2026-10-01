from arclet.alconna import Alconna, CommandMeta
from nonebot_plugin_alconna import on_alconna
from nonebot_plugin_alconna.uniseg import UniMessage

from plugins.commspt_bot.config import ASSETS_DIR, S_
from plugins.commspt_bot.utils.adv_filter import admin_only, in_preset_commspt
from plugins.commspt_bot.utils.messenger import send_to_group

ot = on_alconna(
    Alconna(
        f"{S_.command_prompt}ot",
        meta=CommandMeta(
            description=f"{S_.command_prompt}ot",
            usage=f"{S_.command_prompt}ot",
            example=f"{S_.command_prompt}ot",
        ),
    ),
    rule=in_preset_commspt,
    permission=admin_only,
)


@ot.handle()
async def _ot():
    await send_to_group(
        S_.defined_qq.littleskin_main,
        UniMessage.image(path=ASSETS_DIR / "images" / "honoka cafe ng.png")
        + """本群不允许闲聊，闲聊请加群 651672723
大水怪将会收到我们赠送的禁言大礼包。""",
    )
    await ot.send(UniMessage("✅ Sent"), reply_to=True)
