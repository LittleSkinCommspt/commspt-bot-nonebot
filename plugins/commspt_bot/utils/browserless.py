"""Browserless 网页截图工具

通过 Jinja2 模板渲染 HTML，并按 ``BROWSERLESS_MODE`` 选择渲染后端：
- ``REMOTE``（默认）: 调用 Browserless HTTP 服务（POST /screenshot）
- ``LOCAL``: 使用本地 Playwright + Chromium 渲染（需安装可选依赖 render-local）
            安装方式：``uv sync --extra render-local && uv run playwright install chromium``

主要接口：
- screenshot: 异步渲染 Jinja2 模板并截图返回 PNG 图片字节流
"""

from __future__ import annotations

import asyncio
import json

import httpx
from jinja2 import Environment, FileSystemLoader
from nonebot import get_driver, logger
from pydantic import BaseModel

from plugins.commspt_bot.config import S_, TEMPLATE_DIR, VERIFY_CONTENT

# ---------------------------------------------------------------------------
# LOCAL 渲染后端：常驻 Chromium（懒初始化）
# ---------------------------------------------------------------------------
_LAUNCH_LOCK = asyncio.Lock()
_playwright = None
_browser = None


async def _ensure_browser():
    """懒初始化并返回常驻 Chromium 实例（首次调用时启动 Playwright）。"""
    global _playwright, _browser
    if _browser is not None:
        return _browser

    async with _LAUNCH_LOCK:
        if _browser is not None:
            return _browser
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            # LOCAL 模式缺少可选依赖时给出明确指引
            raise RuntimeError(
                "BROWSERLESS_MODE=LOCAL 需要安装 playwright："
                "uv sync --extra render-local && uv run playwright install chromium",
            ) from exc
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(
            headless=True,
            args=["--ignore-certificate-errors"],
        )
        logger.info("本地 Playwright Chromium 已启动（BROWSERLESS_MODE=LOCAL）")
        return _browser


async def _screenshot_local(
    html: str,
    width: int,
    height: int,
    is_mobile: bool,
    device_scale_factor: float,
) -> bytes:
    """使用本地 Playwright 渲染 HTML 并截图为 PNG 字节流。"""
    browser = await _ensure_browser()
    # 视口配置与远程 Browserless 请求保持一致：分辨率、移动端模拟、设备像素比
    context = await browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=device_scale_factor,
        is_mobile=is_mobile,
        ignore_https_errors=True,
        locale="zh-CN",
        extra_http_headers={"Accept-Language": "zh-CN,en;q=0.9"},
    )
    try:
        page = await context.new_page()
        # 等待网络空闲（networkidle）确保静态资源加载完成，再按视口截图
        await page.set_content(html, wait_until="networkidle")
        return await page.screenshot(type="png")
    finally:
        await context.close()


async def _screenshot_remote(
    html: str,
    width: int,
    height: int,
    is_mobile: bool,
    device_scale_factor: float,
) -> bytes:
    """调用远程 Browserless 服务渲染网页为 PNG 图片字节流。"""
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
        return resp.content


async def screenshot(
    template_name: str,
    width: int = 530,
    height: int = 800,
    is_mobile: bool = True,
    device_scale_factor: float = 2.5,
    **params,
) -> bytes:
    """使用 Jinja2 模板渲染页面并按 ``BROWSERLESS_MODE`` 截图为 PNG 字节流。"""
    # Jinja2 render: 从项目模板目录 TEMPLATE_DIR 加载指定模板文件
    jinja_env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    template = jinja_env.get_template(name=template_name)
    html = template.render(params.model_dump()) if isinstance(params, BaseModel) else template.render(params)

    if S_.browserless_mode == "LOCAL":
        return await _screenshot_local(html, width, height, is_mobile, device_scale_factor)
    return await _screenshot_remote(html, width, height, is_mobile, device_scale_factor)


@get_driver().on_shutdown
async def _close_browser() -> None:
    """应用关闭时释放常驻 Chromium 与 Playwright。"""
    global _playwright, _browser
    if _browser is not None:
        await _browser.close()
        _browser = None
    if _playwright is not None:
        await _playwright.stop()
        _playwright = None
