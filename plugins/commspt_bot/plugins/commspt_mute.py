from typing import Literal

from arclet.alconna import Alconna, Args, CommandMeta
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot_plugin_alconna import At, Match, on_alconna
from nonebot_plugin_alconna.uniseg import UniMessage

from plugins.commspt_bot.config import S_
from plugins.commspt_bot.utils.adv_filter import admin_only, in_preset_cafe

_GROUP_NAME_MAPPING = {
    "main": S_.defined_qq.littleskin_main,
    "cafe": S_.defined_qq.littleskin_cafe,
}


# MARK: %mute
mute = on_alconna(
    Alconna(
        f"{S_.command_prompt}mute",
        Args["target#目标", int | At]["duration#时长", int, 10]["group#群组", Literal["main", "cafe"] | None, None],
        meta=CommandMeta(
            description="禁言用户 (commspt only)",
            usage=rf"{S_.command_prompt}mute <target> [duration] [group]",
            example=rf"{S_.command_prompt}mute @user 10 main",
        ),
    ),
    rule=in_preset_cafe,
    permission=admin_only,
)


@mute.handle()
async def _mute(bot: Bot, event: MessageEvent, target: Match[int | At], duration: int, group: Match[Literal["main", "cafe"] | None]):
    if group.result:
        if isinstance(target.result, At):
            await mute.send(UniMessage("指定群组时不允许使用 @user"))
            return

        await bot.set_group_ban(
            group_id=_GROUP_NAME_MAPPING[group.result],
            user_id=target.result,
            duration=duration * 60,
        )
        return

    user_id = int(target.result.target) if isinstance(target.result, At) else target.result
    if not isinstance(event, GroupMessageEvent):
        await mute.send(UniMessage("请在群聊中使用本命令"))
        return
    await bot.set_group_ban(group_id=event.group_id, user_id=user_id, duration=duration * 60)
    return


# MARK: %unmute
unmute = on_alconna(
    Alconna(
        f"{S_.command_prompt}unmute",
        Args["target#目标", int | At]["group#群组", Literal["main", "cafe"] | None, None],
        meta=CommandMeta(
            description="解除禁言 (commspt only)",
            usage=rf"{S_.command_prompt}unmute <target / qq> [group]",
            example=rf"{S_.command_prompt}unmute @user main",
        ),
    ),
    rule=in_preset_cafe,
    permission=admin_only,
)


@unmute.handle()
async def _unmute(bot: Bot, event: MessageEvent, target: Match[int | At], group: Match[Literal["main", "cafe"] | None]):
    if group.result:
        if isinstance(target.result, At):
            await unmute.send(UniMessage("指定群组时不允许使用 @user"))
            return

        await bot.set_group_ban(
            group_id=_GROUP_NAME_MAPPING[group.result],
            user_id=target.result,
            duration=0,
        )
        return

    user_id = int(target.result.target) if isinstance(target.result, At) else target.result
    if not isinstance(event, GroupMessageEvent):
        await unmute.send(UniMessage("请在群聊中使用本命令"))
        return
    await bot.set_group_ban(group_id=event.group_id, user_id=user_id, duration=0)
    return


# MARK: %recall
recall = on_alconna(
    Alconna(
        f"{S_.command_prompt}recall",
        meta=CommandMeta(
            description="撤回消息 (commspt only)",
            usage=rf"{S_.command_prompt}recall",
            example=rf"{S_.command_prompt}recall",
        ),
    ),
    rule=in_preset_cafe,
    permission=admin_only,
)


@recall.handle()
async def _recall(bot: Bot, event: MessageEvent):
    if event.reply:
        origin_message_id = event.reply.message_id
    else:
        await recall.send(UniMessage("需要回复消息"))
        return
    await bot.delete_msg(message_id=origin_message_id)
    await bot.delete_msg(message_id=event.message_id)


# MARK: %muteall
muteall = on_alconna(
    Alconna(
        f"{S_.command_prompt}muteall",
        Args["group#群组", Literal["main", "cafe"]],
        meta=CommandMeta(
            description="MUTEALL (commspt only)",
            usage=rf"{S_.command_prompt}muteall <group>",
            example=rf"{S_.command_prompt}muteall main",
        ),
    ),
    rule=in_preset_cafe,
    permission=admin_only,
)


@muteall.handle()
async def _mute_all(bot: Bot, group: Match[Literal["main", "cafe"]]):
    await bot.set_group_whole_ban(group_id=_GROUP_NAME_MAPPING[group.result], enable=True)


unmuteall = on_alconna(
    Alconna(
        f"{S_.command_prompt}unmuteall",
        Args["group#群组", Literal["main", "cafe"]],
        meta=CommandMeta(
            description="UNMUTEALL (commspt only)",
            usage=rf"{S_.command_prompt}unmuteall <group>",
            example=rf"{S_.command_prompt}unmuteall main",
        ),
    ),
    rule=in_preset_cafe,
    permission=admin_only,
)


@unmuteall.handle()
async def _unmute_all(bot: Bot, group: Match[Literal["main", "cafe"]]):
    await bot.set_group_whole_ban(group_id=_GROUP_NAME_MAPPING[group.result], enable=False)
