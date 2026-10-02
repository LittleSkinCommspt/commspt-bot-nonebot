"""命令前缀工具

从 NoneBot 运行时配置（`get_driver().config.command_start`）动态读取命令前缀，
避免在代码中硬编码具体前缀字符（如 `&`）。每次调用时实时读取配置，
配合前缀匹配（Alconna 全局前缀）保证展示与实际解析一致。

主要接口：
- configured_prefixes: 读取当前配置的全部命令前缀（长度降序，最长优先）
- primary_prefix: 当前主前缀（排序后的第一个；配置为空时为空字符串）
- display_command: 为命令名添加当前主前缀，用于展示（帮助文本等）
- strip_command_prefix: 剥离文本命中的前缀并返回剩余部分，未命中返回 None
"""

from nonebot import get_driver


def configured_prefixes() -> tuple[str, ...]:
    """读取当前配置的命令前缀，按长度降序排列（保证最长优先匹配）。

    次级按键名升序排序，使结果不受 set 迭代顺序影响（跨进程确定）。
    配置为空时返回 `("",)`，即允许无前缀触发命令。
    """
    command_start = get_driver().config.command_start
    if not command_start:
        return ("",)
    return tuple(sorted(command_start, key=lambda p: (-len(p), p)))


def primary_prefix() -> str:
    """当前配置的主前缀（configured_prefixes 的第一个元素，即最长前缀）。"""
    return configured_prefixes()[0]


def display_command(name: str) -> str:
    """为命令名添加当前主前缀，返回可直接展示的完整命令（如 `&help`）。"""
    return f"{primary_prefix()}{name}"


def strip_command_prefix(text: str) -> str | None:
    """若 text 以任一已配置前缀开头，剥离该前缀并返回剩余部分；否则返回 None。

    依 configured_prefixes 的顺序（最长优先）尝试，因此 `&&ping` 在
    `{"&", "&&"}` 配置下会完整剥离 `&&` 而不是留下一个 `&`。
    """
    for prefix in configured_prefixes():
        if text.startswith(prefix):
            return text[len(prefix):]
    return None
