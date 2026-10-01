"""log_file 插件占位

原 avilla 版 `log_file.py` 为实验性功能：监听群内上传的文件消息并打印元信息。
此处保留同等的占位实现（仅记录日志），便于后续扩展（如解析日志文件内容）。
"""

from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.rule import Rule

from plugins.commspt_bot.utils.adv_filter import from_groups_preset_general


async def _has_file(event: MessageEvent) -> bool:
    return bool(event.message["file"])


process_log_file = on_message(
    rule=from_groups_preset_general() & Rule(_has_file),
    priority=10,
    block=False,
)


@process_log_file.handle()
async def _(event: MessageEvent):
    logger.info("Received file from allowed group.")
    for segment in event.message["file"]:
        logger.info(f"file segment: {segment.data}")
