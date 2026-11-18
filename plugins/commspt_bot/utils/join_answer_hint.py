"""入群申请「答案不是纯数字」分支的人工审核提示。

申请留言的答案不是十进制纯数字时，机器人不会猜测 UID，而是转人工审核。过去通知里
只有一句「答案不是纯数字，需手动处理」，管理员得自己读答案，再判断申请人是没填、
填了邮箱、把 QQ 号当成了 UID，还是只在 UID 前后多打了几个字。本模块把这些常见情形
归类成一个紧凑的提示块，让管理员一眼就知道该怎么处理。

约定：
- 纯函数、无外部调用：只读申请答案与申请人 QQ，不查主站、不查映射库；
- 识别出的数字**只用于展示**，不参与任何校验、台账登记或审批（与 ``uid_from_answer``
  「非纯数字一律视为无效、绝不猜测」的口径一致）；
- 首行始终以「需手动处理」收尾，与其它人工审核提示的措辞保持一致；
- 返回值是用 ``\\n`` 连接的单个文本块：调用方会用空行分隔各条提示，
  拆成多条会让同一件事的说明被空行打散。

主要接口：
- non_numeric_answer_hint: 生成「答案不是纯数字」分支的提示块
"""

import re

_DIGIT_RUN = re.compile(r"\d+")
"""答案里的连续数字片段（含全角数字，与 ``str.isdecimal`` 的宽容口径一致）。"""

_EMAIL_LIKE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
"""形如邮箱的片段。邮箱里的数字（如 ``123456@qq.com``）不应被当成候选 UID。"""

_MAX_DIGITS = 12
"""单个数字片段的最大位数；更长的（手机号拼串、证件号等）不可能是 UID，不展示。"""

_MAX_SHOWN = 3
"""候选 UID 最多展示的个数，超出部分以「等」概括，避免刷屏。"""


def _digit_candidates(text: str) -> list[int]:
    """按出现顺序提取去重后的正整数片段（过长或为 0 的片段直接丢弃）。"""
    seen: dict[int, None] = {}
    for run in _DIGIT_RUN.findall(text):
        if len(run) > _MAX_DIGITS:
            continue
        value = int(run)
        if value > 0:
            seen.setdefault(value, None)
    return list(seen)


def non_numeric_answer_hint(answer: str | None, applicant: int, *, setuid_command: str | None = None) -> str:
    """生成「答案不是纯数字」分支的人工审核提示块。

    Args:
        answer: 已提取的申请答案（见 ``commspt_join_group._extract_answer``），可为空串。
        applicant: 申请人 QQ 号；用于识别「把 QQ 号当成 UID」的误填，``<= 0`` 时不做比对。
        setuid_command: 补绑映射的命令展示文本（如 ``&setuid``）。仅主群批准会写映射台账，
            因此只有主群通知需要传入；为 ``None`` 时不展示补绑提示。

    Returns:
        以 ``\\n`` 连接的多行文本，首行是归类后的结论，其后是 ``ⓘ`` 开头的补充说明。
    """
    text = (answer or "").strip()
    if not text:
        return "👀 申请没有填写答案，需手动处理"

    has_email = _EMAIL_LIKE.search(text) is not None
    candidates = _digit_candidates(_EMAIL_LIKE.sub(" ", text))
    qq_hit = applicant > 0 and applicant in candidates
    uid_candidates = [c for c in candidates if c != applicant]

    if not candidates:
        if has_email:
            return "👀 答案填的是邮箱，不是 UID，需手动处理"
        return "👀 答案里找不到 UID，需手动处理"

    lines = ["👀 答案不是纯数字，需手动处理"]
    if uid_candidates:
        shown = "、".join(str(c) for c in uid_candidates[:_MAX_SHOWN])
        if len(uid_candidates) > _MAX_SHOWN:
            shown += " 等"
        guess = "可能是 UID" if len(uid_candidates) == 1 else "可能其中之一是 UID"
        lines.append(f"ⓘ 识别到 {shown}，{guess}（仅供参考）")
    if qq_hit:
        lines.append(f"ⓘ {applicant} 是申请人的 QQ 号，不是 UID")
    if uid_candidates and setuid_command:
        lines.append(f"ⓘ 批准后不会自动绑定 UID，核实后可用 {setuid_command} 补绑")
    return "\n".join(lines)
