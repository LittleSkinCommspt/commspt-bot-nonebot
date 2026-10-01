import traceback
from io import BytesIO

import httpx
from arclet.alconna import Alconna, Args, CommandMeta
from nonebot import logger
from nonebot_plugin_alconna import Match, on_alconna
from nonebot_plugin_alconna.uniseg import UniMessage
from PIL import Image

from plugins.commspt_bot.config import S_
from plugins.commspt_bot.models.const import (
    CustomSkinLoaderApi,
    PlayerNameInvalidError,
    PlayerNotFoundError,
    PlayerProfile,
    get_csl_player,
    get_ygg_player,
)
from plugins.commspt_bot.utils.adv_filter import admin_only, in_preset_cafe


def check_image_size_64(data: bytes) -> bool:
    """
    检查图片尺寸是否为64*64
    """
    image_data = BytesIO(data)
    img = Image.open(image_data)
    width, height = img.size
    return width == 64 and height == 64


async def check_pro_exists(player_name: str) -> bool:
    return bool(await get_ygg_player(player_type="pro", player_name=player_name))


async def check_ltsk_ygg_exists(player_name: str) -> bool:
    return bool(await get_ygg_player(player_type="ltsk", player_name=player_name))


async def check_ltsk_csl_exists(player_name: str) -> bool:
    csl_player = await get_csl_player(player_name=player_name)
    return (bool(csl_player) and (csl_player.player_existed or False)) or False


async def check_ltsk_orogin_ygg_exists(player_name: str) -> bool:
    return bool(await get_ygg_player(player_type="ltsk", player_name=player_name, origin=True))


async def check_ltsk_origin_csl_exists(player_name: str) -> bool:
    csl_player = await get_csl_player(player_name=player_name, origin=True)
    return (bool(csl_player) and (csl_player.player_existed or False)) or False


async def get_ygg_skin_hash(player_name: str) -> tuple[str | None, str | None]:
    player = await get_ygg_player(player_type="ltsk", player_name=player_name)
    if not player:
        return None, None
    return player.skin.hash if player.skin else None, player.cape.hash if player.cape else None


async def get_csl_skin_hash(player_name: str) -> tuple[str | None, str | None]:
    player = await get_csl_player(player_name=player_name)
    if not player:
        return None, None
    return player.skin_hash, player.cape_hash


async def get_ygg_origin_skin_hash(player_name: str) -> tuple[str | None, str | None]:
    player = await get_ygg_player(player_type="ltsk", player_name=player_name)
    if not player:
        return None, None
    return player.skin.hash if player.skin else None, player.cape.hash if player.cape else None


async def get_csl_origin_skin_hash(player_name: str) -> tuple[str | None, str | None]:
    player = await get_csl_player(player_name=player_name)
    if not player:
        return None, None
    return player.skin_hash, player.cape_hash


def translate_bool(value: bool, yes_word: str = "", no_word: str = "不") -> str:
    return yes_word if value else no_word


check = on_alconna(
    Alconna(
        f"{S_.command_prompt}check",
        Args["player_name#角色名", str],
        meta=CommandMeta(
            description="Check player profile, such as existence and skin hash.",
            usage=rf"{S_.command_prompt}check <player_name>",
            example=rf"{S_.command_prompt}check jeb_",
        ),
    ),
    rule=in_preset_cafe,
    permission=admin_only,
)


@check.handle()
async def check_profile(player_name: Match[str]):
    messages = [f"🔍 {player_name.result} \t的检查报告", ""]

    ygg_profile: PlayerProfile | None = None
    pro_profile: PlayerProfile | None = None
    csl_profile: CustomSkinLoaderApi | None = None

    # CSL
    try:
        csl_profile = await get_csl_player(player_name=player_name.result)
        if csl_profile is None or not csl_profile.player_existed:
            messages.append("❌ CSL: 玩家不存在")
        else:
            messages.append("✅ CSL: 玩家存在")
    except Exception as e:
        messages.append(f"❌ CSL: 发生错误 👇\n {e}")
        logger.exception(traceback.format_exc())
    finally:
        messages.append("")

    # Ygg LittleSkin
    try:
        ygg_profile = await get_ygg_player(player_type="ltsk", player_name=player_name.result)
        if ygg_profile.name != player_name.result:
            messages.append(f"⚠️ Ygg: 玩家名存在大小写错误 👉 {ygg_profile.name}")
        messages.append("✅ Ygg: 玩家存在")

        if ygg_profile.skin is None:
            messages.append("❌ Ygg: 未设置皮肤")
        else:
            async with httpx.AsyncClient(http2=True, follow_redirects=True) as client:
                response = await client.get(str(ygg_profile.skin.url))
                response.raise_for_status()
                if not check_image_size_64(response.content):
                    messages.extend(("⚠️ Ygg: 非标准 64x64 皮肤", "🤖 原版 MC 不支持非标准皮肤"))

    except PlayerNotFoundError:
        messages.append("❌ Ygg: 不存在")
    except Exception as e:
        messages.append(f"❌ Ygg: 发生错误 👇\n {e}")
    finally:
        messages.append("")

    # Ygg Minecraft.net
    try:
        pro_profile = await get_ygg_player(player_type="pro", player_name=player_name.result)
        messages.append(f"⚠️ 正版: 存在同名角色 👉 {pro_profile.name} / {pro_profile.id}")
    except PlayerNameInvalidError:
        messages.append("❔ 正版: 预检: 玩家名含有无效字符 | 可忽略")
    except PlayerNotFoundError:
        messages.append("✅ 正版: 不存在同名角色")
    except Exception as e:
        messages.append(f"❌ 正版: 发生错误 👇\n {e}")
    finally:
        messages.append("")
    # endregion

    await check.send(UniMessage("\n".join(messages)), reply_to=True)
