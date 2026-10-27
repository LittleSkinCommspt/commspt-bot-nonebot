"""外部网络服务失败重试工具

对单个外部网络调用（HTTP API / MongoDB 等）执行有限次重试，并在日志中显式翻译
「哪一个网络服务」失败及其原因，便于运维定位。

设计要点：
- 重试次数取自配置 ``S_.failed_retry_time``（环境变量 ``FAILED_RETRY_TIME``，默认 2），
  语义为「首次失败后再重试的次数」，即合计最多 ``1 + FAILED_RETRY_TIME`` 次请求。
- 重试粒度是单个调用：只重跑失败的那一次请求，不会重跑整个业务流程。
- 固定间隔 1 秒重试（``RETRY_DELAY_SECONDS``）。
- 业务性失败（如 ``PlayerNotFoundError`` 表示「查无此人」）与非瞬时错误（4xx）快速失败，
  不消耗重试次数；429 与 5xx 视为可重试。
- 仅用于外部网络服务；QQ 协议端调用与渲染类服务（SkinRenderMC / Browserless / Playwright）
  不参与重试。
- 请求日志（``utils.request_logging``）联动：中间失败只打控制台，最终失败只落盘一次；
  重试后成功不记为失败文件。日志实现不改变重试时序、异常类型或异常内容。

主要接口：
- call_with_retry: 以统一重试策略调用协程函数
- describe_error: 将异常翻译为中文原因描述
- is_retryable: 判断异常是否值得重试
"""

import asyncio

import httpx
from nonebot import logger
from pymongo.errors import PyMongoError

from plugins.commspt_bot.config import S_
from plugins.commspt_bot.utils.request_logging import retry_log_scope

RETRY_DELAY_SECONDS = 1.0
"""重试之间的固定等待秒数。"""

_LOG_PREFIX = "[网络服务]"


def describe_error(exc: BaseException) -> str:
    """将异常翻译为面向日志的中文原因描述。"""
    if isinstance(exc, httpx.TimeoutException):
        return "请求超时"
    if isinstance(exc, httpx.ConnectError):
        return "无法建立连接"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code} 响应错误"
    if isinstance(exc, httpx.HTTPError):
        return "网络请求异常"
    if isinstance(exc, PyMongoError):
        return "数据库操作异常"
    return f"{type(exc).__name__}: {exc}"


def is_retryable(exc: BaseException, non_retryable: tuple[type[BaseException], ...] = ()) -> bool:
    """判断异常是否值得重试。

    - 命中 ``non_retryable``（业务性结果，如查无此人）：不重试
    - HTTP 4xx（429 除外）：不重试；429 与 5xx：重试
    - 其余异常（超时、连接失败、解析异常、数据库异常等）：重试
    """
    if non_retryable and isinstance(exc, non_retryable):
        return False
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code == 429 or status_code >= 500
    return True


async def _retry_sleep() -> None:
    """重试前的固定等待（单独抽出便于测试断言，无需真实等待）。"""
    await asyncio.sleep(RETRY_DELAY_SECONDS)


async def call_with_retry(
    service: str,
    func,
    *args,
    non_retryable: tuple[type[BaseException], ...] = (),
    **kwargs,
):
    """调用外部网络服务，失败时按配置重试，并在日志中翻译服务名与失败原因。

    Args:
        service: 面向日志的中文服务名（如 "LittleSkin 管理端 API"）。
        func: 待调用的协程函数。
        *args: 透传给 ``func`` 的位置参数。
        non_retryable: 属于业务结果、不应重试的异常类型元组。
        **kwargs: 透传给 ``func`` 的关键字参数。

    Returns:
        ``func`` 的返回值。

    Raises:
        最后一次尝试的原始异常（重试耗尽或不可重试时）。
    """
    attempts = 1 + max(0, S_.failed_retry_time)

    for attempt in range(1, attempts + 1):
        # 每次尝试进入重试日志范围：中间失败只在控制台，最终失败仅落盘一次
        with retry_log_scope(attempt, attempts, service=service) as log_scope:
            try:
                result = await func(*args, **kwargs)
            except Exception as exc:
                if not is_retryable(exc, non_retryable):
                    if non_retryable and isinstance(exc, non_retryable):
                        # 业务结果（查无此人等）：不记失败，外层作用域也不记录
                        log_scope.mark_non_failure(exc)
                    else:
                        logger.warning(f"{_LOG_PREFIX} {service} 请求失败（不重试）：{describe_error(exc)}")
                        # 确定不会再重试：唯一落盘点，记录带实际尝试次数
                        log_scope.mark_final(exc)
                    raise
                if attempt >= attempts:
                    logger.error(
                        f"{_LOG_PREFIX} {service} 连续 {attempts} 次请求失败，放弃重试：{describe_error(exc)}",
                    )
                    # 重试耗尽：唯一落盘点（沿用最内层网络点记录的实际地址 / 服务）
                    log_scope.mark_final(exc)
                    raise
                logger.warning(f"{_LOG_PREFIX} {service} 第 {attempt}/{attempts} 次请求失败：{describe_error(exc)}")
            else:
                if attempt > 1:
                    logger.info(f"{_LOG_PREFIX} {service} 第 {attempt} 次尝试成功")
                return result

        # 确认仍要重试后才等待（保持原有重试时序：失败 → 等待 → 下一次尝试）
        await _retry_sleep()
