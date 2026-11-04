"""LittleSkin 主群与茶馆群入群审核及新成员进群欢迎。

对应 Avilla 原版 modules/join_group.py。
基于 OneBot V11 的 GroupRequestEvent 与 GroupIncreaseNoticeEvent，
实现入群申请自动化校验（云控配置/QMail/UID校验）以及入群欢迎与通知频道推送。

事件：
- GroupRequestEvent: LittleSkin 主群加群申请 (rule=主群; 自动/手动审核)
- GroupRequestEvent: LittleSkin 茶馆群加群申请 (rule=茶馆群; 自动审核)
- GroupIncreaseNoticeEvent: LittleSkin 主群新成员进群 (rule=主群; 发送欢迎语与管理通知)

可靠性约定：
- 每个外部调用（主站 / 映射数据库 / IP 属地 / 云控）各自独立包裹，失败互不牵连；
- 重试统一走 ``call_with_retry``，次数严格由 ``S_.failed_retry_time`` 决定
  （1 次请求 + N 次重试），本模块不写死任何重试次数；
- 「是否放人」只由确定性身份校验（云控策略 / QMail 匹配 / UID 存在性）决定，
  出图、封禁查询等展示环节一律 best-effort；
- 审批调用统一走 ``utils.join_action.execute_join_action``，失败不再静默丢弃；
- 映射台账只在审批执行核心里写，且严格位于放人之前（见 ``execute_join_action``）：
  放人会立刻触发 ``group_increase``，欢迎通知随即读取 UID，后写必然读到空；
- 新成员欢迎通知**不访问映射数据库**：UID 取自审批时登记的进程内表
  （``utils.join_ledger``），未命中时只 @ 用户发欢迎语，不做任何外部查询；
- 已自动同意的结果通知使用纯文本发送，不贴审批表情、不登记审批凭证。
"""

import asyncio

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
from plugins.commspt_bot.models.render_user_info import RenderUserInfo
from plugins.commspt_bot.utils.ban_lookup import banned_records_block
from plugins.commspt_bot.utils.command_prefix import display_command
from plugins.commspt_bot.utils.join_action import (
    ALREADY_HANDLED,
    APPROVAL_EMOJIS,
    SUCCESS,
    JoinActionResult,
    execute_join_action,
    remember_approval,
)
from plugins.commspt_bot.utils.join_ledger import get_join_uid
from plugins.commspt_bot.utils.join_request_notice import (
    JoinRequestNotice,
    NoticeKind,
    NoticeSubtype,
    format_join_request_notice,
)
from plugins.commspt_bot.utils.messenger import send_to_group as _send_to_group
from plugins.commspt_bot.utils.messenger import send_to_group_with_id as _send_to_group_with_id
from plugins.commspt_bot.utils.qq_profile import get_qq_nickname

_SETUID = display_command("setuid")
"""补写映射用的管理端命令展示文本（前缀跟随 COMMAND_START）。"""


def _group_rule(group_id: int):
    """构建仅匹配指定群号事件的 Rule 规则工厂。"""

    async def _checker(event) -> bool:
        return getattr(event, "group_id", None) == group_id

    return Rule(_checker)


def _invited_id_of(req: GroupRequestEvent) -> int | None:
    """读取事件中协议端可能附带的 invited_id。

    返回 ``None`` 表示事件未携带该字段（或取值类型不是整数，例如字符串/布尔）；
    ``0`` 是合法取值，照原样返回并展示，不做任何"缺失"推断。
    该值仅用于通知展示，绝不作为校验/映射/审批身份。
    """
    value = getattr(req, "invited_id", None)
    if value is None:
        return None
    if isinstance(value, bool):  # bool 是 int 的子类，需先排除以免 True/False 被当成 1/0
        return None
    if isinstance(value, int):
        return value
    return None


# 无留言（含 user_id == 0）时使用的占位答案，保证通知格式仍可被解析
_NO_COMMENT_PLACEHOLDER = "（无留言）"
# 兼容旧名：语义已扩展为「无留言」，零申请人与空留言共用同一占位
_ZERO_APPLICANT_ANSWER_PLACEHOLDER = _NO_COMMENT_PLACEHOLDER

_ANSWER_PREFIXES = ("答案：", "答案:")
"""申请留言的答案前缀（全角/半角冒号都兼容）。"""


def _extract_answer(comment: str | None) -> str:
    """从申请留言中提取答案（取最后一个非空白行，无留言时返回空串）。

    QQ 留言常带尾随空行，直接取 ``splitlines()[-1]`` 会得到空串并被误判为
    「答案不是纯数字」。这里从后往前找第一个非空白行，并剥离全角/半角冒号前缀。
    """
    for line in reversed((comment or "").splitlines()):
        text = line.strip()
        if not text:
            continue
        for prefix in _ANSWER_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix) :]
                break
        return text.strip()
    return ""


def _service_failure_text() -> str:
    """主站查询失败提示（重试次数跟随配置）。"""
    return f"⚠️ 主站查询失败（已重试 {S_.failed_retry_time} 次），需手动处理"


def _render_failure_text() -> str:
    """用户卡片渲染失败提示（明确不影响审批）。"""
    return "⚠️ 用户卡片渲染失败（不影响审批）"


def _cloudconfig_failure_text() -> str:
    """云控不可用提示（明确本次按人工审核处理）。"""
    return f"⚠️ 云控不可用（已重试 {S_.failed_retry_time} 次），本次按人工审核处理"


def _mapping_write_failure_text() -> str:
    """映射写入失败提示（审批结果仍有效，只需补写台账）。"""
    return f"⚠️ 映射写入失败，请用 {_SETUID} 补写"


async def _approve_request(
    bot: Bot,
    notice: JoinRequestNotice,
    *,
    source: str,
    qmail_verified: bool = False,
) -> JoinActionResult:
    """统一执行自动同意，异常分类与日志与手动审批保持一致。

    ``qmail_verified`` 透传给审批执行核心，仅用于映射台账里的状态位。
    """
    result = await execute_join_action(
        bot,
        notice,
        approve=True,
        source=source,
        qmail_verified=qmail_verified,
    )
    if result.outcome == SUCCESS:
        logger.success(
            f"join request auto accepted [{source}]: kind={notice.kind} "
            f"applicant={notice.applicant} answer={notice.answer} "
            f"uid={result.uid} mapping_written={result.mapping_written}",
        )
    elif result.outcome == ALREADY_HANDLED:
        logger.warning(
            f"join request already handled or expired [{source}]: kind={notice.kind} "
            f"applicant={notice.applicant} flag={notice.flag}",
        )
    return result


async def _render_card(bot: Bot, ltsk_user: LittleSkinUser, qq: int) -> bytes | None:
    """best-effort 渲染用户卡片；失败返回 None（不影响审批）。"""
    try:
        render = RenderUserInfo(
            **ltsk_user.model_dump(),
            qq=qq,
            qq_nickname=await get_qq_nickname(bot, qq),
        )
        return await render.get_image()
    except Exception as e:
        logger.exception(e)
        return None


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
    invited_id: int | None = None,
) -> None:
    """向群聊发送入群审批通知并贴上 👍/👎 表情，登记表情审批凭证。

    仅用于「需要管理员人工处理」的通知；自动通过 / 纯结果通知请直接用 _send_to_group。
    协议端不支持 set_msg_emoji_like 时静默降级，不影响 do 命令审批。
    ``invited_id`` 仅作为申请人行的候选提示（见 format_join_request_notice）。
    """
    notice = JoinRequestNotice(
        kind=kind,
        applicant=applicant,
        answer=answer,
        sub_type=sub_type,
        flag=flag,
    )
    # 保持与旧实现一致：通知块在前，附加提示行在后
    parts = [format_join_request_notice(kind, applicant, answer, sub_type, flag, invited_id), *message]
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

    # 先登记凭证再贴表情：贴表情期间管理员即可通过 do 命令审批
    await remember_approval(message_id, notice)

    results = await asyncio.gather(
        *(
            bot.call_api("set_msg_emoji_like", message_id=message_id, emoji_id=emoji, set=True)
            for emoji in APPROVAL_EMOJIS
        ),
        return_exceptions=True,
    )
    for emoji, outcome in zip(APPROVAL_EMOJIS, results):
        if isinstance(outcome, BaseException):
            logger.warning(f"贴表情 {emoji} 失败：{type(outcome).__name__}: {outcome}")


async def _auto_accept_notice(
    group_id: int,
    applicant: int,
    answer: str,
    sub_type: NoticeSubtype,
    flag: str,
    *,
    kind: NoticeKind,
    headline: str,
    extra: list[str] | None = None,
    invited_id: int | None = None,
) -> None:
    """发送「已自动同意」的纯文本结果通知（无表情、无审批凭证）。

    申请已被消费，再挂 👍/👎 会诱导管理员对已处理的 flag 重复审批，
    因此这里刻意不走 _send_approval_notice。
    """
    parts = [
        format_join_request_notice(kind, applicant, answer, sub_type, flag, invited_id),
        headline,
        *(extra or []),
    ]
    await _send_to_group(group_id, "\n\n".join(p for p in parts if p))


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
    invited_id = _invited_id_of(req)

    if applicant == 0:
        # 原始 user_id 为 0 时按策略一律转人工审核：不进入云控自动同意、
        # QMail 校验与 QQ/UID 映射写入/查询，由管理员基于通知内容判断。
        answer = _extract_answer(req.comment)
        logger.warning(
            f"(main) request from {applicant} needs manual review because user_id is 0. "
            f"{applicant} > {answer} (invited_id={invited_id})",
        )
        await _send_approval_notice(
            bot,
            S_.defined_qq.commspt_group,
            "Main",
            applicant,
            answer or _NO_COMMENT_PLACEHOLDER,
            req.sub_type,
            req.flag,
            ["👀 申请人 user_id 为 0，需手动处理"],
            invited_id=invited_id,
        )
        return

    answer = _extract_answer(req.comment)
    if not answer:
        # 空留言过去直接 return，申请人会永久卡住且管理员无感知；改为转人工
        logger.warning(f"(main) request from {applicant} has no answer, falling back to manual review.")
        await _send_approval_notice(
            bot,
            S_.defined_qq.commspt_group,
            "Main",
            applicant,
            _NO_COMMENT_PLACEHOLDER,
            req.sub_type,
            req.flag,
            ["👀 申请留言为空，需手动处理"],
            invited_id=invited_id,
        )
        return

    logger.info(f"Member Join Request Event {req.sub_type} flag={req.flag} was received. {applicant} > {answer}")

    if not answer.isdecimal():  # UID 应为十进制纯数字
        logger.warning(
            f"(main) Member Join Request Event {req.sub_type} was ignored. (ANSWER NOT DECIMAL) {applicant} > {answer}",
        )
        await _send_approval_notice(
            bot,
            S_.defined_qq.commspt_group,
            "Main",
            applicant,
            answer,
            req.sub_type,
            req.flag,
            ["👀 答案不是纯数字，需手动处理"],
            invited_id=invited_id,
        )
        return

    uid = int(answer)
    notice = JoinRequestNotice("Main", applicant, answer, req.sub_type, req.flag)

    # ---- ① 云控策略：只在拉取成功且开关打开时自动放人 ----
    # 不使用任何缓存或历史值：拿不到当前授权就不放人（fail-closed），
    # 但云控不可用不阻断下方的 QMail 确定性校验。
    auto_accept = False
    cloudconfig_failed = False
    try:
        cloudconfig = await CloudConfig.fetch()
        auto_accept = cloudconfig.enable_auto_accept_join_request_main
    except Exception as e:
        logger.exception(e)
        cloudconfig_failed = True

    if auto_accept:
        result = await _approve_request(bot, notice, source="auto:cloudconfig")
        if result.outcome == SUCCESS:
            await _auto_accept_notice(
                S_.defined_qq.commspt_group,
                applicant,
                answer,
                req.sub_type,
                req.flag,
                kind="Main",
                headline="👆 已同意 [云控策略：enable_auto_accept_join_request_main]",
                # 云控直通只是自报 UID、未做 QMail 校验，台账状态位为 False；
                # 写入失败时补一条纯文本提示（审批已完成，只需补写）
                extra=None if result.mapping_written is not False else [_mapping_write_failure_text()],
                invited_id=invited_id,
            )
            return
        if result.outcome == ALREADY_HANDLED:
            return
        # 审批调用本身出错：落回人工通知，避免静默丢失
        await _send_approval_notice(
            bot,
            S_.defined_qq.commspt_group,
            "Main",
            applicant,
            answer,
            req.sub_type,
            req.flag,
            ["⚠️ 自动同意调用失败，需手动处理"],
            invited_id=invited_id,
        )
        return

    # ---- ② QMail 校验（唯一一次请求，结果同时用于候选 UID 提示）----
    try:
        email_uid = await LittleSkinUser.qmail_api(applicant)
    except Exception as e:
        logger.exception(e)
        await _send_approval_notice(
            bot,
            S_.defined_qq.commspt_group,
            "Main",
            applicant,
            answer,
            req.sub_type,
            req.flag,
            _build_failure_hints(cloudconfig_failed, _service_failure_text()),
            invited_id=invited_id,
        )
        return

    if email_uid and email_uid.uid == uid:
        # 身份校验通过：写入与登记由 execute_join_action 在放人之前完成（见其文档），
        # 因此这里只会拿到「已放人 + 台账写入结果」，无需再自行写库。
        result = await _approve_request(bot, notice, source="auto:qmail", qmail_verified=True)
        if result.outcome == ALREADY_HANDLED:
            return
        if result.outcome != SUCCESS:
            await _send_approval_notice(
                bot,
                S_.defined_qq.commspt_group,
                "Main",
                applicant,
                answer,
                req.sub_type,
                req.flag,
                ["⚠️ 自动同意调用失败，需手动处理"],
                invited_id=invited_id,
            )
            return
        if result.mapping_written is False:
            await _auto_accept_notice(
                S_.defined_qq.commspt_group,
                applicant,
                answer,
                req.sub_type,
                req.flag,
                kind="Main",
                headline="👆 已同意 [QMAIL 验证通过]",
                extra=[_mapping_write_failure_text()],
                invited_id=invited_id,
            )
        return

    # ---- ③ UID 存在性校验（唯一一次请求，结果同时用于出图）----
    try:
        ltsk_user = await LittleSkinUser.uid_info(uid)
    except Exception as e:
        logger.exception(e)
        await _send_approval_notice(
            bot,
            S_.defined_qq.commspt_group,
            "Main",
            applicant,
            answer,
            req.sub_type,
            req.flag,
            _build_failure_hints(cloudconfig_failed, _service_failure_text()),
            invited_id=invited_id,
        )
        return

    if not ltsk_user:
        logger.warning(
            f"(main) Member Join Request Event {req.sub_type} was ignored. (UID NOT EXISTS) {applicant} > {answer}",
        )
        await _send_approval_notice(
            bot,
            S_.defined_qq.commspt_group,
            "Main",
            applicant,
            answer,
            req.sub_type,
            req.flag,
            _build_failure_hints(cloudconfig_failed, "👀 这个 UID 根本不存在，需手动处理"),
            invited_id=invited_id,
        )
        return

    # ---- 需人工处理：映射不再在申请阶段落库 ----
    # 台账写入统一放在审批执行核心里（先写库再放人），申请阶段写库既解决不了
    # 欢迎通知的竞态，还会给一个尚未批准的申请留下错误映射。
    hints: list[str] = []
    if email_uid:
        hints.append(f"ⓘ 可能才为正确对应的 UID: {email_uid.uid}")
    hints.append("👀 请手动处理")

    image = await _render_card(bot, ltsk_user, applicant)
    if image is None:
        hints.append(_render_failure_text())
    else:
        # 该账号被封禁时，在审批通知里附上飞书封禁记录
        # （通知只发往内部管理群，无需再判断群号）
        if block := await banned_records_block(ltsk_user.uid, permission=ltsk_user.permission):
            hints.append(block)

    logger.warning(
        f"(main) Member Join Request Event {req.sub_type} was ignored. (GENERAL) {applicant} > {answer}",
    )
    await _send_approval_notice(
        bot,
        S_.defined_qq.commspt_group,
        "Main",
        applicant,
        answer,
        req.sub_type,
        req.flag,
        _build_failure_hints(cloudconfig_failed, *hints),
        image,
        invited_id=invited_id,
    )


def _build_failure_hints(cloudconfig_failed: bool, *hints: str) -> list[str]:
    """汇总人工通知的提示行（云控不可用时追加说明，便于运维发现云控故障）。"""
    merged = list(hints)
    if cloudconfig_failed:
        merged.append(_cloudconfig_failure_text())
    return merged


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
    invited_id = _invited_id_of(req)

    if applicant == 0:
        # 原始 user_id 为 0 时按策略一律转人工审核：不查 UID、不查/写映射、不自动同意。
        answer = _extract_answer(req.comment)
        logger.warning(
            f"(cafe) request from {applicant} needs manual review because user_id is 0. "
            f"{applicant} > {answer} (invited_id={invited_id})",
        )
        await _send_approval_notice(
            bot,
            S_.defined_qq.littleskin_cafe,
            "Cafe",
            applicant,
            answer or _NO_COMMENT_PLACEHOLDER,
            req.sub_type,
            req.flag,
            ["👀 申请人 user_id 为 0，需手动处理"],
            invited_id=invited_id,
        )
        return

    answer = _extract_answer(req.comment)
    if not answer:
        # 空留言过去直接 return，申请人会永久卡住且管理员无感知；改为转人工
        logger.warning(f"(cafe) request from {applicant} has no answer, falling back to manual review.")
        await _send_approval_notice(
            bot,
            S_.defined_qq.littleskin_cafe,
            "Cafe",
            applicant,
            _NO_COMMENT_PLACEHOLDER,
            req.sub_type,
            req.flag,
            ["👀 申请留言为空，需手动处理"],
            invited_id=invited_id,
        )
        return

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
            invited_id=invited_id,
        )
        return

    uid = int(answer)
    notice = JoinRequestNotice("Cafe", applicant, answer, req.sub_type, req.flag)

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
            [_service_failure_text()],
            invited_id=invited_id,
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
            invited_id=invited_id,
        )
        return

    # 仅依据主站当前封禁状态；不把飞书历史封禁记录作为拒绝依据。
    if uid_exists.permission == -1 and S_.cafe_banned_user_action == "manual":
        await _send_approval_notice(
            bot,
            S_.defined_qq.littleskin_cafe,
            "Cafe",
            applicant,
            answer,
            req.sub_type,
            req.flag,
            ["⚠️ 已被封禁用户，需手动处理"],
            invited_id=invited_id,
        )
        return

    if uid_exists.permission == -1 and S_.cafe_banned_user_action == "reject":
        result = await execute_join_action(
            bot,
            notice,
            approve=False,
            reason="该 LittleSkin 账号已被封禁",
            source="auto:cafe:banned",
        )
        if result.outcome == SUCCESS:
            # 已消费的申请只播报结果，不登记人工审批凭证或贴审批表情。
            await _send_to_group(
                S_.defined_qq.littleskin_cafe,
                f"👆 已拒绝 [LittleSkin 账号被封禁]：QQ {applicant} -> UID {uid}",
            )
        elif result.outcome != ALREADY_HANDLED:
            await _send_approval_notice(
                bot,
                S_.defined_qq.littleskin_cafe,
                "Cafe",
                applicant,
                answer,
                req.sub_type,
                req.flag,
                ["⚠️ 账号被封禁，自动拒绝调用失败，需手动处理"],
                invited_id=invited_id,
            )
        return

    # general: approve
    result = await _approve_request(bot, notice, source="auto:cafe")
    if result.outcome == ALREADY_HANDLED:
        return
    if result.outcome != SUCCESS:
        # 审批调用失败过去会抛到 NoneBot，管理员什么也收不到；改为补发人工通知
        await _send_approval_notice(
            bot,
            S_.defined_qq.littleskin_cafe,
            "Cafe",
            applicant,
            answer,
            req.sub_type,
            req.flag,
            ["⚠️ 自动同意调用失败，需手动处理"],
            invited_id=invited_id,
        )
        return

    # 审批已完成，UID 取自申请答案（审批时已登记），不回查映射库
    await _send_to_group(
        S_.defined_qq.littleskin_cafe,
        f"(RESULT) QQ {applicant} -> UID {uid}",
    )


# endregion
# region member join welcome
member_join_welcome = on_notice(
    rule=_group_rule(S_.defined_qq.littleskin_main),
    priority=1,
    block=False,
)


@member_join_welcome.handle()
async def member_join_welcome_handler(bot: Bot, event: GroupIncreaseNoticeEvent):
    if event.user_id == int(bot.self_id):
        return  # 机器人自己入群，不处理

    welcome_msg = Message() + MessageSegment.at(event.user_id) + " "
    nofi_msg = [f"用户已入群 > {event.user_id}"]

    # UID 只从审批时登记的进程内表读取：不查映射库、不做任何兜底外部查询。
    # 放人会立刻触发本事件，若这里回查 MongoDB 就会与审批前置写入抢时序
    # （过去稳定读到空，表现为通知群永远显示「未找到 UIDMapping 信息」）。
    join_uid = get_join_uid(event.user_id)

    # add UID info
    if join_uid:
        welcome_msg = welcome_msg + f"UID: {join_uid.uid}  "
        nofi_msg.append(f"UID: {join_uid.uid}（来自入群申请答案）")

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
    await member_join_welcome.send(welcome_msg)

    if not join_uid:
        # 无登记（管理员直拉入群 / 免审邀请 / Bot 重启过）或申请未填有效 UID：
        # 只发已 @ 的欢迎语，不再产生任何外部调用，也不向通知群播报半截信息。
        logger.info(
            "member joined without pending uid: user_id={user_id}（仅发送欢迎语，不查映射）",
            user_id=event.user_id,
        )
        return

    # render image
    image: bytes | None = None  # pre define

    ltsk_user: LittleSkinUser | None = None
    try:
        ltsk_user = await LittleSkinUser.uid_info(join_uid.uid)
    except Exception as e:
        logger.exception(e)
        nofi_msg.append(_service_failure_text())

    if ltsk_user is None:
        if not any(text.startswith("⚠️") for text in nofi_msg):
            # UID not exists
            nofi_msg.append("❌ 这个 UID 根本不存在")
    else:
        # QMail 状态以「主站邮箱是否为该 QQ 的 QQ 邮箱」为准：
        # 不再依赖映射库里的 qmail_verified 位（该位只反映审批当时是否校验过）
        if join_uid.qmail_verified:
            nofi_msg.append("QMAIL ✅ 验证通过")
        elif ltsk_user.email.lower() == f"{event.user_id}@qq.com":
            nofi_msg.append("QMAIL ❔ 邮箱匹配但本次未校验")
        elif ltsk_user.email.lower().endswith("@qq.com"):
            nofi_msg.append("QMAIL ❔ 与 QQ 号不匹配")
        else:
            nofi_msg.append("QMAIL ❌ 非 QQ 邮箱")

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
        image = await _render_card(bot, ltsk_user, event.user_id)
        if image is None:
            nofi_msg.append(_render_failure_text())

    # send noti to notification channel
    noti = UniMessage()
    if image:
        noti = noti.image(raw=image)
    noti = noti + "\n".join(nofi_msg)
    await _send_to_group(S_.defined_qq.notification_channel, noti)


# endregion
