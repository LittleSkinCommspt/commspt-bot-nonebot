"""异步随机延时工具

提供基于系统安全随机源的异步延时功能，用于防止高频请求或风控规避。

主要接口：
- random_sleep: 执行指定最大时长范围内的随机休眠
"""

import asyncio
from random import SystemRandom


async def random_sleep(tmax: float = 1.0):
    """执行 [0, tmax) 秒范围内的异步随机延时"""
    # 使用操作系统提供的安全随机源（SystemRandom）生成 [0.0, 1.0) 随机数，
    # 乘以 tmax 产生 [0, tmax) 秒的随机延时，用于打散并发请求并降低被目标服务风控的概率
    await asyncio.sleep(tmax * SystemRandom().random())
    return True
