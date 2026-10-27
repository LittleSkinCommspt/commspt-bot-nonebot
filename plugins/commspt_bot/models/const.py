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
from yggdrasil_mc.exceptions import PlayerNotFoundError  # re-export 供子插件使用
from yggdrasil_mc.models import PlayerProfile

from plugins.commspt_bot.config import S_
from plugins.commspt_bot.utils.request_logging import external_request

from .csl_api import CustomSkinLoaderApi

LTSK_YGG_ENDPOINT = "https://littleskin.cn/api/yggdrasil"
LTSK_CSL_ENDPOINT = "https://littleskin.cn/csl"
PRO_YGG_ENDPOINT = "https://api.mojang.com"
"""Mojang 官方 API 根地址（SDK 未配置 api_root 时使用，同时作为日志地址兜底）。"""

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


# 业务性结果不记为请求失败：
# - PlayerNotFoundError：SDK 在 204/400/404 时抛出的「查无此人」；
# - PlayerNameInvalidError：正版角色名非法，正常在发请求前的本地预检就已抛出。
_YGG_NON_FAILURES: tuple[type[BaseException], ...] = (PlayerNotFoundError, PlayerNameInvalidError)


def _ygg_log_target(player_type: Literal["pro", "ltsk"], origin: bool) -> tuple[str, str]:
    """返回 (服务名, 接口根地址) 供请求日志使用。

    地址只取配置好的接口根地址：SDK 异常自身带 ``request`` 时日志优先用真实 URL，
    这里的值仅作为「异常不带 request」时的明确兜底，绝不臆造完整请求地址。
    """
    if player_type == "pro":
        return "Mojang 正版 API", PRO_YGG_ENDPOINT
    if origin:
        return "LittleSkin 源站 Yggdrasil API", LTSK_ORIGIN_YGG_ENDPOINT
    return "LittleSkin Yggdrasil API", LTSK_YGG_ENDPOINT


async def get_csl_player(player_name: str, origin: bool = False) -> CustomSkinLoaderApi | None:
    """通过 CSL API 获取玩家皮肤加载配置。"""
    # 请求日志由 CustomSkinLoaderApi.get 内部的作用域负责（地址取实际请求的 CSL URL）
    if origin:
        return await LTSK_CSL.get(api_root=LTSK_ORIGIN_CSL_ENDPOINT, username=player_name)
    return await LTSK_CSL.get(api_root=LTSK_CSL_ENDPOINT, username=player_name)


async def get_ygg_player(
    player_type: Literal["pro", "ltsk"],
    player_name: str,
    origin: bool = False,
) -> PlayerProfile:
    """通过 Yggdrasil API 查询正版（Mojang）或 LittleSkin 玩家 Profile。"""
    if player_type == "pro" and not set(player_name).issubset(PRO_ALLOWED_CHARS):
        # 本地预检失败：不发任何请求，因此不进入请求日志作用域
        raise PlayerNameInvalidError("pre-check: player_name contains invalid chars")

    service, endpoint = _ygg_log_target(player_type, origin)
    # 请求日志作用域覆盖「请求 + 响应解析」：SDK 内部的 httpx 异常自带真实 URL；
    # 解析类异常（无 request）以接口根地址兜底；查无此人属于业务结果，不记录。
    with external_request(service, endpoint, non_failures=_YGG_NON_FAILURES):
        if player_type == "pro":
            return await PRO_YGG.by_name_async(player_name)
        if origin:
            return await LTSK_ORIGIN_YGG.by_name_async(player_name)
        return await LTSK_YGG.by_name_async(player_name)
