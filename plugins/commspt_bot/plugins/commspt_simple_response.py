"""LittleSkin 社区常见问题与快捷回复的静态问答分发器。

对应 Avilla 原版 modules/simple_response.py。
基于单一 on_message 分发器 + 可热重载的内存注册表，替代原版的逐命令 on_alconna 注册。
命令前缀跟随 COMMAND_START 配置（通过 command_prefix 工具读取），不再硬编码。
管理员可通过 sreload 命令在运行时重新加载 commspt_simple_response.json，
新增/删除/修改的命令无需重启即可生效。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from arclet.alconna import Alconna, CommandMeta
from nonebot import logger, on_message
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import matchers
from nonebot.typing import T_State
from nonebot_plugin_alconna import AlconnaMatcher, on_alconna
from nonebot_plugin_alconna.uniseg import Image, Text, UniMessage

from plugins.commspt_bot.config import ASSETS_DIR, SIMPLE_RESPONSE_FILE
from plugins.commspt_bot.models.simple_response import (
    ImagePart,
    SimpleResponse,
    TextPart,
    load_simple_responses_checked,
)
from plugins.commspt_bot.utils.adv_filter import admin_only, in_preset_cafe
from plugins.commspt_bot.utils.command_prefix import display_command, strip_command_prefix
from plugins.commspt_bot.utils.onebot_message import NATIVE_COMMANDS
from plugins.commspt_bot.utils.random_sleep import random_sleep


# ---------------------------------------------------------------------------
# ReloadReport
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ReloadReport:
    """reload_registry() 的执行结果。"""

    ok: bool = False
    error: str | None = None
    total: int = 0
    added: set[str] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)
    changed: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Registry (module-level mutable state)
# ---------------------------------------------------------------------------
_LOOKUP: dict[str, SimpleResponse] = {}
"""别名展开后的全量查找表：命令名/别名 → SimpleResponse。"""

_PRIMARY: dict[str, SimpleResponse] = {}
"""仅主命令名 → SimpleResponse，用于 reload diff 计算。"""


# ---------------------------------------------------------------------------
# _build_message (unchanged — tests import it)
# ---------------------------------------------------------------------------
def _build_message(entry: SimpleResponse) -> UniMessage:
    """根据 SimpleResponse 条目构建 UniMessage。

    - messages 不为 None 时：按列表顺序渲染（ImagePart → Image，TextPart → Text）
    - 否则沿用经典格式：图片在前，文本在后
    """
    msg = UniMessage()
    if entry.messages is not None:
        for part in entry.messages:
            if isinstance(part, ImagePart):
                img_path = ASSETS_DIR / part.path
                msg.append(
                    Image(raw=img_path.read_bytes())
                    if img_path.is_file()
                    else Image(path=img_path)
                )
            elif isinstance(part, TextPart):
                msg.append(Text(part.content))
    else:
        for p in entry.images:
            img_path = ASSETS_DIR / p
            msg.append(
                Image(raw=img_path.read_bytes())
                if img_path.is_file()
                else Image(path=img_path)
            )
        if entry.text is not None:
            msg.append(Text(entry.text))
    return msg


# ---------------------------------------------------------------------------
# Collision scan helper
# ---------------------------------------------------------------------------
def _registered_command_paths() -> set[str]:
    """扫描所有已注册的 matcher，收集命令名（不含 ``Alconna::`` 前缀）。

    - ``AlconnaMatcher``：使用 ``_command_path``
    - 原生命令：取 ``NATIVE_COMMANDS``（由 ``native_command_rule`` 登记），
      使静态问答 JSON 键名不会与原生命令冲突（例如 mute）。
    """
    paths: set[str] = set(NATIVE_COMMANDS)
    for _prio, ms in matchers.items():
        for m in ms:
            if issubclass(m, AlconnaMatcher):
                paths.add(m._command_path.removeprefix("Alconna::"))
    return paths


# ---------------------------------------------------------------------------
# reload_registry
# ---------------------------------------------------------------------------
def reload_registry() -> ReloadReport:
    """从 SIMPLE_RESPONSE_FILE 重新加载注册表，原子替换 _LOOKUP / _PRIMARY。

    - 加载失败：保留原注册表，返回 ``ReloadReport(ok=False, error=...)``。
    - 加载成功：构建别名展开后的查找表，替换 _LOOKUP/_PRIMARY，
      diff 计算 added/removed/changed。
    """
    global _LOOKUP, _PRIMARY

    loaded = load_simple_responses_checked(SIMPLE_RESPONSE_FILE)
    if not loaded.ok:
        return ReloadReport(ok=False, error=loaded.error)

    registered_cmds = _registered_command_paths()
    reserved = {"sreload"}

    new_lookup: dict[str, SimpleResponse] = {}
    new_primary: dict[str, SimpleResponse] = {}

    # --- Phase 1: primary names ---
    for name, entry in loaded.registry.items():
        if name in reserved:
            logger.warning(f"简单问答主命令 {name!r} 与保留命令冲突，已跳过")
            continue
        if name in registered_cmds:
            logger.warning(f"简单问答主命令 {name!r} 与已注册 Alconna 命令冲突，已跳过")
            continue
        new_lookup[name] = entry
        new_primary[name] = entry

    # --- Phase 2: aliases ---
    for name, entry in loaded.registry.items():
        if name not in new_primary:
            # primary was skipped
            continue
        for alias in entry.aliases:
            if alias in reserved:
                logger.warning(f"简单问答别名 {alias!r}（来自 {name!r}）与保留命令冲突，已跳过")
                continue
            if alias in registered_cmds:
                logger.warning(f"简单问答别名 {alias!r}（来自 {name!r}）与已注册 Alconna 命令冲突，已跳过")
                continue
            if alias in new_lookup:
                logger.warning(
                    f"简单问答别名 {alias!r}（来自 {name!r}）"
                    f"与已有命令名冲突，已跳过（显式命令名优先）"
                )
                continue
            new_lookup[alias] = entry

    # --- Diff ---
    old_keys = set(_PRIMARY.keys())
    new_keys = set(new_primary.keys())
    added = new_keys - old_keys
    removed = old_keys - new_keys
    changed = {k for k in old_keys & new_keys if _PRIMARY[k] != new_primary[k]}

    # --- Atomic swap (GIL-atomic reference assignment) ---
    _LOOKUP = new_lookup
    _PRIMARY = new_primary

    return ReloadReport(
        ok=True,
        total=len(new_primary),
        added=added,
        removed=removed,
        changed=changed,
    )


# ---------------------------------------------------------------------------
# match_simple_response (pure, testable)
# ---------------------------------------------------------------------------
def match_simple_response(plaintext: str) -> SimpleResponse | None:
    """在当前注册表中查找与 plaintext 匹配的 SimpleResponse。

    流程：lstrip → strip_command_prefix → strip+split → 要求恰好 1 个 token → 查表。
    """
    remainder = strip_command_prefix(plaintext.lstrip())
    if remainder is None:
        return None
    tokens = remainder.strip().split()
    if len(tokens) != 1:
        return None
    return _LOOKUP.get(tokens[0])


# ---------------------------------------------------------------------------
# Dispatcher rule
# ---------------------------------------------------------------------------
def _sr_rule(event: MessageEvent, state: T_State) -> bool:
    """匹配规则：在当前注册表中查找命令，命中则将条目存入 state。"""
    entry = match_simple_response(event.get_plaintext())
    if entry is None:
        return False
    state["sr_entry"] = entry
    return True


# ---------------------------------------------------------------------------
# Matchers
# ---------------------------------------------------------------------------
sr_matcher = on_message(rule=in_preset_cafe & _sr_rule, priority=10, block=True)
"""单一分发器：服务所有静态问答命令。"""

sreload = on_alconna(
    Alconna(
        "sreload",
        meta=CommandMeta(
            description=display_command("sreload"),
            usage=display_command("sreload"),
        ),
    ),
    rule=in_preset_cafe,
    permission=admin_only,
    priority=10,
    block=True,
)
"""管理员热重载命令：重新读取 commspt_simple_response.json 并替换注册表。"""


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
@sr_matcher.handle()
async def _handle_simple_response(bot: Bot, event: MessageEvent, state: T_State) -> None:
    entry: SimpleResponse = state["sr_entry"]
    await random_sleep()
    await _build_message(entry).send(target=event, bot=bot, reply_to=entry.reply)


@sreload.handle()
async def _handle_sreload() -> None:
    report = reload_registry()
    if report.ok:
        summary = (
            f"✅ 热重载成功\n"
            f"  总计: {report.total}\n"
            f"  新增: {sorted(report.added) or '无'}\n"
            f"  移除: {sorted(report.removed) or '无'}\n"
            f"  变更: {sorted(report.changed) or '无'}"
        )
        await sreload.send(UniMessage(summary), reply_to=True)
    else:
        await sreload.send(
            UniMessage(f"❌ 热重载失败，保留原配置：{report.error}"),
            reply_to=True,
        )


# ---------------------------------------------------------------------------
# Import-time initialization
# ---------------------------------------------------------------------------
logger.info("正在加载简单问答注册表...")
_init_report = reload_registry()
if _init_report.ok:
    logger.info(f"简单问答注册表加载完成，共 {_init_report.total} 个命令")
else:
    logger.error(f"简单问答注册表加载失败：{_init_report.error}")
