"""按 UID 查询飞书封禁记录并格式化输出。

供 ``&user`` 与入群相关自动通知复用：账号处于封禁状态时，按 UID 取出表格中
对应记录一并展示。调用范围由各命令 / 事件规则限定，此处不再判断群号。

查询失败一律降级为空字符串，避免影响主流程（出图、入群审批）。

主要接口：
- format_ban_records: 把检索结果渲染为文本
- lookup_ban_records: 按 UID 查询并渲染
- banned_records_block: 仅在封禁状态下返回文本块
"""

from __future__ import annotations

from typing import Any

import arrow
from nonebot import logger

from plugins.commspt_bot.config import S_
from plugins.commspt_bot.models.feishu_bitable import FeishuBitable
from plugins.commspt_bot.utils.ban_record import resolve_field_mapping

BANNED_PERMISSION = -1
"""LittleSkin 账号处于封禁状态时的 permission 取值。"""

MAX_DISPLAY_RECORDS = 5
"""最多展示的记录条数，超出部分仅提示总数。"""


def _format_timestamp(value: Any) -> str:
    """把飞书返回的毫秒时间戳格式化为北京时间。"""
    if value is None or value == "":
        return ""
    try:
        return arrow.get(int(value) / 1000).to("Asia/Shanghai").format("YYYY-MM-DD HH:mm")
    except (TypeError, ValueError):
        return str(value)


def _field_text(value: Any) -> str:
    """把字段值转为可读文本，兼容文本数组、多选数组、人员对象等形态。"""
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(value.get("text") or value.get("link") or "")
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("name") or ""))
            else:
                parts.append(str(item))
        return "、".join(p for p in parts if p)
    return str(value)


def _record_line(record: dict[str, Any], mapping: dict[str, str]) -> str:
    """把单条记录渲染为一行。"""
    fields = record.get("fields") or {}
    parts: list[str] = []

    for logical, label in (("category", "类别"), ("note", "备注"), ("auto_operator", "处理人")):
        if (column := mapping.get(logical)) and (text := _field_text(fields.get(column))):
            parts.append(f"{label}：{text}")

    if (column := mapping.get("updated_at")) and (text := _format_timestamp(fields.get(column))):
        parts.append(f"时间：{text}")

    return "· " + " / ".join(parts) if parts else "· （无可用字段）"


def format_ban_records(records: list[dict[str, Any]], mapping: dict[str, str], uid: int) -> str:
    """把检索结果渲染为多行文本；无记录时返回空字符串。"""
    if not records:
        return ""

    lines = [f"📋 UID {uid} 在封禁记录表中有 {len(records)} 条记录："]
    for record in records[:MAX_DISPLAY_RECORDS]:
        lines.append(_record_line(record, mapping))
    if len(records) > MAX_DISPLAY_RECORDS:
        lines.append(f"… 其余 {len(records) - MAX_DISPLAY_RECORDS} 条请到表格查看")
    return "\n".join(lines)


async def lookup_ban_records(uid: int) -> str:
    """按 UID 查询封禁记录；无记录、未配置或查询失败时返回空字符串。"""
    cfg = S_.feishu_ban
    if not cfg.app_token or not cfg.table_id:
        logger.debug("未配置飞书多维表格，跳过封禁记录附加查询")
        return ""

    try:
        bitable = FeishuBitable(cfg.app_token, cfg.table_id)
        fields = await bitable.fetch_fields()
        available = {field.field_name: field.field_name for field in fields}
        mapping = resolve_field_mapping(
            available,
            {
                "uid": cfg.fields.uid,
                "category": cfg.fields.category,
                "note": cfg.fields.note,
                "auto_operator": cfg.fields.auto_operator,
            },
        )

        uid_column = mapping.get("uid")
        if not uid_column:
            logger.warning("封禁记录表缺少 UID 列，跳过附加查询")
            return ""

        records = await bitable.search_records([(uid_column, str(uid))], logic="and")
        return format_ban_records(records, mapping, uid)
    except Exception as e:
        logger.warning(f"查询飞书封禁记录失败（已忽略）：{type(e).__name__}: {e}")
        return ""


async def banned_records_block(uid: int, *, permission: int) -> str:
    """仅在账号被封禁时返回可追加的封禁记录文本块。"""
    if permission != BANNED_PERMISSION:
        return ""
    return await lookup_ban_records(uid)


__all__ = [
    "BANNED_PERMISSION",
    "MAX_DISPLAY_RECORDS",
    "banned_records_block",
    "format_ban_records",
    "lookup_ban_records",
]
