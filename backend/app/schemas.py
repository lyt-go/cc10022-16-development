"""通用接口契约；模块字段由领域服务持有，不再为每个模块复制一份模型类。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class ActionPayload(BaseModel):
    action: str
    remark: str | None = None


class ConvertPayload(BaseModel):
    """批量标准码转换请求：记录列表 + 可选清洗规则与分区设置。"""
    entity_model: str
    records: list[dict[str, Any]] = Field(default_factory=list)
    rule_id: int | None = None
    partition_field: str = "区域"
    record_key_field: str = "记录编号"


class ResolvePayload(BaseModel):
    """单条参考数据解析请求：按类别把原编码解析为标准码。"""
    category: str
    code: Any = None


class ResolveBatchPayload(BaseModel):
    """批量参考数据解析请求：同一类别下多个原编码。"""
    category: str
    codes: list[Any] = Field(default_factory=list)


class RerunPayload(BaseModel):
    """原批次重跑请求：converted 用上次转换结果，source 用原始输入。"""
    input_mode: str = "converted"
