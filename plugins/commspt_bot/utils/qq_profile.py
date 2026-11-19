"""QQ 账号资料查询工具

通过 OneBot V11 API 获取 QQ 账号的公开资料，用于出图展示。
与绑定关系无关，可在任意出图场景复用。

资料属于纯展示字段，查询使用 3 秒短超时：协议端无响应时不阻塞出图主流程。

``get_stranger_info`` 的标准字段只有 ``nickname`` / ``sex`` / ``age``；等级、注册时间、
个性签名是各协议端的扩展字段，命名也不统一。这里按常见命名逐个尝试，取不到就留空，
由模板决定不展示——绝不编造或推断。

主要接口：
- QQProfile: 一次查询得到的 QQ 公开资料（缺失字段为空值）
- parse_stranger_info: 把 ``get_stranger_info`` 的返回解析为 QQProfile（纯函数）
- get_qq_profile: 查询指定 QQ 的公开资料，失败时返回空资料
- get_qq_nickname: 查询指定 QQ 的全局昵称，失败时返回空字符串
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot

_LEVEL_KEYS = ("level", "qqLevel", "qq_level")
_REG_TIME_KEYS = ("reg_time", "regTime", "RegisterTime")
_SIGN_KEYS = ("long_nick", "longNick", "sign")


@dataclass(frozen=True, slots=True)
class QQProfile:
    """QQ 公开资料；协议端没给的字段保持空值（``""`` / ``None``）。

    - sex: 原样保留协议端的 ``male`` / ``female``，其它取值一律视为未知（空串）
    - registered_at: QQ 号注册时间（UTC），协议端未提供时为 ``None``
    """

    nickname: str = ""
    level: int | None = None
    sex: str = ""
    age: int | None = None
    registered_at: datetime | None = None
    sign: str = ""


def _positive_int(value: Any) -> int | None:
    """取正整数；bool、非数字、非正数一律视为缺失。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdecimal():
        value = int(value.strip())
    if isinstance(value, int) and value > 0:
        return value
    return None


def _first(info: dict, keys: tuple[str, ...]) -> Any:
    """按顺序返回第一个存在且非 None 的字段值。"""
    for key in keys:
        if info.get(key) is not None:
            return info[key]
    return None


def parse_stranger_info(info: dict) -> QQProfile:
    """把 ``get_stranger_info`` 的返回解析为 QQProfile；异常或缺失的字段留空。"""
    nickname = info.get("nickname") or ""
    sex = info.get("sex") if info.get("sex") in ("male", "female") else ""

    age = _positive_int(info.get("age"))
    if age is not None and age >= 150:
        age = None

    registered_at = None
    reg_time = _positive_int(_first(info, _REG_TIME_KEYS))
    if reg_time is not None:
        # 个别协议端给毫秒时间戳
        seconds = reg_time / 1000 if reg_time > 10**12 else reg_time
        try:
            registered_at = datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            registered_at = None

    sign = _first(info, _SIGN_KEYS)
    return QQProfile(
        nickname=nickname if isinstance(nickname, str) else str(nickname),
        level=_positive_int(_first(info, _LEVEL_KEYS)),
        sex=sex,
        age=age,
        registered_at=registered_at,
        sign=sign.strip() if isinstance(sign, str) else "",
    )


async def get_qq_profile(bot: Bot, qq: int | str) -> QQProfile:
    """通过 OneBot V11 ``get_stranger_info`` 获取 QQ 公开资料。

    失败（协议端不支持、目标不可查、网络异常等）时记录告警并返回空资料，
    由调用方决定是否省略展示，不影响出图主流程。

    调用带 3 秒短超时：资料是纯展示字段，协议端无响应时不应阻塞主流程。
    """
    try:
        info = await asyncio.wait_for(bot.get_stranger_info(user_id=int(qq), no_cache=False), timeout=3)
    except Exception as e:
        logger.warning(f"获取 QQ {qq} 资料失败: {e}")
        return QQProfile()
    return parse_stranger_info(info if isinstance(info, dict) else {})


async def get_qq_nickname(bot: Bot, qq: int | str) -> str:
    """获取 QQ 全局昵称，失败时返回空字符串（同 get_qq_profile 的超时与降级口径）。"""
    return (await get_qq_profile(bot, qq)).nickname
