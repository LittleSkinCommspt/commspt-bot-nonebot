"""IP 属地查询服务数据模型与请求封装。

封装冰凌 IP 归属地查询 API（IPIP 服务），用于解析 IP 地址的地理位置与运营商归属。
从 Avilla 原版移植，支持通过自定义 SSL 根证书与 HTTP/2 协议调用内部/代理接口。

主要接口：
- BingLingIPIP: IP 地理信息数据模型
- BingLingIPIP.get: 请求 API 获取指定 IP 的归属地信息
"""

import httpx
from pydantic import BaseModel

from plugins.commspt_bot.config import S_, VERIFY_CONTENT
from plugins.commspt_bot.utils.request_logging import external_request

_IPIP_SERVICE = "冰凌 IP 属地 API"
"""请求日志中的服务名。"""


class BingLingIPIP(BaseModel):
    """IP 归属地与网络运营商信息模型。"""

    country_name: str | None = None
    region_name: str | None = None
    city_name: str | None = None
    owner_domain: str | None = None
    isp_domain: str | None = None
    latitude: str | None = None
    longitude: str | None = None
    china_region_code: str | None = None
    china_district_code: str | None = None
    country_code: str | None = None
    continent_code: str | None = None

    @classmethod
    async def get(cls, ip: str):
        """获取指定 IP 的地理位置与网络信息。

        ```json
        {
            "country_name": "中国",
            "region_name": "湖北",
            "city_name": "武汉",
            "owner_domain": "",
            "isp_domain": "移动",
            "latitude": "30.572399",
            "longitude": "114.279121",
            "china_region_code": null,
            "china_district_code": null,
            "country_code": "CN",
            "continent_code": "AP"
        }
        ```
        """
        endpoint = S_.api_bingling_ipip.endpoint
        # httpx 的 base_url 合并结果（用于日志地址兜底，与真实请求地址一致）
        url = f"{endpoint.rstrip('/')}/{ip}"
        # 请求日志作用域覆盖「请求 + 响应解析」：超时 / 状态码 / JSON 与模型校验失败都会落盘
        with external_request(_IPIP_SERVICE, url) as scope:
            # 使用系统证书存储进行 SSL 校验，开启 HTTP/2 访问 API 端点
            async with httpx.AsyncClient(
                verify=VERIFY_CONTENT,
                base_url=endpoint,
                http2=True,
            ) as client:
                resp = await client.get(f"/{ip}")
            scope.response = resp
            # 4xx/5xx 单独检测并记录（不改变「照常解析响应体」的既有降级）
            scope.report_http_status()
            return cls(**resp.json())
