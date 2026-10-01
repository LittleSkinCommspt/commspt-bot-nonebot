"""LittleSkin 社区常见问题与快捷回复的静态问答命令集。

对应 Avilla 原版 modules/simple_response.py。
基于 NoneBot2 + Alconna 动态注册命令匹配器，替代原版 AvillaCommands，
通过 register() 工厂函数批量注册命令，将问答文案或富文本统一包装为 UniMessage 并附带随机延迟回复。

命令：
- &ping             快速存活检测 (适用群: in_preset_cafe; 权限: 所有人; 引用回复)
- &help             机器人帮助文档与源码仓库指引 (适用群: in_preset_cafe; 权限: 所有人)
- &cafe             Honoka Café 水群引导提示与图片 (适用群: in_preset_cafe; 权限: 所有人)
- &browser          网页显示异常排查指引与示例图 (适用群: in_preset_cafe; 权限: 所有人)
- &log.csl          CustomSkinLoader 日志路径与提交提示 (适用群: in_preset_cafe; 权限: 所有人)
- &csl.log          CustomSkinLoader 日志路径与提交提示（同 &log.csl） (适用群: in_preset_cafe; 权限: 所有人)
- &log.mc           Minecraft 游戏与外置登录调试日志导出提示 (适用群: in_preset_cafe; 权限: 所有人)
- &csl.config       CustomSkinLoader 配置文件与加载顺序修改指引 (适用群: in_preset_cafe; 权限: 所有人)
- &pay              爱发电一对一赞助支持渠道链接 (适用群: in_preset_cafe; 权限: 所有人)
- &manual           LittleSkin 用户使用手册与 RTFM 引导图 (适用群: in_preset_cafe; 权限: 所有人)
- &pro_verify       LittleSkin 正版验证影响与账号离线性质说明 (适用群: in_preset_cafe; 权限: 所有人)
- &ygg.online_mode  外置登录服务器 online-mode 配置说明 (适用群: in_preset_cafe; 权限: 所有人)
- &cape_format      披风图片规格要求说明 (适用群: in_preset_cafe; 权限: 所有人)
- &network          网络维护及地区 DNS 污染排查建议 (适用群: in_preset_cafe; 权限: 所有人)
- &faq              手册常见问题解答 (FAQ) 章节指引 (适用群: in_preset_cafe; 权限: 所有人)
- &hta              提问前准备事项与信息收集指引 (适用群: in_preset_cafe; 权限: 所有人)
- &copyright        材质版权申诉所需资料与邮件格式说明 (适用群: in_preset_cafe; 权限: 所有人)
"""

from pathlib import Path

from arclet.alconna import Alconna, CommandMeta
from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot_plugin_alconna import on_alconna
from nonebot_plugin_alconna.uniseg import Image, Text, UniMessage

from plugins.commspt_bot.config import ASSETS_DIR
from plugins.commspt_bot.utils.adv_filter import in_preset_cafe
from plugins.commspt_bot.utils.random_sleep import random_sleep

default_rule = in_preset_cafe


# region register
def register(command: str | list[str], response: str | UniMessage | list, reply: bool = False):
    """批量注册简易响应命令的工厂函数，将指定命令注册为 Alconna 匹配器并绑定响应处理。

    Args:
        command (str): The command to register.
        response (str | UniMessage | list): The response to send when the command is triggered.
        reply (bool, optional): Flag indicating whether to reply to the triggering message. Defaults to False.

    Returns:
        None
    """

    def _to_unimsg(resp: str | UniMessage | list) -> UniMessage:
        """将纯文本、UniMessage 或包含图片/文本的列表统一转换为 UniMessage 消息对象。"""
        if isinstance(resp, UniMessage):
            return resp
        if isinstance(resp, str):
            return UniMessage(resp)
        msg = UniMessage()
        for item in resp:
            if isinstance(item, str):
                msg.append(Text(item))
            elif isinstance(item, Path):
                msg.append(Image(path=item))
            elif isinstance(item, Image):
                msg.append(item)
            else:
                msg.append(Text(str(item)))
        return msg

    commands = [command] if isinstance(command, str) else command
    for command_item in commands:
        logger.info(f"- ✅ &{command_item}")

        # 动态创建独立的 Alconna 匹配器；block=False 确保不阻断其他同优先级的消息处理器
        _matcher = on_alconna(
            Alconna(
                command_item,
                meta=CommandMeta(
                    description=f"&{command_item}",
                    usage=f"&{command_item}",
                ),
            ),
            rule=default_rule,
            priority=10,
            block=False,
        )

        # 独立函数注册 handler，避免循环变量被闭包捕获共享
        _register_handler(_matcher, _to_unimsg(response), reply)


def _register_handler(matcher: type, response: UniMessage, reply: bool):
    """为单个 matcher 注册响应函数（避免循环变量被闭包共享）"""

    @matcher.handle()
    async def _simple_response(event: MessageEvent):
        await random_sleep()  # 随机休眠数秒模拟打字延迟，防风控与刷屏
        await matcher.send(response, reply_to=reply)

# endregion

print("registering simple response...")


register("ping", "在", reply=True)

register(
    "help",
    """请参阅 https://bot-manual.commspt.littlesk.in/
源码请参见 https://github.com/LittleSkinCommspt/commspt-bot-avilla

请注意查看使用条例；在此提醒您: **请不要滥用机器人的任何功能，不然你有可能会被某个神秘人士出警**""",
)

register(
    "cafe",
    [
        ASSETS_DIR / "images" / "honoka cafe ng.png",
        """本群不允许讨论非 LittleSkin 问题和闲聊，可以加入 Honoka Café 和大家一起水群。
群号: 651672723""",
    ],
)

register(
    "browser",
    [
        ASSETS_DIR / "images" / "browser.png",
        "详见 https://manual.littlesk.in/faq/site#broken-webpage",
    ],
)

register(
    ["log.csl", "csl.log"],
    """CustomSkinLoader 的日志位于 .minecraft/CustomSkinLoader/CustomSkinLoader.log
在使用版本隔离的情况下则为 .minecraft/versions/{version}/CustomSkinLoader/CustomSkinLoader.log

请将 CustomSkinLoader 日志文件直接发送至群内。

详见 https://manual.littlesk.in/problems#customskinloader""",
)

register(
    "log.mc",
    "请使用启动器的「测试游戏」功能启动游戏，并在复现问题后导出日志发送至群内。如果问题与外置登录有关，请在启动器的「JVM 参数（Java 虚拟机参数）」设置中填入 -Dauthlibinjector.debug",
)

register(
    "csl.config",
    """若安装了 CustomSkinLoader 后无法正确加载皮肤，可能是当前角色名被同名正版优先加载，可通过以下方法手动修改 CustomSkinLoader 的加载顺序：
https://manual.littlesk.in/newbee/csl#edit-csl-config""",
)

register(
    "pay",
    """在群里和大佬吹牛逼帮助不了你的问题？
速来 https://afdian.com/a/tnqzh123
获取一对一帮助服务即可快速解决你的问题！""",
)

register(
    "manual",
    [
        ASSETS_DIR / "images" / "rtfm.png",
        """请仔细阅读 LittleSkin 用户使用手册，特别是「常见问题解答」！
https://manual.littlesk.in/""",
    ],
)

register(
    "pro_verify",
    """目前在 LittleSkin 验证正版后会产生如下影响：
· 在主页上获得一个「正版」（英文也为「正版」）徽标
· 赠送您 1000 积分；
· 在皮肤站内取回您的正版 ID 对应的角色（如果您的 ID 已被人抢注）。

请参考 https://manual.littlesk.in/newbee/premium

使用「正版验证」的前提是「您购买了正版并在官方启动器启动过一次游戏」；如您的目的并不是这个，请考虑换种问法提问。

请注意，无论是否进行正版验证，您的 LittleSkin 外置登录账号始终不具备正版的属性，性质 **仍为离线账号**。
您无法将 LittleSkin 外置登录账号代替正版账号使用。""",
)

register(
    "ygg.online_mode",
    """请确认服务器正确配置 authlib-injector 并将 online-mode 设为 true，否则请使用 CustomSkinLoader。
如果服务器未开启「正版验证」则所有登录方式都会被服务器视为离线模式处理；
即服务器自行生成 UUID，且不会向验证服务器（皮肤站 / 正版）获取材质。
详细：https://manual.littlesk.in/yggdrasil/""",
)

register(
    "cape_format",
    """「不是有效的披风文件」
LittleSkin 对于披风文件的格式要求如下：
· png 格式文件
· 宽高比需为 2:1
· 为 64x32 的整倍数""",
)

register(
    "network",
    """「登录失败：身份验证服务器目前正在停机维护」
「无法验证用户名」
「验证服务器他们宕了吗？」：
玄学的网络问题会导致此情况的出现，请优先检查您的网络环境和使用的域名是否为 littleskin.cn，并在重启游戏后再次尝试登录。

如果您位于福建省，有概率因为地区性的 DNS 污染而导致无法连接到 LittleSkin。
此时请您查阅群公告以解决此问题。
有时部分无法连接的问题也可通过群公告的教程解决。""",
)

register(
    "faq",
    """请您查看手册上的 常见问题解答 (FAQ) 章节，尝试按照手册上的指示自行解决您的问题。如无法解决请您继续询问。
https://manual.littlesk.in/faq""",
)


register(
    "hta",
    """请您阅读手册上的 遇到问题了咋办 章节后，准备好可能需要的 信息 / 文件 后，再来询问，否则有可能无法获得 (社区) 支持组 的帮助！
https://manual.littlesk.in/problems""",
)

register(
    "copyright",
    """「版权申诉」
请准备可以证明材质所有者的相关资料，以便进行申诉。
相关资料如：
- 材质的工程文件 / 约稿记录
- 在其他平台的材质发布帖 / 创作动态
- ... 等

并准备好您的 UID，您的 QQ 号，需申诉材质的 TID（如需要申诉多个材质，可使用 txt 文件，一行一个材质链接，附在 zip 内） 等信息。

请将这些文件统一使用 zip 格式打包，并使用您在 LittleSkin 绑定的邮箱，通过 邮件附件 的方式发送至 support@littlesk.in 以进行申诉。我们一般会在 7 个工作日内处理您的请求。""",
)
