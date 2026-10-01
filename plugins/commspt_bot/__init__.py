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

sub_plugins = nonebot.load_plugins(
    str(Path(__file__).parent.joinpath("plugins").resolve()),
)
