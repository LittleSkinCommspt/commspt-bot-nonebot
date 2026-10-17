"""封禁记录命令的参数解析与列名映射。

把 ``&banlog`` 的文本参数解析为「UID + 类别列表 + 备注」，并把逻辑字段映射到
多维表格中的真实列名。全部为纯函数，便于单元测试。

命令形态：``&banlog <UID> <类别...> <备注...>``。类别必须命中表格「类别」列的选项，
可连续给出多个；遇到第一个不属于类别的 token 起，剩余文本全部作为备注。

主要接口：
- BanArgs: 解析结果
- parse_ban_args: 解析 &banlog 参数
- validate_categories: 校验类别是否都在表格选项中
- resolve_field_mapping: 把逻辑字段映射为表格真实列名
- missing_required_fields: 找出未匹配的必需逻辑字段
"""

from __future__ import annotations

# 逻辑字段 → 候选列名（按优先级），可被 .env 的 FEISHU_BAN__FIELDS__* 覆盖
FIELD_ALIASES: dict[str, list[str]] = {
    "uid": ["UID", "uid", "用户UID", "LittleSkin UID"],
    "category": ["类别", "分类", "违规类别"],
    "note": ["备注", "说明", "补充说明"],
    "auto_operator": ["自动化处理人员", "自动化处理人", "处理人员"],
    "updated_at": ["最后更新时间", "更新时间", "修改时间"],
}

REQUIRED_FIELDS: tuple[str, ...] = ("uid", "category", "note", "auto_operator")
"""必须存在于表格中的逻辑字段，缺列时拒绝写入。"""

FIELD_LABELS: dict[str, str] = {
    "uid": "UID",
    "category": "类别",
    "note": "备注",
    "auto_operator": "自动化处理人员",
    "updated_at": "最后更新时间",
}
"""逻辑字段的中文名称，用于提示文案。"""

NOTE_SEPARATOR = "--note"
"""强制其后内容归入备注的标记，用于备注首词与类别同名时的消歧。"""


class BanArgs:
    """``&banlog`` 解析后的参数。"""

    __slots__ = ("categories", "note", "uid")

    def __init__(self, uid: int, categories: list[str], note: str = ""):
        self.uid = uid
        self.categories = categories
        self.note = note

    def __repr__(self) -> str:
        return f"BanArgs(uid={self.uid}, categories={self.categories!r}, note={self.note!r})"


def _segment_text(token) -> str:
    """读取文本段的原始文本；非文本段返回空字符串。"""
    if getattr(token, "type", None) != "text":
        return ""
    return (getattr(token, "data", {}) or {}).get("text", "") or ""


def parse_ban_args(tokens: list, categories: set[str]) -> tuple[BanArgs | None, str]:
    """解析 ``&banlog`` 的参数 token。

    成功返回 ``(BanArgs, "")``，失败返回 ``(None, 错误说明)``。
    """
    if not tokens:
        return None, "缺少参数"

    first = _segment_text(tokens[0]).strip()
    if not first:
        return None, "第一个参数必须是 LittleSkin UID"
    if not first.isdecimal():
        return None, f"UID 必须是纯数字，收到 {first!r}"
    uid = int(first)

    parsed_categories: list[str] = []
    note_parts: list[str] = []
    in_note = False

    for token in tokens[1:]:
        text = _segment_text(token).strip()
        if not text:
            continue
        if text == NOTE_SEPARATOR:
            in_note = True
            continue
        if not in_note and text in categories and len(parsed_categories) < len(categories):
            parsed_categories.append(text)
            continue
        in_note = True
        note_parts.append(text)

    if not parsed_categories:
        available = "、".join(sorted(categories)) or "（表格中未配置类别选项）"
        return None, f"缺少类别。可选类别：{available}"

    return BanArgs(uid=uid, categories=parsed_categories, note=" ".join(note_parts).strip()), ""


def validate_categories(categories: list[str], available: set[str]) -> str:
    """校验类别是否都在表格选项中，返回错误说明（空字符串表示合法）。"""
    invalid = [c for c in categories if c not in available]
    if not invalid:
        return ""
    return f"类别不在表格选项中：{'、'.join(invalid)}\n可选类别：{'、'.join(sorted(available))}"


def resolve_field_mapping(
    available_names: dict[str, str],
    explicit: dict[str, str] | None = None,
) -> dict[str, str]:
    """把逻辑字段映射为表格真实列名。

    ``explicit`` 中显式指定的列名优先；指定了但表格中不存在时不回退到别名，
    以便交由缺列检查明确报错。
    """
    explicit = explicit or {}
    normalized = {value.strip().lower(): key for key, value in available_names.items()}

    resolved: dict[str, str] = {}
    for logical, candidates in FIELD_ALIASES.items():
        wanted = (explicit.get(logical) or "").strip()
        if wanted:
            if wanted in available_names:
                resolved[logical] = wanted
            elif real := normalized.get(wanted.lower()):
                resolved[logical] = real
            continue
        for candidate in candidates:
            if real := normalized.get(candidate.strip().lower()):
                resolved[logical] = real
                break
    return resolved


def missing_required_fields(mapping: dict[str, str], writable: set[str] | None = None) -> list[str]:
    """返回不可用的必需逻辑字段。

    未映射到表格列的字段视为缺失；传入 ``writable`` 时，映射到只读列（公式、查找
    引用、创建/修改时间等）的字段同样视为缺失——这类列写入时会被静默跳过，
    不提前拦下就会产生缺字段的脏记录。
    """
    missing = []
    for name in REQUIRED_FIELDS:
        column = mapping.get(name)
        if column is None or (writable is not None and column not in writable):
            missing.append(name)
    return missing
