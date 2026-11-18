"""入群申请「答案不是纯数字」提示卡的渲染数据模型与图片生成。

与用户信息卡（``render_user_info``）刻意区分：那张是 LittleSkin 账号档案（大圆角、
信息网格），这张是回执单（直角墨线）——主角是一对红色直角引号「」框住的申请人原话，
底部是「拒绝 / 自定义理由 / 通过」三格操作栏，拒绝一格整格填红。

只展示、不判定：卡片内容全部来自申请事件本身（申请人 QQ、昵称、答案），不查主站、
不查映射库，也不从答案里识别或猜测 UID。答案不是 UID 的申请默认不通过，但拒绝同样
要管理员手动操作，因此卡片底部列出处理方式：贴 👎 按默认理由拒绝、引用回复
``do reject 理由``（开启 JOIN_REPLY_REJECT_ENABLED 后显示为「拒绝 理由」）自定义理由、
贴 👍 / ``do accept`` 通过。

主要接口：
- RenderJoinAnswerHint: 提示卡渲染上下文模型
- RenderJoinAnswerHint.get_image: 通过浏览器无头服务截图生成卡片图片
"""

from datetime import datetime

import arrow
from pydantic import BaseModel

from plugins.commspt_bot.config import S_

# 主题判定与用户卡片共用同一口径（北京时间 7–19 点浅色），避免两张卡在同一时刻一明一暗
from plugins.commspt_bot.models.render_user_info import HumanReadableTime, _is_dark_at
from plugins.commspt_bot.utils.browserless import screenshot
from plugins.commspt_bot.utils.join_action import DEFAULT_REJECT_REASON
from plugins.commspt_bot.utils.join_request_notice import NoticeKind, NoticeSubtype


class RenderJoinAnswerHint(BaseModel):
    """「答案不是纯数字」提示卡的渲染上下文。"""

    generated_at: HumanReadableTime
    kind: NoticeKind
    sub_type: NoticeSubtype
    applicant: int
    qq_nickname: str = ""
    answer: str = ""
    # 贴 👎 / 不带理由的 do reject 使用的默认拒绝理由，与审批执行核心保持同一来源
    reject_reason: str = DEFAULT_REJECT_REASON
    is_dark_mode: bool = False

    async def get_image(self, *, now: datetime | None = None) -> bytes:
        """调用 Browserless 服务渲染提示卡截图（与用户卡片相同的透明整页截图口径）。"""
        params = self.model_dump()
        # 快捷拒绝开启时，卡片上的引用回复写法换成更顺手的「拒绝 理由」（do reject 仍可用）
        params["reply_reject_enabled"] = S_.join_reply_reject_enabled
        if S_.user_card_auto_theme:
            params["is_dark_mode"] = _is_dark_at(now if now is not None else arrow.utcnow().datetime)
        return await screenshot("join-answer-hint.html.jinja", **params, height=1, full_page=True, transparent=True)
