"""云控配置数据模型与获取接口。

封装远程云控配置服务，提供主群自动同意入群、临时入群欢迎消息等动态开关与参数。
从 Avilla 原版移植，通过 HTTP API 定期或按需拉取最新云端配置。

主要接口：
- CloudConfig: 云控配置数据模型
- CloudConfig.fetch: 请求云控端点获取最新配置
"""

from datetime import datetime
from typing import Annotated, Self

import httpx
from pydantic import BaseModel, Field

from plugins.commspt_bot.config import S_, VERIFY_CONTENT
from plugins.commspt_bot.utils.request_logging import external_request

_CLOUDCONFIG_SERVICE = "云控配置"
"""请求日志中的服务名。"""

_CLOUDCONFIG_PATH = "/bot/"
"""云控配置接口路径。"""


class CloudConfig(BaseModel):
    """机器人动态云控配置模型。"""

    enable_auto_accept_join_request_main: bool = False
    enable_temporary_welcome_message_main: bool = False
    temporary_welcome_message_main: str = ""

    timestamp: Annotated[
        float,
        Field(
            default_factory=lambda: datetime.now().astimezone().timestamp(),
        ),
    ]

    @classmethod
    async def fetch(cls) -> Self:
        """请求 {S_.api_cloudconfig.endpoint}/bot/ 获取最新云控配置。"""
        endpoint = S_.api_cloudconfig.endpoint
        # httpx 的 base_url 合并结果（用于日志地址兜底，与真实请求地址一致）
        url = f"{endpoint.rstrip('/')}{_CLOUDCONFIG_PATH}"
        # 请求日志作用域覆盖「请求 + 响应解析」：状态码、JSON 与模型校验失败都会被记录
        with external_request(_CLOUDCONFIG_SERVICE, url) as scope:
            # 启用 HTTP/2 与自动重定向请求云控服务端点
            async with httpx.AsyncClient(
                http2=True,
                base_url=endpoint,
                follow_redirects=True,
                verify=VERIFY_CONTENT,
            ) as client:
                resp = await client.get(_CLOUDCONFIG_PATH)
            scope.response = resp
            # 4xx/5xx 单独检测并记录（不改变「照常解析响应体」的既有降级）
            scope.report_http_status()
            return cls(**resp.json())
