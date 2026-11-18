"""入群申请「答案不是纯数字」提示卡的渲染数据模型与图片生成。

与用户信息卡（``render_user_info``）刻意区分：那张是 LittleSkin 账号档案，这张是
「待人工审核」单——主角是申请人写下的原话，机器人认出的片段（可能的 UID、申请人
QQ 号、邮箱）直接标注在原文上方。

只展示、不判定：卡片内容全部来自 ``utils.join_answer_hint.analyze_answer`` 与申请事件
本身，不查主站、不查映射库；识别出的数字不参与任何校验或台账登记。

主要接口：
- RenderJoinAnswerHint: 提示卡渲染上下文模型
- RenderJoinAnswerHint.from_analysis: 由答案分析结果构建上下文
- RenderJoinAnswerHint.get_image: 通过浏览器无头服务截图生成卡片图片
"""

from datetime import datetime

import arrow
from pydantic import BaseModel

from plugins.commspt_bot.config import S_

# 主题判定与用户卡片共用同一口径（北京时间 7–19 点浅色），避免两张卡在同一时刻一明一暗
from plugins.commspt_bot.models.render_user_info import HumanReadableTime, _is_dark_at
from plugins.commspt_bot.utils.browserless import screenshot
from plugins.commspt_bot.utils.join_answer_hint import AnswerAnalysis, SegmentRole
from plugins.commspt_bot.utils.join_request_notice import NoticeKind, NoticeSubtype


class RenderJoinAnswerHint(BaseModel):
    """「答案不是纯数字」提示卡的渲染上下文。"""

    generated_at: HumanReadableTime
    kind: NoticeKind
    sub_type: NoticeSubtype
    applicant: int
    qq_nickname: str = ""
    reason: str
    segments: list[tuple[str, SegmentRole]]
    has_uid: bool = False
    setuid_command: str | None = None
    is_dark_mode: bool = False

    @classmethod
    def from_analysis(
        cls,
        analysis: AnswerAnalysis,
        *,
        kind: NoticeKind,
        sub_type: NoticeSubtype,
        applicant: int,
        qq_nickname: str = "",
        setuid_command: str | None = None,
    ) -> "RenderJoinAnswerHint":
        """由答案分析结果构建渲染上下文。

        ``setuid_command`` 只在主群传入：仅主群批准会写映射台账；模板里还会再要求
        识别到候选 UID 才展示补绑提示，与文字提示的口径一致。
        """
        return cls(
            kind=kind,
            sub_type=sub_type,
            applicant=applicant,
            qq_nickname=qq_nickname,
            reason=analysis.reason,
            segments=list(analysis.segments),
            has_uid=bool(analysis.uid_candidates),
            setuid_command=setuid_command,
        )

    async def get_image(self, *, now: datetime | None = None) -> bytes:
        """调用 Browserless 服务渲染提示卡截图（与用户卡片相同的透明整页截图口径）。"""
        params = self.model_dump()
        if S_.user_card_auto_theme:
            params["is_dark_mode"] = _is_dark_at(now if now is not None else arrow.utcnow().datetime)
        return await screenshot("join-answer-hint.html.jinja", **params, height=1, full_page=True, transparent=True)
