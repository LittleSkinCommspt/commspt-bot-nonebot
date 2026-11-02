"""httpx 统一重试传输层

用 ``httpx-retries`` 的 ``RetryTransport`` 为所有对外 HTTP 调用提供重试，
替代原先包在业务调用外的 ``call_with_retry``。重试次数严格来自
``S_.failed_retry_time``（1 次请求 + N 次重试），本模块不定义任何私有默认值。

设计要点：
- **重试次数单一来源**：``build_retry()`` 只读 ``S_.failed_retry_time``；
  ``httpx-retries`` 的 ``total`` 语义正是「首次之外的重试次数」，与配置语义一致，
  无需 ±1 换算。
- **TLS / HTTP2 必须传给内层 transport**：``httpx.Client`` 在显式传入
  ``transport=`` 后会忽略 ``verify`` / ``http2`` / ``limits`` / ``cert``，
  因此这些参数只能挂在 ``httpx.AsyncHTTPTransport`` 上，否则会静默降级为
  系统证书 + HTTP/1.1。
- **重试条件对齐原有语义**：``retry.py`` 原先对任意 ≥500 与 429 重试、对 4xx
  快速失败。``httpx-retries`` 默认只认 ``{429, 502, 503, 504}``，此处显式枚举
  500–599 与 429，保持行为不变。
- **逐次进度上报**：子类覆写 ``asleep()`` 上报 ``(第几次, 共几次)``，交给
  ``utils.request_logging`` 写入「尝试=N/M」字段，同时输出与旧实现同格式的
  控制台日志；重试耗尽时由外层 ``external_request`` 落盘一次。
- **幂等方法白名单**：只在 ``GET`` / ``HEAD`` / ``OPTIONS`` 等幂等方法上重试，
  审批类 POST（如 ``set_group_add_request``）不在本模块覆盖范围内。
"""

from __future__ import annotations

import httpx
from httpx_retries import Retry, RetryTransport
from nonebot import logger

from plugins.commspt_bot.config import S_, VERIFY_CONTENT
from plugins.commspt_bot.utils.request_logging import (
    reset_attempt_progress,
    set_attempt_progress,
)
from plugins.commspt_bot.utils.retry import _LOG_PREFIX, describe_error

_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, *range(500, 600)})
"""可重试的 HTTP 状态码：429 限流 + 全部 5xx（与旧 ``is_retryable`` 一致）。"""

_RETRYABLE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE", "TRACE"})
"""可重试的幂等方法（不含 POST / PATCH）。"""


class LoggingRetry(Retry):
    """在每次重试等待前上报进度并输出与旧实现一致的控制台日志。

    继承而非包装：``httpx-retries`` 的 ``increment()`` 会用 ``copy_with()``
    重建实例，子类额外构造参数不会被保留，因此这里覆写 ``copy_with`` 把
    ``service`` 手动带过去，其余状态仍由父类维护。
    """

    service: str = "外部服务"
    """面向日志的服务名（由 ``build_retry`` 注入，跨 ``copy_with`` 保留）。"""

    def copy_with(self, **kwargs) -> LoggingRetry:  # type: ignore[override]
        """重建实例时保留 ``service``（父类实现只回传已知字段）。"""
        new = super().copy_with(**kwargs)
        new.service = self.service
        return new

    async def asleep(self, response: httpx.Response | Exception) -> None:
        """异步等待：上报进度 → 输出控制台日志 → 交给父类计算并等待。

        ``httpx-retries`` 在调用本方法前已执行 ``increment()``，因此
        ``attempts_made`` 正是「刚刚失败的那一次」，不需要再 +1。
        """
        attempt = self.attempts_made
        attempts = self.total + 1
        set_attempt_progress(attempt, attempts)
        if isinstance(response, Exception):
            detail = describe_error(response)
        else:
            detail = f"HTTP {response.status_code} 响应错误"
        logger.warning(f"{_LOG_PREFIX} {self.service} 第 {attempt}/{attempts} 次请求失败：{detail}")
        await super().asleep(response)


def build_retry(service: str, *, allow_post: bool = False) -> Retry:
    """按 ``S_.failed_retry_time`` 构造重试策略。

    Args:
        service: 面向日志的服务名（如 ``"LittleSkin 管理端 API"``）。
        allow_post: 是否允许重试 POST。仅用于自身幂等的接口（例如飞书多维表格
            写入靠固定 ``client_token`` 去重），默认关闭以避免重复副作用。

    Returns:
        配置好的 ``Retry``；重试次数与间隔均取自配置，不写死。
    """
    retries = max(0, S_.failed_retry_time)
    methods = _RETRYABLE_METHODS | {"POST"} if allow_post else _RETRYABLE_METHODS
    retry = LoggingRetry(
        total=retries,
        allowed_methods=methods,
        status_forcelist=_RETRYABLE_STATUS_CODES,
        # 首次等待 = factor × 2¹ = 1s，与旧实现的固定 1 秒间隔对齐
        backoff_factor=0.5,
        backoff_jitter=0.0,  # 关闭抖动：保持固定间隔，行为可预测
        respect_retry_after_header=True,
        max_backoff_wait=10.0,  # 单次等待上限，防止超大 Retry-After 拖住流程
        # 累计等待预算；0 次重试时不能传 0（库要求正数）
        total_timeout=float(retries * 10) if retries else None,
    )
    retry.service = service
    return retry


def build_transport(service: str, *, allow_post: bool = False) -> RetryTransport:
    """构造带重试的异步传输层（TLS 与 HTTP/2 显式传给内层）。"""
    inner = httpx.AsyncHTTPTransport(verify=VERIFY_CONTENT, http2=True)
    return _AttemptScopedTransport(inner, retry=build_retry(service, allow_post=allow_post))


class _AttemptScopedTransport(RetryTransport):
    """在每次请求前后清理「尝试进度」，避免污染同一任务里的后续调用。

    ``_ATTEMPT`` 是 ContextVar：若只在重试时写入而不清理，一次带重试的请求
    结束后，同一任务里后续**未重试**的失败会错误地带上「尝试=2/3」之类的字段。
    这里把清理收口在 transport 边界，调用方无需关心。
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        reset_attempt_progress()
        try:
            return await super().handle_async_request(request)
        finally:
            reset_attempt_progress()


def async_client(service: str, *, allow_post: bool = False, **kwargs) -> httpx.AsyncClient:
    """构造挂载统一重试传输层的 ``AsyncClient``。

    ``verify`` / ``http2`` 由内层传输层负责，调用方不得再传入（会被 httpx 忽略）。
    其余参数（``base_url`` / ``timeout`` / ``headers`` / ``follow_redirects`` 等）
    原样透传。
    """
    return httpx.AsyncClient(transport=build_transport(service, allow_post=allow_post), **kwargs)


__all__ = [
    "LoggingRetry",
    "async_client",
    "build_retry",
    "build_transport",
    "reset_attempt_progress",
]
