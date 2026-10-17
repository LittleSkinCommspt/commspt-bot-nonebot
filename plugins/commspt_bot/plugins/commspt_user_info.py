"""LittleSkin 用户信息卡片查询与 UID 绑定管理插件

移植自原 Avilla 版 user_info.py 模块，在 NoneBot2 + Alconna 体系下实现。
通过 LittleSkin API 获取用户信息，结合 MongoDB 中的 QQ 绑定数据，通过 Browserless 渲染 HTML 模板生成资料卡片；
同时提供管理员命令维护 QQ 与 UID 的映射关系，OneBot V11 下兼容 At 提及与纯数字 QQ 输入。

命令：
- &user <uid>            查询指定 UID 用户的资料卡片并渲染为图片   (适用群: in_preset_commspt; 权限: admin_only)
- &setuid <target> <uid> 绑定目标 QQ (@ 提及或纯数字) 与 LittleSkin UID   (适用群: in_preset_cafe; 权限: admin_only)

附加行为：若被查询账号处于封禁状态（permission == -1），则在资料卡片后一并发出
该 UID 在飞书多维表格中的封禁记录。命令本身仅限 commspt_group / dev_group 可用，
故无需再单独判断群号。
"""

from arclet.alconna import Alconna, Args, CommandMeta
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot_plugin_alconna import At, Match, on_alconna
from nonebot_plugin_alconna.uniseg import UniMessage

from plugins.commspt_bot.models.littleskin_api import LittleSkinUser
from plugins.commspt_bot.models.mongodb_data import UIDMapping
from plugins.commspt_bot.models.render_user_info import RenderUserInfo
from plugins.commspt_bot.utils.adv_filter import (
    admin_only,
    in_preset_cafe,
    in_preset_commspt,
)
from plugins.commspt_bot.utils.ban_lookup import banned_records_block
from plugins.commspt_bot.utils.mongodb_manager import write_uid_db
from plugins.commspt_bot.utils.qq_profile import get_qq_nickname
from plugins.commspt_bot.utils.replies import SERVICE_FAILURE_MESSAGE
from plugins.commspt_bot.utils.retry import call_with_retry

user_info = on_alconna(
    Alconna(
        "user",
        Args["uid#UID", int],
        meta=CommandMeta(
            description="查询用户信息 (commspt [group] only)",
            usage=r"&user <uid>",
            example=r"&user 123456",
        ),
    ),
    rule=in_preset_commspt,
    permission=admin_only,
)


@user_info.handle()
async def _user_info(bot: Bot, uid: Match[int]):
    """根据 UID 查询 LittleSkin 用户信息及 QQ 绑定记录，渲染卡片图片并发送。"""
    logger.info(f"Looking for user info uid={uid.result}")
    try:
        # 调用 LittleSkin API 获取用户公开信息（失败自动重试，仅重跑本次调用）
        ltsk_user = await call_with_retry("LittleSkin 管理端 API", LittleSkinUser.uid_info, uid.result)
        # 从 MongoDB 查询 UID 绑定的 QQ 号（失败自动重试）
        mapping_qq = await call_with_retry("MongoDB 映射数据库", UIDMapping.fetch, uid=uid.result)
    except Exception as e:
        logger.error(f"&user 外部服务请求失败：{type(e).__name__}: {e}")
        await user_info.send(UniMessage(SERVICE_FAILURE_MESSAGE))
        return
    logger.info(f"UID Mapping: {uid.result} -> {mapping_qq}")
    if not ltsk_user:
        await user_info.send(UniMessage(f"未找到 UID 为 {uid.result} 的用户"))
        logger.error(f"UID {uid.result} not found.")
        return
    logger.info(f"Ready to render {uid.result} ↓")
    logger.info(ltsk_user)
    try:
        # 查询绑定 QQ 的全局昵称（协议端调用，失败时为空，卡片自动省略昵称）
        qq = mapping_qq.qq if mapping_qq else None
        qq_nickname = await get_qq_nickname(bot, qq) if qq else ""
        # 组装数据，通过 HTML 模板与 Browserless 渲染截图（渲染类服务不重试）
        render = RenderUserInfo(**ltsk_user.model_dump(), qq=qq, qq_nickname=qq_nickname)
        image = await render.get_image()
    except Exception as e:
        logger.error(f"&user 出图失败：{type(e).__name__}: {e}")
        await user_info.send(UniMessage(SERVICE_FAILURE_MESSAGE))
        return
    await user_info.send(UniMessage.image(raw=image))
    logger.success("Image sent.")

    # 账号被封禁时，追加该 UID 的飞书封禁记录
    # （命令规则已限定 commspt_group / dev_group，无需再判断群号）
    if block := await banned_records_block(uid.result, permission=ltsk_user.permission):
        await user_info.send(UniMessage(block))


set_uid = on_alconna(
    Alconna(
        "setuid",
        Args["target#目标", At | int]["uid#UID", int],
        meta=CommandMeta(
            description="设置用户记录的 UID (commspt only)",
            usage=r"&setuid <target> <uid>",
            example=r"&setuid @SerinaNya 15301",
        ),
    ),
    rule=in_preset_cafe,
    permission=admin_only,
)


@set_uid.handle()
async def _set_uid(target: Match[At | int], uid: Match[int], event: MessageEvent):
    """设置并持久化指定 QQ 与 LittleSkin UID 的映射记录。"""
    # 兼容处理：支持 OneBot V11 的 At 消息段与纯数字 QQ 号两种输入形式
    target_qq = int(target.result.target) if isinstance(target.result, At) else target.result
    target_uid = uid.result
    # 将 QQ <-> UID 映射关系持久化存储到 MongoDB
    await write_uid_db(uid=target_uid, qq=target_qq)
    await set_uid.send(UniMessage(f"RESULT ✅ > QQ {target_qq} <-> UID {target_uid}"))
