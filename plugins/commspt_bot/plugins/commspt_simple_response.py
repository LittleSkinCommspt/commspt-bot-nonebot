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

from arclet.alconna import Alconna, CommandMeta
from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot_plugin_alconna import on_alconna
from nonebot_plugin_alconna.uniseg import Image, Text, UniMessage

from plugins.commspt_bot.config import ASSETS_DIR, SIMPLE_RESPONSE_FILE
from plugins.commspt_bot.models.simple_response import SimpleResponse, load_simple_responses
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


def _build_message(entry: SimpleResponse) -> UniMessage:
    """根据 SimpleResponse 条目构建 UniMessage（图片在前，文本在后）。"""
    msg = UniMessage()
    for p in entry.images:
        msg.append(Image(path=ASSETS_DIR / p))
    if entry.text is not None:
        msg.append(Text(entry.text))
    return msg


_simple_responses = load_simple_responses(SIMPLE_RESPONSE_FILE)

for _command, _entry in _simple_responses.items():
    register(
        [_command, *_entry.aliases],
        _build_message(_entry),
        reply=_entry.reply,
    )
