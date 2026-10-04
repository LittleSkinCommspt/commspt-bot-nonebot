"""Browserless 网页截图工具

通过 Jinja2 模板渲染 HTML 并调用 Browserless API 渲染网页为图片。

主要接口：
- screenshot: 异步渲染 Jinja2 模板并截图返回 PNG 图片字节流
"""

import json

import httpx
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

from plugins.commspt_bot.config import S_, TEMPLATE_DIR, VERIFY_CONTENT


async def screenshot(
    template_name: str,
    width: int = 530,
    height: int = 800,
    is_mobile: bool = True,
    device_scale_factor: float = 2.5,
    **params,
) -> bytes:
    """使用 Jinja2 模板渲染页面并调用 Browserless 服务截图为 PNG 字节流"""
    # Jinja2 render: 从项目模板目录 TEMPLATE_DIR 加载指定模板文件
    jinja_env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    template = jinja_env.get_template(name=template_name)
    html = template.render(params.model_dump()) if isinstance(params, BaseModel) else template.render(params)

    # send request to /screenshot
    # 使用系统证书存储，并通过 ALPN 支持 h2 与 http/1.1。
    async with httpx.AsyncClient(
        base_url=S_.api_browserless.endpoint,
        verify=VERIFY_CONTENT,
        http2=True,
        timeout=20,
    ) as client:
        resp = await client.post(
            "/screenshot",
            params={
                # Chromium 启动参数：忽略证书错误以兼容自签名环境，并开启无头模式
                "launch": json.dumps(
                    {
                        "args": ["--ignore-certificate-errors"],
                        "ignoreHTTPSErrors": True,
                        "headless": True,
                    },
                ),
            },
            json={
                "html": html,
                "options": {"type": "png"},
                # 视口配置：指定截图分辨率、移动端视口模拟及设备像素比（高 DPI 保证渲染清晰度）
                "viewport": {
                    "width": width,
                    "height": height,
                    "isMobile": is_mobile,
                    "deviceScaleFactor": device_scale_factor,
                },
                # 请求头配置与页面加载策略：设置中文语言偏好，并等待网络连接空闲（networkidle0）确保静态资源加载完成
                "setExtraHTTPHeaders": {"Accept-Language": "zh-CN,en;q=0.9"},
                "gotoOptions": {"waitUntil": ["networkidle0"]},
            },
        )

        # raise exception if status is bad
        resp.raise_for_status()

        # return image from response
        return resp.content
