"""群文件消息监听与日志记录（占位插件）。

对应 Avilla 原版 modules/log_file.py 实验性功能。
原版监听群文件上传并打印 FileData；此处适配 OneBot V11 消息事件，
筛选含有 file 消息段的消息并输出元信息日志，预留后续扩展（如日志自动解析分析）。

事件：
- MessageEvent (含有 file 消息段): 监听预设群内上传文件的消息并记录段元数据 (适用群: in_preset_general; 权限: 所有人)
"""

from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.rule import Rule

from plugins.commspt_bot.utils.adv_filter import from_groups_preset_general


async def _has_file(event: MessageEvent) -> bool:
    """检查消息事件中是否包含 file 类型的消息段。"""
    return bool(event.message["file"])


# priority=10 且 block=False，仅记录文件元数据，不阻断后续其他处理器的执行
process_log_file = on_message(
    rule=from_groups_preset_general() & Rule(_has_file),
    priority=10,
    block=False,
)


@process_log_file.handle()
async def _(event: MessageEvent):
    """记录群内接收到的文件消息段元数据。"""
    logger.info("Received file from allowed group.")
    for segment in event.message["file"]:
        logger.info(f"file segment: {segment.data}")
