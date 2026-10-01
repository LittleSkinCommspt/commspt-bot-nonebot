"""MongoDB 数据库数据模型与持久化封装。

封装 MongoDB 中的 commspt-bot.uid 集合，用于维护 QQ 号与 LittleSkin UID 的映射关系。
从 Avilla 原版移植，支持按 QQ 号或 UID 查询绑定记录，以及执行 upsert 更新。

主要接口：
- UIDMapping: QQ 与 LittleSkin UID 映射模型
- UIDMapping.update: 插入或更新当前映射记录（upsert）
- UIDMapping.fetch: 按 QQ 号或 UID 查询映射记录
"""

from datetime import datetime
from typing import Self

from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, field_serializer

from plugins.commspt_bot.config import S_


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
        """将当前映射记录持久化到 MongoDB（存在则更新，不存在则插入）。"""
        mongo = AsyncIOMotorClient(S_.db_mongo.url)
        coll = mongo["commspt-bot"]["uid"]
        query = {"qq": self.qq}
        data = self.model_dump()
        # MongoDB upsert 分支：已存在记录则更新，否则新增记录
        if await coll.find_one(query):
            _ = await coll.update_one(query, {"$set": data})
        else:
            _ = await coll.insert_one(data)
        mongo.close()

    @classmethod
    async def fetch(cls, qq: int | None = None, uid: int | None = None) -> Self | None:
        """按 QQ 号或 LittleSkin UID 从 MongoDB 查询绑定映射。"""
        mongo = AsyncIOMotorClient(S_.db_mongo.url)
        coll = mongo["commspt-bot"]["uid"]
        if qq:
            if data := await coll.find_one({"qq": qq}):
                return cls(**data)
        elif uid and (data := await coll.find_one({"uid": uid})):
            return cls(**data)
        mongo.close()
        return None
