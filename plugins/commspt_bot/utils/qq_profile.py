"""QQ 账号资料查询工具

通过 OneBot V11 API 获取 QQ 账号的全局昵称，用于用户信息卡片展示。
与绑定关系无关，可在任意出图场景复用。

主要接口：
- get_qq_nickname: 查询指定 QQ 的全局昵称，失败时返回空字符串
"""

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot


async def get_qq_nickname(bot: Bot, qq: int | str) -> str:
    """通过 OneBot V11 ``get_stranger_info`` 获取 QQ 全局昵称。

    失败（协议端不支持、目标不可查、网络异常等）时记录告警并返回空字符串，
    由调用方决定是否省略昵称展示，不影响出图主流程。
    """
    try:
        info = await bot.get_stranger_info(user_id=int(qq), no_cache=False)
    except Exception as e:
        logger.warning(f"获取 QQ {qq} 全局昵称失败: {e}")
        return ""
    return info.get("nickname", "") or ""
