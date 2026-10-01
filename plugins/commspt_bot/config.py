"""commspt-bot 插件配置与运行常量

本文件包含两部分配置：

1. 插件配置 Schema（Setting）：通过 NoneBot 的 get_plugin_config(Setting) 导出配置单例 S_，
   实际配置值从项目根目录的 .env 文件中读取（大小写不敏感）：

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
    LITTLESKIN_ADMIN_TOKEN=...

2. 应用配置（AppConfig）：通过 YAML 文件读取结构化列表等配置，导出配置单例 C_。
   默认从项目根目录的 config.yml 读取（可通过环境变量 COMMSPT_CONFIG_FILE 覆盖路径）：

    admin_list:
      - 10001
      - 10002

3. 简易问答内容文件：静态问答（simple_response）所用的 JSON 内容文件，
   默认位于项目根目录的 commspt_simple_response.json（可通过环境变量 COMMSPT_SIMPLE_RESPONSE_FILE 覆盖路径）。

4. 插件静态资源目录：字体、图片等静态资源所在目录，
   默认位于项目根目录的 assets/（可通过环境变量 COMMSPT_ASSETS_DIR 覆盖路径）。

配置规则说明：
- 嵌套环境变量：配置模型中的嵌套字段在环境变量中使用双下划线 `__` 分隔（如 `DEFINED_QQ__LITTLESKIN_MAIN` 映射到 `Setting.defined_qq.littleskin_main`）。
- 复杂类型：非复杂类型（字符串/数字/布尔值）直接书写；字典对象（如 `API_CLOUDCONFIG`）使用标准 JSON 格式书写。
- 列表类型（如管理员列表）统一写入 config.yml，不再使用 .env。

导出的主要模块级常量与单例：
- BASE_DIR: 插件根目录绝对路径
- PROJECT_ROOT: 项目根目录绝对路径
- ASSETS_DIR: 插件静态资源（字体、图片等）目录路径（默认项目根目录的 assets，可用 COMMSPT_ASSETS_DIR 覆盖）
- TEMPLATE_DIR: Jinja2 渲染模板文件目录路径
- VERIFY_CONTENT: 预设支持 HTTP/2 ALPN 协商的 SSLContext 对象
- JOIN_ANNOUNCEMENT_FILE: 新成员进群公告缓存文件路径（项目工作目录下的 .join-announcement.txt）
- CONFIG_FILE: config.yml 配置文件路径（默认项目根目录，可用 COMMSPT_CONFIG_FILE 覆盖）
- SIMPLE_RESPONSE_FILE: 简易问答内容文件路径（默认项目根目录的 commspt_simple_response.json，可用 COMMSPT_SIMPLE_RESPONSE_FILE 覆盖）
- S_: 插件全局配置对象单例（来自 .env）
- C_: 应用配置对象单例（来自 config.yml）
"""

import os
import ssl
from pathlib import Path

import yaml
from nonebot import get_plugin_config
from nonebot.log import logger
from pydantic import BaseModel, ConfigDict

# 插件根目录及静态资源、模板路径
BASE_DIR = Path(__file__).parent
PROJECT_ROOT = BASE_DIR.parent.parent
# 插件静态资源（字体、图片等）目录路径，默认位于项目根目录，可用环境变量覆盖
ASSETS_DIR = Path(os.environ.get("COMMSPT_ASSETS_DIR", str(PROJECT_ROOT / "assets")))
TEMPLATE_DIR = BASE_DIR / "templates"

# 应用配置文件（config.yml）路径，默认位于项目根目录，可用环境变量覆盖
CONFIG_FILE = Path(os.environ.get("COMMSPT_CONFIG_FILE", str(PROJECT_ROOT / "config.yml")))

# 简易问答（simple_response）内容文件路径，默认位于项目根目录，可用环境变量覆盖
SIMPLE_RESPONSE_FILE = Path(os.environ.get("COMMSPT_SIMPLE_RESPONSE_FILE", str(PROJECT_ROOT / "commspt_simple_response.json")))

# 等价于旧版 httpx.create_ssl_context(verify=..., http2=True)：
# httpx 0.28 起不再提供 http2 参数，需自行设置 ALPN 以协商 HTTP/2
VERIFY_CONTENT = ssl.create_default_context()
VERIFY_CONTENT.set_alpn_protocols(["h2", "http/1.1"])

# 新成员入群公告暂存文件路径（保存在当前工作目录下）
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
    defined_qq: DefinedQQ = DefinedQQ()
    api_skinrendermc: API_SkinRenderMC = API_SkinRenderMC()
    api_mihari_svg: API_mihari_svg = API_mihari_svg()
    db_mongo: DB_mongo = DB_mongo()
    api_bingling_ipip: API_bingling_ipip = API_bingling_ipip()
    api_browserless: API_browserless = API_browserless()
    api_littleskin_origin: API_littleskin_origin = API_littleskin_origin()
    api_cloudconfig: API_cloudconfig = API_cloudconfig()

    littleskin_admin_token: str = ""


class AppConfig(BaseModel):
    """config.yml 应用配置模型。"""

    model_config = ConfigDict(extra="ignore")

    # 管理员 QQ 列表（可执行 %mute / %check / do 等管理员命令）
    admin_list: list[int] = []


def _load_app_config() -> AppConfig:
    """读取并解析 config.yml；文件缺失时返回默认配置。"""
    if not CONFIG_FILE.is_file():
        logger.warning(f"未找到应用配置文件 {CONFIG_FILE}，管理员列表为空，请复制 config.yml.example 为 config.yml")
        return AppConfig()

    data = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise TypeError(f"应用配置文件格式错误（应为 YAML 映射）：{CONFIG_FILE}")
    return AppConfig(**data)


# 读取并导出全局插件配置单例
S_ = get_plugin_config(Setting)

# 读取并导出应用配置单例
C_ = _load_app_config()
