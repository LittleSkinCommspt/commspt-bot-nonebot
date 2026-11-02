"""MongoDB 数据库管理工具

用于持久化存储与查询 QQ 号与 LittleSkin UID 的绑定关系。

主要接口：
- write_uid_db: 写入或更新 QQ 与 LittleSkin UID 的映射记录
- get_uid_db: 根据 QQ 号查询关联的 LittleSkin UID

连接管理：复用进程级共享客户端（见 ``utils.mongo_client``），不再每次操作新建并关闭
客户端。共享客户端省掉了每次调用的握手 + 认证开销，故障期也不会因反复重连而成倍
放大 ``serverSelectionTimeout`` 的等待；连接的释放在应用关闭时统一完成。

写入语义：``write_uid_db`` 使用单条原子 upsert（``update_one(..., upsert=True)``），
重试幂等（``insert_one`` 重试可能产生重复行），并省掉一次 ``find_one`` 往返。

请求日志（``utils.request_logging``）联动：
- 每个 Mongo 网络边界（``find_one`` / ``update_one``）都包在
  ``external_request`` 作用域内，按操作名记录失败；地址为连接串 + 库/集合元数据
  （连接串里的凭据由公共模块脱敏）；
- 未使用的 ``get_uid_db`` 同样覆盖，避免后续启用时成为日志盲区；
- 作用域只覆盖单次数据库操作，不覆盖业务流程，异常原样透传。
"""

from datetime import datetime

import pytz

from plugins.commspt_bot.models.mongodb_data import (
    MONGO_COLLECTION,
    MONGO_DATABASE,
    MONGO_SERVICE,
    mongo_failure_address,
)
from plugins.commspt_bot.utils.mongo_client import get_client
from plugins.commspt_bot.utils.request_logging import external_request


async def write_uid_db(uid: int | str, qq: int | str):
    """写入或更新 QQ 号与 LittleSkin UID 的映射记录及更新时间戳。

    使用单条原子 upsert：重试幂等（``insert_one`` 重试可能产生重复行），
    且省掉一次 ``find_one`` 往返。``$set`` 不含 ``qmail_verified``，
    因此管理端 ``&setuid`` 不会覆盖既有的邮箱验证状态。
    """
    uid = int(uid) if not isinstance(uid, int) else uid
    qq = int(qq) if not isinstance(qq, int) else qq

    coll = get_client()[MONGO_DATABASE][MONGO_COLLECTION]
    record = {"uid": uid, "qq": qq, "last_update": datetime.now(tz=pytz.UTC).timestamp()}
    with external_request(MONGO_SERVICE, mongo_failure_address(), method="update_one"):
        await coll.update_one({"qq": qq}, {"$set": record}, upsert=True)


async def get_uid_db(qq: int | str) -> int | None:
    """根据 QQ 号查询绑定的 LittleSkin UID，未找到则返回 None"""
    # make sure int: 确保 QQ 号为整数类型
    qq = int(qq) if not isinstance(qq, int) else qq

    coll = get_client()[MONGO_DATABASE][MONGO_COLLECTION]

    with external_request(MONGO_SERVICE, mongo_failure_address(), method="find_one"):
        i = await coll.find_one({"qq": qq})

    return i["uid"] if i else None
