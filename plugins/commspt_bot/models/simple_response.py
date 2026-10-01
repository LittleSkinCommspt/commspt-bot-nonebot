"""简单问答命令配置数据模型与加载器。

封装静态问答（simple response）JSON 配置文件的 schema 定义与 fail-soft 加载逻辑。
每个键对应一条命令条目，包含别名列表、是否回复、文本内容及图片路径列表；
或使用 messages 有序片段列表，支持文字与图片的任意交替排列。
图片路径的实际解析（相对于 ASSETS_DIR）由调用方（子插件）负责，本模块不读取文件系统资源。

主要接口：
- TextPart: 文本片段（type="text"）
- ImagePart: 图片片段（type="image"）
- SimpleResponse: 单条命令响应配置的 pydantic v2 模型
- load_simple_responses: 从指定路径加载并校验配置，失败时降级返回空字典
"""

import json
from pathlib import Path
from typing import Annotated, Literal

import pydantic
from nonebot import logger
from pydantic import BaseModel, ConfigDict, Field, model_validator


class TextPart(BaseModel):
    """有序消息片段：纯文本。"""

    type: Literal["text"] = "text"
    content: str

    model_config = ConfigDict(extra="forbid")


class ImagePart(BaseModel):
    """有序消息片段：图片（路径相对于 ASSETS_DIR）。"""

    type: Literal["image"] = "image"
    path: str

    model_config = ConfigDict(extra="forbid")


class SimpleResponse(BaseModel):
    """单条简单问答命令的响应配置。

    两种互斥的消息体格式：
    - 经典格式：text + images（图片在前，文本在后）
    - 有序片段格式：messages（TextPart/ImagePart 任意交替排列）
    两者不能同时出现。
    """

    aliases: list[str] = []
    reply: bool = False
    text: str | None = None
    images: list[str] = []
    messages: list[Annotated[TextPart | ImagePart, Field(discriminator="type")]] | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _messages_exclusive(self):
        """messages 与 text/images 不能同时使用。"""
        if self.messages is not None and (self.text is not None or self.images):
            raise ValueError("messages 与 text/images 不能同时使用")
        return self


def load_simple_responses(path: Path) -> dict[str, SimpleResponse]:
    """从 JSON 文件加载简单问答配置，逐条校验，失败时降级。

    Args:
        path: 指向 simple response JSON 配置文件的路径。

    Returns:
        校验通过的条目字典；文件缺失或顶层结构异常时返回空字典。
        单条校验失败的条目被跳过，不影响其余条目。
    """
    if not path.is_file():
        logger.warning(f"简单问答配置文件不存在：{path}")
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"简单问答配置文件读取或解析失败（{path}）：{e}")
        return {}

    if not isinstance(raw, dict):
        logger.error(f"简单问答配置文件顶层结构应为对象（dict），实际为 {type(raw).__name__}：{path}")
        return {}

    result: dict[str, SimpleResponse] = {}
    for key, value in raw.items():
        try:
            result[key] = SimpleResponse.model_validate(value)
        except pydantic.ValidationError as e:
            logger.error(f"简单问答配置条目 {key!r} 校验失败，已跳过：{e}")

    return result
