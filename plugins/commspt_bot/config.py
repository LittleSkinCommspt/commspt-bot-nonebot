"""commspt-bot 配置

本文件只定义配置 schema，实际取值请写在项目根目录的 .env 中（大小写不敏感）：

    COMMAND_PROMPT=&
    DEFINED_QQ__FORWARD_BOT=123456
    DEFINED_QQ__LITTLESKIN_MAIN=123456
    DEFINED_QQ__LITTLESKIN_CAFE=123456
    DEFINED_QQ__COMMSPT_GROUP=123456
    DEFINED_QQ__CSL_GROUP=123456
    DEFINED_QQ__NOTIFICATION_CHANNEL=123456
    DEFINED_QQ__DEV_GROUP=123456
    API_SKINRENDERMC__ENDPOINT=https://...
    API_MIHARI_SVG__ENDPOINT=https://...
    DB_MONGO__URL=mongodb://...
    API_BINGLING_IPIP__ENDPOINT=https://...
    API_BROWSERLESS__ENDPOINT=https://...
    API_LITTLESKIN_ORIGIN__ENDPOINT=https://littleskin.cn
    API_CLOUDCONFIG={"endpoint": "...", "username": "...", "password": "..."}
    DEV_MODE=false
    ADMIN_LIST=[10001,10002]
    LITTLESKIN_ADMIN_TOKEN=...

非复杂类型（字符串/数字）直接写值，列表与对象类型使用 JSON 书写。
"""

import ssl
from pathlib import Path

from nonebot import get_plugin_config
from pydantic import BaseModel

BASE_DIR = Path(__file__).parent
ASSETS_DIR = BASE_DIR / "assets"
TEMPLATE_DIR = BASE_DIR / "templates"

# 等价于旧版 httpx.create_ssl_context(verify=..., http2=True)：
# httpx 0.28 起不再提供 http2 参数，需自行设置 ALPN 以协商 HTTP/2
VERIFY_CONTENT = ssl.create_default_context()
VERIFY_CONTENT.set_alpn_protocols(["h2", "http/1.1"])

JOIN_ANNOUNCEMENT_FILE = Path.cwd() / ".join-announcement.txt"


class DefinedQQ(BaseModel):
    forward_bot: int = 0
    littleskin_main: int = 0
    littleskin_cafe: int = 0
    commspt_group: int = 0
    csl_group: int = 0
    notification_channel: int = 0
    dev_group: int = 0


class API_SkinRenderMC(BaseModel):
    endpoint: str = ""


class API_mihari_svg(BaseModel):
    endpoint: str = ""


class DB_mongo(BaseModel):
    url: str = ""


class API_bingling_ipip(BaseModel):
    endpoint: str = ""


class API_browserless(BaseModel):
    endpoint: str = ""


class API_littleskin_origin(BaseModel):
    endpoint: str = "https://littleskin.cn"


class API_cloudconfig(BaseModel):
    endpoint: str = ""
    username: str = ""
    password: str = ""


class Setting(BaseModel):
    command_prompt: str = "&"
    defined_qq: DefinedQQ = DefinedQQ()
    api_skinrendermc: API_SkinRenderMC = API_SkinRenderMC()
    api_mihari_svg: API_mihari_svg = API_mihari_svg()
    db_mongo: DB_mongo = DB_mongo()
    api_bingling_ipip: API_bingling_ipip = API_bingling_ipip()
    api_browserless: API_browserless = API_browserless()
    api_littleskin_origin: API_littleskin_origin = API_littleskin_origin()
    api_cloudconfig: API_cloudconfig = API_cloudconfig()

    dev_mode: bool = False
    admin_list: list[int] = []
    littleskin_admin_token: str = ""


S_ = get_plugin_config(Setting)
