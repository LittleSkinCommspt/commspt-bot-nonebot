"""通用过滤器

原项目基于 Avilla 的 `Selector` 判断来群；此处改为基于 NoneBot 事件的谓词，
等价语义：`from_groups(...)` -> `Rule`，`by_admin_only(...)` -> `Permission`。
"""

from nonebot.adapters import Event
from nonebot.permission import Permission
from nonebot.rule import Rule

from plugins.commspt_bot.config import S_

Q_ = S_.defined_qq


def from_groups(allowed_groups: list[int]):
    async def _wrapper(event: Event) -> bool:
        return getattr(event, "group_id", None) in allowed_groups

    return Rule(_wrapper)


def from_groups_preset_general():
    """
    Preset groups: `littleskin_main`, `commspt_group`, `dev_group`
    """
    return from_groups([Q_.littleskin_main, Q_.commspt_group, Q_.dev_group])


def from_groups_preset_cafe():
    """
    Preset groups: `littleskin_main`, `littleskin_cafe`, `commspt_group`, `dev_group`
    """
    return from_groups([Q_.littleskin_main, Q_.littleskin_cafe, Q_.commspt_group, Q_.dev_group])


def from_groups_preset_general_no_commspt():
    """
    Preset groups: `littleskin_main`, `littleskin_cafe``
    """
    return from_groups([Q_.littleskin_main])


def from_groups_preset_only_cafe():
    """
    Preset groups: `littleskin_cafe`
    """
    return from_groups([Q_.littleskin_cafe])


def from_groups_preset_commspt():
    """
    Preset groups: `commspt_group`, `dev_group`
    """
    return from_groups([Q_.commspt_group, Q_.dev_group])


def by_admin_only():
    async def _wrapper(event: Event) -> bool:
        try:
            user_id = event.get_user_id()
        except Exception:
            return False
        return int(user_id) in S_.admin_list

    return Permission(_wrapper)


# 常用 Preset 的实例，供 `on_alconna(..., rule=..., permission=...)` 直接使用
admin_only = by_admin_only()
in_preset_general = from_groups_preset_general()
in_preset_cafe = from_groups_preset_cafe()
in_preset_general_no_commspt = from_groups_preset_general_no_commspt()
in_preset_only_cafe = from_groups_preset_only_cafe()
in_preset_commspt = from_groups_preset_commspt()
