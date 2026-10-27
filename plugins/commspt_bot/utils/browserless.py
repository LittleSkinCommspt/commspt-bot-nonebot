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

from plugins.commspt_bot.config import ASSETS_DIR, S_, TEMPLATE_DIR, VERIFY_CONTENT
from plugins.commspt_bot.utils.request_logging import external_request

_BROWSERLESS_SERVICE = "Browserless 截图服务"
"""请求日志中的服务名（仅用于 REMOTE 后端的服务端请求）。"""

# 模板资源基址：REMOTE 走内网 CDN；LOCAL 走本地 assets/browserless（file:// 便于 set_content 解析，
# 因 set_content 无 baseURL，相对路径无法解析）。LOCAL 只需字体一个文件，由人工放入该目录（已 gitignore）。
# 图标已内嵌为模板里的 inline SVG，渲染期不再有任何图标 JS/CSS 外链。
_REMOTE_ASSETS_ORIGIN = "https://assets-z1-113a.serinanya.fwnet"
_REMOTE_FONT_URL = f"{_REMOTE_ASSETS_ORIGIN}/MiSans-Bold.ttf"
# LOCAL 资源目录内必须存在的文件（与用户放入的文件名保持约定）
_LOCAL_FONT_FILE = "MiSans-Bold.ttf"


def _resolve_assets() -> dict[str, str]:
    """按渲染模式返回模板资源变量（assets_origin / font_url）。

    LOCAL 模式下要求 assets/browserless 内字体存在，缺失即抛错终止（不静默回退远程，
    否则会拍出缺字体的卡片）。
    """
    if S_.browserless_mode != "LOCAL":
        return {
            "assets_origin": _REMOTE_ASSETS_ORIGIN,
            "font_url": _REMOTE_FONT_URL,
        }

    local_dir = ASSETS_DIR / "browserless"
    if not (local_dir / _LOCAL_FONT_FILE).is_file():
        raise RuntimeError("处理你的请求时发生了一些问题：LOCAL 模式下缺失部分资源文件")
    base = local_dir.resolve().as_uri()
    return {
        "assets_origin": "",  # 本地无需 preconnect
        "font_url": f"{base}/{_LOCAL_FONT_FILE}",
    }


# 本地渲染的空白 file:// 锚点页文件名（放在 assets/browserless 内，随该目录一并被 gitignore）。
# 它仅用于建立一个 file:// 源，见 _screenshot_local 中关于 set_content 安全模型限制的说明。
_LOCAL_ANCHOR_NAME = "_anchor.html"
_LOCAL_ANCHOR_HTML = "<!doctype html><html><head></head><body></body></html>"


async def _ensure_local_anchor() -> str:
    """返回本地空白 file:// 锚点页的 URI；不存在则创建。

    该锚点页只是给 Playwright 一个真实的 ``file://`` 文档源，供后续 ``document.write``
    注入模板 HTML 时，页面能以 file:// 源加载同目录的 file:// 资源（字体）。
    """
    local_dir = ASSETS_DIR / "browserless"
    local_dir.mkdir(parents=True, exist_ok=True)
    anchor_path = local_dir / _LOCAL_ANCHOR_NAME
    if not anchor_path.is_file():
        anchor_path.write_text(_LOCAL_ANCHOR_HTML, encoding="utf-8")
    return anchor_path.resolve().as_uri()


# ---------------------------------------------------------------------------
# LOCAL 渲染后端：常驻 Chromium（懒初始化）
# ---------------------------------------------------------------------------
_LAUNCH_LOCK = asyncio.Lock()
_playwright = None
_browser = None
_FONT_TIMEOUT_SECONDS = 10
# 截图前的就绪判定：字体加载完成 → 再等一帧布局绘制（避免中文/数字用临时回退字体渲染）。
# 模板图标已是内嵌 SVG，渲染期没有需要等待的外部图标脚本，故只剩这两步。
# 合成单次 evaluate，LOCAL 与 REMOTE 两条后端共用同一套判定。
_READY = (
    "async () => { await document.fonts.ready; "
    "await new Promise(resolve => requestAnimationFrame(resolve)); return true; }"
)


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
    full_page: bool = False,
    transparent: bool = False,
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
        # 为什么不用 set_content：
        #   LOCAL 模式下模板的 css/js/字体都指向本地 file:// 资源（assets/browserless）。
        #   ``page.set_content()`` 生成的文档源是「about:blank 不透明源」，Chromium 出于
        #   本地文件安全模型，禁止该源加载任何 file:// 子资源——实测表现为：
        #     · <script src="file://…/all.min.js"> 不执行 → FontAwesome 图标不转换（无图标）
        #     · @import 'file://…/fontawesome.min.css' 不生效 → 无图标样式
        #     · @font-face src=file://… 加载失败（document.fonts 状态为 error）→ 字体回退
        #   该限制由页面源（origin）决定，与 CSP / --disable-web-security / --allow-file-access-from-files
        #   等启动参数无关，无法通过 flag 绕过（已实测均无效）。
        #
        # 因此改为：先 goto 一个静态空白 file:// 锚点页建立「file:// 源」，再 document.write
        # 注入模板 HTML。此时页面源就是 file://，同源 file:// 子资源可正常加载，
        # 图标与字体均生效，且资源保持外链（无需把 JS/字体内联进 HTML）。
        anchor = await _ensure_local_anchor()
        await page.goto(anchor, wait_until="load")
        await page.evaluate(
            "html => { document.open(); document.write(html); document.close(); }",
            html,
        )
        # document.write 后等待子资源（FA 的 JS/CSS、字体）发起并空闲，语义对齐原 set_content 的 networkidle
        await page.wait_for_load_state("networkidle")
        # 字体/图标就绪后再截图（见 _READY）
        await asyncio.wait_for(page.evaluate(_READY), timeout=_FONT_TIMEOUT_SECONDS + 5)
        return await page.screenshot(type="png", full_page=full_page, omit_background=transparent)
    finally:
        await context.close()


async def _screenshot_remote(
    html: str,
    width: int,
    height: int,
    is_mobile: bool,
    device_scale_factor: float,
    full_page: bool = False,
    transparent: bool = False,
) -> bytes:
    """调用远程 Browserless 服务渲染网页为 PNG 图片字节流。"""
    endpoint = S_.api_browserless.endpoint
    # 请求日志作用域只覆盖「本服务自己发出的这一次请求」：不采集 Browserless 服务端
    # 内部拉取页面资源的行为；LOCAL（Playwright）后端纯本地，不进入日志。
    with external_request(_BROWSERLESS_SERVICE, f"{endpoint.rstrip('/')}/screenshot", method="POST") as scope:
        async with httpx.AsyncClient(
            base_url=endpoint,
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
                    "options": {"type": "png", "fullPage": full_page, "omitBackground": transparent},
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
                    "waitForFunction": {"fn": _READY, "timeout": (_FONT_TIMEOUT_SECONDS + 5) * 1000},
                },
            )
            scope.response = resp
            # raise exception if status is bad
            resp.raise_for_status()
            return resp.content


async def screenshot(
    template_name: str,
    width: int = 530,
    height: int = 800,
    is_mobile: bool = True,
    device_scale_factor: float = 2.5,
    full_page: bool = False,
    transparent: bool = False,
    **params,
) -> bytes:
    """渲染模板并返回 PNG；``full_page=True`` 捕获视口之外的完整内容。

    ``transparent=True`` 时页面背景透明（PNG 保留 alpha），截图内容即卡片本体。
    """
    # Jinja2 render: 从项目模板目录 TEMPLATE_DIR 加载指定模板文件
    jinja_env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    template = jinja_env.get_template(name=template_name)
    # 资源基址按渲染后端注入（REMOTE→内网 CDN；LOCAL→本地 assets/browserless，缺失即报错）
    assets = _resolve_assets()
    base_ctx = params.model_dump() if isinstance(params, BaseModel) else dict(params)
    html = template.render({**base_ctx, "transparent": transparent, **assets})

    if S_.browserless_mode == "LOCAL":
        return await _screenshot_local(html, width, height, is_mobile, device_scale_factor, full_page, transparent)
    return await _screenshot_remote(html, width, height, is_mobile, device_scale_factor, full_page, transparent)


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
