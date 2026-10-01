import arrow
from nonebot import logger, on_notice, on_request
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupIncreaseNoticeEvent,
    GroupRequestEvent,
)
from nonebot.rule import Rule
from nonebot_plugin_alconna.uniseg import At, UniMessage

from plugins.commspt_bot.config import JOIN_ANNOUNCEMENT_FILE, S_
from plugins.commspt_bot.models.cloudconfig import CloudConfig
from plugins.commspt_bot.models.littleskin_api import LittleSkinUser
from plugins.commspt_bot.models.mongodb_data import UIDMapping
from plugins.commspt_bot.models.render_user_info import RenderUserInfo
from plugins.commspt_bot.utils.messenger import send_to_group as _send_to_group
from plugins.commspt_bot.utils.random_sleep import random_sleep


def _group_rule(group_id: int):
    async def _checker(event) -> bool:
        return getattr(event, "group_id", None) == group_id

    return Rule(_checker)


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

    answer = req.comment.splitlines()[-1].removeprefix("答案：").strip()
    logger.info(f"Member Join Request Event {req.sub_type} flag={req.flag} was received. {applicant} > {answer}")
    message.append(
        f"""新的入群申请 (Main)
» 申请人 {applicant}
» 答案     {answer}

id={req.sub_type}_{req.flag}""",
    )

    try:
        cloudconfig = await CloudConfig.fetch()
        if cloudconfig.enable_auto_accept_join_request_main:
            await random_sleep(3)  # sleep before action
            await req.approve(bot)

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
        message.append("👀 答案不是纯数字，需手动处理")

        await random_sleep(3)  # sleep before action
        await _send_to_group(S_.defined_qq.commspt_group, "\n\n".join(m for m in message if m))
        return

    uid = int(answer)

    # qmail api verification
    if (ltsk_qmail := await LittleSkinUser.qmail_api(applicant)) and ltsk_qmail.uid == uid:
        # ok: pass verification
        await UIDMapping(uid=uid, qq=applicant, qmail_verified=True).update()
        logger.success(
            f"(main) Member Join Request Event {req.sub_type} was accepted. (QMAIL PASS) {applicant} > {answer}",
        )

        await random_sleep(3)  # sleep before action
        await req.approve(bot)
        message.append("👆 已同意 [QMAIL API passed]")
        return

    # lstk uid check
    if not await LittleSkinUser.uid_info(uid):
        # failed: uid not exists
        logger.warning(
            f"(main) Member Join Request Event {req.sub_type} was ignored. (UID NOT EXISTS) {applicant} > {answer}",
        )
        message.append("👀 这个 UID 根本不存在，需手动处理")
        await random_sleep(3)  # sleep before action
        await _send_to_group(S_.defined_qq.commspt_group, "\n\n".join(m for m in message if m))
        return

    if email_uid := await LittleSkinUser.qmail_api(qq=applicant):
        may_current_uid = email_uid.uid
        message.append(f"ⓘ 可能才为正确对应的 UID: {may_current_uid}")

    # failed: not pass verification
    logger.warning(f"(main) Member Join Request Event {req.sub_type} was ignored. (GENERAL) {applicant} > {answer}")
    await UIDMapping(uid=uid, qq=applicant).update()
    message.append("👀 请手动处理")

    image: bytes | None = None
    if ltsk_user := await LittleSkinUser.uid_info(answer):
        render = RenderUserInfo(**ltsk_user.model_dump(), qq=int(applicant))
        image = await render.get_image()
    else:
        message.append("👀 未获取到 UID 信息，无法渲染图片")

    await random_sleep(4)  # sleep before action
    noti = UniMessage()
    if image:
        noti = noti.image(raw=image)
    noti = noti + "\n\n".join(m for m in message if m)
    await _send_to_group(S_.defined_qq.commspt_group, noti)


# endregion
# region cafe
cafe_join_request = on_request(
    rule=_group_rule(S_.defined_qq.littleskin_cafe),
    priority=1,
    block=False,
)


@cafe_join_request.handle()
async def _(bot: Bot, event: GroupRequestEvent):
    req = event
    applicant = req.user_id
    message: list[str] = []
    if not req.comment:
        return

    answer = req.comment.splitlines()[-1].removeprefix("答案：").strip()
    logger.info(f"(cafe) Member Join Request Event {req.sub_type} flag={req.flag} was received. {applicant} > {answer}")
    message.append(
        f"""新的入群申请 (Cafe)
» 申请人 {applicant}
» 答案     {answer}

id={req.sub_type}_{req.flag}""",
    )

    if not answer.isdecimal():  # UID 应为十进制纯数字
        logger.warning(
            f"(cafe) Member Join Request Event {req.sub_type} was ignored. (ANSWER NOT DECIMAL) {applicant} > {answer}",
        )
        message.append("👀 答案不是纯数字，需手动处理")
        return

    uid = int(answer)

    # more sleep is better
    await random_sleep(3)

    # lstk uid check
    if not await LittleSkinUser.uid_info(uid):
        # failed: uid not exists
        logger.warning(
            f"(cafe) Member Join Request Event {req.sub_type} was ignored. (UID NOT EXISTS) {applicant} > {answer}",
        )
        message.append("👀 这个 UID 根本不存在，需手动处理")
        await _send_to_group(S_.defined_qq.littleskin_cafe, "\n\n".join(m for m in message if m))
        return

    # general: approve
    mapping_uid = await UIDMapping.fetch(qq=applicant)
    status = "✅" if (mapping_uid and mapping_uid.uid == uid) else "⚠️"
    await req.approve(bot)
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

    welcome_msg = UniMessage(At("user", str(event.user_id))) + " "
    nofi_msg = [f"用户已入群 > {event.user_id}"]

    uid_mapping = await UIDMapping.fetch(qq=event.user_id)

    # add UID info
    if uid_mapping:
        welcome_msg = welcome_msg + f"UID: {uid_mapping.uid}  "
        nofi_msg.append(f"UID: {uid_mapping.uid}")

    # add join announcement
    join_announcement = ""
    if JOIN_ANNOUNCEMENT_FILE.exists():
        join_announcement = JOIN_ANNOUNCEMENT_FILE.read_text(encoding="UTF-8")
    else:
        logger.warning(f"未找到入群公告文件: {JOIN_ANNOUNCEMENT_FILE}")

    try:
        cloudconfig = await CloudConfig.fetch()
        if cloudconfig.enable_temporary_welcome_message_main:
            # override join announcement if temporary welcome message is enabled
            join_announcement = cloudconfig.temporary_welcome_message_main
    except Exception as e:
        logger.exception(e)

    welcome_msg = welcome_msg + f"\n{join_announcement}"

    # send to main group
    await random_sleep(2)
    await member_join_welcome.send(welcome_msg)

    # render image
    image: bytes | None = None  # pre define

    if uid_mapping:
        ltsk_user = await LittleSkinUser.uid_info(uid_mapping.uid)
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
            render = RenderUserInfo(**ltsk_user.model_dump(), qq=event.user_id)
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
