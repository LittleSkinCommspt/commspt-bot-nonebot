from datetime import datetime
from time import time

from arclet.alconna import Alconna, Args, CommandMeta
from httpx import HTTPStatusError
from nonebot_plugin_alconna import Match, on_alconna
from nonebot_plugin_alconna.uniseg import UniMessage

from plugins.commspt_bot.config import S_
from plugins.commspt_bot.models.const import (
    TZ_SHANGHAI,
    PlayerNotFoundError,
    get_ygg_player,
)
from plugins.commspt_bot.utils.adv_filter import in_preset_cafe
from plugins.commspt_bot.utils.skinrendermcapi import (
    process_image,
    request_skinrendermc,
)


async def _render_skin(matcher, player_name: str, player_type: str, source: str):
    """查询玩家皮肤并渲染，source 用于水印文案（LittleSkin / Pro）"""
    start_time = time()
    try:
        player = await get_ygg_player(player_type=player_type, player_name=player_name)
    except PlayerNotFoundError:
        await matcher.send(UniMessage(f"「{player_name}」不存在"), reply_to=True)
        return

    skin_url = player.skin.url if player.skin else None
    cape_url = player.cape.url if player.cape else None
    name_tag = player.name

    try:
        image = await request_skinrendermc(
            skin_url=str(skin_url) if skin_url else None,
            cape_url=str(cape_url) if cape_url else None,
            name_tag=name_tag,
        )
    except HTTPStatusError as e:
        await matcher.send(UniMessage(f"SkinRenderMC API Error, Code: {e.response.status_code}"), reply_to=True)
        return

    skin_hash = player.skin.hash[:8] if player.skin and player.skin.hash else None
    skin_model = player.skin.metadata.model if player.skin and player.skin.metadata else None
    cape_hash = player.cape.hash[:8] if player.cape and player.cape.hash else None

    cost_time = time() - start_time
    now_time = datetime.now(TZ_SHANGHAI).isoformat()

    await matcher.send(
        UniMessage.image(
            raw=process_image(
                image,
                f"{cost_time:.3f}s / Skin {skin_hash} ({skin_model}), Cape {cape_hash} / {now_time}, via SkinRenderMC, {source}",
            ),
        ),
    )


view = on_alconna(
    Alconna(
        f"{S_.command_prompt}view",
        Args["player_name#角色名", str],
        meta=CommandMeta(
            description="查看玩家皮肤",
            usage=rf"{S_.command_prompt}view <player_name>",
            example=rf"{S_.command_prompt}view SerinaNya",
        ),
    ),
    rule=in_preset_cafe,
)

view_ygg = on_alconna(
    Alconna(
        f"{S_.command_prompt}view.ygg",
        Args["player_name#角色名", str],
        meta=CommandMeta(
            description="查看玩家皮肤 (LittleSkin)",
            usage=rf"{S_.command_prompt}view.ygg <player_name>",
            example=rf"{S_.command_prompt}view.ygg SerinaNya",
        ),
    ),
    rule=in_preset_cafe,
)


@view.handle()
async def cmd_view(player_name: Match[str]):
    await _render_skin(view, player_name.result, "ltsk", "LittleSkin")


@view_ygg.handle()
async def cmd_view_ygg(player_name: Match[str]):
    await _render_skin(view_ygg, player_name.result, "ltsk", "LittleSkin")


view_pro = on_alconna(
    Alconna(
        r"%view.pro",
        Args["player_name#角色名", str],
        meta=CommandMeta(
            description="查看玩家皮肤 (Pro)",
            usage=r"%view.pro <player_name>",
            example=r"%view.pro SerinaNya",
        ),
    ),
    rule=in_preset_cafe,
)


@view_pro.handle()
async def cmd_view_pro(player_name: Match[str]):
    await _render_skin(view_pro, player_name.result, "pro", "Pro")
