"""用户信息卡片渲染数据模型与图片生成。

整合 LittleSkin 用户数据、QQ 绑定信息与 IP 属地，构建用户信息卡片的渲染上下文。
从 Avilla 原版移植，通过 Browserless 将 HTML/Jinja 模板渲染为用户资料卡片图片。

主要接口：
- HumanReadableTime: 格式化为可读字符串的时间类型
- RenderUserInfo: 用户信息卡片渲染上下文模型
- RenderUserInfo.get_image: 查询 IP 属地并通过浏览器无头服务截图生成卡片图片
"""

from datetime import datetime
from typing import Annotated

import arrow
from pydantic import BaseModel, EmailStr, Field, IPvAnyAddress, computed_field
from pydantic.functional_serializers import PlainSerializer

from plugins.commspt_bot.models.bingling_ipip import BingLingIPIP
from plugins.commspt_bot.utils.browserless import screenshot

# 使用 PlainSerializer 序列化为 YYYY-MM-DD HH:mm:ss 格式字符串的人类可读时间类型
HumanReadableTime = Annotated[
    datetime,
    PlainSerializer(lambda t: arrow.get(t).format("YYYY-MM-DD HH:mm:ss")),
    Field(default_factory=datetime.now),
]


class RenderUserInfo(BaseModel):
    """用于渲染用户信息卡片的数据上下文模型。"""

    generated_at: HumanReadableTime
    uid: int
    permission: int
    score: int
    nickname: str
    network: str = ""

    qq: int | None = None
    qq_nickname: str = ""

    register_at: HumanReadableTime
    last_sign_at: HumanReadableTime

    email: EmailStr
    verified: bool

    ip: list[Annotated[str, IPvAnyAddress]]

    ban_reason: str | None = None

    # 计算字段：根据邮箱验证状态与大小写规则动态生成辅助提示说明
    @computed_field
    def email_help(self) -> str:
        """生成邮箱验证与格式提示文本。"""
        v: list[str] = []
        v.append("已验证" if self.verified else "未验证")
        if self.email.lower() != self.email:
            v.append("⚠️ 含有大写字母 ⚠️ ")
        return " / ".join(v)

    async def get_image(self) -> bytes:
        """整合 IP 属地并调用 Browserless 服务渲染用户资料卡片截图。"""
        # 获取 IP 属地信息
        ipip = await BingLingIPIP.get(self.ip[0])
        self.network = f"{ipip.country_name}{ipip.region_name}{ipip.city_name} {ipip.isp_domain}{ipip.owner_domain}"

        return await screenshot("user-info.html.jinja", **self.model_dump(), height=750 if self.qq else 600)
