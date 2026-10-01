"""Minecraft 玩家皮肤与披风渲染展示模块。

从 Avilla 原版的皮肤查询与渲染逻辑移植到 NoneBot2 + Alconna 架构。
采用 UniMessage 构建图片消息段，统一跨平台与 OneBot V11 协议的图片发送方式。

命令：
- &view <player_name>   查看 LittleSkin 玩家皮肤 (in_preset_cafe; 默认)
- &view.ygg <player_name>   查看 LittleSkin 玩家皮肤 (in_preset_cafe; 默认)
- %view.pro <player_name>   查看 Blessing Skin Pro 玩家皮肤 (in_preset_cafe; 默认)
"""

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
    """查询玩家皮肤与披风材质，请求渲染服务并发送带水印的渲染图。"""
    start_time = time()
    try:
        # 调用外部 Yggdrasil API 查询玩家档案（包含皮肤、披风 URL 及材质元数据）
        player = await get_ygg_player(player_type=player_type, player_name=player_name)
    except PlayerNotFoundError:
        await matcher.send(UniMessage(f"「{player_name}」不存在"), reply_to=True)
        return

    # 提取皮肤与披风的下载直链以及角色名铭牌文本
    skin_url = player.skin.url if player.skin else None
    cape_url = player.cape.url if player.cape else None
    name_tag = player.name

    try:
        # 调用外部 SkinRenderMC 渲染接口生成 3D 角色模型视图图片
        image = await request_skinrendermc(
            skin_url=str(skin_url) if skin_url else None,
            cape_url=str(cape_url) if cape_url else None,
            name_tag=name_tag,
        )
    except HTTPStatusError as e:
        await matcher.send(UniMessage(f"SkinRenderMC API Error, Code: {e.response.status_code}"), reply_to=True)
        return

    # 提取材质哈希前缀及皮肤模型类型（如 slim/default），用于生成水印信息
    skin_hash = player.skin.hash[:8] if player.skin and player.skin.hash else None
    skin_model = player.skin.metadata.model if player.skin and player.skin.metadata else None
    cape_hash = player.cape.hash[:8] if player.cape and player.cape.hash else None

    # 计算整体耗时并获取上海时区的当前时间戳
    cost_time = time() - start_time
    now_time = datetime.now(TZ_SHANGHAI).isoformat()

    # process_image 对原始渲染图进行图片处理并绘制底部文本水印；UniMessage.image 以原始字节流形式封装上传
    await matcher.send(
        UniMessage.image(
            raw=process_image(
                image,
                f"{cost_time:.3f}s / Skin {skin_hash} ({skin_model}), Cape {cape_hash} / {now_time}, via SkinRenderMC, {source}",
            ),
        ),
    )


# 命令参数：player_name 为需要查询的玩家角色名（字符串）
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

# 命令参数：player_name 为需要查询的玩家角色名（字符串，针对 LittleSkin 显式前缀）
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


# 命令参数：player_name 为需要查询的玩家角色名（字符串，固定前缀 %view.pro 针对 Blessing Skin Pro）
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
