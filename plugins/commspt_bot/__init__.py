"""LittleSkin 社区支持机器人父插件入口与子插件加载器。

项目由原 Avilla 框架重构迁移至 NoneBot2 + Alconna 架构。
本模块作为根插件声明 PluginMetadata 并限定支持 OneBot V11 适配器（supported_adapters={"~onebot.v11"}），
并在初始化时通过 nonebot.load_plugins 动态加载 plugins/ 子目录下的所有功能子插件（插件 ID 格式形如 commspt_bot:commspt_xxx）。
"""

from pathlib import Path

import nonebot
from nonebot.plugin import PluginMetadata

from .config import Setting

__plugin_meta__ = PluginMetadata(
    name="commspt-bot",
    description="LittleSkin 社区支持 QQ 机器人 (NoneBot2 / Alconna)",
    usage="参见 https://bot-manual.commspt.littlesk.in/",
    type="application",
    homepage="https://github.com/LittleSkinCommspt/commspt-bot-avilla",
    supported_adapters={"~onebot.v11"},
    config=Setting,
)

# 动态加载 plugins/ 目录下的所有业务子插件
sub_plugins = nonebot.load_plugins(
    str(Path(__file__).parent.joinpath("plugins").resolve()),
)
