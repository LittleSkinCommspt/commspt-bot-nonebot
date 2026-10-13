"""入群审批的表情回应交互。

对应 `commspt_do_action_join.py` 的文字命令审批，为同一条审批通知消息
提供「贴 👍/👎」的快捷审批方式，两者共用 `utils/join_action.py` 的执行核心。

工作方式：
- commspt_join_group 发出待人工审核通知后贴上 👍（128077）/ 👎（128078），
  并通过 `remember_approval` 登记 ``message_id -> JoinRequestNotice`` 凭证；
- 本插件监听协议端推送的 ``group_msg_emoji_like`` 事件，校验群聊、权限与凭证后，
  取回对应凭证并调用 ``execute_join_action`` 执行审批；
- 审批完成后在群内 @ 操作管理员播报结果（文案与 do 命令共用 ``describe_result``），
  成功时撤销通知消息上的 👍/👎 引导表情。

注：nonebot-adapter-onebot 无 ``group_msg_emoji_like`` 类型化事件类，
故以 ``notice_type`` 宽匹配 + ``getattr`` 读取附加字段。
"""

from nonebot import logger, on_notice
from nonebot.adapters.onebot.v11 import Bot
from nonebot.adapters.onebot.v11.event import NoticeEvent
from nonebot.rule import Rule

from plugins.commspt_bot.config import C_, S_
from plugins.commspt_bot.utils.join_action import (
    APPROVAL_EMOJIS,
    EMOJI_APPROVE,
    EMOJI_REJECT,
    SUCCESS,
    describe_result,
    execute_join_action,
    pop_approval,
    remember_approval,
)
from plugins.commspt_bot.utils.messenger import send_to_group_with_at
from plugins.commspt_bot.utils.random_sleep import random_sleep


def _is_emoji_like(event: NoticeEvent) -> bool:
    """仅匹配群消息表情回应事件（协议端 SnowLuma 推送）。"""
    return getattr(event, "notice_type", None) == "group_msg_emoji_like"


def _field(obj, name: str, default=None):
    """从 dict 或对象上按字段名取值（兼容协议端两种序列化形态）。"""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


emoji_approval = on_notice(rule=Rule(_is_emoji_like), priority=1, block=False)

# 允许表情审批的群聊集合：主群审批通知发往 commspt_group，茶馆群审批通知发往 littleskin_cafe。
# 凭证索引按 message_id 全局唯一，无需区分来源群。
_ALLOWED_GROUPS = {
    S_.defined_qq.commspt_group,
    S_.defined_qq.littleskin_cafe,
}

# 审批引导表情集合（用于快速判断事件是否与审批相关）
_APPROVAL_EMOJI_SET = set(APPROVAL_EMOJIS)


def _extract_emoji_ids(likes) -> set[str]:
    """从事件 likes 字段提取表情编号集合（兼容 dict / 对象两种形态）。"""
    return {str(eid) for like in (likes or []) if (eid := _field(like, "emoji_id")) is not None}


async def verify_operator(bot: Bot, message_id: int, emoji_id: str, operator_id: int) -> bool:
    """用 get_msg_emoji_likes 复核 operator 确实回应该消息的该表情。

    返回 True 表示确认（或查询失败时按事件本身放行），False 表示确认未回应。
    """
    try:
        data = await bot.call_api("get_msg_emoji_likes", message_id=message_id)
    except Exception:
        # 查询失败时放行，依事件本身为准
        return True
    for item in data or []:
        if str(_field(item, "emoji_id")) != emoji_id:
            continue
        users = _field(item, "users") or []
        return any(_field(u, "user_id") == operator_id for u in users)
    return False


async def clear_guide_emojis(bot: Bot, message_id: int) -> None:
    """撤销 Bot 在通知消息上贴的 👍/👎 引导表情（失败仅告警，不影响审批结果）。"""
    for emoji in APPROVAL_EMOJIS:
        try:
            await bot.call_api(
                "set_msg_emoji_like",
                message_id=message_id,
                emoji_id=emoji,
                set=False,
            )
        except Exception as e:
            logger.warning(f"撤销引导表情 {emoji} 失败：{type(e).__name__}: {e}")


@emoji_approval.handle()
async def emoji_approval_handler(bot: Bot, event: NoticeEvent):
    """处理审批通知消息上的表情回应。"""
    # 仅处理「添加回应」，且排除 Bot 自身（Bot 贴表情同样会触发 add 事件）
    if getattr(event, "sub_type", None) != "add":
        return
    operator_id = getattr(event, "operator_id", None)
    if operator_id is None or operator_id == int(bot.self_id):
        return
    group_id = getattr(event, "group_id", None)
    if group_id not in _ALLOWED_GROUPS:
        return
    if operator_id not in C_.admin_list:
        return

    # likes 为全群累计，此处仅用于快速判断事件是否与审批相关
    emoji_ids = _extract_emoji_ids(getattr(event, "likes", None))
    if not (_APPROVAL_EMOJI_SET & emoji_ids):
        return

    message_id = getattr(event, "message_id", None)
    if message_id is None:
        return

    # 弹出即消费，保证同一申请只被处理一次
    message_id = int(message_id)
    notice = await pop_approval(message_id)
    if notice is None:
        return

    # 单一表情直接判定；多种表情并存时用 get_msg_emoji_likes 复核本人意图
    if emoji_ids == {EMOJI_APPROVE}:
        approve: bool | None = True
    elif emoji_ids == {EMOJI_REJECT}:
        approve = False
    elif await verify_operator(bot, message_id, EMOJI_APPROVE, operator_id):
        approve = True
    elif await verify_operator(bot, message_id, EMOJI_REJECT, operator_id):
        approve = False
    else:
        # 复核失败时保守处理：不审批，把凭证放回
        await remember_approval(message_id, notice)
        return

    await random_sleep(2)
    result = await execute_join_action(
        bot,
        notice,
        approve=approve,
        operator_id=operator_id,
        source="reaction",
    )

    # 群内播报结果（文案与 do 命令一致），失败不影响审批本身
    action = "accept" if approve else "reject"
    try:
        await send_to_group_with_at(group_id, operator_id, describe_result(result, action))
    except Exception as e:
        logger.warning(f"发送审批结果反馈失败：{type(e).__name__}: {e}")

    # 成功后撤销引导表情，失败时保留以便重试
    if result.outcome == SUCCESS:
        await clear_guide_emojis(bot, message_id)
