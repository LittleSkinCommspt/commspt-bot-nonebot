import re
from dataclasses import dataclass
from typing import Literal

NoticeKind = Literal["Main", "Cafe"]
NoticeSubtype = Literal["add", "invite"]


@dataclass(frozen=True)
class JoinRequestNotice:
    kind: NoticeKind
    applicant: int
    answer: str
    sub_type: NoticeSubtype
    flag: str


class JoinRequestNoticeError(ValueError):
    pass


# 末尾边界断言 (?=[\r\n]|$) 确保 flag 后为行尾/串尾，仍拒绝 id=add_flag_extra 之类的粘连。
# 解析使用 search 以容忍生产者拼在通知前后的提示行与图片 CQ 段。
# 申请人行的括号后缀为可选候选提示（事件携带 invited_id 时由 formatter 追加），
# 语义等价于旧版式：解析结果中的 applicant 始终是原始的申请人数字，候选 ID 仅作展示。
# 答案行允许为空（无留言的申请走「答案不是纯数字」人工分支），
# 分隔空格用 ` *` 匹配，兼容平台裁掉行尾空白的情况；历史上「（无留言）」
# 等占位文本仍按普通答案解析，不新增任何填补逻辑。
# 「问题」行可选（申请留言带入群问题时由 formatter 追加），仅作展示，不进入解析结果。
_NOTICE_PATTERN = re.compile(
    r"新的入群申请 \((?P<kind>Main|Cafe)\)\n"
    r"» 申请人 (?P<applicant>[0-9]+)(?: \(也可能是: -?[0-9]+\))?\n"
    r"(?:» 问题 *[^\r\n]*\n)?"
    r"» 答案 *(?P<answer>[^\r\n]*)\n"
    r"\nid=(?P<sub_type>add|invite)_(?P<flag>[^\s_\x00-\x1f\x7f]+)"
    r"(?=[\r\n]|$)",
)


def format_join_request_notice(
    kind: NoticeKind,
    applicant: int,
    answer: str,
    sub_type: NoticeSubtype,
    flag: str,
    invited_id: int | None = None,
    *,
    question: str = "",
) -> str:
    """生成入群申请通知文本。

    ``invited_id`` 为可选的尾部参数（位置或关键字传入皆可，**不是 keyword-only**），
    默认 ``None`` 表示事件未携带该字段；携带时在申请人行后追加
    `` (也可能是: {invited_id})``，``0`` 也是有效取值并照原样展示。
    该提示只是展示用途，不参与校验、映射或实际审批身份。

    ``question`` 为申请留言里的入群问题，非空时在答案行上方追加 ``» 问题     {question}``，
    同样只作展示。
    """
    applicant_line = f"» 申请人 {applicant}"
    if invited_id is not None:
        applicant_line = f"{applicant_line} (也可能是: {invited_id})"
    question_line = f"» 问题     {question}\n" if question else ""
    return f"新的入群申请 ({kind})\n{applicant_line}\n{question_line}» 答案     {answer}\n\nid={sub_type}_{flag}"


# 精简引用行：通知附了提示卡（图片）时，文字部分只保留这一行，供 do 命令 / 快捷拒绝溯源，
# 形如 ``id=Main/add/1687233060/<flag>``。申请人、答案等给人看的信息都在图片里。
# 不携带答案：只用于答案不是有效 UID 的通知，解析结果的 answer 为空串，审批时同样不登记 UID。
# 图片段在文字前且不换行（str(Message) 形如 ``[CQ:image,...]id=...``），因此不锚定行首，
# 只用后顾断言排除 ``fileid=`` 之类的粘连；flag 在最后，可含 ``/`` 与 ``:``。
_REF_PATTERN = re.compile(
    r"(?<![0-9A-Za-z])id=(?P<kind>Main|Cafe)/(?P<sub_type>add|invite)/(?P<applicant>[0-9]+)/"
    r"(?P<flag>[^\s_\x00-\x1f\x7f]+)"
    r"(?=[\r\n]|$)",
)


def format_join_request_ref(kind: NoticeKind, applicant: int, sub_type: NoticeSubtype, flag: str) -> str:
    """生成精简引用行（附图通知的文字部分）。

    只用于答案不是有效 UID 的通知：引用行不携带答案，解析回来的 answer 为空串。
    """
    return f"id={kind}/{sub_type}/{applicant}/{flag}"


def parse_join_request_notice(message: str) -> JoinRequestNotice:
    """从消息文本解析入群申请通知；完整通知块优先，其次是精简引用行。"""
    match = _NOTICE_PATTERN.search(message)
    if match is None:
        match = _REF_PATTERN.search(message)
    if match is None:
        raise JoinRequestNoticeError("Message does not match a complete join-request notice")
    fields = match.groupdict()
    match fields["kind"]:
        case "Main" | "Cafe" as kind:
            pass
        case _:
            raise JoinRequestNoticeError("Message does not match a complete join-request notice")
    match fields["sub_type"]:
        case "add" | "invite" as sub_type:
            pass
        case _:
            raise JoinRequestNoticeError("Message does not match a complete join-request notice")
    return JoinRequestNotice(
        kind=kind,
        applicant=int(fields["applicant"]),
        answer=fields.get("answer") or "",
        sub_type=sub_type,
        flag=fields["flag"],
    )
