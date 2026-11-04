"""MongoDB 数据库管理工具

用于持久化存储与查询 QQ 号与 LittleSkin UID 的绑定关系。

主要接口：
- write_uid_db: 写入或更新 QQ 与 LittleSkin UID 的映射记录
- get_uid_db: 根据 QQ 号查询关联的 LittleSkin UID
- upsert_uid_mapping: 入群审批前置的映射落库（best-effort，压了超时上限）

连接管理：复用进程级共享客户端（见 ``utils.mongo_client``），不再每次操作新建并关闭
客户端。共享客户端省掉了每次调用的握手 + 认证开销，故障期也不会因反复重连而成倍
放大 ``serverSelectionTimeout`` 的等待；连接的释放在应用关闭时统一完成。

写入语义：``write_uid_db`` 使用单条原子 upsert（``update_one(..., upsert=True)``），
重试幂等（``insert_one`` 重试可能产生重复行），并省掉一次 ``find_one`` 往返。

``upsert_uid_mapping`` 是入群审批链路专用的写入入口，与 ``write_uid_db`` 的区别：
- 它处在「先落库、再放人」的关键路径上，因此总耗时必须有上限
  （``PREAPPROVE_TIMEOUT_SECONDS``），避免 MongoDB 故障时把管理员审批拖成分钟级；
- 它显式携带 ``qmail_verified``，因为该字段由审批路径的 QMail 校验结果决定；
- 它从不抛异常，只返回是否写入成功，调用方（审批执行核心）据此决定是否需要
  提示管理员用管理命令补写台账。

请求日志（``utils.request_logging``）联动：
- 每个 Mongo 网络边界（``find_one`` / ``update_one``）都包在
  ``external_request`` 作用域内，按操作名记录失败；地址为连接串 + 库/集合元数据
  （连接串里的凭据由公共模块脱敏）；
- 未使用的 ``get_uid_db`` 同样覆盖，避免后续启用时成为日志盲区；
- 作用域只覆盖单次数据库操作，不覆盖业务流程，异常原样透传。
"""

import asyncio
from datetime import datetime

import pytz
from nonebot import logger

from plugins.commspt_bot.models.mongodb_data import (
    MONGO_COLLECTION,
    MONGO_DATABASE,
    MONGO_SERVICE,
    UIDMapping,
    mongo_failure_address,
)
from plugins.commspt_bot.utils.mongo_client import get_client
from plugins.commspt_bot.utils.request_logging import external_request
from plugins.commspt_bot.utils.retry import call_with_retry

PREAPPROVE_TIMEOUT_SECONDS = 5.0
"""入群审批前置写库的总超时上限（秒）。

放人操作必须在写库之后，因此这里的等待会直接反映为审批延迟。MongoDB 不可达时，
``call_with_retry`` 的 1 + N 次尝试乘以 ``serverSelectionTimeoutMS`` 会让管理员
白等几十秒；压一个上限后最坏只多等 5 秒，写失败照常放人并用管理命令补写即可。
"""


async def write_uid_db(uid: int | str, qq: int | str):
    """写入或更新 QQ 号与 LittleSkin UID 的映射记录及更新时间戳。

    使用单条原子 upsert：重试幂等（``insert_one`` 重试可能产生重复行），
    且省掉一次 ``find_one`` 往返。``$set`` 不含 ``qmail_verified``，
    因此管理端 ``&setuid`` 不会覆盖既有的邮箱验证状态。
    """
    uid = int(uid) if not isinstance(uid, int) else uid
    qq = int(qq) if not isinstance(qq, int) else qq

    coll = get_client()[MONGO_DATABASE][MONGO_COLLECTION]
    record = {"uid": uid, "qq": qq, "last_update": datetime.now(tz=pytz.UTC).timestamp()}
    with external_request(MONGO_SERVICE, mongo_failure_address(), method="update_one"):
        await coll.update_one({"qq": qq}, {"$set": record}, upsert=True)


async def get_uid_db(qq: int | str) -> int | None:
    """根据 QQ 号查询绑定的 LittleSkin UID，未找到则返回 None"""
    # make sure int: 确保 QQ 号为整数类型
    qq = int(qq) if not isinstance(qq, int) else qq

    coll = get_client()[MONGO_DATABASE][MONGO_COLLECTION]

    with external_request(MONGO_SERVICE, mongo_failure_address(), method="find_one"):
        i = await coll.find_one({"qq": qq})

    return i["uid"] if i else None


async def upsert_uid_mapping(
    uid: int,
    qq: int,
    *,
    qmail_verified: bool = False,
    timeout: float = PREAPPROVE_TIMEOUT_SECONDS,
) -> bool:
    """入群审批前置的映射落库（best-effort，永不抛异常，返回是否写入成功）。

    必须由审批执行核心在**放人之前**调用：放人会立刻触发 ``group_increase``，
    欢迎通知随即回查映射；写入晚于审批就会稳定读到空记录。

    Args:
        uid: 本次放行使用的 LittleSkin UID（取自申请留言的答案）。
        qq: 申请人 QQ 号。
        qmail_verified: 该 UID 是否已通过 QMail 确定性校验。
        timeout: 总耗时上限（秒），超时按失败处理，不再继续等待。

    Returns:
        ``True`` 表示已写入 MongoDB；``False`` 表示超时或写入异常（调用方应提示
        管理员用管理命令补写台账，但**不得**因此阻止放人）。
    """
    mapping = UIDMapping(uid=uid, qq=qq, qmail_verified=qmail_verified)
    try:
        await asyncio.wait_for(
            call_with_retry(MONGO_SERVICE, mapping.update),
            timeout,
        )
    except TimeoutError:
        logger.error(f"映射写入超时（>{timeout:g} 秒），QQ {qq} -> UID {uid} 未落库")
        return False
    except Exception as e:
        logger.exception(e)
        return False
    return True
