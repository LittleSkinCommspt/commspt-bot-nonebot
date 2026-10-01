"""CustomSkinLoader (CSL) API 响应数据模型与查询接口。

封装 CustomSkinLoader 规范的皮肤接口响应（{api_root}/{username}.json）。
从 Avilla 原版移植，在模型验证前自动派生玩家是否存在、皮肤材质类型、材质哈希等扩展属性。

主要接口：
- CustomSkinLoaderApi: CSL API 响应数据模型及材质解析
- CustomSkinLoaderApi.get: 请求指定 CSL API 根路径获取玩家皮肤配置
"""

from typing import Literal

import httpx
from nonebot import logger
from pydantic import BaseModel, model_validator
from pydantic.fields import Field


class CustomSkinLoaderApi(BaseModel):
    """CustomSkinLoader /csl/{name}.json API 响应数据模型。"""

    username: str | None
    skins: dict[Literal["default", "slim"], str | None] | None
    skin_hash: str | None = None
    cape_hash: str | None = Field(None, alias="cape")
    player_existed: bool | None = True
    skin_type: Literal["default", "slim"] | None = None
    skin_existed: bool | None = True
    cape_existed: bool | None = True

    # 模型验证前预处理：根据原始字典派生 player_existed/skin_type/skin_existed/cape_existed/skin_hash
    @model_validator(mode="before")
    @classmethod
    def pre_processor(cls, values: dict):
        player_existed = bool(values)
        if not player_existed:
            skin_type = None
            skin_existed = False
            cape_existed = False
        else:
            skin_type = "slim" if "slim" in values["skins"] else "default" if values["skins"]["default"] else None
            cape_existed = "cape" in values and bool(values["cape"])
        # parse skin hash
        if skin_type == "default":
            skin_hash = values["skins"]["default"]
        elif skin_type == "slim":
            skin_hash = values["skins"]["slim"]
        else:
            skin_hash = None
        skin_existed = bool(skin_hash)

        values.update(
            {
                "player_existed": player_existed,
                "skin_type": skin_type,
                "skin_existed": skin_existed,
                "cape_existed": cape_existed,
                "skin_hash": skin_hash,
            }
        )
        return values

    @classmethod
    async def get(cls, api_root: str, username: str):
        """请求 {api_root}/{username}.json 获取玩家 CSL 材质配置。"""
        async with httpx.AsyncClient(base_url=api_root) as client:
            resp = (await client.get(f"{username}.json")).raise_for_status().json()
            if not resp:
                logger.warning(f"Player {username} not found.")
                return None
            return cls(**resp)
