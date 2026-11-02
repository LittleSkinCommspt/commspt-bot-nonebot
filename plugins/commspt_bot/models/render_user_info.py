"""用户信息卡片渲染数据模型与图片生成。

整合 LittleSkin 用户数据、QQ 绑定信息与 IP 属地，构建用户信息卡片的渲染上下文。
从 Avilla 原版移植，通过 Browserless 将 HTML/Jinja 模板渲染为用户资料卡片图片。

IP 属地属于「可降级展示项」：端点未配置、请求超时、重试耗尽或响应解析失败时，
卡片回落为「未获取」，不影响出图主流程。

主要接口：
- HumanReadableTime: 格式化为可读字符串的时间类型
- RenderUserInfo: 用户信息卡片渲染上下文模型
- RenderUserInfo.get_image: 解析 IP 属地并通过浏览器无头服务截图生成卡片图片
- RenderUserInfo._resolve_network: 解析注册 IP 属地，失败时降级为空串
"""

from datetime import datetime
from typing import Annotated

import arrow
from nonebot import logger
from pydantic import BaseModel, EmailStr, Field, IPvAnyAddress, computed_field
from pydantic.functional_serializers import PlainSerializer

from plugins.commspt_bot.config import S_
from plugins.commspt_bot.models.bingling_ipip import BingLingIPIP
from plugins.commspt_bot.utils.browserless import screenshot
from plugins.commspt_bot.utils.relative_time import humanize_since
from plugins.commspt_bot.utils.retry import call_with_retry

# 使用 PlainSerializer 序列化为 YYYY-MM-DD HH:mm:ss 格式字符串的人类可读时间类型
HumanReadableTime = Annotated[
    datetime,
    PlainSerializer(lambda t: arrow.get(t).format("YYYY-MM-DD HH:mm:ss")),
    Field(default_factory=datetime.now),
]


def _is_dark_at(now: datetime) -> bool:
    """按明确的北京时间窗口判断主题，避免依赖服务器本地时区。"""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Theme clock must include a timezone")
    hour = arrow.get(now).to("Asia/Shanghai").hour
    return not 7 <= hour < 19


def _join_geo(*parts: str | None, sep: str = "") -> str:
    """拼接 IP 属地字段，跳过缺失值。

    IPIP 接口对查不到的字段返回 null，直接 f-string 拼接会把 ``None`` 当文本写进卡片
    （且结果非空，模板里的 ``or '未获取'`` 兜底拦不住）。
    """
    return sep.join(part for part in parts if part)


class RenderUserInfo(BaseModel):
    """用于渲染用户信息卡片的数据上下文模型。"""

    generated_at: HumanReadableTime
    uid: int
    permission: int
    score: int
    nickname: str
    network: str = ""
    is_dark_mode: bool = False

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

    async def get_image(self, *, now: datetime | None = None) -> bytes:
        """整合 IP 属地并调用 Browserless 服务渲染用户资料卡片截图。

        IP 属地是纯展示字段：查询失败（未配置端点、超时、重试耗尽、响应异常）
        只会让卡片显示「未获取」，不阻断出图。
        """
        # IP 属地是纯展示字段：任何失败都降级为「未获取」，绝不阻断出图
        self.network = await self._resolve_network()

        # 以「生成于」为基准的相对时间，供卡片标注注册/签到距今多久
        params = self.model_dump()
        params["register_ago"] = humanize_since(self.generated_at, self.register_at)
        params["last_sign_ago"] = humanize_since(self.generated_at, self.last_sign_at)

        # 最小视口高度配合完整页面截图，避免长昵称/封禁原因被裁切或留下固定高度空白。
        if S_.user_card_auto_theme:
            params["is_dark_mode"] = _is_dark_at(now if now is not None else arrow.utcnow().datetime)
        return await screenshot("user-info.html.jinja", **params, height=1, full_page=True, transparent=True)

    async def _resolve_network(self) -> str:
        """解析注册 IP 属地。

        属地为纯展示字段，任一环节失败都返回空串（模板回落「未获取」）：
        - 无可用 IP（LittleSkin 未返回 IP 列表）；
        - 未配置 IP 属地端点；
        - 查询重试耗尽或响应异常。
        重试次数由 ``S_.failed_retry_time`` 决定，此处不写死次数。
        """
        if not self.ip:
            return ""
        geo_config = getattr(S_, "api_bingling_ipip", None)
        # 配置块整体缺失时无从判定是否启用，交给实际请求失败后降级；
        # 仅当端点被显式配置为空串时才跳过查询。
        if geo_config is not None and not geo_config.endpoint:
            logger.debug("未配置 IP 属地端点，跳过查询")
            return ""
        try:
            ipip = await call_with_retry("冰凌 IP 属地 API", BingLingIPIP.get, str(self.ip[0]))
        except Exception as e:
            logger.warning(f"IP 属地查询失败（卡片显示「未获取」）：{type(e).__name__}: {e}")
            return ""
        region = _join_geo(ipip.country_name, ipip.region_name, ipip.city_name)
        provider = _join_geo(ipip.isp_domain, ipip.owner_domain)
        return " ".join(part for part in (region, provider) if part)
