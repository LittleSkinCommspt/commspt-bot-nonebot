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
    ygg_latest_data = await AuthlibInjectorLatest.get()
    await ygg_latest.send(
        UniMessage(
            f"「Authlib Injector」\n当前最新版本 > {ygg_latest_data.version}\n下载地址 > {ygg_latest_data.download_url}",
        ),
        reply_to=True,
    )


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
    version: int = parma["version"]
    ftype: str = parma["type"]
    os_: str = parma["os"]
    arch: str = parma["arch"]
    java_latest_data: list[LibericaJavaLatest] = await LibericaJavaLatest.get(
        version_feature=version,
        bundle_type=f"{ftype}-full",
        os=os_,
        architecture=arch,
    )
    await java_latest.send(
        UniMessage(
            f"「Liberica Java {java_latest_data[0].feature_version} ({java_latest_data[0].bundle_type})」\n下载地址 > {java_latest_data[0].download_url_mirror}",
        ),
        reply_to=True,
    )
