"""入群申请批准瞬间的 UID 登记表（进程内）

为什么需要这张表
----------------
放人（``set_group_add_request``）会立刻触发协议端的 ``group_increase``，NoneBot 在
同一秒内就会把欢迎处理器派发出去。欢迎通知过去靠回查 MongoDB 映射库拿 UID，于是
形成读写竞态：审批调用还没返回、映射还没写入，欢迎侧就已经 ``find_one`` 完成并
拿到空结果，表现为主群欢迎正常但通知群永远显示「未找到 UIDMapping 信息」。

本模块把「申请留言里的答案」当作 UID 的唯一事实来源：审批之前先登记到这张进程内
表，欢迎处理器直接读内存即可命中，不需要任何外部调用，也不受 MongoDB 快慢影响。

设计要点
--------
- 纯内存、无外部依赖：登记是同步语义上「必定成功」的，不会因为网络问题丢数据；
- 带 TTL 的惰性清理，避免长期运行累积无界条目；
- 键是 QQ 号：同一 QQ 短时间内重复申请会覆盖旧值，符合「以最后一次申请为准」；
- 只提供「按 QQ 取 UID」，不再承担「QQ↔UID 审核/一致性校验」职责——那是
  管理员主动查询流程（``&uid`` / ``&user`` / ``&setuid``）与 MongoDB 的职责。

主要接口：
- uid_from_answer: 从申请留言的答案解析 UID（非纯数字一律视为无效）
- remember_join_uid: 登记一条待入群用户的 UID
- get_join_uid: 取出登记（过期视为不存在）
- forget_join_uid: 撤销登记（拒绝入群 / 审批调用失败时）
- purge_expired_join_uids: 主动清理过期条目（供诊断或定时任务调用）
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from nonebot import logger

_PENDING_TTL = 10 * 60
"""登记保留时长（秒）。足够覆盖「审批 -> 协议端推送入群事件 -> 欢迎通知」的最坏延迟。"""


@dataclass(frozen=True, slots=True)
class JoinUid:
    """一条待入群用户的 UID 登记。

    - uid: 申请留言里填写的 LittleSkin UID
    - qmail_verified: 该 UID 是否已通过 QMail（QQ 邮箱归属）确定性校验
    - source: 登记来源标记，仅用于日志与通知展示（当前恒为 ``"answer"``）
    """

    uid: int
    qmail_verified: bool = False
    source: str = "answer"


_INDEX: dict[int, JoinUid] = {}
"""QQ 号 -> 登记内容。"""

_INDEX_CREATED_AT: dict[int, float] = {}
"""QQ 号 -> 登记时刻（``time.monotonic()``，不受系统时钟调整影响）。"""


def uid_from_answer(answer: str | None) -> int | None:
    """从申请留言的答案解析 UID；非纯十进制数字（含空串、占位符）返回 ``None``。

    只接受十进制纯数字：``"42"`` / ``" 42 "`` 是有效 UID，``"42a"``、
    ``"（无留言）"``、``"４２"``（全角）等一律判为无效，绝不猜测。
    """
    text = (answer or "").strip()
    if not text or not text.isdecimal():
        return None
    return int(text)


def remember_join_uid(qq: int, uid: int, *, qmail_verified: bool = False, source: str = "answer") -> JoinUid:
    """登记 ``qq`` 即将入群的 UID（覆盖同 QQ 的旧登记），返回登记内容。

    调用方必须保证在真正放人**之前**调用，否则欢迎侧仍可能读不到。
    """
    _purge_locked()
    record = JoinUid(uid=uid, qmail_verified=qmail_verified, source=source)
    _INDEX[qq] = record
    _INDEX_CREATED_AT[qq] = time.monotonic()
    return record


def get_join_uid(qq: int) -> JoinUid | None:
    """取出 ``qq`` 的登记；不存在或已过期返回 ``None``。"""
    _purge_locked()
    return _INDEX.get(qq)


def forget_join_uid(qq: int) -> None:
    """撤销 ``qq`` 的登记（拒绝入群、审批调用失败、审批已被他人处理时）。"""
    _INDEX.pop(qq, None)
    _INDEX_CREATED_AT.pop(qq, None)


def _purge_locked() -> None:
    """清理超过保留时限的登记（本模块无 await 点，无需加锁）。"""
    deadline = time.monotonic() - _PENDING_TTL
    expired = [qq for qq, ts in _INDEX_CREATED_AT.items() if ts < deadline]
    for qq in expired:
        _INDEX.pop(qq, None)
        _INDEX_CREATED_AT.pop(qq, None)
    if expired:
        logger.debug("purged {n} expired join uid entries", n=len(expired))


def purge_expired_join_uids() -> int:
    """主动清理过期登记，返回清理数量。"""
    before = len(_INDEX)
    _purge_locked()
    return before - len(_INDEX)


def clear_join_uids() -> None:
    """清空全部登记（测试与诊断用）。"""
    _INDEX.clear()
    _INDEX_CREATED_AT.clear()
