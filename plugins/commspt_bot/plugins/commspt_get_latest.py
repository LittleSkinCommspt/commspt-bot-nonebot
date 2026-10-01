"""组件与运行环境最新版本查询模块。

从 Avilla 原版的版本查询指令移植到 NoneBot2 + Alconna 架构。
通过 UniMessage 发送统一格式的回复，兼容跨平台与 OneBot V11 协议端。

命令：
- &csl.latest   获取 CustomSkinLoader 最新版本与配置指引 (in_preset_cafe; 默认)
- &ygg.latest   获取 Authlib Injector 最新版本信息 (in_preset_cafe; 默认)
- &java.latest [version] [type] [os] [arch]   获取 Liberica Java 最新版本及镜像下载链接 (in_preset_cafe; 默认)
"""

from arclet.alconna import Alconna, Args, Arparma, CommandMeta
from nonebot_plugin_alconna import on_alconna
from nonebot_plugin_alconna.uniseg import UniMessage

from plugins.commspt_bot.config import S_
from plugins.commspt_bot.models.version_api import (
    AuthlibInjectorLatest,
    LibericaJavaLatest,
)
from plugins.commspt_bot.utils.adv_filter import in_preset_cafe

csl_latest = on_alconna(
    Alconna(
        f"{S_.command_prompt}csl.latest",
        meta=CommandMeta(
            description="获取 CustomSkinLoader 最新版本信息",
            usage=rf"{S_.command_prompt}csl.latest",
            example=rf"{S_.command_prompt}csl.latest",
        ),
    ),
    rule=in_preset_cafe,
)


@csl_latest.handle()
async def _csl_latest():
    """发送 CustomSkinLoader 的下载指引与配置页面地址。"""
    # CSL 无需外部 API 动态轮询，直接指引前往 LittleSkin 用户配置生成页获取
    await csl_latest.send(UniMessage("「CustomSkinLoader」\n请前往 https://littleskin.cn/user/config 下载"), reply_to=True)


ygg_latest = on_alconna(
    Alconna(
        f"{S_.command_prompt}ygg.latest",
        meta=CommandMeta(
            description="获取 Yggdrasil 最新版本信息",
            usage=rf"{S_.command_prompt}ygg.latest",
            example=rf"{S_.command_prompt}ygg.latest",
        ),
    ),
    rule=in_preset_cafe,
)


@ygg_latest.handle()
async def _ygg_latest():
    """查询并返回 Authlib Injector 的最新版本与下载链接。"""
    # 请求外部 API 查询 authlib-injector 的最新构建版本及发布下载链接
    ygg_latest_data = await AuthlibInjectorLatest.get()
    await ygg_latest.send(
        UniMessage(
            f"「Authlib Injector」\n当前最新版本 > {ygg_latest_data.version}\n下载地址 > {ygg_latest_data.download_url}",
        ),
        reply_to=True,
    )


# 命令参数：Java 主版本号(默认17)、包类型(默认jre)、操作系统类型(默认windows)、架构(默认x86)
java_latest = on_alconna(
    Alconna(
        f"{S_.command_prompt}java.latest",
        Args["version#Java 版本", int, 17]["type#Java 类型", str, "jre"]["os#操作系统类型", str, "windows"]["arch#架构", str, "x86"],
        meta=CommandMeta(
            description="获取 Java 最新版本信息",
            usage=rf"{S_.command_prompt}java.latest [version] [type] [os] [arch]",
            example=rf"{S_.command_prompt}java.latest 17 jdk windows x86",
        ),
    ),
    rule=in_preset_cafe,
)


@java_latest.handle()
async def _java_latest(parma: Arparma):
    """根据版本、类型、操作系统与架构查询 Liberica Java 的最新下载链接。"""
    # 从命令解析结果中提取各筛选维度参数
    version: int = parma["version"]
    ftype: str = parma["type"]
    os_: str = parma["os"]
    arch: str = parma["arch"]
    # 调用外部 BellSoft Liberica API 查询符合筛选条件的 Java 运行时/开发包列表
    java_latest_data: list[LibericaJavaLatest] = await LibericaJavaLatest.get(
        version_feature=version,
        bundle_type=f"{ftype}-full",
        os=os_,
        architecture=arch,
    )
    # 裁剪并提取首个匹配结果的特性版本、bundle 类型以及国内镜像下载链接
    await java_latest.send(
        UniMessage(
            f"「Liberica Java {java_latest_data[0].feature_version} ({java_latest_data[0].bundle_type})」\n下载地址 > {java_latest_data[0].download_url_mirror}",
        ),
        reply_to=True,
    )
