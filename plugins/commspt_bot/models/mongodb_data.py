"""MongoDB 数据库数据模型与持久化封装。

封装 MongoDB 中的 commspt-bot.uid 集合，用于维护 QQ 号与 LittleSkin UID 的映射关系。
从 Avilla 原版移植，支持按 QQ 号或 UID 查询绑定记录，以及执行 upsert 更新。

主要接口：
- UIDMapping: QQ 与 LittleSkin UID 映射模型
- UIDMapping.update: 插入或更新当前映射记录（单条原子 upsert）
- UIDMapping.fetch: 按 QQ 号或 UID 查询映射记录
- mongo_failure_address: 请求日志用的连接地址（连接串 + 库/集合元数据）

连接管理：复用进程级共享客户端（见 ``utils.mongo_client``），不再每次操作新建并关闭
客户端。旧实现按需创建客户端、操作完成后 ``close()``，但 ``fetch()`` 命中记录时从
``with`` 块内 ``return``，导致 ``close()`` 永不执行——每次成功查询都会泄漏一个客户端
及其后台监控任务。改用共享客户端后该问题消失，同时省掉每次操作的手握与认证开销。

请求日志（``utils.request_logging``）联动：
- 每个 Mongo 网络边界（``find_one`` / ``update_one``）都包在 ``external_request``
  作用域内，响应数据到模型的解析也在同一作用域，因此连接失败、数据库报错、
  响应字段异常都会按操作名记录一次失败（嵌套 / 重试去重由公共模块负责）；
- 作用域只覆盖网络调用与解析，不覆盖整个业务流程；异常一律原样透传。
"""

from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field, field_serializer

from plugins.commspt_bot.config import S_
from plugins.commspt_bot.utils.mongo_client import get_client
from plugins.commspt_bot.utils.request_logging import external_request

MONGO_SERVICE = "MongoDB 映射数据库"
"""请求日志中的服务名（与重试层使用的一致）。"""

MONGO_DATABASE = "commspt-bot"
MONGO_COLLECTION = "uid"


def mongo_failure_address() -> str:
    """失败记录用的地址：MongoDB 连接串 + 数据库/集合元数据。

    只拼接连接串与库表信息，不额外输出任何凭据：连接串里的 userinfo 由
    ``utils.request_logging`` 统一脱敏为 ``***@主机``，主机与库表名保留以便排障。
    连接串可能带查询参数（``?authSource=...``），因此路径段插在查询串之前。
    """
    base = S_.db_mongo.url.strip()
    target = f"{MONGO_DATABASE}/{MONGO_COLLECTION}"
    if not base:
        return target
    head, sep, query = base.partition("?")
    path = f"{head.rstrip('/')}/{target}"
    return f"{path}?{query}" if sep else path


class UIDMapping(BaseModel):
    """QQ 账号与 LittleSkin UID 绑定映射模型。"""

    uid: int
    qq: int
    last_update: datetime | None = Field(default_factory=datetime.now)
    qmail_verified: bool | None = False

    # 将 datetime 对象序列化为时间戳存入数据库
    @field_serializer("last_update")
    def serialize_last_update(self, value: datetime):
        return value.timestamp()

    async def update(self) -> None:
        """将当前映射记录持久化到 MongoDB（按 qq 原子 upsert，重试幂等）。"""
        coll = get_client()[MONGO_DATABASE][MONGO_COLLECTION]
        data = self.model_dump()
        with external_request(MONGO_SERVICE, mongo_failure_address(), method="update_one"):
            await coll.update_one({"qq": self.qq}, {"$set": data}, upsert=True)

    @classmethod
    async def fetch(cls, qq: int | None = None, uid: int | None = None) -> Self | None:
        """按 QQ 号或 LittleSkin UID 从 MongoDB 查询绑定映射。"""
        coll = get_client()[MONGO_DATABASE][MONGO_COLLECTION]
        address = mongo_failure_address()
        if qq:
            # 查询与「响应数据 -> 模型」解析同处一个作用域：字段异常同样记为一次失败
            with external_request(MONGO_SERVICE, address, method="find_one"):
                if data := await coll.find_one({"qq": qq}):
                    return cls(**data)
        elif uid:
            with external_request(MONGO_SERVICE, address, method="find_one"):
                if data := await coll.find_one({"uid": uid}):
                    return cls(**data)
        return None
