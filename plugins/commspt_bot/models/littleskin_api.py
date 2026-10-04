"""LittleSkin 管理端用户数据模型与查询接口。

封装 LittleSkin 管理端 API（/api/admin/users），支持按查询字符串、QQ 邮箱或 UID 查询用户信息。
从 Avilla 原版移植，调用时使用配置的管理员 Bearer Token 进行鉴权。

主要接口：
- LittleSkinUser: LittleSkin 管理端返回的用户数据模型
- LittleSkinUser.query: 调用管理端 API 执行通用用户查询
- LittleSkinUser.qmail_api: 按 QQ 邮箱前缀查询用户
- LittleSkinUser.uid_info: 按 LittleSkin UID 查询用户
"""

from datetime import datetime
from typing import Annotated

import arrow
import httpx
from pydantic import (
    AfterValidator,
    BaseModel,
    EmailStr,
    IPvAnyAddress,
    field_validator,
)

from plugins.commspt_bot.config import S_, VERIFY_CONTENT

# 使用 AfterValidator 将时间统一规范化为 Asia/Shanghai 时区的 datetime
StdTime = Annotated[
    datetime,
    AfterValidator(lambda v: arrow.get(v).replace(tzinfo="Asia/Shanghai").datetime),
]


class LittleSkinUser(BaseModel):
    """LittleSkin 管理端 API 返回的用户信息模型。"""

    uid: int
    nickname: str
    email: EmailStr
    locale: str | None = None
    score: int
    avatar: int = 0
    ip: list[IPvAnyAddress]
    is_dark_mode: bool = False

    permission: int = 0
    # 权限等级枚举：
    # Banned = -1 (封禁),
    # Normal = 0 (普通用户),
    # Admin = 1 (管理员),
    # SuperAdmin = 2 (超级管理员),

    last_sign_at: datetime
    register_at: datetime
    verified: bool
    verification_token: str = ""
    salt: str = ""

    ban_reason: str | None = None

    # 在验证前将 API 返回的逗号分隔 IP 字符串切分为列表
    @field_validator("ip", mode="before")
    def validate_ip(cls, v: str):
        return v.split(", ")

    @classmethod
    async def query(cls, query_string: str):
        """调用 LittleSkin 管理端 API (/api/admin/users) 查询用户信息。"""
        # 使用配置的管理员 Token 进行 Bearer 鉴权，并开启 HTTP/2
        async with httpx.AsyncClient(
            http2=True,
            headers={"Authorization": f"Bearer {S_.littleskin_admin_token}"},
            verify=VERIFY_CONTENT,
        ) as client:
            api = await client.get("https://littleskin.cn/api/admin/users", params={"q": query_string})
            if data := api.json()["data"]:
                return cls(**data[0])
            return None

    @classmethod
    async def qmail_api(cls, qq: int | str):
        """通过 QQ 邮箱查询绑定的 LittleSkin 用户信息。"""
        return await cls.query(f"email:'{qq}@qq.com'")

    @classmethod
    async def uid_info(cls, uid: int | str):
        """通过 LittleSkin UID 查询用户信息。"""
        return await cls.query(f"uid:{uid}")
