"""Minecraft 角色查询与皮肤服务常量及客户端封装。

封装 LittleSkin 线上/自有源（origin）的 Yggdrasil 与 CSL 接口及 Mojang 正版验证客户端。
从 Avilla 原版移植，供 NoneBot 子插件统一获取玩家皮肤材质与 Yggdrasil Profile。

主要接口：
- LTSK_YGG / LTSK_ORIGIN_YGG / PRO_YGG: LittleSkin 与 Mojang 官方 Yggdrasil 客户端单例
- PlayerNameInvalidError: 正版角色名字符合法性校验异常
- get_csl_player: 通过 CSL API 查询 LittleSkin 玩家皮肤信息
- get_ygg_player: 通过 Yggdrasil API 查询正版或 LittleSkin 玩家 Profile
"""

import string
from typing import Literal
from urllib.parse import urljoin

from pytz import timezone
from yggdrasil_mc.client import YggdrasilMC
from yggdrasil_mc.exceptions import PlayerNotFoundError  # noqa: F401  re-export 供子插件使用
from yggdrasil_mc.models import PlayerProfile

from plugins.commspt_bot.config import S_

from .csl_api import CustomSkinLoaderApi

LTSK_YGG_ENDPOINT = "https://littleskin.cn/api/yggdrasil"
LTSK_CSL_ENDPOINT = "https://littleskin.cn/csl"

# 由配置派生自有源（origin）端点
LTSK_ORIGIN_YGG_ENDPOINT = urljoin(S_.api_littleskin_origin.endpoint, "/api/yggdrasil")
LTSK_ORIGIN_CSL_ENDPOINT = urljoin(S_.api_littleskin_origin.endpoint, "/csl")

LTSK_YGG = YggdrasilMC(api_root=LTSK_YGG_ENDPOINT)
LTSK_ORIGIN_YGG = YggdrasilMC(api_root=LTSK_ORIGIN_YGG_ENDPOINT)
PRO_YGG = YggdrasilMC()
TZ_SHANGHAI = timezone("Asia/Shanghai")
LTSK_CSL = CustomSkinLoaderApi

# Mojang 正版角色名合法字符集白名单（字母、数字、下划线、减号）
PRO_ALLOWED_CHARS = set(string.ascii_letters + string.digits + "_-")


class PlayerNameInvalidError(ValueError):
    """正版角色名包含非法字符时抛出的异常。"""

    def __init__(self, message):
        super().__init__(message)


async def get_csl_player(player_name: str, origin: bool = False) -> CustomSkinLoaderApi | None:
    """通过 CSL API 获取玩家皮肤加载配置。"""
    if origin:
        return await LTSK_CSL.get(api_root=LTSK_ORIGIN_CSL_ENDPOINT, username=player_name)
    return await LTSK_CSL.get(api_root=LTSK_CSL_ENDPOINT, username=player_name)


async def get_ygg_player(
    player_type: Literal["pro", "ltsk"],
    player_name: str,
    origin: bool = False,
) -> PlayerProfile:
    """通过 Yggdrasil API 查询正版（Mojang）或 LittleSkin 玩家 Profile。"""
    if player_type == "pro":
        if not set(player_name).issubset(PRO_ALLOWED_CHARS):
            raise PlayerNameInvalidError("pre-check: player_name contains invalid chars")
        return await PRO_YGG.by_name_async(player_name)
    if origin:
        return await LTSK_ORIGIN_YGG.by_name_async(player_name)
    return await LTSK_YGG.by_name_async(player_name)
