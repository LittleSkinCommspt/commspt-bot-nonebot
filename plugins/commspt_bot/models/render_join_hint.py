"""入群申请「答案不是纯数字」提示卡的渲染数据模型与图片生成。

与用户信息卡（``render_user_info``）共用同一套样式（``templates/card-base.css.jinja``），
内容不同：那张是 LittleSkin 账号档案，这张以申请人的原话为标题，下面是入群问题与申请人的
QQ 公开资料。默认不出图（JOIN_HINT_CARD_ENABLED 开启后才发送）。

Bot 只在条件满足时有自动同意权；答案不是纯数字就转人工（对方可能无法注册等）。卡片只摆事实：
内容全部来自申请事件本身与 ``get_stranger_info``，不查主站、不查映射库，不从答案里识别或
猜测 UID，也不给处理建议。

主要接口：
- RenderJoinAnswerHint: 提示卡渲染上下文模型
- RenderJoinAnswerHint.from_profile: 由 QQ 公开资料构建上下文
- RenderJoinAnswerHint.get_image: 通过浏览器无头服务截图生成卡片图片
"""

from datetime import datetime

import arrow
from pydantic import BaseModel

from plugins.commspt_bot.config import S_

# 主题判定与用户卡片共用同一口径（北京时间 7–19 点浅色），避免两张卡在同一时刻一明一暗
from plugins.commspt_bot.models.render_user_info import HumanReadableTime, _is_dark_at
from plugins.commspt_bot.utils.browserless import screenshot
from plugins.commspt_bot.utils.join_request_notice import NoticeKind, NoticeSubtype
from plugins.commspt_bot.utils.qq_profile import QQProfile
from plugins.commspt_bot.utils.relative_time import humanize_since


class RenderJoinAnswerHint(BaseModel):
    """「答案不是纯数字」提示卡的渲染上下文；QQ 资料字段缺失时模板不展示对应行。"""

    generated_at: HumanReadableTime
    kind: NoticeKind
    sub_type: NoticeSubtype
    applicant: int
    answer: str = ""
    # 申请留言里的入群问题（没有则为空串）；精简文字模式下问题只在卡片上
    question: str = ""
    # 协议端事件里可能附带的另一个 QQ（与文字通知「也可能是」一致，仅作展示）
    invited_id: int | None = None
    qq_nickname: str = ""
    qq_level: int | None = None
    qq_sex: str = ""
    qq_age: int | None = None
    qq_registered_at: datetime | None = None
    qq_sign: str = ""
    is_dark_mode: bool = False

    @classmethod
    def from_profile(
        cls,
        profile: QQProfile,
        *,
        kind: NoticeKind,
        sub_type: NoticeSubtype,
        applicant: int,
        answer: str,
        invited_id: int | None = None,
        question: str = "",
    ) -> "RenderJoinAnswerHint":
        """由申请事件信息与 QQ 公开资料构建渲染上下文。"""
        return cls(
            kind=kind,
            sub_type=sub_type,
            applicant=applicant,
            answer=answer,
            question=question,
            invited_id=invited_id,
            qq_nickname=profile.nickname,
            qq_level=profile.level,
            qq_sex=profile.sex,
            qq_age=profile.age,
            qq_registered_at=profile.registered_at,
            qq_sign=profile.sign,
        )

    async def get_image(self, *, now: datetime | None = None) -> bytes:
        """调用 Browserless 服务渲染提示卡截图（与用户卡片相同的透明整页截图口径）。"""
        params = self.model_dump()
        # QQ 注册时间：相对时间为主读数，日期为次要信息（与用户卡「注册」行同一写法）
        params["qq_registered_ago"] = ""
        params["qq_registered_on"] = ""
        if self.qq_registered_at is not None:
            params["qq_registered_ago"] = humanize_since(self.generated_at, self.qq_registered_at)
            params["qq_registered_on"] = arrow.get(self.qq_registered_at).to("Asia/Shanghai").format("YYYY-MM-DD")
        if S_.user_card_auto_theme:
            params["is_dark_mode"] = _is_dark_at(now if now is not None else arrow.utcnow().datetime)
        return await screenshot("join-answer-hint.html.jinja", **params, height=1, full_page=True, transparent=True)
