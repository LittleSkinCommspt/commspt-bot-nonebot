"""玩家 Yggdrasil 资料查询插件

移植自原 Avilla 版 profile.py 模块，在 NoneBot2 + Alconna 体系下实现。
通过 Yggdrasil API 分别查询 LittleSkin 社区用户与 Mojang 官方正版用户的皮肤、披风与 UUID 等档案信息。

命令：
- &ygg <player_name>   查询 LittleSkin Yggdrasil 玩家资料   (适用群: in_preset_cafe; 权限: 无限制)
- &pro <player_name>   查询 Mojang 官方正版玩家资料   (适用群: in_preset_cafe; 权限: 无限制)
"""

from arclet.alconna import Alconna, Args, CommandMeta
from httpx import HTTPStatusError
from nonebot_plugin_alconna import Match, on_alconna
from nonebot_plugin_alconna.uniseg import UniMessage

from plugins.commspt_bot.config import S_
from plugins.commspt_bot.models.const import PlayerNotFoundError, get_ygg_player
from plugins.commspt_bot.utils.adv_filter import in_preset_cafe
from plugins.commspt_bot.utils.random_sleep import random_sleep

# region %ygg
ygg = on_alconna(
    Alconna(
        f"{S_.command_prompt}ygg",
        Args["player_name#角色名", str],
        meta=CommandMeta(
            description="查询 Yggdrasil 玩家信息",
            usage=rf"{S_.command_prompt}ygg <player_name>",
            example=rf"{S_.command_prompt}ygg SerinaNya",
        ),
    ),
    rule=in_preset_cafe,
)


@ygg.handle()
async def cmd_ygg(player_name: Match[str]):
    """查询并展示指定角色在 LittleSkin Yggdrasil API 中的资料与材质信息。"""
    try:
        # 调用外部 LittleSkin Yggdrasil API 查询角色档案
        player = await get_ygg_player(player_type="ltsk", player_name=player_name.result)
    except PlayerNotFoundError:
        _message = f"「{player_name.result}」不存在"
        await ygg.send(UniMessage(_message), reply_to=True)
        return
    except HTTPStatusError as e:
        _message = f"请求错误: {e.response.status_code}"
        await ygg.send(UniMessage(_message), reply_to=True)
        return
    # success
    # 提取皮肤模型（默认 default 或纤细 slim）与材质哈希
    skin_model = player.skin.metadata.model if player.skin and player.skin.metadata else None

    _message = f"""「{player.name}」的资料 - 来自 Yggdrasil API

» Skin ({skin_model}): {player.skin.hash if player.skin and player.skin.hash else None}

» Cape: {player.cape.hash if player.cape and player.cape.hash else None}

» UUID: {player.id}"""

    # 随机延时模拟人类行为，规避频率限制后发送回复
    await random_sleep(2)
    await ygg.send(UniMessage(_message), reply_to=True)


# endregion


# region %pro
pro = on_alconna(
    Alconna(
        f"{S_.command_prompt}pro",
        Args["player_name#角色名", str],
        meta=CommandMeta(
            description="查询 Pro 玩家信息",
            usage=rf"{S_.command_prompt}ygg <player_name>",
            example=rf"{S_.command_prompt}ygg SerinaNya",
        ),
    ),
    rule=in_preset_cafe,
)


@pro.handle()
async def cmd_pro(player_name: Match[str]):
    """查询并展示指定角色在 Mojang 官方正版 API 中的资料与材质信息。"""
    try:
        # 调用外部 Mojang 正版 API 查询角色档案
        player = await get_ygg_player(player_type="pro", player_name=player_name.result)
    except PlayerNotFoundError:
        _message = f"「{player_name.result}」不存在"
        await pro.send(UniMessage(_message), reply_to=True)
        return
    except HTTPStatusError as e:
        _message = f"请求错误: {e.response.status_code}"
        await pro.send(UniMessage(_message), reply_to=True)
        return
    # success
    # 提取皮肤模型（默认 default 或纤细 slim）与材质哈希
    skin_model = player.skin.metadata.model if player.skin and player.skin.metadata else None

    _message = f"""「{player.name}」的资料 - 来自 Pro

» Skin ({skin_model}): {player.skin.hash if player.skin and player.skin.hash else None}

» Cape: {player.cape.hash if player.cape and player.cape.hash else None}

» UUID: {player.id}"""

    # 随机延时模拟人类行为，规避频率限制后发送回复
    await random_sleep(2)
    await pro.send(UniMessage(_message), reply_to=True)


# endregion
