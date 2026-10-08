# commspt-bot-nonebot

LittleSkin Community Support QQ bot

LittleSkin 的社区支持 QQ 机器人，主要基于 [nonebot/nonebot2](https://github.com/nonebot/nonebot2) 框架。

## 新增/优化的特性

- [简易问答内容配置](#simple-response-content)
- **泛平台消息层**：消息收发、图片、@ 均基于 `UniMessage`（UniSeg），命令解析跨平台通用
- **双后端出图**：`BROWSERLESS_MODE` 可在远程 Browserless 服务与本地 Playwright 渲染间切换

## 目录结构
*此结构可以表达大部分框架原理，但可能不是实时更新*
```
assets/                               # 图片与字体（可通过 COMMSPT_ASSETS_DIR 覆盖）
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
│   ├── browserless.py            # Jinja2 渲染 → Browserless 远程 / 本地 Playwright 截图
│   ├── onebot_message.py         # 原生命令匹配 / 参数解析 / 引用回复工具
│   ├── skinrendermcapi.py        # 皮肤渲染 + 水印
│   ├── mongodb_manager.py        # UID 映射读写
│   └── random_sleep.py           # 随机延时（拟人化）
├── templates/                    # 用户信息卡模板
└── plugins/                      # 13 个子插件（每个功能一个）
    ├── commspt_simple_response.py    # 单一 on_message 分发器，服务 commspt_simple_response.json 中的全部静态问答命令；管理员 &sreload 可在运行时热重载
    ├── commspt_profile.py            # &ygg / &pro 玩家查询
    ├── commspt_cao.py                # 生草复读机
    ├── commspt_view_skin.py          # &view / &view.ygg / %view.pro 皮肤渲染
    ├── commspt_profile_check.py      # &check 玩家体检
    ├── commspt_user_info.py          # &user / &setuid 用户信息卡
    ├── commspt_group_member.py       # &uid QQ↔UID 查询
    ├── commspt_get_latest.py         # &csl.latest / &ygg.latest / &java.latest
    ├── commspt_mute.py               # &mute / &unmute / &recall / &muteall ...（原生 OneBot V11）
    ├── commspt_join_group.py         # 入群申请审核 + 新成员欢迎
    ├── commspt_do_action_join.py     # do accept|reject 手动审批（裸命令，原生 on_regex）
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
静态资源（图片、字体）默认存放在项目根目录的 `assets/` 下，可通过 `COMMSPT_ASSETS_DIR` 环境变量覆盖。

配置项说明：

| 配置项 | 说明 |
|---|---|
| `COMMAND_START` | 命令前缀（NoneBot 内置），默认 `["&"]` |
| `ALCONNA_USE_COMMAND_START` | 是否将 `COMMAND_START` 作为 Alconna 全局命令前缀。**库默认值为 `false`**；本项目在 `.env.example` 中设为 `true`，且**必须为 `true`**，否则配置的前缀不会应用到一般 Alconna 命令（含静态问答分发器的前缀识别）。禁言 / 撤回 / 入群审批等原生命令自行读取纯文本前缀，不受该开关影响。 |
| `DEFINED_QQ__LITTLESKIN_MAIN` / `__LITTLESKIN_CAFE` | 主群 / 水群群号 |
| `DEFINED_QQ__COMMSPT_GROUP` | 社区支持组群号 |
| `DEFINED_QQ__NOTIFICATION_CHANNEL` | 通知群号（入群欢迎通知） |
| `DEFINED_QQ__DEV_GROUP` | 开发群群号 |
| `admin_list`（`config.yml`） | 管理员 QQ 列表（YAML 数组） |
| `LITTLESKIN_ADMIN_TOKEN` | LittleSkin Admin API Token |
| `DB_MONGO__URL` | MongoDB 连接串（QQ↔UID 映射） |
| `API_BROWSERLESS__ENDPOINT` | browserless 截图服务（`BROWSERLESS_MODE=REMOTE` 时使用） |
| `BROWSERLESS_MODE` | 出图后端：`REMOTE`（默认，调用远程 Browserless）或 `LOCAL`（本地 Playwright 渲染）。`LOCAL` 需先安装可选依赖与浏览器内核：`uv sync --extra render-local && uv run playwright install chromium` |
| `API_SKINRENDERMC__ENDPOINT` | 皮肤渲染服务 |
| `API_CLOUDCONFIG` | 云控配置（JSON 对象） |
| `COMMSPT_SIMPLE_RESPONSE_FILE` | 简易问答内容 JSON 文件路径（默认项目根目录 `commspt_simple_response.json`） |
| `COMMSPT_ASSETS_DIR` | 静态资源目录（默认项目根目录 `assets/`） |

入群审批 `do` 命令只接受裸命令 `do accept` 或 `do reject [单个不含空白的原因词]`。`do` 使用前缀无关的原生 `on_regex`，因此带全局前缀的 `&do`（例如 `&do accept`）不会匹配，多词拒绝原因也不会匹配。

### 3. 运行

```bash
uv run nb run                    # 或
uv run python -m nonebot ...     # 由 nb-cli 生成启动脚本
```

### 4. 测试

```bash
uv run pytest -q
```

测试覆盖插件加载、Alconna 命令 + 1 个静态问答分发器（服务 commspt_simple_response.json 中的全部问答命令）的注册、命令参数解析（`Match` / `At` / 默认值 / 别名）、
原生命令（`&mute` / `&unmute` / `&recall` / `&muteall` / `&unmuteall` / `do`）的规则匹配与参数解析、
群白名单、管理员权限、业务逻辑直连测试（禁言 / 撤回 / 全员禁言的 API 调用参数），
以及简易问答 JSON 加载测试（`tests/test_simple_response.py`，覆盖默认路径、环境变量覆盖、文件缺失、schema 校验、有序 `messages` 片段构建等场景）。

<a id="simple-response-content"></a>

## 简易问答内容配置（开发者）

`commspt_simple_response.json` 是一个 JSON 对象，键为**命令名**，值为一条问答条目。

### 条目字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `aliases` | `string[]`（可选） | 别称命令名，例如 `log.csl` 的别名 `csl.log` |
| `reply` | `bool`（可选，默认 `false`） | 是否引用回复触发消息 |
| `text` | `string`（可选） | 文本内容，`\n` 表示换行 |
| `images` | `string[]`（可选） | 图片路径数组，**相对于 `ASSETS_DIR`**（例如 `images/browser.png`）；渲染时图片在前、文本在后 |
| `messages` | 有序片段数组（可选） | 支持多张图片与图文任意交错；与 `text`/`images` **互斥** |

`messages` 与 `text`/`images` 不能同时出现在同一条目中，加载时会跳过冲突条目并记录错误日志。

### `messages` 片段格式

每个片段是一个带 `type` 的对象：

- `{"type": "text", "content": "..."}` 文本片段
- `{"type": "image", "path": "images/xxx.png"}` 图片片段（`path` 相对于 `ASSETS_DIR`）

片段按数组顺序渲染，单条回复因此可以携带**多张图片**，也可以任意交错图文。

### 示例

经典 text + images 条目：

```json
"browser": {
  "images": [
    "images/browser.png"
  ],
  "text": "详见 https://manual.littlesk.in/faq/site#broken-webpage"
}
```

有序多图条目（`messages`）：

```json
"demo": {
  "messages": [
    {"type": "image", "path": "images/browser.png"},
    {"type": "text",  "content": "网页显示异常请先看手册："},
    {"type": "image", "path": "images/rtfm.png"}
  ]
}
```

### 运行时热重载（`&sreload`）

编辑 `commspt_simple_response.json` 后，管理员在群内发送配置前缀对应的 `sreload` 命令（默认为 `&sreload`）即可在**不重启机器人**的情况下让变更生效。支持的变更类型包括：新增命令、删除命令、重命名命令（修改键名或 `aliases`）、修改回复文本或图片。

热重载失败（文件格式错误、JSON 解析失败等）时，机器人会向管理员报告错误原因，**保留原配置继续服务**，不会中断现有命令。

注意事项：
- 键名或别名与 `sreload` 同名的条目会被跳过并记录警告（`sreload` 为保留命令名）。
- 键名或别名与其他已注册命令（Alconna 或原生 OneBot V11 群管命令）同名的条目也会被跳过并记录警告，不会触发双重响应。
- 热重载是**手动操作**，不存在文件监听或自动触发机制。

## 平台支持说明

| 能力 | 实现方式 | 平台范围 |
|---|---|---|
| 命令解析、文本/图片/@/引用 | Alconna + `UniMessage`（UniSeg） | **泛平台**（任何已支持适配器） |
| 跨群发送 | `UniMessage.send(Target.group(...))` | **泛平台** |
| 禁言 / 解除禁言 / 全员禁言 | 原生 `on_message` + `bot.set_group_ban` / `set_group_whole_ban` | OneBot V11 |
| 撤回消息 | 原生 `on_message` + `bot.delete_msg` | OneBot V11 |
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
| 原生命令（`on_command` 语义） | `on_message(rule=native_command_rule(...))`（基于 `get_plaintext`，兼容 `&` 前缀）+ `extract_command_args` |
| `S_ = Setting(**yaml.safe_load(...))` | `S_ = get_plugin_config(Setting)`（值来自 `.env`）+ `C_`（列表值来自 `config.yml`） |

原版 `log_file.py`（实验性）以占位形式保留为 `commspt_log_file.py`。
