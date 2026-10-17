"""飞书多维表格封禁记录写入插件。

把管理员登记的封禁信息写入飞书多维表格，便于团队复盘与查询。本功能不与
LittleSkin 数据库联通，UID 由命令直接给出。

命令（受全局 COMMAND_START 影响，默认前缀 &）：
- &banlog <UID> <类别...> [备注...]   写入一条封禁记录          (in_preset_cafe; admin_only)
- &banlog.fields                     打印表格字段与类别选项     (in_preset_cafe; admin_only)

注意：``banlog`` 只登记记录，不执行封禁动作；禁言群成员请用 ``&mute``。

写入的列为 UID（数字）、类别（多选）、备注（文本）、自动化处理人员（文本，取触发
命令的管理员 QQ）。「处理人」是人员字段，只接受 open_id / user_id / union_id，
应用身份无法写入，故该列留空。

类别选项在运行时从表格字段读取并缓存，表格改选项后无需改代码；列名按别名匹配，
.env 中显式指定优先，缺列时明确报错。
"""

import time

from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import Bot, MessageEvent

from plugins.commspt_bot.config import S_
from plugins.commspt_bot.models.feishu_bitable import FeishuBitable, FeishuField
from plugins.commspt_bot.utils.adv_filter import admin_only, in_preset_cafe
from plugins.commspt_bot.utils.ban_record import (
    FIELD_LABELS,
    missing_required_fields,
    parse_ban_args,
    resolve_field_mapping,
    validate_categories,
)
from plugins.commspt_bot.utils.command_prefix import display_command
from plugins.commspt_bot.utils.onebot_message import extract_command_args, native_command_rule, reply_to

CATEGORY_CACHE_TTL = 300
"""类别选项缓存的有效期（秒）。"""

_category_cache: dict[tuple[str, str], tuple[float, set[str]]] = {}


def _bitable() -> FeishuBitable:
    """按配置构造多维表格客户端。"""
    cfg = S_.feishu_ban
    return FeishuBitable(cfg.app_token, cfg.table_id)


def _explicit_field_map() -> dict[str, str]:
    """读取配置中显式指定的列名映射。"""
    fields = S_.feishu_ban.fields
    return {
        "uid": fields.uid,
        "category": fields.category,
        "note": fields.note,
        "auto_operator": fields.auto_operator,
    }


async def _load_schema(bitable: FeishuBitable) -> tuple[list[FeishuField], dict[str, str]]:
    """拉取表格字段并解析逻辑字段 → 真实列名映射。"""
    fields = await bitable.fetch_fields()
    available = {field.field_name: field.field_name for field in fields}
    return fields, resolve_field_mapping(available, _explicit_field_map())


async def _load_categories(bitable: FeishuBitable, fields: list[FeishuField], mapping: dict[str, str]) -> set[str]:
    """读取「类别」列当前可用的选项集合（带缓存）。"""
    category_column = mapping.get("category")
    if not category_column:
        return set()

    key = (bitable.app_token, bitable.table_id)
    now = time.time()
    if cached := _category_cache.get(key):
        expire_at, cached_options = cached
        if now < expire_at:
            return set(cached_options)

    category_field = next((f for f in fields if f.field_name == category_column), None)
    options = set(category_field.options) if category_field else set()
    _category_cache[key] = (now + CATEGORY_CACHE_TTL, options)
    return options


def _writable_columns(fields: list[FeishuField]) -> set[str]:
    """返回当前表格中可写入的列名集合（排除公式、查找引用等只读列）。"""
    return {field.field_name for field in fields if not field.readonly}


def _describe_fields(fields: list[FeishuField]) -> str:
    """把表格字段渲染为一行提示，便于管理员核对列名。"""
    if not fields:
        return "（表格中没有字段）"
    return "、".join(f"{f.field_name}({f.type_name})" for f in fields)


def _describe_mapping(mapping: dict[str, str]) -> str:
    """把逻辑字段 → 列名的映射渲染为多行文本。"""
    lines = []
    for logical, label in FIELD_LABELS.items():
        target = mapping.get(logical)
        lines.append(f"· {label} → {target}" if target else f"· {label} → 未匹配")
    return "\n".join(lines)


def _usage() -> str:
    """生成跟随当前命令前缀的用法提示。"""
    return f"用法：{display_command('banlog')} <UID> <类别> [备注]"


# MARK: &banlog
banlog = on_message(
    rule=native_command_rule("banlog") & in_preset_cafe,
    permission=admin_only,
    priority=1,
    block=False,
)


@banlog.handle()
async def _banlog(bot: Bot, event: MessageEvent):
    """解析 &banlog 参数并写入一条封禁记录。"""
    tokens = extract_command_args(event.get_message())
    if not tokens:
        await banlog.send(reply_to(event) + _usage())
        return

    try:
        bitable = _bitable()
    except ValueError as e:
        await banlog.send(reply_to(event) + str(e))
        return

    try:
        fields, mapping = await _load_schema(bitable)
    except Exception as e:
        logger.error(f"&banlog 读取表格字段失败：{type(e).__name__}: {e}")
        await banlog.send(reply_to(event) + f"读取表格字段失败：{e}")
        return

    if missing := missing_required_fields(mapping, _writable_columns(fields)):
        names = "、".join(FIELD_LABELS.get(name, name) for name in missing)
        await banlog.send(
            reply_to(event)
            + f"表格缺少必需列或必需列不可写：{names}\n表内现有字段：{_describe_fields(fields)}\n"
            + "请在 .env 中显式指定 FEISHU_BAN__FIELDS__* 列名配置，且不要映射到公式/查找引用等只读列。"
        )
        return

    categories = await _load_categories(bitable, fields, mapping)
    args, error = parse_ban_args(tokens, categories)
    if args is None:
        await banlog.send(reply_to(event) + f"{error}\n{_usage()}")
        return

    if error := validate_categories(args.categories, categories):
        await banlog.send(reply_to(event) + error)
        return

    values = {
        mapping["uid"]: args.uid,
        mapping["category"]: args.categories,
        mapping["note"]: args.note,
        mapping["auto_operator"]: str(event.get_user_id()),
    }

    try:
        payload = FeishuBitable.build_fields(fields, values)
        record_id = await bitable.create_record(payload)
    except Exception as e:
        logger.error(f"&banlog 写入失败：{type(e).__name__}: {e}")
        await banlog.send(reply_to(event) + f"写入表格失败：{e}")
        return

    logger.success(f"&banlog 写入成功 record_id={record_id}")
    reply = f"已写入封禁记录（UID {args.uid} / {'、'.join(args.categories)}）"
    if args.note:
        reply += f"\n备注：{args.note}"
    await banlog.send(reply_to(event) + reply)


# MARK: &banlog.fields
banlog_fields = on_message(
    rule=native_command_rule("banlog.fields") & in_preset_cafe,
    permission=admin_only,
    priority=1,
    block=False,
)


@banlog_fields.handle()
async def _banlog_fields(bot: Bot, event: MessageEvent):
    """打印表格真实字段、类别选项与列名匹配结果。"""
    try:
        bitable = _bitable()
        fields, mapping = await _load_schema(bitable)
    except Exception as e:
        logger.error(f"&banlog.fields 读取表格字段失败：{type(e).__name__}: {e}")
        await banlog_fields.send(reply_to(event) + f"读取表格失败：{e}")
        return

    lines = ["表格字段："]
    for field in fields:
        readonly = "（只读）" if field.readonly else ""
        lines.append(f"· {field.field_name} — {field.type_name}{readonly}")

    lines.extend(("", "列名匹配：", _describe_mapping(mapping)))

    if mapping.get("category"):
        options = await _load_categories(bitable, fields, mapping)
        lines.extend(("", f"可选类别：{'、'.join(sorted(options)) or '（未配置选项）'}"))

    if missing := missing_required_fields(mapping, _writable_columns(fields)):
        lines.extend(("", "⚠️ 缺少必需列或必需列不可写：" + "、".join(FIELD_LABELS.get(n, n) for n in missing)))

    await banlog_fields.send(reply_to(event) + "\n".join(lines))
