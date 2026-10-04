"""外部组件版本查询 API 模型与请求封装。

封装 CustomSkinLoader（GitHub Releases）、authlib-injector（官方制品库）及 Liberica JDK（BellSoft API）的版本信息。
从 Avilla 原版移植，为版本查询指令提供外部 API 响应反序列化与镜像链接派生。

主要接口：
- CustomSkinLoaderLatest: CustomSkinLoader 最新 Release 数据模型与获取
- AuthlibInjectorLatest: authlib-injector 最新构建产物数据模型与获取
- LibericaJavaLatest: Liberica JDK 发布版本数据模型与查询
"""

from datetime import datetime
from typing import Annotated

import httpx
from pydantic import (
    AliasGenerator,
    BaseModel,
    ConfigDict,
    TypeAdapter,
    alias_generators,
)
from pydantic.fields import Field
from pydantic.networks import AnyHttpUrl

from plugins.commspt_bot.config import VERIFY_CONTENT


class CustomSkinLoaderLatest(BaseModel):
    """CustomSkinLoader GitHub Release 最新版本响应模型。"""

    class Downloads(BaseModel):
        """CustomSkinLoader 各 Loader 构建产物下载地址。"""

        fabric: Annotated[AnyHttpUrl, str] = Field(alias="Fabric")
        forge: Annotated[AnyHttpUrl, str] = Field(alias="Forge")
        forgeactive: Annotated[AnyHttpUrl, str] = Field(alias="ForgeActive")

        @property
        def generate_download_text(self) -> str:
            """生成包含各 Loader 版本的文本格式下载列表。"""
            return f"Fabric > {self.fabric}\nForge > {self.forge}\nForge Active > {self.forgeactive}"

    version: str
    downloads: Downloads

    @classmethod
    async def get(cls):
        """获取 CustomSkinLoader 最新版本信息

        请求 GitHub Releases API (https://api.github.com/repos/CustomSkinLoader/CustomSkinLoader/releases/latest)。

        Returns:
            CustomSkinLoaderLatest: CustomSkinLoader 最新版本信息
        """
        async with httpx.AsyncClient(verify=VERIFY_CONTENT) as client:
            return cls(
                **(await client.get("https://api.github.com/repos/CustomSkinLoader/CustomSkinLoader/releases/latest"))
                .raise_for_status()
                .json(),
            )


class AuthlibInjectorLatest(BaseModel):
    """authlib-injector 构建制品最新版本响应模型。"""

    class CheckSums(BaseModel):
        """authlib-injector 制品校验和信息。"""

        sha256: str

    build_number: int
    version: str
    release_time: datetime
    download_url: Annotated[AnyHttpUrl, str]
    checksums: CheckSums

    @classmethod
    async def get(cls):
        """获取 Authlib-Injector 最新版本信息

        请求 authlib-injector 官方制品接口 (https://authlib-injector.yushi.moe/artifact/latest.json)。

        Returns:
            AuthlibInjectorLatest: Authlib-Injector 最新版本信息
        """
        async with httpx.AsyncClient(verify=VERIFY_CONTENT) as client:
            return cls(
                **(await client.get("https://authlib-injector.yushi.moe/artifact/latest.json"))
                .raise_for_status()
                .json()
            )


class LibericaJavaLatest(BaseModel):
    """BellSoft Liberica JDK 发行版本信息模型。"""

    # 将 API 返回的小驼峰命名字段映射为 Python 蛇形属性名
    model_config = ConfigDict(alias_generator=AliasGenerator(validation_alias=alias_generators.to_camel))
    bitness: int
    latest_lts: bool = Field(alias="latestLTS")
    update_version: int
    download_url: Annotated[AnyHttpUrl, str]
    latest_in_feature_version: bool
    lts: bool = Field(alias="LTS")
    bundle_type: str
    feature_version: int
    package_type: str
    fx: bool = Field(alias="FX")
    ga: bool = Field(alias="GA")
    architecture: str
    latest: bool
    extra_version: int
    build_version: int
    eol: bool = Field(alias="EOL")
    os: str
    interim_version: int
    version: str
    sha1: str
    filename: str
    installation_type: str
    size: int
    patch_version: int
    tck: bool = Field(alias="TCK")
    update_type: str

    @property
    def download_url_mirror(self):
        """派生官方镜像下载地址。"""
        return f"https://download.bell-sw.com/java/{self.version}/{self.filename}"

    @classmethod
    async def get(
        cls,
        **kwargs,
    ):
        """获取 Liberica Java 版本信息

        请求 BellSoft API (https://api.bell-sw.com/v1/liberica/releases)。
        参考 [BellSoft 官方 API 文档](https://api.bell-sw.com/api.html#/Binaries/get_liberica_releases)。

        Returns:
            List[LibericaJavaLatest]: Liberica Java 版本信息列表
        """

        libereca_releases = TypeAdapter(list[cls])

        # 将下划线命名参数转换为 API 接收的中划线命名参数（如 feature_version -> feature-version）
        for key in kwargs:
            kwargs[key.replace("_", "-")] = kwargs.pop(key)
        async with httpx.AsyncClient(verify=VERIFY_CONTENT) as client:
            return libereca_releases.validate_python(
                (
                    await client.get(
                        "https://api.bell-sw.com/v1/liberica/releases",
                        params=kwargs,
                    )
                )
                .raise_for_status()
                .json(),
            )
