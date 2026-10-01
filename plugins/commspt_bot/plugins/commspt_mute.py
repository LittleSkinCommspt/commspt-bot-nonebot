"""群管禁言与消息撤回功能模块。

从 Avilla 原版的群管功能移植到 NoneBot2 + Alconna 架构。
依赖 OneBot V11 协议特定的群管理 API（set_group_ban、set_group_whole_ban、delete_msg）。

命令：
- &mute <target> [duration] [group]   禁言群成员 (in_preset_cafe; admin_only)
- &unmute <target> [group]   解除群成员禁言 (in_preset_cafe; admin_only)
- &recall   撤回回复的消息及命令自身 (in_preset_cafe; admin_only)
- &muteall <group>   开启指定群全员禁言 (in_preset_cafe; admin_only)
- &unmuteall <group>   解除指定群全员禁言 (in_preset_cafe; admin_only)
"""

from typing import Literal

from arclet.alconna import Alconna, Args, CommandMeta
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot_plugin_alconna import At, Match, on_alconna
from nonebot_plugin_alconna.uniseg import UniMessage

from plugins.commspt_bot.config import S_
from plugins.commspt_bot.utils.adv_filter import admin_only, in_preset_cafe

# 将 group 选项别名映射到实际配置的 QQ 群号
_GROUP_NAME_MAPPING = {
    "main": S_.defined_qq.littleskin_main,
    "cafe": S_.defined_qq.littleskin_cafe,
}


# MARK: %mute
mute = on_alconna(
    Alconna(
        "mute",
        Args["target#目标", int | At]["duration#时长", int, 10]["group#群组", Literal["main", "cafe"] | None, None],
        meta=CommandMeta(
            description="禁言用户 (commspt only)",
            usage=r"&mute <target> [duration] [group]",
            example=r"&mute @user 10 main",
        ),
    ),
    rule=in_preset_cafe,
    permission=admin_only,
)


@mute.handle()
async def _mute(bot: Bot, event: MessageEvent, target: Match[int | At], duration: int, group: Match[Literal["main", "cafe"] | None]):
    """执行禁言操作，支持跨群指定或当前群禁言。"""
    if group.result:
        # 跨群禁言时 @user 仅携带当前群的消息上下文，可能造成跨群目标歧义，故禁止使用 @user，仅支持 QQ 号
        if isinstance(target.result, At):
            await mute.send(UniMessage("指定群组时不允许使用 @user"))
            return

        # 调用 OneBot V11 API 跨群禁言；API 的 duration 单位为秒，故将输入的分钟数乘以 60
        await bot.set_group_ban(
            group_id=_GROUP_NAME_MAPPING[group.result],
            user_id=target.result,
            duration=duration * 60,
        )
        return

    # At 消息段与 QQ 纯数字的兼容分支：若为 At 则提取其绑定的 target 并转为 int，否则直接使用传入数字
    user_id = int(target.result.target) if isinstance(target.result, At) else target.result
    # 未指定 group 时针对当前群操作，必须是群聊消息；非群聊事件（如私聊）则早退
    if not isinstance(event, GroupMessageEvent):
        await mute.send(UniMessage("请在群聊中使用本命令"))
        return
    # 当前群禁言：set_group_ban 的 duration 单位为秒，将输入的分钟数转换为秒（duration * 60）
    await bot.set_group_ban(group_id=event.group_id, user_id=user_id, duration=duration * 60)
    return


# MARK: %unmute
unmute = on_alconna(
    Alconna(
        "unmute",
        Args["target#目标", int | At]["group#群组", Literal["main", "cafe"] | None, None],
        meta=CommandMeta(
            description="解除禁言 (commspt only)",
            usage=r"&unmute <target / qq> [group]",
            example=r"&unmute @user main",
        ),
    ),
    rule=in_preset_cafe,
    permission=admin_only,
)


@unmute.handle()
async def _unmute(bot: Bot, event: MessageEvent, target: Match[int | At], group: Match[Literal["main", "cafe"] | None]):
    """执行解除禁言操作，支持跨群指定或当前群解除。"""
    if group.result:
        # 指定跨群目标群组时，不允许使用 @user 以免产生跨群目标歧义，仅允许输入 QQ 号
        if isinstance(target.result, At):
            await unmute.send(UniMessage("指定群组时不允许使用 @user"))
            return

        # OneBot V11 中 set_group_ban 的 duration=0 表示解除禁言
        await bot.set_group_ban(
            group_id=_GROUP_NAME_MAPPING[group.result],
            user_id=target.result,
            duration=0,
        )
        return

    # 提取目标 QQ 号：兼容 At 消息段与直接输入的 QQ 数字
    user_id = int(target.result.target) if isinstance(target.result, At) else target.result
    # 未指定 group 时需在群聊中使用，非群聊消息则早退
    if not isinstance(event, GroupMessageEvent):
        await unmute.send(UniMessage("请在群聊中使用本命令"))
        return
    # duration=0 解除当前群指定用户的禁言状态
    await bot.set_group_ban(group_id=event.group_id, user_id=user_id, duration=0)
    return


# MARK: %recall
recall = on_alconna(
    Alconna(
        "recall",
        meta=CommandMeta(
            description="撤回消息 (commspt only)",
            usage=r"&recall",
            example=r"&recall",
        ),
    ),
    rule=in_preset_cafe,
    permission=admin_only,
)


@recall.handle()
async def _recall(bot: Bot, event: MessageEvent):
    """撤回被回复的消息以及当前发送的撤回指令消息。"""
    if event.reply:
        origin_message_id = event.reply.message_id
    else:
        await recall.send(UniMessage("需要回复消息"))
        return
    # 分别撤回被引用的目标消息和触发撤回的指令消息
    await bot.delete_msg(message_id=origin_message_id)
    await bot.delete_msg(message_id=event.message_id)


# MARK: %muteall
muteall = on_alconna(
    Alconna(
        "muteall",
        Args["group#群组", Literal["main", "cafe"]],
        meta=CommandMeta(
            description="MUTEALL (commspt only)",
            usage=r"&muteall <group>",
            example=r"&muteall main",
        ),
    ),
    rule=in_preset_cafe,
    permission=admin_only,
)


@muteall.handle()
async def _mute_all(bot: Bot, group: Match[Literal["main", "cafe"]]):
    """开启指定预设群组的全员禁言。"""
    # set_group_whole_ban 的 enable=True 表示开启全员禁言
    await bot.set_group_whole_ban(group_id=_GROUP_NAME_MAPPING[group.result], enable=True)


unmuteall = on_alconna(
    Alconna(
        "unmuteall",
        Args["group#群组", Literal["main", "cafe"]],
        meta=CommandMeta(
            description="UNMUTEALL (commspt only)",
            usage=r"&unmuteall <group>",
            example=r"&unmuteall main",
        ),
    ),
    rule=in_preset_cafe,
    permission=admin_only,
)


@unmuteall.handle()
async def _unmute_all(bot: Bot, group: Match[Literal["main", "cafe"]]):
    """解除指定预设群组的全员禁言。"""
    # set_group_whole_ban 的 enable=False 表示解除全员禁言
    await bot.set_group_whole_ban(group_id=_GROUP_NAME_MAPPING[group.result], enable=False)
