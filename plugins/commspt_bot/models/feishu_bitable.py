"""飞书多维表格（Bitable）客户端。

把封禁记录写入多维表格，仅依赖自建应用的 ``tenant_access_token``。
"""

from __future__ import annotations

import time
import uuid
from typing import Any, cast

import httpx
from nonebot import logger
from pydantic import BaseModel

from plugins.commspt_bot.config import S_, VERIFY_CONTENT
from plugins.commspt_bot.utils.retry import call_with_retry

FEISHU_BASE_URL = "https://open.feishu.cn/open-apis"
"""飞书开放平台 API 根地址。"""

TOKEN_REFRESH_MARGIN = 300
"""提前刷新 tenant_access_token 的秒数。"""

FIELD_MAX_PAGES = 10
"""列出字段时的最大翻页数，防止异常分页信息导致死循环。"""

SEARCH_MAX_PAGES = 20
"""检索记录时的最大翻页数，防止异常分页信息导致死循环。"""

FIELD_TYPE_TEXT = 1
FIELD_TYPE_NUMBER = 2
FIELD_TYPE_SINGLE_SELECT = 3
FIELD_TYPE_MULTI_SELECT = 4
FIELD_TYPE_DATE = 5
FIELD_TYPE_CHECKBOX = 7
FIELD_TYPE_PERSON = 11
FIELD_TYPE_PHONE = 13
FIELD_TYPE_URL = 15
FIELD_TYPE_ATTACHMENT = 17
FIELD_TYPE_SINGLE_LINK = 18
FIELD_TYPE_LOOKUP = 19
FIELD_TYPE_FORMULA = 20
FIELD_TYPE_DUPLEX_LINK = 21
FIELD_TYPE_LOCATION = 22
FIELD_TYPE_GROUP_CHAT = 23
FIELD_TYPE_CREATED_TIME = 1001
FIELD_TYPE_MODIFIED_TIME = 1002
FIELD_TYPE_CREATED_USER = 1003
FIELD_TYPE_MODIFIED_USER = 1004
FIELD_TYPE_AUTO_NUMBER = 1005

# 由飞书自动维护，写入时必须跳过，否则接口报错
READONLY_FIELD_TYPES = frozenset(
    {
        FIELD_TYPE_LOOKUP,
        FIELD_TYPE_FORMULA,
        FIELD_TYPE_SINGLE_LINK,
        FIELD_TYPE_DUPLEX_LINK,
        FIELD_TYPE_CREATED_TIME,
        FIELD_TYPE_MODIFIED_TIME,
        FIELD_TYPE_CREATED_USER,
        FIELD_TYPE_MODIFIED_USER,
        FIELD_TYPE_AUTO_NUMBER,
    }
)

FIELD_TYPE_NAMES = {
    FIELD_TYPE_TEXT: "文本",
    FIELD_TYPE_NUMBER: "数字",
    FIELD_TYPE_SINGLE_SELECT: "单选",
    FIELD_TYPE_MULTI_SELECT: "多选",
    FIELD_TYPE_DATE: "日期",
    FIELD_TYPE_CHECKBOX: "复选框",
    FIELD_TYPE_PERSON: "人员",
    FIELD_TYPE_PHONE: "电话",
    FIELD_TYPE_URL: "超链接",
    FIELD_TYPE_ATTACHMENT: "附件",
    FIELD_TYPE_SINGLE_LINK: "单向关联",
    FIELD_TYPE_LOOKUP: "查找引用",
    FIELD_TYPE_FORMULA: "公式",
    FIELD_TYPE_DUPLEX_LINK: "双向关联",
    FIELD_TYPE_LOCATION: "地理位置",
    FIELD_TYPE_GROUP_CHAT: "群组",
    FIELD_TYPE_CREATED_TIME: "创建时间",
    FIELD_TYPE_MODIFIED_TIME: "修改时间",
    FIELD_TYPE_CREATED_USER: "创建人",
    FIELD_TYPE_MODIFIED_USER: "修改人",
    FIELD_TYPE_AUTO_NUMBER: "自动编号",
}

_ERROR_HINTS = {
    99991663: "tenant_access_token 已失效，请检查 App ID / App Secret 是否正确",
    99991672: "应用未开通所需权限，请到开放平台为应用添加 bitable:app 并发布版本",
    91403: "应用未被添加为多维表格协作者：请打开表格 ⋯ → 更多 → 添加文档应用，并授予可编辑",
    1254302: "多维表格开启了高级权限：需在高级权限设置中新建含该应用的群组并授予读写",
    1254301: "多维表格未开启高级权限或该表不支持高级权限",
    1254018: "字段名不存在或传入的筛选字段有误，请核对表格列名",
    1254064: "日期字段的值格式不正确，需写入毫秒级时间戳",
    1254045: "字段值类型与列类型不匹配，请检查列类型（数字/文本/日期/单选/多选）",
    1254060: "多选字段的值必须是数组形式",
}

_token_cache: dict[str, Any] = {"token": "", "expire_at": 0.0}


class FeishuAPIError(RuntimeError):
    """飞书接口返回非 0 code 时抛出的异常。"""

    def __init__(self, code: int, msg: str, hint: str = ""):
        self.code = code
        self.msg = msg
        self.hint = hint or _ERROR_HINTS.get(code, "")
        detail = f"飞书接口错误 code={code} msg={msg}"
        if self.hint:
            detail = f"{detail}（{self.hint}）"
        super().__init__(detail)


class FeishuField(BaseModel):
    """多维表格的一个字段（列）。"""

    field_id: str
    field_name: str
    type: int = FIELD_TYPE_TEXT
    ui_type: str = ""
    options: list[str] = []

    @property
    def type_name(self) -> str:
        """字段类型的中文名称。"""
        return FIELD_TYPE_NAMES.get(self.type, f"未知({self.type})")

    @property
    def readonly(self) -> bool:
        """是否为只读字段。"""
        return self.type in READONLY_FIELD_TYPES


def _api_error_from(response: httpx.Response) -> FeishuAPIError:
    """把飞书错误响应解析为 FeishuAPIError。"""
    try:
        payload = response.json()
    except Exception:
        return FeishuAPIError(-1, f"HTTP {response.status_code} {response.text[:200]}")
    return FeishuAPIError(int(payload.get("code", -1)), str(payload.get("msg", "")))


class FeishuBitable:
    """飞书多维表格客户端。"""

    def __init__(self, app_token: str, table_id: str):
        if not app_token or not table_id:
            raise ValueError("飞书多维表格配置缺失：请在 .env 中填写 FEISHU_BAN__APP_TOKEN 与 FEISHU_BAN__TABLE_ID")
        self.app_token = app_token
        self.table_id = table_id

    @staticmethod
    def _client() -> httpx.AsyncClient:
        """构造带统一超时与 TLS 配置的异步客户端。"""
        return httpx.AsyncClient(timeout=15.0, verify=VERIFY_CONTENT, follow_redirects=True)

    @staticmethod
    async def _get_token(force_refresh: bool = False) -> str:
        """获取 tenant_access_token（进程内缓存，提前 5 分钟刷新）。"""
        now = time.time()
        if not force_refresh and _token_cache["token"] and now < _token_cache["expire_at"]:
            return _token_cache["token"]

        app_id = S_.api_feishu.app_id
        app_secret = S_.api_feishu.app_secret
        if not app_id or not app_secret:
            raise FeishuAPIError(
                -1,
                "未配置飞书应用凭证",
                "请在 .env 中填写 API_FEISHU__APP_ID 与 API_FEISHU__APP_SECRET",
            )

        resp = cast(
            httpx.Response,
            await call_with_retry("飞书 API（获取凭证）", FeishuBitable._post_token, app_id, app_secret),
        )
        payload = resp.json()
        if int(payload.get("code", -1)) != 0 or resp.status_code >= 400:
            # 凭证错误属于配置问题，重试无意义，直接抛出可读提示
            raise FeishuAPIError(
                int(payload.get("code", -1)),
                str(payload.get("msg", "")) or f"HTTP {resp.status_code}",
            )

        token = payload["tenant_access_token"]
        expire = int(payload.get("expire", 7200))
        _token_cache["token"] = token
        _token_cache["expire_at"] = now + max(60, expire - TOKEN_REFRESH_MARGIN)
        logger.debug(f"飞书 tenant_access_token 已刷新，有效期 {expire} 秒")
        return token

    @classmethod
    async def _send(cls, method: str, path: str, token: str, **kwargs) -> httpx.Response:
        """发送单次业务请求。

        5xx 以 ``HTTPStatusError`` 抛出，交由 ``call_with_retry`` 判定为瞬时故障重试；
        4xx 原样返回，由上层解析飞书业务错误码（这类错误重试无意义）。
        """
        async with cls._client() as client:
            resp = await client.request(
                method,
                f"{FEISHU_BASE_URL}{path}",
                headers={"Authorization": f"Bearer {token}"},
                **kwargs,
            )
        if resp.status_code >= 500:
            resp.raise_for_status()
        return resp

    @staticmethod
    async def _post_token(app_id: str, app_secret: str) -> httpx.Response:
        """请求 tenant_access_token，5xx 交由重试层处理。"""
        async with FeishuBitable._client() as client:
            resp = await client.post(
                f"{FEISHU_BASE_URL}/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
        if resp.status_code >= 500:
            resp.raise_for_status()
        return resp

    @classmethod
    async def _request(cls, method: str, path: str, **kwargs) -> dict[str, Any]:
        """发起带鉴权的请求。

        网络层失败（超时、连接错误、5xx）由 ``call_with_retry`` 按 ``FAILED_RETRY_TIME``
        重试；token 失效（99991663）时强制刷新后重跑一次。``kwargs`` 在进入重试前即已
        固化，因此写入请求的 ``client_token`` 在重试之间保持不变，不会产生重复记录。
        """
        for attempt in (1, 2):
            token = await cls._get_token(force_refresh=attempt == 2)
            resp = cast(
                httpx.Response,
                await call_with_retry("飞书 API", cls._send, method, path, token, **kwargs),
            )

            if resp.status_code >= 400:
                err = _api_error_from(resp)
                if err.code == 99991663 and attempt == 1:
                    logger.warning("飞书 token 失效，正在刷新后重试")
                    _token_cache["token"] = ""
                    continue
                raise err

            payload = resp.json()
            code = int(payload.get("code", -1))
            if code == 99991663 and attempt == 1:
                logger.warning("飞书 token 失效（响应体内），正在刷新后重试")
                _token_cache["token"] = ""
                continue
            if code != 0:
                raise FeishuAPIError(code, str(payload.get("msg", "")))
            return payload.get("data") or {}

        raise FeishuAPIError(99991663, "tenant_access_token 刷新后仍然无效")

    async def fetch_fields(self) -> list[FeishuField]:
        """列出数据表全部字段（含单选/多选的选项名称），自动翻页。"""
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        for _ in range(FIELD_MAX_PAGES):
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            data = await self._request(
                "GET",
                f"/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/fields",
                params=params,
            )
            items.extend(data.get("items") or [])
            page_token = data.get("page_token")
            if not data.get("has_more") or not page_token:
                break
        else:
            logger.warning(f"字段数超过 {FIELD_MAX_PAGES} 页上限，仅解析前 {len(items)} 个")

        result: list[FeishuField] = []
        for item in items:
            options = [
                str(opt.get("name", ""))
                for opt in ((item.get("property") or {}).get("options") or [])
                if opt.get("name")
            ]
            result.append(
                FeishuField(
                    field_id=str(item.get("field_id", "")),
                    field_name=str(item.get("field_name", "")),
                    type=int(item.get("type", FIELD_TYPE_TEXT)),
                    ui_type=str(item.get("ui_type") or ""),
                    options=options,
                )
            )
        return result

    @staticmethod
    def coerce_value(field: FeishuField, value: Any) -> Any:
        """按字段类型把 Python 值转换为飞书可接受的格式。"""
        if value is None:
            return None

        if field.type == FIELD_TYPE_DATE:
            if hasattr(value, "timestamp"):
                return int(value.timestamp() * 1000)
            numeric = float(value)
            # 小于 1e11 视为秒级时间戳
            return int(numeric * 1000) if numeric < 1e11 else int(numeric)

        if field.type == FIELD_TYPE_NUMBER:
            numeric = float(value)
            return int(numeric) if numeric.is_integer() else numeric

        if field.type == FIELD_TYPE_CHECKBOX:
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "是", "y")
            return bool(value)

        if field.type == FIELD_TYPE_MULTI_SELECT:
            items = list(value) if isinstance(value, (list, tuple)) else [value]
            return [str(item) for item in items]

        if field.type in (
            FIELD_TYPE_TEXT,
            FIELD_TYPE_SINGLE_SELECT,
            FIELD_TYPE_PHONE,
            FIELD_TYPE_URL,
        ):
            return str(value)

        return value

    @classmethod
    def build_fields(cls, fields: list[FeishuField], values: dict[str, Any]) -> dict[str, Any]:
        """组装新增记录的 ``fields`` 请求体，跳过空值与只读列。"""
        by_name = {f.field_name: f for f in fields}
        payload: dict[str, Any] = {}
        for name, value in values.items():
            if value is None or value == "":
                continue
            field = by_name.get(name)
            if field is None or field.readonly:
                continue
            payload[name] = cls.coerce_value(field, value)
        return payload

    async def create_record(self, fields: dict[str, Any]) -> str:
        """新增一条记录并返回 record_id（client_token 保证重试幂等）。"""
        if not fields:
            raise ValueError("没有可写入的字段：请检查配置中的字段映射是否与表格列名一致")
        data = await self._request(
            "POST",
            f"/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records",
            params={"client_token": str(uuid.uuid4())},
            json={"fields": fields},
        )
        record = data.get("record") or {}
        return str(record.get("record_id", ""))

    async def search_records(
        self,
        conditions: list[tuple[str, str]],
        logic: str = "or",
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """按 ``(列名, 值)`` 精确匹配检索记录，自动翻页。"""
        filter_conditions = [
            {"field_name": name, "operator": "is", "value": [str(value)]}
            for name, value in conditions
            if name and value != ""
        ]
        if not filter_conditions:
            return []

        body = {"filter": {"conjunction": logic, "conditions": filter_conditions}}
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        for _ in range(SEARCH_MAX_PAGES):
            params: dict[str, Any] = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            data = await self._request(
                "POST",
                f"/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records/search",
                params=params,
                json=body,
            )
            items.extend(data.get("items") or [])
            page_token = data.get("page_token")
            if not data.get("has_more") or not page_token:
                break
        else:
            logger.warning(f"检索结果超过 {SEARCH_MAX_PAGES} 页上限，仅返回前 {len(items)} 条")

        return items
