"""MongoDB 数据库管理工具

用于持久化存储与查询 QQ 号与 LittleSkin UID 的绑定关系。

主要接口：
- write_uid_db: 写入或更新 QQ 与 LittleSkin UID 的映射记录
- get_uid_db: 根据 QQ 号查询关联的 LittleSkin UID
"""

from datetime import datetime

import pytz
from motor.motor_asyncio import AsyncIOMotorClient

from plugins.commspt_bot.config import S_


async def write_uid_db(uid: int | str, qq: int | str):
    """写入或更新 QQ 号与 LittleSkin UID 的映射记录及更新时间戳"""
    # make sure int: 确保 UID 与 QQ 为整数类型以保证查询与索引一致性
    uid = int(uid) if not isinstance(uid, int) else uid
    qq = int(qq) if not isinstance(qq, int) else qq

    # 客户端生命周期管理：按需创建异步连接，并在操作完成后显式关闭释放连接池
    mongo = AsyncIOMotorClient(S_.db_mongo.url)
    coll = mongo["commspt-bot"]["uid"]
    i = await coll.find_one({"qq": qq})

    r = {"uid": uid, "qq": qq, "last_update": datetime.now(tz=pytz.UTC).timestamp()}

    if i:
        await coll.update_one({"qq": qq}, {"$set": r})
    else:
        await coll.insert_one(r)

    # 操作结束显式关闭 Motor 客户端连接
    mongo.close()


async def get_uid_db(qq: int | str) -> int | None:
    """根据 QQ 号查询绑定的 LittleSkin UID，未找到则返回 None"""
    # make sure int: 确保 QQ 号为整数类型
    qq = int(qq) if not isinstance(qq, int) else qq

    # 客户端生命周期管理：按需创建异步连接，并在查询完成后显式关闭
    mongo = AsyncIOMotorClient(S_.db_mongo.url)
    coll = mongo["commspt-bot"]["uid"]
    i = await coll.find_one({"qq": qq})

    mongo.close()

    return i["uid"] if i else None
