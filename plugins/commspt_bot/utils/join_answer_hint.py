"""入群申请「答案不是纯数字」分支的人工审核提示。

申请留言的答案不是十进制纯数字时，机器人不会猜测 UID，而是转人工审核。过去通知里
只有一句「答案不是纯数字，需手动处理」，管理员得自己读答案，再判断申请人是没填、
填了邮箱、把 QQ 号当成了 UID，还是只在 UID 前后多打了几个字。本模块把这些常见情形
归类，供文字提示与提示卡片（``models.render_join_hint``）共用同一份分析结果。

约定：
- 纯函数、无外部调用：只读申请答案与申请人 QQ，不查主站、不查映射库；
- 识别出的数字**只用于展示**，不参与任何校验、台账登记或审批（与 ``uid_from_answer``
  「非纯数字一律视为无效、绝不猜测」的口径一致）；
- 文字提示首行始终以「需手动处理」收尾，与其它人工审核提示的措辞保持一致；
- 文字提示是用 ``\\n`` 连接的单个文本块：调用方会用空行分隔各条提示，
  拆成多条会让同一件事的说明被空行打散。

主要接口：
- analyze_answer: 把答案归类，并切分出可在卡片上逐段标注的片段
- non_numeric_answer_hint: 生成「答案不是纯数字」分支的文字提示块（出图失败时的回落）
"""

import re
from dataclasses import dataclass
from typing import Literal

_DIGIT_RUN = re.compile(r"\d+")
"""答案里的连续数字片段（含全角数字，与 ``str.isdecimal`` 的宽容口径一致）。"""

_EMAIL_LIKE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
"""形如邮箱的片段。邮箱里的数字（如 ``123456@qq.com``）不应被当成候选 UID。"""

_MAX_DIGITS = 12
"""单个数字片段的最大位数；更长的（手机号拼串、证件号等）不可能是 UID，不展示。"""

_MAX_SHOWN = 3
"""文字提示里候选 UID 最多展示的个数，超出部分以「等」概括，避免刷屏。"""

SegmentRole = Literal["plain", "uid", "qq", "email"]
"""答案片段的标注类别：普通文本 / 可能的 UID / 申请人 QQ 号 / 邮箱。"""


@dataclass(frozen=True, slots=True)
class AnswerAnalysis:
    """一条非数字答案的归类结果。

    - reason: 归类结论（不含表情与「需手动处理」），卡片与文字提示共用
    - uid_candidates: 去重后按出现顺序排列的候选 UID（已排除申请人 QQ 号）
    - qq_hit: 答案里是否出现了申请人自己的 QQ 号
    - segments: 按原文顺序切分的 ``(原文片段, 类别)``，拼起来与去空白后的答案一致
    """

    reason: str
    uid_candidates: tuple[int, ...]
    qq_hit: bool
    segments: tuple[tuple[str, SegmentRole], ...]

    @property
    def headline(self) -> str:
        """文字提示首行。"""
        return f"👀 {self.reason}，需手动处理"


def _digit_role(run: str, applicant: int) -> tuple[SegmentRole, int | None]:
    """判定一个数字片段的类别；返回 ``(类别, 数值)``，过长或为 0 的片段视为普通文本。"""
    if len(run) > _MAX_DIGITS:
        return "plain", None
    value = int(run)
    if value <= 0:
        return "plain", None
    if applicant > 0 and value == applicant:
        return "qq", value
    return "uid", value


def _split(text: str, applicant: int) -> list[tuple[str, SegmentRole, int | None]]:
    """把答案按「邮箱 / 数字片段 / 其余文本」切分，保留原文写法（全角、前导零）。"""
    pieces: list[tuple[str, SegmentRole, int | None]] = []

    def push_plain(chunk: str) -> None:
        if not chunk:
            return
        if pieces and pieces[-1][1] == "plain":
            pieces[-1] = (pieces[-1][0] + chunk, "plain", None)
        else:
            pieces.append((chunk, "plain", None))

    def push_text(chunk: str) -> None:
        cursor = 0
        for match in _DIGIT_RUN.finditer(chunk):
            push_plain(chunk[cursor : match.start()])
            role, value = _digit_role(match.group(), applicant)
            if role == "plain":
                push_plain(match.group())
            else:
                pieces.append((match.group(), role, value))
            cursor = match.end()
        push_plain(chunk[cursor:])

    cursor = 0
    for match in _EMAIL_LIKE.finditer(text):
        push_text(text[cursor : match.start()])
        pieces.append((match.group(), "email", None))
        cursor = match.end()
    push_text(text[cursor:])
    return pieces


def analyze_answer(answer: str | None, applicant: int) -> AnswerAnalysis:
    """归类一条非数字答案。

    Args:
        answer: 已提取的申请答案（见 ``commspt_join_group._extract_answer``），可为空串。
        applicant: 申请人 QQ 号；用于识别「把 QQ 号当成 UID」的误填，``<= 0`` 时不做比对。
    """
    text = (answer or "").strip()
    pieces = _split(text, applicant) if text else []

    seen: dict[int, None] = {}
    for _, role, value in pieces:
        if role == "uid" and value is not None:
            seen.setdefault(value, None)
    uid_candidates = tuple(seen)
    qq_hit = any(role == "qq" for _, role, _ in pieces)
    has_email = any(role == "email" for _, role, _ in pieces)

    if not text:
        reason = "申请没有填写答案"
    elif uid_candidates or qq_hit:
        reason = "答案不是纯数字"
    elif has_email:
        reason = "答案填的是邮箱，不是 UID"
    else:
        reason = "答案里找不到 UID"

    return AnswerAnalysis(
        reason=reason,
        uid_candidates=uid_candidates,
        qq_hit=qq_hit,
        segments=tuple((chunk, role) for chunk, role, _ in pieces),
    )


def non_numeric_answer_hint(answer: str | None, applicant: int, *, setuid_command: str | None = None) -> str:
    """生成「答案不是纯数字」分支的文字提示块（提示卡片渲染失败时使用）。

    Args:
        answer: 已提取的申请答案，可为空串。
        applicant: 申请人 QQ 号，``<= 0`` 时不做 QQ 号比对。
        setuid_command: 补绑映射的命令展示文本（如 ``&setuid``）。仅主群批准会写映射台账，
            因此只有主群通知需要传入；为 ``None`` 时不展示补绑提示。

    Returns:
        以 ``\\n`` 连接的多行文本，首行是归类后的结论，其后是 ``ⓘ`` 开头的补充说明。
    """
    analysis = analyze_answer(answer, applicant)
    lines = [analysis.headline]
    candidates = analysis.uid_candidates
    if candidates:
        shown = "、".join(str(c) for c in candidates[:_MAX_SHOWN])
        if len(candidates) > _MAX_SHOWN:
            shown += " 等"
        guess = "可能是 UID" if len(candidates) == 1 else "可能其中之一是 UID"
        lines.append(f"ⓘ 识别到 {shown}，{guess}（仅供参考）")
    if analysis.qq_hit:
        lines.append(f"ⓘ {applicant} 是申请人的 QQ 号，不是 UID")
    if candidates and setuid_command:
        lines.append(f"ⓘ 批准后不会自动绑定 UID，核实后可用 {setuid_command} 补绑")
    return "\n".join(lines)
