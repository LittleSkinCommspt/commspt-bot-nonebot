"""群管禁言与消息撤回功能模块。

从 Avilla 原版的群管功能移植到 NoneBot2 原生 OneBot V11 架构，不依赖 Alconna / UniMessage。
依赖 OneBot V11 协议特定的群管理 API（set_group_ban、set_group_whole_ban、delete_msg）。
命令匹配基于事件纯文本（见 utils.onebot_message.native_command_rule），兼容 ``&`` 前缀。

命令（受全局 COMMAND_START 影响，默认前缀 &）：
- &mute <target> [duration] [group]   禁言群成员 (in_preset_cafe; admin_only)
- &unmute <target> [group]   解除群成员禁言 (in_preset_cafe; admin_only)
- &recall   撤回回复的消息及命令自身 (in_preset_cafe; admin_only)
- &muteall <group>   开启指定群全员禁言 (in_preset_cafe; admin_only)
- &unmuteall <group>   解除指定群全员禁言 (in_preset_cafe; admin_only)
"""

from typing import Literal

from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, MessageSegment

from plugins.commspt_bot.config import S_
from plugins.commspt_bot.utils.adv_filter import admin_only, in_preset_cafe
from plugins.commspt_bot.utils.onebot_message import extract_command_args, native_command_rule, reply_to, segment_text

# 将 group 选项别名映射到实际配置的 QQ 群号
_GROUP_NAME_MAPPING = {
    "main": S_.defined_qq.littleskin_main,
    "cafe": S_.defined_qq.littleskin_cafe,
}

GroupName = Literal["main", "cafe"]


def _parse_group(token: MessageSegment) -> GroupName | None:
    """解析群组别名（main / cafe），非法取值返回 None。"""
    text = segment_text(token)
    if text in ("main", "cafe"):
        return text
    return None


def _parse_target(token: MessageSegment) -> tuple[int, bool] | None:
    """解析目标为 ``(user_id, is_at)``；非法返回 None。

    - At 段：取其绑定的 qq（排除 @全体成员 等非数字目标），``is_at=True``
    - 纯数字文本：``is_at=False``
    """
    if token.type == "at":
        qq = str(token.data.get("qq", ""))
        if not qq.isdecimal():
            return None
        return int(qq), True
    text = segment_text(token)
    if text.isdecimal():
        return int(text), False
    return None


def _parse_duration(token: MessageSegment) -> int | None:
    """解析时长（分钟）；非法返回 None。"""
    try:
        return int(segment_text(token))
    except ValueError:
        return None


# MARK: %mute
mute = on_message(
    rule=native_command_rule("mute") & in_preset_cafe,
    permission=admin_only,
    priority=1,
    block=False,
)


@mute.handle()
async def _mute(bot: Bot, event: MessageEvent):
    """执行禁言操作，支持跨群指定或当前群禁言。"""
    tokens = extract_command_args(event.get_message())
    if not 1 <= len(tokens) <= 3:
        return

    target = _parse_target(tokens[0])
    if target is None:
        return
    user_id, is_at = target

    duration = 10
    if len(tokens) >= 2:
        parsed_duration = _parse_duration(tokens[1])
        if parsed_duration is None:
            return
        duration = parsed_duration

    group: GroupName | None = None
    if len(tokens) == 3:
        group = _parse_group(tokens[2])
        if group is None:
            return

    if group is not None:
        # 跨群禁言时 @user 仅携带当前群的消息上下文，可能造成跨群目标歧义，故禁止使用 @user，仅支持 QQ 号
        if is_at:
            await mute.send(reply_to(event) + "指定群组时不允许使用 @user")
            return

        # 调用 OneBot V11 API 跨群禁言；API 的 duration 单位为秒，故将输入的分钟数乘以 60
        await bot.set_group_ban(
            group_id=_GROUP_NAME_MAPPING[group],
            user_id=user_id,
            duration=duration * 60,
        )
        return

    # 未指定 group 时针对当前群操作，必须是群聊消息；非群聊事件（如私聊）则早退
    if not isinstance(event, GroupMessageEvent):
        await mute.send(reply_to(event) + "请在群聊中使用本命令")
        return
    # 当前群禁言：set_group_ban 的 duration 单位为秒，将输入的分钟数转换为秒（duration * 60）
    await bot.set_group_ban(group_id=event.group_id, user_id=user_id, duration=duration * 60)


# MARK: %unmute
unmute = on_message(
    rule=native_command_rule("unmute") & in_preset_cafe,
    permission=admin_only,
    priority=1,
    block=False,
)


@unmute.handle()
async def _unmute(bot: Bot, event: MessageEvent):
    """执行解除禁言操作，支持跨群指定或当前群解除。"""
    tokens = extract_command_args(event.get_message())
    if not 1 <= len(tokens) <= 2:
        return

    target = _parse_target(tokens[0])
    if target is None:
        return
    user_id, is_at = target

    group: GroupName | None = None
    if len(tokens) == 2:
        group = _parse_group(tokens[1])
        if group is None:
            return

    if group is not None:
        # 指定跨群目标群组时，不允许使用 @user 以免产生跨群目标歧义，仅允许输入 QQ 号
        if is_at:
            await unmute.send(reply_to(event) + "指定群组时不允许使用 @user")
            return

        # OneBot V11 中 set_group_ban 的 duration=0 表示解除禁言
        await bot.set_group_ban(
            group_id=_GROUP_NAME_MAPPING[group],
            user_id=user_id,
            duration=0,
        )
        return

    # 未指定 group 时需在群聊中使用，非群聊消息则早退
    if not isinstance(event, GroupMessageEvent):
        await unmute.send(reply_to(event) + "请在群聊中使用本命令")
        return
    # duration=0 解除当前群指定用户的禁言状态
    await bot.set_group_ban(group_id=event.group_id, user_id=user_id, duration=0)


# MARK: %recall
recall = on_message(
    rule=native_command_rule("recall") & in_preset_cafe,
    permission=admin_only,
    priority=1,
    block=False,
)


@recall.handle()
async def _recall(bot: Bot, event: MessageEvent):
    """撤回被回复的消息以及当前发送的撤回指令消息。"""
    if event.reply:
        origin_message_id = event.reply.message_id
    else:
        await recall.send(reply_to(event) + "需要回复消息")
        return
    # 分别撤回被引用的目标消息和触发撤回的指令消息
    await bot.delete_msg(message_id=origin_message_id)
    await bot.delete_msg(message_id=event.message_id)


# MARK: %muteall
muteall = on_message(
    rule=native_command_rule("muteall") & in_preset_cafe,
    permission=admin_only,
    priority=1,
    block=False,
)


@muteall.handle()
async def _mute_all(bot: Bot, event: MessageEvent):
    """开启指定预设群组的全员禁言。"""
    tokens = extract_command_args(event.get_message())
    if len(tokens) != 1:
        return
    group = _parse_group(tokens[0])
    if group is None:
        return
    # set_group_whole_ban 的 enable=True 表示开启全员禁言
    await bot.set_group_whole_ban(group_id=_GROUP_NAME_MAPPING[group], enable=True)


# MARK: %unmuteall
unmuteall = on_message(
    rule=native_command_rule("unmuteall") & in_preset_cafe,
    permission=admin_only,
    priority=1,
    block=False,
)


@unmuteall.handle()
async def _unmute_all(bot: Bot, event: MessageEvent):
    """解除指定预设群组的全员禁言。"""
    tokens = extract_command_args(event.get_message())
    if len(tokens) != 1:
        return
    group = _parse_group(tokens[0])
    if group is None:
        return
    # set_group_whole_ban 的 enable=False 表示解除全员禁言
    await bot.set_group_whole_ban(group_id=_GROUP_NAME_MAPPING[group], enable=False)
