"""OneBot V11 原生命令辅助

在不依赖 Alconna / UniMessage 的前提下提供前缀无关的原生命令匹配与参数解析：

- ``NATIVE_COMMANDS``: 已注册的原生命令名集合（供 simple_response 冲突检测）
- ``native_command_rule``: 基于事件纯文本（``get_plaintext``，已反转义）匹配命令名。
  OneBot V11 的 ``MessageSegment.__str__`` 会转义 ``&`` 等字符，导致 NoneBot 内置
  ``on_command``（依赖 ``TrieRule``）在 ``COMMAND_START="&"`` 下无法命中，
  故此处改用与 simple_response 相同的纯文本匹配方式。
- ``extract_command_args``: 去掉命令名（含配置前缀）后返回参数 token（At 段保留）
- ``segment_text``: 读取文本段的原始文本（不经过 CQ 转义）
- ``reply_to``: 引用触发消息的回复段

主要接口：
- native_command_rule(*names): 构造原生命令匹配规则并登记命令名
- extract_command_args(message): 解析命令参数 token 列表
- reply_to(event): 生成引用当前消息的 MessageSegment.reply 段
"""

from __future__ import annotations

from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment
from nonebot.rule import Rule

from plugins.commspt_bot.utils.command_prefix import strip_command_prefix

NATIVE_COMMANDS: set[str] = set()
"""已注册的原生命令名，供 commspt_simple_response 做命令冲突检测。"""


def native_command_rule(*names: str) -> Rule:
    """构造匹配指定原生命令名的 Rule，并把命令名登记到 ``NATIVE_COMMANDS``。"""
    NATIVE_COMMANDS.update(names)

    async def _checker(event: MessageEvent) -> bool:
        remainder = strip_command_prefix(event.get_plaintext().lstrip())
        if not remainder:
            return False
        return remainder.split(maxsplit=1)[0] in names

    return Rule(_checker)


def segment_text(segment: MessageSegment) -> str:
    """读取文本段的原始文本（不经过 CQ 转义）。"""
    return segment.data.get("text", "")


def extract_command_args(message: Message) -> list[MessageSegment]:
    """去掉开头的命令名（含配置前缀）后返回参数 token 列表。

    - 文本段拆分为 token，At 段原样保留
    - 仅剥离首个文本段中的命令名；其余文本段按原样分词
    """
    tokens: list[MessageSegment] = []
    command_consumed = False
    for segment in message:
        if segment.is_text():
            text = segment_text(segment)
            if not command_consumed:
                stripped = strip_command_prefix(text.lstrip())
                if stripped is None:
                    continue
                command_consumed = True
                remainder = stripped.split(maxsplit=1)
                if len(remainder) == 2:
                    tokens.extend(MessageSegment.text(token) for token in remainder[1].split())
                continue
            tokens.extend(MessageSegment.text(token) for token in text.split())
        elif segment.type == "at":
            tokens.append(segment)
    return tokens


def reply_to(event: MessageEvent) -> MessageSegment:
    """构造引用触发消息的回复段。"""
    return MessageSegment.reply(event.message_id)
