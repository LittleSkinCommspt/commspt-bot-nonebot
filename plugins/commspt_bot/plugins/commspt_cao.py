"""生草复读机：群内整条消息都是「草」时复读一个镜像反转的草。

对应 Avilla 原版 modules/cao.py。
原版基于 Graia 的 ``Twilight([RegexMatch(r'^草+$')])`` 限定群聊为茶馆群（littleskin_cafe），
命中后回复一个 RTL 反转控制符 +「草」。
此处改用 NoneBot2 的 ``on_message`` + 规则谓词实现，语义保持一致：

- 仅在小皮肤咖啡馆群（``littleskin_cafe``）生效
- 当群友发送的纯文本整条由若干「草」组成（``草`` / ``草草`` / ``草草草`` ...）时触发
- robot 回复 ``\\u202e草``：``\\u202e``（U+202E RIGHT-TO-LEFT OVERRIDE）使紧随其后的
  「草」在客户端以镜像翻转显示，形成「生草」的整活效果
"""

from __future__ import annotations

import re

from nonebot import on_message
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot_plugin_alconna.uniseg import UniMessage

from plugins.commspt_bot.utils.adv_filter import in_preset_only_cafe

# 回复内容：RTL 反转控制符 + 草（避免被编辑器/格式化工具误解，用转义序列书写）
CAO_REPLY = "\u202e草"


def match_cao(text: str) -> bool:
    """判断纯文本是否整条由若干「草」组成（等价原版 ``^草+$``）。"""
    return re.fullmatch(r"草+", text) is not None


async def _cao_rule(event: MessageEvent) -> bool:
    """命中规则：茶馆群 + 纯文本整条全为「草」。"""
    return match_cao(event.get_plaintext())


# 仅茶馆群、不 block（不独占消息，背离原版 broadcast 语义最小），与简单问答分发器同优先级
cao_matcher = on_message(rule=in_preset_only_cafe & _cao_rule, priority=10, block=False)


@cao_matcher.handle()
async def _handle_cao(bot: Bot, event: MessageEvent) -> None:
    """复读一个镜像反转的草。"""
    await UniMessage.text(CAO_REPLY).send(target=event, bot=bot)