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
        # 使用配置的 CA 证书内容（VERIFY_CONTENT）进行 SSL 校验，开启 HTTP/2 访问 API 端点
        async with httpx.AsyncClient(
            verify=VERIFY_CONTENT, base_url=S_.api_bingling_ipip.endpoint, http2=True,
        ) as client:
            resp = await client.get(f"/{ip}")
        return cls(**resp.json())
