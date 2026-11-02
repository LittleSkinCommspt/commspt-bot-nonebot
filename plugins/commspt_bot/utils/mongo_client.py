"""MongoDB 共享客户端

进程级复用一个 Motor 客户端，避免每次查询/写入都新建连接池：
- 旧实现每次调用 ``AsyncIOMotorClient(...)`` 再 ``close()``，正常路径也要付一次
  握手 + 认证开销；
- 故障期每次调用都要重新经历完整的 serverSelectionTimeout，重试会成倍放大延迟。

超时值取自 ``S_.db_mongo``，连接串中已显式声明的同名选项优先（不覆盖运维设置）。

主要接口：
- get_client: 返回进程级共享客户端（首次调用时创建）
- current_client: 返回已创建的客户端（不触发创建，供测试与诊断）
- close_client: 关闭并重置单例（重复调用安全）
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

from motor.motor_asyncio import AsyncIOMotorClient
from nonebot import get_driver, logger

from plugins.commspt_bot.config import S_

_client: AsyncIOMotorClient | None = None
"""进程级共享客户端；``None`` 表示尚未创建。"""

_TIMEOUT_OPTIONS: tuple[tuple[str, str], ...] = (
    ("connectTimeoutMS", "connect_timeout_ms"),
    ("serverSelectionTimeoutMS", "server_selection_timeout_ms"),
    ("socketTimeoutMS", "socket_timeout_ms"),
)
"""（客户端参数名, 配置字段名）对照表。"""


def _declared_options(url: str) -> set[str]:
    """返回连接串查询参数里已显式声明的选项名（小写）。

    用于避免用配置默认值覆盖运维在连接串中写入的显式设置。
    """
    try:
        query = urlsplit(url).query
    except ValueError:
        return set()
    return {key.lower() for key, _ in parse_qsl(query, keep_blank_values=True)}


def _timeout_kwargs(url: str) -> dict[str, int]:
    """按配置生成超时参数，跳过连接串中已声明的选项。"""
    declared = _declared_options(url)
    cfg = S_.db_mongo
    kwargs: dict[str, int] = {}
    for option, attr in _TIMEOUT_OPTIONS:
        if option.lower() in declared:
            continue
        kwargs[option] = int(getattr(cfg, attr))
    return kwargs


def get_client() -> AsyncIOMotorClient:
    """返回进程级共享的 Motor 客户端（首次调用时创建）。"""
    global _client
    if _client is not None:
        return _client
    url = S_.db_mongo.url.strip()
    if not url:
        raise RuntimeError("未配置 DB_MONGO__URL，无法访问 QQ↔UID 映射数据库")
    _client = AsyncIOMotorClient(url, **_timeout_kwargs(url))
    logger.info("MongoDB 共享客户端已创建")
    return _client


def current_client() -> AsyncIOMotorClient | None:
    """返回已创建的共享客户端；未创建时返回 ``None``（不触发创建）。"""
    return _client


async def close_client() -> None:
    """关闭共享客户端并重置单例；重复调用安全。"""
    global _client
    client, _client = _client, None
    if client is not None:
        client.close()
        logger.info("MongoDB 共享客户端已关闭")


@get_driver().on_shutdown
async def _shutdown() -> None:
    """应用关闭时释放连接池。"""
    await close_client()
