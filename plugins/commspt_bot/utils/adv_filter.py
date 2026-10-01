"""通用过滤器与事件规则

提供群聊白名单过滤与管理员权限校验等 NoneBot 规则谓词与常用预设。
原项目基于 Avilla 的 `Selector` 判断来群；此处改为基于 NoneBot 事件的谓词，
等价语义：`from_groups(...)` -> `Rule`，`by_admin_only(...)` -> `Permission`。

主要接口：
- from_groups: 构造限制指定群聊的 Rule 规则
- by_admin_only: 构造仅管理员可触发的 Permission 权限
- from_groups_preset_*: 各预设群聊组合的 Rule 工厂函数
- admin_only / in_preset_*: 预设规则与权限的单例实例
"""

from nonebot.adapters import Event
from nonebot.permission import Permission
from nonebot.rule import Rule

from plugins.commspt_bot.config import S_

Q_ = S_.defined_qq


def from_groups(allowed_groups: list[int]):
    """构造限制事件来源群聊的 Rule 规则"""
    async def _wrapper(event: Event) -> bool:
        # 使用 getattr 而非直接访问属性，避免私聊或非群聊事件缺少 group_id 抛出 AttributeError
        return getattr(event, "group_id", None) in allowed_groups

    # 群聊来源属于消息接收环境匹配规则，对应 NoneBot 的 Rule 语义
    return Rule(_wrapper)


def from_groups_preset_general():
    """通用群聊预设规则

    Preset groups: `littleskin_main` (主群), `commspt_group` (社区支持群), `dev_group` (开发群)
    """
    return from_groups([Q_.littleskin_main, Q_.commspt_group, Q_.dev_group])


def from_groups_preset_cafe():
    """茶馆及关联群聊预设规则

    Preset groups: `littleskin_main` (主群), `littleskin_cafe` (茶馆群), `commspt_group` (社区支持群), `dev_group` (开发群)
    """
    return from_groups([Q_.littleskin_main, Q_.littleskin_cafe, Q_.commspt_group, Q_.dev_group])


def from_groups_preset_general_no_commspt():
    """仅主群预设规则（排除社区支持群）

    Preset groups: `littleskin_main` (主群)
    """
    return from_groups([Q_.littleskin_main])


def from_groups_preset_only_cafe():
    """仅茶馆群预设规则

    Preset groups: `littleskin_cafe` (茶馆群)
    """
    return from_groups([Q_.littleskin_cafe])


def from_groups_preset_commspt():
    """社区支持与开发群预设规则

    Preset groups: `commspt_group` (社区支持群), `dev_group` (开发群)
    """
    return from_groups([Q_.commspt_group, Q_.dev_group])


def by_admin_only():
    """构造限制仅管理员可触发的 Permission 权限"""
    async def _wrapper(event: Event) -> bool:
        try:
            user_id = event.get_user_id()
        except Exception:
            return False
        # 用户身份鉴权对应 NoneBot 的 Permission 语义
        return int(user_id) in S_.admin_list

    return Permission(_wrapper)


# 常用 Preset 的实例，供 `on_alconna(..., rule=..., permission=...)` 直接使用
admin_only = by_admin_only()
in_preset_general = from_groups_preset_general()
in_preset_cafe = from_groups_preset_cafe()
in_preset_general_no_commspt = from_groups_preset_general_no_commspt()
in_preset_only_cafe = from_groups_preset_only_cafe()
in_preset_commspt = from_groups_preset_commspt()
