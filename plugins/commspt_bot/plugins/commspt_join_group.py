"""LittleSkin 主群与茶馆群入群审核及新成员进群欢迎。

对应 Avilla 原版 modules/join_group.py。
基于 OneBot V11 的 GroupRequestEvent 与 GroupIncreaseNoticeEvent，
实现入群申请自动化校验（云控配置/QMail/UID校验）以及入群欢迎与通知频道推送。

事件：
- GroupRequestEvent: LittleSkin 主群加群申请 (rule=主群; 自动/手动审核)
- GroupRequestEvent: LittleSkin 茶馆群加群申请 (rule=茶馆群; 自动审核)
- GroupIncreaseNoticeEvent: LittleSkin 主群新成员进群 (rule=主群; 发送欢迎语与管理通知)
"""

import arrow
from nonebot import logger, on_notice, on_request
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupIncreaseNoticeEvent,
    GroupRequestEvent,
    Message,
    MessageSegment,
)
from nonebot.rule import Rule
from nonebot_plugin_alconna.uniseg import UniMessage

from plugins.commspt_bot.config import S_
from plugins.commspt_bot.models.cloudconfig import CloudConfig
from plugins.commspt_bot.models.littleskin_api import LittleSkinUser
from plugins.commspt_bot.models.mongodb_data import UIDMapping
from plugins.commspt_bot.models.render_user_info import RenderUserInfo
from plugins.commspt_bot.utils.ban_lookup import banned_records_block
from plugins.commspt_bot.utils.join_action import APPROVAL_EMOJIS, remember_approval
from plugins.commspt_bot.utils.join_request_notice import (
    JoinRequestNotice,
    NoticeKind,
    NoticeSubtype,
    format_join_request_notice,
)
from plugins.commspt_bot.utils.messenger import send_to_group as _send_to_group
from plugins.commspt_bot.utils.messenger import send_to_group_with_id as _send_to_group_with_id
from plugins.commspt_bot.utils.qq_profile import get_qq_nickname
from plugins.commspt_bot.utils.random_sleep import random_sleep


def _group_rule(group_id: int):
    """构建仅匹配指定群号事件的 Rule 规则工厂。"""
    async def _checker(event) -> bool:
        return getattr(event, "group_id", None) == group_id

    return Rule(_checker)


async def _send_approval_notice(
    bot: Bot,
    group_id: int,
    kind: NoticeKind,
    applicant: int,
    answer: str,
    sub_type: NoticeSubtype,
    flag: str,
    message: list[str],
    image: bytes | None = None,
) -> None:
    """向群聊发送入群审批通知并贴上 👍/👎 表情，登记表情审批凭证。

    仅用于「需要管理员人工处理」的通知；自动通过 / 纯结果通知请直接用 _send_to_group。
    协议端不支持 set_msg_emoji_like 时静默降级，不影响 do 命令审批。
    """
    notice = JoinRequestNotice(
        kind=kind,
        applicant=applicant,
        answer=answer,
        sub_type=sub_type,
        flag=flag,
    )
    # 保持与旧实现一致：通知块在前，附加提示行在后
    parts = [format_join_request_notice(kind, applicant, answer, sub_type, flag), *message]
    noti = UniMessage()
    if image:
        noti = noti.image(raw=image)
    noti = noti + "\n\n".join(m for m in parts if m)

    raw_msg_id = await _send_to_group_with_id(group_id, noti)
    try:
        message_id = int(raw_msg_id) if raw_msg_id is not None else None
    except (TypeError, ValueError):
        message_id = None
    if message_id is None:
        logger.warning("无法从发送回执解析 message_id，跳过贴表情（可用 do 命令审批）")
        return

    for emoji in APPROVAL_EMOJIS:
        try:
            await bot.call_api(
                "set_msg_emoji_like",
                message_id=message_id,
                emoji_id=emoji,
                set=True,
            )
        except Exception as e:
            logger.warning(f"贴表情 {emoji} 失败：{type(e).__name__}: {e}")

    await remember_approval(message_id, notice)


# region member join request
# region main
main_join_request = on_request(
    rule=_group_rule(S_.defined_qq.littleskin_main),
    priority=1,
    block=False,
)


@main_join_request.handle()
async def member_join_request(bot: Bot, event: GroupRequestEvent):
    req = event
    applicant = req.user_id
    message: list[str] = []
    if not req.comment:
        logger.warning(f"(main) request from {applicant} was ignored because request message is empty.")
        return

    answer = req.comment.splitlines()[-1].removeprefix("答案：").strip()  # 从申请留言最后一行提取填写的 UID 答案
    logger.info(f"Member Join Request Event {req.sub_type} flag={req.flag} was received. {applicant} > {answer}")

    try:
        cloudconfig = await CloudConfig.fetch()
        if cloudconfig.enable_auto_accept_join_request_main:  # 云控策略：若启用主群自动同意则直接批准
            await random_sleep(3)  # sleep before action
            await req.approve(bot)  # 调用 OneBot V11 API 同意入群申请

            message.append(format_join_request_notice("Main", applicant, answer, req.sub_type, req.flag))
            message.append("👆 已同意 [云控策略：enable_auto_accept_join_request_main]")
            logger.info(
                f"Member Join Request Event {req.sub_type} flag={req.flag} was auto accepted by cloudconfig policy "
                f"[enable_auto_accept_join_request_main]. {applicant} > {answer}",
            )

            await random_sleep(3)  # sleep before action
            await _send_to_group(S_.defined_qq.commspt_group, "\n\n".join(m for m in message if m))
            return
    except Exception as e:
        logger.exception(e)

    if not answer.isdecimal():  # UID 应为十进制纯数字
        logger.warning(
            f"(main) Member Join Request Event {req.sub_type} was ignored. (ANSWER NOT DECIMAL) {applicant} > {answer}",
        )
        await random_sleep(3)  # sleep before action
        await _send_approval_notice(
            bot,
            S_.defined_qq.commspt_group,
            "Main",
            applicant,
            answer,
            req.sub_type,
            req.flag,
            ["👀 答案不是纯数字，需手动处理"],
        )
        return

    uid = int(answer)

    image: bytes | None = None
    qmail_passed = False
    uid_not_exists = False
    api_error = False
    try:
        # qmail api verification
        ltsk_qmail = await LittleSkinUser.qmail_api(applicant)
        if ltsk_qmail and ltsk_qmail.uid == uid:
            # ok: pass verification
            await UIDMapping(uid=uid, qq=applicant, qmail_verified=True).update()  # 记录/更新 QQ 与 UID 映射及验证状态
            logger.success(
                f"(main) Member Join Request Event {req.sub_type} was accepted. (QMAIL PASS) {applicant} > {answer}",
            )
            qmail_passed = True
        elif not await LittleSkinUser.uid_info(uid):  # 校验所填 UID 是否在 LittleSkin 平台存在
            # failed: uid not exists
            logger.warning(
                f"(main) Member Join Request Event {req.sub_type} was ignored. (UID NOT EXISTS) {applicant} > {answer}",
            )
            message.append("👀 这个 UID 根本不存在，需手动处理")
            uid_not_exists = True
        else:
            if email_uid := await LittleSkinUser.qmail_api(qq=applicant):  # 若申请人 QQ 邮箱曾绑定过其他 UID 则提示可能正确的 UID
                message.append(f"ⓘ 可能才为正确对应的 UID: {email_uid.uid}")

            # 响应体里的 invited_id 有时才是真实对应的 UID：
            # 当协议端给出的请求体中 user_id 为 0（申请人身份字段缺失/异常）时，
            # 被邀请人 invited_id 往往才代表真正要核对的那个人。
            # 这是「需要判断」的提示，因此独立成条（不与上面的 UID 提示合并同类项），
            # 仅当响应体确实携带了非零 invited_id 时才输出，避免无意义空提示。
            if invited_id := getattr(req, "invited_id", None):  # Getattr 兜底：协议端未携带该字段时属性不存在
                hint = f"ⓘ 响应体(invited_id)反映他可能是: {invited_id}"
                # message 各项会被 _send_approval_notice 用 "\n\n".join 拼接，
                # 直接 append 会在两条 ⓘ 之间多出一个空行；这里改用单换行紧跟上一行，
                # 使两条同族提示紧凑相邻（其它提示行之间的空行保持不变）。
                if message and message[-1].startswith("ⓘ 可能才为正确对应的 UID:"):
                    message[-1] += f"\n{hint}"
                else:
                    message.append(hint)

            # failed: not pass verification
            logger.warning(
                f"(main) Member Join Request Event {req.sub_type} was ignored. (GENERAL) {applicant} > {answer}",
            )
            await UIDMapping(uid=uid, qq=applicant).update()
            message.append("👀 请手动处理")

            if ltsk_user := await LittleSkinUser.uid_info(answer):  # 查询并渲染用户信息卡片，辅助管理员人工审核
                render = RenderUserInfo(
                    **ltsk_user.model_dump(), qq=int(applicant), qq_nickname=await get_qq_nickname(bot, applicant)
                )
                image = await render.get_image()
                # 该账号被封禁时，在审批通知里附上飞书封禁记录
                # （通知只发往内部管理群，无需再判断群号）
                if block := await banned_records_block(ltsk_user.uid, permission=ltsk_user.permission):
                    message.append(block)
            else:
                message.append("👀 未获取到 UID 信息，无法渲染图片")
    except Exception as e:
        # 主站或映射数据库不可用时降级：仍发送申请通知，交由管理员手动处理
        logger.exception(e)
        message.append("⚠️ 主站/映射数据库服务请求失败，需手动处理")
        image = None
        api_error = True

    if qmail_passed:
        await random_sleep(3)  # sleep before action
        await req.approve(bot)  # 校验通过，调用 API 同意入群
        return

    if api_error:
        # 请求失败仍需向群聊发送加群申请通知，方便管理员交互处理
        await random_sleep(4)  # sleep before action
        await _send_approval_notice(
            bot, S_.defined_qq.commspt_group, "Main", applicant, answer, req.sub_type, req.flag, message, image
        )
        return

    if uid_not_exists:
        await random_sleep(3)  # sleep before action
        await _send_approval_notice(
            bot, S_.defined_qq.commspt_group, "Main", applicant, answer, req.sub_type, req.flag, message, image
        )
        return

    await random_sleep(4)  # sleep before action
    await _send_approval_notice(
        bot, S_.defined_qq.commspt_group, "Main", applicant, answer, req.sub_type, req.flag, message, image
    )


# endregion
# region cafe
cafe_join_request = on_request(
    rule=_group_rule(S_.defined_qq.littleskin_cafe),
    priority=1,
    block=False,
)


@cafe_join_request.handle()
async def cafe_join_request_handler(bot: Bot, event: GroupRequestEvent):
    req = event
    applicant = req.user_id
    if not req.comment:
        return

    answer = req.comment.splitlines()[-1].removeprefix("答案：").strip()  # 从申请留言最后一行提取填写的 UID 答案
    logger.info(f"(cafe) Member Join Request Event {req.sub_type} flag={req.flag} was received. {applicant} > {answer}")

    if not answer.isdecimal():  # UID 应为十进制纯数字
        logger.warning(
            f"(cafe) Member Join Request Event {req.sub_type} was ignored. (ANSWER NOT DECIMAL) {applicant} > {answer}",
        )
        # 即便无法自动处理，也需向群聊发送申请通知，方便管理员交互处理
        await _send_approval_notice(
            bot,
            S_.defined_qq.littleskin_cafe,
            "Cafe",
            applicant,
            answer,
            req.sub_type,
            req.flag,
            ["👀 答案不是纯数字，需手动处理"],
        )
        return

    uid = int(answer)

    # more sleep is better
    await random_sleep(3)

    # lstk uid check
    try:
        uid_exists = await LittleSkinUser.uid_info(uid)
    except Exception as e:
        # 主站不可用时降级：仍发送申请通知，交由管理员手动处理
        logger.exception(e)
        await _send_approval_notice(
            bot,
            S_.defined_qq.littleskin_cafe,
            "Cafe",
            applicant,
            answer,
            req.sub_type,
            req.flag,
            ["⚠️ 需手动处理"],
        )
        return

    if not uid_exists:
        # failed: uid not exists
        logger.warning(
            f"(cafe) Member Join Request Event {req.sub_type} was ignored. (UID NOT EXISTS) {applicant} > {answer}",
        )
        await _send_approval_notice(
            bot,
            S_.defined_qq.littleskin_cafe,
            "Cafe",
            applicant,
            answer,
            req.sub_type,
            req.flag,
            ["👀 这个 UID 根本不存在，需手动处理"],
        )
        return

    # general: approve
    mapping_failed = False
    message: list[str] = []
    try:
        mapping_uid = await UIDMapping.fetch(qq=applicant)
        status = "✅" if (mapping_uid and mapping_uid.uid == uid) else "⚠️"  # 检查是否与主群记录的 UID 映射一致
    except Exception as e:
        # 映射数据库不可用不影响审批，仅标记为未知并提示手动核对
        logger.exception(e)
        status = "⚠️"
        mapping_failed = True
        message.append("⚠️ 需手动处理")

    await req.approve(bot)  # 茶馆群只要 UID 存在即自动同意入群
    if mapping_failed:
        # 映射查询失败时附上申请通知，方便管理员核对处理
        message.append(f"(RESULT) Mapping {status}: QQ {applicant} -> UID {uid}")
        await _send_to_group(S_.defined_qq.littleskin_cafe, "\n\n".join(m for m in message if m))
    else:
        await _send_to_group(S_.defined_qq.littleskin_cafe, f"(RESULT) Mapping {status}: QQ {applicant} -> UID {uid}")


# endregion


# region member join welcome
member_join_welcome = on_notice(
    rule=_group_rule(S_.defined_qq.littleskin_main),
    priority=1,
    block=False,
)


@member_join_welcome.handle()
async def _(bot: Bot, event: GroupIncreaseNoticeEvent):
    if event.user_id == int(bot.self_id):
        return  # 机器人自己入群，不处理

    welcome_msg = Message() + MessageSegment.at(event.user_id) + " "
    nofi_msg = [f"用户已入群 > {event.user_id}"]

    uid_mapping = await UIDMapping.fetch(qq=event.user_id)  # 查询新成员已绑定的 UID 信息

    # add UID info
    if uid_mapping:
        welcome_msg = welcome_msg + f"UID: {uid_mapping.uid}  "
        nofi_msg.append(f"UID: {uid_mapping.uid}")

    # add join announcement

    # default annoucement text
    join_announcement = "欢迎来到 LittleSkin 问题反馈群！请首先阅读置顶公告。此群禁止讨论除 LittleSkin 以外的内容。\n你还可以选择加入 Honoka Café 和我们一起聊天！群号：651672723。"

    # try to fetch annoucement text from cloudconfig to override the default text
    try:
        cloudconfig = await CloudConfig.fetch()
        if cloudconfig.enable_temporary_welcome_message_main:
            # override join announcement if temporary welcome message is enabled
            join_announcement = cloudconfig.temporary_welcome_message_main  # 云控策略启用时优先使用临时欢迎语
    except Exception as e:
        logger.exception(e)

    welcome_msg = welcome_msg + f"\n{join_announcement}"

    # send to main group
    await random_sleep(2)
    await member_join_welcome.send(welcome_msg)

    # render image
    image: bytes | None = None  # pre define

    if uid_mapping:
        ltsk_user = await LittleSkinUser.uid_info(uid_mapping.uid)  # 获取 LittleSkin 用户详细信息用于拼装管理审核通知
        # if qmail verified (only noti)
        if uid_mapping.qmail_verified:
            nofi_msg.append("QMAIL ✅ 验证通过")
        elif ltsk_user:
            nofi_msg.append(
                f"QMAIL {'❔ 与 QQ 号不匹配' if ltsk_user.email.lower().endswith('@qq.com') else '❌ 非 QQ 邮箱'}",
            )

        if ltsk_user:
            # check whether email contains uppercase letters (only noti)
            if ltsk_user.email.lower() != ltsk_user.email:
                nofi_msg.append("⚠️ 邮箱含有大写字母")

            # add LTSK email verification status (only noti)
            nofi_msg.append(f"邮箱验证 {'✅ 已验证' if ltsk_user.verified else '❌ 未验证'} ({ltsk_user.email})")

            # add registration time (only noti)
            reg_time = arrow.get(ltsk_user.register_at, tzinfo="Asia/Shanghai").format("YYYY-MM-DD HH:mm:ss")
            nofi_msg.append(f"注册时间: {reg_time}")

            # resay: if user was banned
            if ltsk_user.permission == -1:
                nofi_msg.append("❌ 账号被封禁")

            # render image
            render = RenderUserInfo(
                **ltsk_user.model_dump(), qq=event.user_id, qq_nickname=await get_qq_nickname(bot, event.user_id)
            )
            image = await render.get_image()
        else:
            # UID not exists
            nofi_msg.append("❌ 这个 UID 根本不存在")
    else:
        nofi_msg.append("🈚 未找到 UIDMapping 信息")

    await random_sleep(3)
    # send noti to notification channel
    noti = UniMessage()
    if image:
        noti = noti.image(raw=image)
    noti = noti + "\n".join(nofi_msg)
    await _send_to_group(S_.defined_qq.notification_channel, noti)


# endregion
