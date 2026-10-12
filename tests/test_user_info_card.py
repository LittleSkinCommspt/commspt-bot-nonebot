"""用户档案状态、内容转义以及两种截图后端的完整页面契约。"""

import ast
import asyncio
import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock

import pytest
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "plugins/commspt_bot/templates"


@pytest.fixture
def user_data():
    return {
        "generated_at": "2026-10-12 20:00:00",
        "uid": 100001,
        "permission": 0,
        "score": 2048,
        "nickname": "LittleSkin_Demo",
        "network": "中国 · 上海 · 示例网络",
        "qq": 123456789,
        "qq_nickname": "演示用户",
        "register_at": "2024-02-09 14:23:11",
        "last_sign_at": "2026-10-12 19:47:26",
        "email": "123456789@qq.com",
        "verified": True,
        "email_help": "已验证",
        "ban_reason": None,
        "is_dark_mode": False,
    }


@pytest.fixture
def template():
    return Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True).get_template("user-info.html.jinja")


@pytest.mark.parametrize("permission", [0, 1, 2])
def test_active_accounts_show_status_instead_of_permission(template, user_data, permission):
    user_data["permission"] = permission
    html = template.render(user_data)
    assert "账户状态" in html
    assert 'account-badge">正常<' in html
    assert 'class="ban-notice"' not in html


@pytest.mark.parametrize("reason", [None, "", "   \n\t"])
def test_banned_accounts_have_notice_even_without_reason(template, user_data, reason):
    user_data.update(permission=-1, ban_reason=reason)
    html = template.render(user_data)
    assert 'class="record is-banned"' in html
    assert 'account-badge">已封禁<' in html
    assert 'class="ban-notice"' in html
    assert "未提供封禁原因" in html


def test_long_reason_and_user_text_are_preserved_and_escaped(template, user_data):
    reason = "<script>alert(1)</script>\n" + "一段很长的封禁原因。" * 200
    user_data.update(permission=-1, ban_reason=reason, nickname='<img src=x onerror="alert(1)">')
    html = template.render(user_data)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;\n" in html
    assert "一段很长的封禁原因。" * 200 in html
    assert "&lt;img src=x" in html
    assert "<script>" not in html
    assert "<img " not in html


def test_unverified_email_does_not_change_account_status(template, user_data):
    user_data.update(verified=False, email="Demo@example.com", email_help="未验证 / 含有大写字母")
    html = template.render(user_data)
    assert 'account-badge">正常<' in html
    assert 'class="email is-unverified"' in html
    assert "未验证 / 含有大写字母" in html


def test_optional_qq_and_never_signed_in(template, user_data):
    user_data.update(qq=None, qq_nickname="", last_sign_at="2000-01-01 00:00:00")
    html = template.render(user_data)
    assert 'class="qq-grid"' not in html
    assert "从未签到过" in html
    assert "注册 IP 属地" in html


def test_dark_theme_uses_existing_user_preference(template, user_data):
    assert 'data-theme="light"' in template.render(user_data)
    user_data["is_dark_mode"] = True
    assert 'data-theme="dark"' in template.render(user_data)


def test_dates_have_separate_date_and_clock_rows(template, user_data):
    html = template.render(user_data)
    assert 'datetime="2024-02-09T14:23:11"><span>2024-02-09</span><span class="clock">14:23:11</span>' in html
    assert 'datetime="2026-10-12T19:47:26"><span>2026-10-12</span><span class="clock">19:47:26</span>' in html


def test_email_alone_does_not_imply_qq_binding(template, user_data):
    user_data.update(qq=None, email="123456789@qq.com")
    html = template.render(user_data)
    assert 'class="qq-grid"' not in html


def test_shield_only_appears_for_banned_accounts(template, user_data):
    assert 'class="ban-icon"' not in template.render(user_data)
    user_data["permission"] = -1
    assert 'class="ban-icon"' in template.render(user_data)


def load_isolated_module(monkeypatch, name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def renderer(monkeypatch):
    # 不启动机器人、不加载整套插件，也不读取部署配置或访问真实服务。
    nonebot = ModuleType("nonebot")
    nonebot.get_driver = lambda: SimpleNamespace(on_shutdown=lambda callback: callback)
    nonebot.logger = SimpleNamespace(info=lambda *args: None)
    monkeypatch.setitem(sys.modules, "nonebot", nonebot)
    config = ModuleType("plugins.commspt_bot.config")
    config.S_ = SimpleNamespace(
        browserless_mode="REMOTE",
        api_browserless=SimpleNamespace(endpoint="https://example.com"),
        user_card_auto_theme=False,
    )
    config.TEMPLATE_DIR = TEMPLATES
    config.VERIFY_CONTENT = True
    monkeypatch.setitem(sys.modules, "plugins.commspt_bot.config", config)
    return load_isolated_module(monkeypatch, "card_test_browserless", "plugins/commspt_bot/utils/browserless.py")


@pytest.mark.parametrize("full_page", [False, True])
async def test_local_backend_forwards_full_page_and_closes_context(renderer, monkeypatch, full_page):
    events = []

    async def wait_for_fonts(*args):
        events.append("fonts")

    async def capture(*args, **kwargs):
        events.append("capture")
        return b"png"

    page = SimpleNamespace(
        set_content=AsyncMock(),
        evaluate=AsyncMock(side_effect=wait_for_fonts),
        screenshot=AsyncMock(side_effect=capture),
    )
    context = SimpleNamespace(new_page=AsyncMock(return_value=page), close=AsyncMock())
    browser = SimpleNamespace(new_context=AsyncMock(return_value=context))
    monkeypatch.setattr(renderer, "_ensure_browser", AsyncMock(return_value=browser))
    assert await renderer._screenshot_local("<html></html>", 530, 1, True, 2.5, full_page) == b"png"
    page.screenshot.assert_awaited_once_with(type="png", full_page=full_page)
    page.evaluate.assert_awaited_once_with(renderer._FONTS_READY)
    assert events == ["fonts", "capture"]
    context.close.assert_awaited_once()


async def test_font_timeout_prevents_capture_and_closes_context(renderer, monkeypatch):
    async def pending_fonts(*args):
        await asyncio.Event().wait()

    page = SimpleNamespace(
        set_content=AsyncMock(),
        evaluate=AsyncMock(side_effect=pending_fonts),
        screenshot=AsyncMock(return_value=b"png"),
    )
    context = SimpleNamespace(new_page=AsyncMock(return_value=page), close=AsyncMock())
    browser = SimpleNamespace(new_context=AsyncMock(return_value=context))
    monkeypatch.setattr(renderer, "_ensure_browser", AsyncMock(return_value=browser))
    monkeypatch.setattr(renderer, "_FONT_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(TimeoutError):
        await renderer._screenshot_local("<html></html>", 530, 1, True, 2.5, True)
    page.screenshot.assert_not_awaited()
    context.close.assert_awaited_once()


@pytest.mark.parametrize("full_page", [False, True])
async def test_remote_backend_forwards_full_page(renderer, monkeypatch, full_page):
    class Client:
        def __init__(self, **kwargs):
            self.post = AsyncMock(return_value=SimpleNamespace(content=b"png", raise_for_status=lambda: None))
            clients.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    clients = []
    monkeypatch.setattr(renderer.httpx, "AsyncClient", Client)
    assert await renderer._screenshot_remote("<html></html>", 530, 1, True, 2.5, full_page) == b"png"
    payload = clients[0].post.await_args.kwargs["json"]
    assert payload["options"] == {"type": "png", "fullPage": full_page}
    assert payload["viewport"]["height"] == 1
    assert payload["waitForFunction"] == {"fn": renderer._FONTS_READY, "timeout": 10000}


@pytest.mark.parametrize("mode", ["LOCAL", "REMOTE"])
async def test_public_screenshot_keeps_default_and_opt_in(renderer, monkeypatch, user_data, mode):
    local, remote = AsyncMock(return_value=b"png"), AsyncMock(return_value=b"png")
    monkeypatch.setattr(renderer, "_screenshot_local", local)
    monkeypatch.setattr(renderer, "_screenshot_remote", remote)
    renderer.S_.browserless_mode = mode
    backend = local if mode == "LOCAL" else remote
    await renderer.screenshot("user-info.html.jinja", **user_data)
    assert backend.await_args.args[2] == 800
    assert backend.await_args.args[-1] is False
    await renderer.screenshot("user-info.html.jinja", height=1, full_page=True, **user_data)
    assert backend.await_args.args[2] == 1
    assert backend.await_args.args[-1] is True
    assert "LittleSkin_Demo" in backend.await_args.args[0]


async def test_user_card_requests_full_content_and_keeps_dark_mode(renderer, monkeypatch, user_data):
    monkeypatch.setitem(sys.modules, "plugins.commspt_bot.utils.browserless", renderer)
    ipip = ModuleType("plugins.commspt_bot.models.bingling_ipip")
    ipip.BingLingIPIP = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(
                country_name="中国",
                region_name="上海",
                city_name="",
                isp_domain="示例",
                owner_domain="网络",
            )
        )
    )
    monkeypatch.setitem(sys.modules, "plugins.commspt_bot.models.bingling_ipip", ipip)
    model = load_isolated_module(monkeypatch, "card_test_model", "plugins/commspt_bot/models/render_user_info.py")
    screenshot = AsyncMock(return_value=b"png")
    monkeypatch.setattr(model, "screenshot", screenshot)
    data = dict(user_data, ip=["127.0.0.1"], is_dark_mode=True)
    for field in ("generated_at", "register_at", "last_sign_at"):
        data[field] = datetime.fromisoformat(data[field] + "+08:00")
    assert await model.RenderUserInfo(**data).get_image() == b"png"
    assert screenshot.await_args.kwargs["height"] == 1
    assert screenshot.await_args.kwargs["full_page"] is True
    assert screenshot.await_args.kwargs["is_dark_mode"] is True
    assert screenshot.await_args.kwargs["register_at"] == "2024-02-09 14:23:11"
    assert screenshot.await_args.kwargs["last_sign_at"] == "2026-10-12 19:47:26"
    assert screenshot.await_args.kwargs["generated_at"] == "2026-10-12 20:00:00"


@pytest.fixture
def card_model(renderer, monkeypatch):
    monkeypatch.setitem(sys.modules, "plugins.commspt_bot.utils.browserless", renderer)
    ipip = ModuleType("plugins.commspt_bot.models.bingling_ipip")
    ipip.BingLingIPIP = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(
                country_name="中国",
                region_name="上海",
                city_name="",
                isp_domain="示例",
                owner_domain="网络",
            )
        )
    )
    monkeypatch.setitem(sys.modules, ipip.__name__, ipip)
    model = load_isolated_module(monkeypatch, "card_auto_theme_model", "plugins/commspt_bot/models/render_user_info.py")
    monkeypatch.setattr(model, "screenshot", AsyncMock(return_value=b"png"))
    return model


def test_auto_theme_config_defaults_enabled():
    # 执行真实配置 schema，避免加载部署配置、证书或机器人。
    classes = []
    for node in ast.parse((ROOT / "plugins/commspt_bot/config.py").read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ClassDef):
            classes.append(node)
            if node.name == "Setting":
                break
    scope = {"BaseModel": BaseModel, "Literal": Literal}
    exec(compile(ast.Module(body=classes, type_ignores=[]), "config.py", "exec"), scope)  # noqa: S102
    assert scope["Setting"]().user_card_auto_theme is True
    assert scope["Setting"](user_card_auto_theme="false").user_card_auto_theme is False


@pytest.mark.parametrize(
    "timestamp,dark",
    [
        ("2026-10-12T06:59:59+08:00", True),
        ("2026-10-12T07:00:00+08:00", False),
        ("2026-10-12T18:59:59+08:00", False),
        ("2026-10-12T19:00:00+08:00", True),
        ("2026-10-12T22:59:59+00:00", True),
        ("2026-10-12T23:00:00+00:00", False),
        ("2026-10-12T10:59:59+00:00", False),
        ("2026-10-12T11:00:00+00:00", True),
    ],
)
def test_auto_theme_boundaries_and_utc_conversion(card_model, timestamp, dark):
    assert card_model._is_dark_at(datetime.fromisoformat(timestamp)) is dark


def test_auto_theme_rejects_ambiguous_naive_clock(card_model):
    with pytest.raises(ValueError, match="timezone"):
        card_model._is_dark_at(datetime(2026, 10, 12, 7))


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("account_dark", [False, True])
@pytest.mark.parametrize("hour,auto_dark", [(7, False), (19, True)])
async def test_auto_theme_and_account_preference(
    card_model, renderer, user_data, enabled, account_dark, hour, auto_dark
):
    renderer.S_.user_card_auto_theme = enabled
    card = card_model.RenderUserInfo(**dict(user_data, ip=["192.0.2.41"], is_dark_mode=account_dark))
    moment = datetime.fromisoformat(f"2026-10-12T{hour:02}:00:00+08:00")
    assert await card.get_image(now=moment) == b"png"
    assert card_model.screenshot.await_args.kwargs["is_dark_mode"] is (auto_dark if enabled else account_dark)
    assert card.is_dark_mode is account_dark


@pytest.mark.parametrize("hour,theme", [(7, "light"), (19, "dark")])
async def test_auto_theme_keeps_ban_notice(card_model, renderer, user_data, template, hour, theme):
    renderer.S_.user_card_auto_theme = True
    card = card_model.RenderUserInfo(**dict(user_data, ip=["192.0.2.41"], permission=-1, ban_reason=None))
    await card.get_image(now=datetime.fromisoformat(f"2026-10-12T{hour:02}:00:00+08:00"))
    html = template.render(card_model.screenshot.await_args.kwargs)
    assert f'data-theme="{theme}"' in html
    assert 'class="record is-banned"' in html
    assert 'class="ban-icon"' in html
    assert "未提供封禁原因" in html


async def test_auto_theme_default_clock_is_explicit_utc(card_model, renderer, user_data, monkeypatch):
    renderer.S_.user_card_auto_theme = True

    moment = datetime.fromisoformat("2026-10-12T11:00:00+00:00")
    monkeypatch.setattr(card_model.arrow, "utcnow", lambda: SimpleNamespace(datetime=moment))
    card = card_model.RenderUserInfo(**dict(user_data, ip=["192.0.2.41"], is_dark_mode=False))
    await card.get_image()
    assert card_model.screenshot.await_args.kwargs["is_dark_mode"] is True
    assert card.is_dark_mode is False
