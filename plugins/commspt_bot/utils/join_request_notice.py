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


_NOTICE_PATTERN = re.compile(
    r"新的入群申请 \((?P<kind>Main|Cafe)\)\n"
    r"» 申请人 (?P<applicant>[0-9]+)\n"
    r"» 答案     (?P<answer>[^\r\n]+)\n"
    r"\nid=(?P<sub_type>add|invite)_(?P<flag>[^\s_\x00-\x1f\x7f]+)",
)


def format_join_request_notice(
    kind: NoticeKind,
    applicant: int,
    answer: str,
    sub_type: NoticeSubtype,
    flag: str,
) -> str:
    return (
        f"新的入群申请 ({kind})\n"
        f"» 申请人 {applicant}\n"
        f"» 答案     {answer}\n"
        f"\n"
        f"id={sub_type}_{flag}"
    )


def parse_join_request_notice(message: str) -> JoinRequestNotice:
    match = _NOTICE_PATTERN.fullmatch(message)
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
        answer=fields["answer"],
        sub_type=sub_type,
        flag=fields["flag"],
    )
