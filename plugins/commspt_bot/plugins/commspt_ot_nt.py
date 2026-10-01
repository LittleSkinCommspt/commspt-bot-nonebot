"""跨群发送禁止闲聊警告提示。

对应 Avilla 原版 modules/ot_nt.py（OT 即 Off-Topic）。
原版通过 ctx.scene.into 跨群发送消息，此处利用 send_to_group 辅助函数，
由管理群向 LittleSkin 主群定向推送禁止水群的警告图文，并在当前群回复确认。

命令：
- &ot               向 LittleSkin 主群发送禁止闲聊警告图文 (适用群: in_preset_commspt; 权限: 管理员 admin_only)
"""

from arclet.alconna import Alconna, CommandMeta
from nonebot_plugin_alconna import on_alconna
from nonebot_plugin_alconna.uniseg import UniMessage

from plugins.commspt_bot.config import ASSETS_DIR, S_
from plugins.commspt_bot.utils.adv_filter import admin_only, in_preset_commspt
from plugins.commspt_bot.utils.messenger import send_to_group

ot = on_alconna(
    Alconna(
        "ot",
        meta=CommandMeta(
            description="&ot",
            usage="&ot",
            example="&ot",
        ),
    ),
    rule=in_preset_commspt,
    permission=admin_only,
)


@ot.handle()
async def _ot():
    """向主群跨群发送闲聊警告图文，并在当前管理群回复确认。"""
    await send_to_group(
        S_.defined_qq.littleskin_main,
        UniMessage.image(path=ASSETS_DIR / "images" / "honoka_cafe_ng.png")
        + """本群不允许闲聊，闲聊请加群 651672723
大水怪将会收到我们赠送的禁言大礼包。""",
    )
    await ot.send(UniMessage("✅ Sent"), reply_to=True)
