# commspt-bot-nonebot

LittleSkin Community Support QQ bot

LittleSkin 的社区支持 QQ 机器人，主要基于 [nonebot/nonebot2](https://github.com/nonebot/nonebot2) 框架。

## 新增/优化的特性

- [简易问答内容配置](#simple-response-content)
- **泛平台消息层**：消息收发、图片、@ 均基于 `UniMessage`（UniSeg），命令解析跨平台通用
- **双后端出图**：`BROWSERLESS_MODE` 可在远程 Browserless 服务与本地 Playwright 渲染间切换
- **外部服务失败重试**：`FAILED_RETRY_TIME` 控制重试次数（默认 2，即合计最多 3 次请求），失败后回复统一提示「处理你的请求时发生了一些问题」并记录各网络服务的中文失败日志
- **入群审批双入口**：既可在通知消息下回复 `do accept` / `do reject` 文字命令审批，也可直接对通知消息贴 👍 / 👎 表情快捷审批（见[入群审批](#join-approval)）
- **封禁记录上云**：`&banlog` 一条命令把封禁信息写入飞书多维表格，类别走表格选项校验，支持多选与备注（见[飞书封禁记录](#feishu-ban-record)）

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
│   ├── feishu_bitable.py         # 飞书多维表格客户端（&banlog 写入）
│   └── render_user_info.py       # 用户信息卡数据模型 + 出图
├── utils/
│   ├── adv_filter.py             # 群白名单 / 管理员 规则与权限
│   ├── messenger.py              # 跨群发送工具
│   ├── join_action.py            # 入群审批公共执行核心 + 表情审批凭证索引
│   ├── join_request_notice.py    # 入群申请通知的格式化与解析
│   ├── browserless.py            # Jinja2 渲染 → Browserless 远程 / 本地 Playwright 截图
│   ├── onebot_message.py         # 原生命令匹配 / 参数解析 / 引用回复工具
│   ├── skinrendermcapi.py        # 皮肤渲染 + 水印
│   ├── mongodb_manager.py        # UID 映射读写
│   ├── ban_lookup.py             # 按 UID 查询封禁记录（&user / 入群通知复用）
│   ├── ban_record.py             # &banlog 参数解析与表格列名映射（纯函数）
│   └── random_sleep.py           # 随机延时（拟人化）
├── templates/                    # 用户信息卡模板
└── plugins/                      # 14 个子插件（每个功能一个）
    ├── commspt_simple_response.py    # 单一 on_message 分发器，服务 commspt_simple_response.json 中的全部静态问答命令；管理员 &sreload 可在运行时热重载
    ├── commspt_profile.py            # &ygg / &pro 玩家查询
    ├── commspt_cao.py                # 生草复读机
    ├── commspt_view_skin.py          # &view / &view.ygg / %view.pro 皮肤渲染
    ├── commspt_profile_check.py      # &check 玩家体检
    ├── commspt_user_info.py          # &user / &setuid 用户信息卡
    ├── commspt_group_member.py       # &uid QQ↔UID 查询
    ├── commspt_get_latest.py         # &csl.latest / &ygg.latest / &java.latest
    ├── commspt_mute.py               # &mute / &unmute / &recall / &muteall ...（原生 OneBot V11）
    ├── commspt_ban_record.py         # &banlog 封禁记录写入飞书多维表格
    ├── commspt_join_group.py         # 入群申请审核 + 新成员欢迎
    ├── commspt_do_action_join.py     # do accept|reject 手动审批（回复通知消息，裸命令，原生 on_regex）
    ├── commspt_join_emoji.py         # 对审批通知贴 👍/👎 表情快捷审批（原生 on_notice）
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
| `BROWSERLESS_MODE` | 出图后端：`REMOTE`（默认，调用远程 Browserless）或 `LOCAL`（本地 Playwright 渲染）。`LOCAL` 需先安装可选依赖与浏览器内核：`uv sync --extra render-local && uv run playwright install chromium`，并自行准备 `assets/browserless/` 下的本地资源（含字体，详见下文「本地渲染」小节） |
| `FAILED_RETRY_TIME` | 外部网络服务请求失败后的重试次数（默认 `2`，即合计最多 3 次请求；`0` 表示不重试）。生效于 `&ygg` / `&pro` / `&user` / `&uid`，渲染类服务（SkinRenderMC / Browserless / 本地 Playwright）与 QQ 协议端调用不重试 |
| `API_SKINRENDERMC__ENDPOINT` | 皮肤渲染服务 |
| `API_CLOUDCONFIG` | 云控配置（JSON 对象） |
| `API_FEISHU__APP_ID` / `API_FEISHU__APP_SECRET` | 飞书自建应用凭证（`&banlog` 写多维表格用），见[飞书封禁记录](#feishu-ban-record) |
| `FEISHU_BAN__APP_TOKEN` / `FEISHU_BAN__TABLE_ID` | 多维表格 `app_token` 与 `table_id` |
| `FEISHU_BAN__FIELDS__*` | 多维表格中各逻辑字段对应的列名 |
| `COMMSPT_SIMPLE_RESPONSE_FILE` | 简易问答内容 JSON 文件路径（默认项目根目录 `commspt_simple_response.json`） |
| `COMMSPT_ASSETS_DIR` | 静态资源目录（默认项目根目录 `assets/`） |

#### 本地渲染（`BROWSERLESS_MODE=LOCAL`）与字体

`LOCAL` 模式不依赖远程 Browserless，改用本地 Playwright + Chromium 出图，模板中所有远程资源会改从项目根目录的 `assets/browserless/` 读取。

卡片的主字体是 **MiSans Bold**（小米 MiSans，免费商用），由 `@font-face` 显式加载，`REMOTE` 与 `LOCAL` 都用它，不再依赖渲染机上装了什么字体——早期用系统字体栈时，Windows 命中 `Noto Sans SC`、Linux 命中 `Noto Sans CJK SC`，字重与度量都不同，同一模板在两处出图并不一致。

UID / 积分 / 邮箱 / QQ / 时间戳等编号类字段另用等宽字体栈（`SFMono-Regular, Consolas, "Liberation Mono", monospace`）——这些字段逐位核对，等宽位宽更易读。该栈逐平台解析，属有意为之。`email_help` 里的 `⚠️` 不在 MiSans 内，回退到宿主字体是可接受的。

> **字体许可**：MiSans 由小米提供，免费商用（含嵌入），许可要求「在软件中注明使用了 MiSans 字体」。本仓库不随附字体文件，请自行从[官方页面](https://hyperos.mi.com/font/zh/)获取并遵守其许可协议。`assets/browserless/` 已加入 `.gitignore`，不会被提交。
>
> 若未放入字体，`LOCAL` 模式启动出图时会直接报错终止（不静默回退），避免产出缺字体的卡片。

`LOCAL` 模式所需的文件（文件名固定，缺失即报错）：

| 文件 | 版本 | 说明 |
|---|---|---|
| `all.min.js` | Font Awesome Free **6.5.2** | Font Awesome 6 的 JS（`<i>` → inline SVG 转换） |
| `fontawesome.min.css` | Font Awesome Free **6.5.2** | Font Awesome 6 的 CSS |
| `MiSans-Bold.ttf` | **4.009** | 卡片主字体（名称固定） |

入群审批 `do` 命令只接受裸命令 `do accept` 或 `do reject [单个不含空白的原因词]`。`do` 使用前缀无关的原生 `on_regex`，因此带全局前缀的 `&do`（例如 `&do accept`）不会匹配，多词拒绝原因也不会匹配。

### 用户信息卡主题

`USER_CARD_AUTO_THEME` 默认开启：按 `Asia/Shanghai` 时区，07:00（含）至 19:00（不含）使用浅色，其余时间使用深色，与服务器本地时区无关。设为 `false` 后，完全恢复被查询账户的 `is_dark_mode` 偏好。该开关只影响用户信息卡，不修改账户数据，也不影响其他图卡。

<a id="feishu-ban-record"></a>

### 飞书封禁记录（`&banlog`）

把管理员的封禁操作自动登记到飞书多维表格，便于团队复盘与查询。该功能**不与 LittleSkin 数据库联通**，UID 由命令直接给出。

命令（管理员，`in_preset_cafe` 群组可用）：

| 命令 | 说明 |
|---|---|
| `&banlog <UID> <类别...> [备注...]` | 写入一条封禁记录 |
| `&banlog.fields` | 打印表格字段、类别选项与列名匹配结果（接入时自检用） |

书写规则：

- 第一个参数必须是纯数字 UID；
- 其后连续属于表格「类别」列选项的 token 依次计入类别（该列是多选，可一次给多个）；
- 从第一个不属于类别的 token 起，剩余全部作为备注；
- 备注首词恰好与某个类别同名时，用 `--note` 强制划分：`&banlog 43228 账户异常 --note 上传材质 很多`。

示例：

```
&banlog 43228 账户异常 批量上传大量材质
&banlog 43228 昵称 角色名 同时封禁昵称和角色名
```

写入的列：`UID`（数字）、`类别`（多选）、`备注`（文本）、`自动化处理人员`（文本，取触发命令的管理员 QQ）。
「处理人」是人员字段，只接受 `open_id` / `user_id` / `union_id`，应用身份无法写入，故该列留空。

类别选项在运行时从表格字段读取（缓存 5 分钟），因此表格改选项后无需改代码。

#### 前置配置

1. 在 [开放平台](https://open.feishu.cn/app) 创建**企业自建应用**，取得 `App ID` / `App Secret`，填入 `.env`：

   ```ini
   API_FEISHU__APP_ID=cli_xxxxxxxxxxxxxxxx
   API_FEISHU__APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

2. 为应用开通权限 **`bitable:app`**（查看、评论、编辑和管理多维表格）。该权限属免审权限，开通即生效。

3. **发布应用版本**。要在多维表格的「添加文档应用」里搜到该应用，必须有已发布的版本，且同时满足：
   - 已开启**机器人能力**（应用管理 → 添加应用能力 → 机器人）；
   - 发布版本的**可用范围**包含多维表格的所有者。

4. 打开多维表格 → 右上角 `⋯` → `更多` → **添加文档应用** → 搜索该应用 → 权限设为 **可编辑**。
   ⚠️ 只给「可阅读」时，读接口正常但写入会返回 `403 / 91403 Forbidden`。

5. 在 `.env` 中填写表格标识与列名映射：

   ```ini
   FEISHU_BAN__APP_TOKEN=bascnxxxxxxxxxxxxxxxxxxxxxxxx
   FEISHU_BAN__TABLE_ID=tblxxxxxxxxxxxxxx
   FEISHU_BAN__FIELDS__UID=UID
   FEISHU_BAN__FIELDS__CATEGORY=类别
   FEISHU_BAN__FIELDS__NOTE=备注
   FEISHU_BAN__FIELDS__AUTO_OPERATOR=自动化处理人员
   ```

   列名留空则按内置别名自动探测，自动探测结果可用 `&banlog.fields` 查看。

   若表格在知识库中（链接含 `/wiki/`），需先用 `wiki/v2/spaces/get_node` 换取真实的 `app_token`（`obj_token`）。

#### 实现要点

- **凭证缓存**：`tenant_access_token` 在进程内缓存，提前 5 分钟刷新；遇到 `99991663` 会强制刷新并重试一次。
- **幂等写入**：每次新增记录生成 uuid4 作为 `client_token`，网络超时后的重试不会在表格中产生重复行。
- **列名不硬编码**：按别名自动匹配表格列名，`.env` 的 `FEISHU_BAN__FIELDS__*` 显式指定优先；配置了但表格中不存在的列、或必需字段映射到了只读列，都会被视为缺列并明确报错，不会静默写歪。
- **只读列保护**：公式、查找引用、创建/修改时间、关联字段等系统列在组装请求体时自动跳过。
- **错误翻译**：`91403`（未加为协作者）、`1254302`（高级权限未授权）、`1254018`（字段名不存在）等错误码会翻译成可操作的中文提示。

#### 封禁记录附加展示

当被查询账号处于**封禁状态**（`permission == -1`）时，以下位置会额外带上该 UID 在表格中的封禁记录：

| 位置 | 触发条件 | 发送到 |
|---|---|---|
| `&user` | 查询落到封禁账号 | 当前群（`&user` 本身仅限 `commspt_group` / `dev_group`） |
| 主群入群审批通知 | 申请所填 UID 对应账号被封禁 | `commspt_group` |

茶馆群入群审批、新成员欢迎通知（发往 `notification_channel`）**不展示**封禁记录。

展示格式：

```
📋 UID 43228 在封禁记录表中有 2 条记录：
· 类别：昵称、角色名 / 备注：批量违规 / 处理人：841968078 / 时间：2026-10-17 20:15
· 类别：账户异常 / 备注：批量上传材质 / 处理人：841968078 / 时间：2026-10-16 11:02
```

最多展示 5 条，超出部分只提示总数。该信息属于**附加内容**：飞书接口异常、表格未配置或缺少 UID 列时一律静默跳过，绝不影响 `&user` 出图或入群审批本身。

<a id="join-approval"></a>

### 入群审批

当入群申请无法自动处理（答案为非纯数字、UID 不存在、Admin API 查询失败等）时，机器人会把申请详情发到管理群（主群 → `commspt_group`，茶馆群 → `littleskin_cafe`），并为该通知消息贴上 👍 / 👎 引导表情，供管理员审批。管理员有两种等价的操作方式，二者共用同一执行核心，同一条申请只会被处理一次：

1. **文字命令**：回复该通知消息，发送 `do accept` 或 `do reject [原因]`（裸命令，不受全局前缀影响）。
2. **表情回应**：直接对该通知消息贴 👍（批准）或 👎（拒绝）。仅发起审批的管理员本人、且在允许的群聊内有效；Bot 自身贴表情不会触发。

表情审批的处理要点：

- 凭证按 `message_id` 登记，**弹出即消费**，确保每条申请只被处理一次；凭证默认保留 24 小时，期间惰性清理过期条目。
- 单表情直接判定意图；多种表情并存时调用 `get_msg_emoji_likes` 复核操作者本人贴的表情，查询失败时按 fail-closed 处理（不审批、保留凭证供重试）。
- 审批结果在群内 @ 操作管理员播报；成功时撤销通知消息上的 👍/👎 引导表情，执行出错则保留凭证便于重试。
- 协议端不支持 `set_msg_emoji_like` / `group_msg_emoji_like` 时静默降级，不影响 `do` 命令审批。

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
群白名单、管理员权限、业务逻辑直连测试（禁言 / 撤回 / 全员禁言的 API 调用参数）。此外：

- `tests/test_join_action.py`：入群审批公共执行核心（`execute_join_action` 的批准/拒绝参数、异常归类），
  以及表情审批凭证索引（`remember_approval` / `pop_approval` 的弹出即消费、过期清理等）的单元测试。
- `tests/test_user_info_card.py`：用户信息卡的数据模型与渲染相关测试。

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
| 审批通知表情回应 | 原生 `on_notice` + `set_msg_emoji_like` / `get_msg_emoji_likes` | OneBot V11（需协议端支持 `group_msg_emoji_like`） |

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
| 无（NoneBot 新增） | 审批通知表情回应：`on_notice` + `set_msg_emoji_like` / `get_msg_emoji_likes` |
| 原生命令（`on_command` 语义） | `on_message(rule=native_command_rule(...))`（基于 `get_plaintext`，兼容 `&` 前缀）+ `extract_command_args` |
| `S_ = Setting(**yaml.safe_load(...))` | `S_ = get_plugin_config(Setting)`（值来自 `.env`）+ `C_`（列表值来自 `config.yml`） |

原版 `log_file.py`（实验性）以占位形式保留为 `commspt_log_file.py`。
