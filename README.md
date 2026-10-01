# commspt-bot-nonebot

LittleSkin 社区支持 QQ 机器人 —— **NoneBot2 + Alconna** 实现，由 [commspt-bot-avilla](https://github.com/LittleSkinCommspt/commspt-bot-avilla)（Avilla 版）移植而来。

## 特性

- **Alconna 命令规范**：所有命令使用 [Arclet Alconna](https://github.com/ArcletProject/Alconna) 声明式定义，参数强类型校验、自动帮助输出
- **泛平台消息层**：消息收发、图片、@ 均基于 `UniMessage`（UniSeg），命令解析跨平台通用
- **协议相关动作**：禁言、撤回、入群审批等基于 OneBot V11 API（见下文说明）

## 目录结构

```
plugins/commspt_bot/              # 父插件（共享层）
├── __init__.py                   # PluginMetadata + 自动加载子插件
├── config.py                     # 配置 schema（值请写在 .env）
├── models/                       # 外部 API 的 pydantic 模型层
│   ├── const.py                  # Yggdrasil / CSL 客户端与常量
│   ├── littleskin_api.py         # LittleSkin Admin API
│   ├── mongodb_data.py           # UIDMapping（Mongo）
│   ├── cloudconfig.py            # 云控开关
│   ├── csl_api.py                # CustomSkinLoader API
│   ├── version_api.py            # 版本查询（CSL / Authlib / Liberica Java）
│   ├── bingling_ipip.py          # IP 归属地
│   └── render_user_info.py       # 用户信息卡数据模型 + 出图
├── utils/
│   ├── adv_filter.py             # 群白名单 / 管理员 规则与权限
│   ├── messenger.py              # 跨群发送工具
│   ├── browserless.py            # Jinja2 → browserless 截图
│   ├── skinrendermcapi.py        # 皮肤渲染 + 水印
│   ├── mongodb_manager.py        # UID 映射读写
│   └── random_sleep.py           # 随机延时（拟人化）
├── templates/                    # 用户信息卡模板
├── assets/                       # 图片与字体
└── plugins/                      # 13 个子插件（每个功能一个）
    ├── commspt_simple_response.py    # 静态问答（&help / &faq / &pay ...）；回复内容见根目录 commspt_simple_response.json
    ├── commspt_profile.py            # &ygg / &pro 玩家查询
    ├── commspt_view_skin.py          # &view / &view.ygg / %view.pro 皮肤渲染
    ├── commspt_profile_check.py      # &check 玩家体检
    ├── commspt_user_info.py          # &user / &setuid 用户信息卡
    ├── commspt_group_member.py       # &uid QQ↔UID 查询
    ├── commspt_get_latest.py         # &csl.latest / &ygg.latest / &java.latest
    ├── commspt_mute.py               # &mute / &unmute / &recall / &muteall ...
    ├── commspt_join_group.py         # 入群申请审核 + 新成员欢迎
    ├── commspt_do_action_join.py     # do accept|reject 手动审批
    ├── commspt_ot_nt.py              # &ot 定向提醒
    ├── commspt_dev.py                # &id 环境信息
    └── commspt_log_file.py           # 群文件消息日志（占位）
```

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置

```bash
cp .env.example .env                # 或 .env.prod
cp config.yml.example config.yml
```

按需填写：群号（`DEFINED_QQ__*`）、管理员列表（`config.yml` 中的 `admin_list`）、外部 API 地址、
`LITTLESKIN_ADMIN_TOKEN`、`DB_MONGO__URL` 等。**简单与嵌套配置从 `.env` 读取（`config.py` 的 `Setting` 只定义 schema）；
结构化列表配置从 `config.yml` 读取（默认位于项目根目录，可用 `COMMSPT_CONFIG_FILE` 覆盖路径）。**
简易问答（`&help` / `&faq` / `&pay` 等）的回复内容在项目根目录的 `commspt_simple_response.json` 中编辑，可通过 `COMMSPT_SIMPLE_RESPONSE_FILE` 环境变量覆盖路径。

配置项说明：

| 配置项 | 说明 |
|---|---|
| `COMMAND_START` | 命令前缀（NoneBot 内置），默认 `["&"]` |
| `ALCONNA_USE_COMMAND_START` | 是否将 `COMMAND_START` 作为 Alconna 全局命令前缀，默认 `true` |
| `DEFINED_QQ__LITTLESKIN_MAIN` / `__LITTLESKIN_CAFE` | 主群 / 水群群号 |
| `DEFINED_QQ__COMMSPT_GROUP` | 社区支持组群号 |
| `DEFINED_QQ__NOTIFICATION_CHANNEL` | 通知群号（入群欢迎通知） |
| `DEFINED_QQ__DEV_GROUP` | 开发群群号 |
| `admin_list`（`config.yml`） | 管理员 QQ 列表（YAML 数组） |
| `LITTLESKIN_ADMIN_TOKEN` | LittleSkin Admin API Token |
| `DB_MONGO__URL` | MongoDB 连接串（QQ↔UID 映射） |
| `API_BROWSERLESS__ENDPOINT` | browserless 截图服务 |
| `API_SKINRENDERMC__ENDPOINT` | 皮肤渲染服务 |
| `API_CLOUDCONFIG` | 云控配置（JSON 对象） |
| `COMMSPT_SIMPLE_RESPONSE_FILE` | 简易问答内容 JSON 文件路径（默认项目根目录 `commspt_simple_response.json`） |

### 3. 运行

```bash
uv run nb run                    # 或
uv run python -m nonebot ...     # 由 nb-cli 生成启动脚本
```

### 4. 测试

```bash
uv run pytest -q
```

包含 55 个测试：插件加载、37 个命令注册、命令参数解析（`Match` / `At` / 默认值 / 别名）、
群白名单、管理员权限、业务逻辑直连测试（禁言 / 撤回 / 全员禁言的 API 调用参数），
以及简易问答 JSON 加载测试（`tests/test_simple_response.py`，覆盖默认路径、环境变量覆盖、文件缺失等场景）。

## 平台支持说明

| 能力 | 实现方式 | 平台范围 |
|---|---|---|
| 命令解析、文本/图片/@/引用 | Alconna + `UniMessage`（UniSeg） | **泛平台**（任何已支持适配器） |
| 跨群发送 | `UniMessage.send(Target.group(...))` | **泛平台** |
| 禁言 / 解除禁言 / 全员禁言 | `bot.set_group_ban` / `set_group_whole_ban` | OneBot V11 |
| 撤回消息 | `bot.delete_msg` | OneBot V11 |
| 入群审批（自动/手动） | `GroupRequestEvent.approve()` / `set_group_add_request` | OneBot V11 |

泛平台消息层已就绪；如需接入其它平台，只需在 `utils/messenger.py` 与相关子插件中
增加对应平台的动作实现。

## 从 Avilla 版移植的对应关系

| Avilla | NoneBot + Alconna |
|---|---|
| `@alcommand(Alconna(...))` | `on_alconna(Alconna(...))` + `@matcher.handle()` |
| `@dispatcher_from_preset_cafe` | `rule=in_preset_cafe` |
| `@dispather_by_admin_only` | `permission=admin_only` |
| `ctx: Context` / `message: Message` | `event: MessageEvent` / `bot: Bot` |
| `Args["x", int \| Notice]` | `Args["x", int \| At]` |
| `ctx.scene.send_message(x, reply=msg)` | `matcher.send(x, reply_to=True)` |
| `ctx.scene.into(f"::group({g})").send_message(x)` | `UniMessage(x).send(Target.group(str(g), ...))` |
| `Picture(RawResource(b))` | `UniMessage.image(raw=b)` |
| `MuteCapability` / `RequestCapability` | `bot.set_group_ban` / `event.approve()` |
| `S_ = Setting(**yaml.safe_load(...))` | `S_ = get_plugin_config(Setting)`（值来自 `.env`）+ `C_`（列表值来自 `config.yml`） |

原版 `log_file.py`（实验性）以占位形式保留为 `commspt_log_file.py`。
