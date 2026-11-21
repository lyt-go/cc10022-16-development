"""统一资源接口：查询、导出、登记和动作按模块 key 分派到领域服务。"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.schemas import (
    ActionPayload,
    ActionResult,
    ConvertPayload,
    EntryPayload,
    PageResult,
    RerunPayload,
    ResolveBatchPayload,
    ResolvePayload,
)
from app.services import service_for
from app.services.field_cleanse import FieldCleanseService
from app.services.mdm_reference import MdmReferenceService

router = APIRouter(prefix="/api", tags=["业务资源"])


def require_service(module: str):
    service = service_for(module)
    if service is None:
        raise HTTPException(status_code=404, detail=f"未知业务模块：{module}")
    return service


@router.get("/{module}", response_model=PageResult[dict])
def list_entries(
    module: str,
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    service = require_service(module)
    filters = {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in service.LIST_FIELDS and value.strip()
    }
    items, total = service.list_entries(
        filters=filters, keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{module}/export")
def export_entries(
    module: str,
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> StreamingResponse:
    service = require_service(module)
    filters = {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in service.LIST_FIELDS and value.strip()
    }
    items, _ = service.list_entries(
        filters=filters, keyword=keyword, status=status, page=1, size=1_000_000)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", *service.LIST_FIELDS, "status"])
    for item in items:
        values = [item.get("id"), *(item.get(field, "") for field in service.LIST_FIELDS),
                  item.get("status", "")]
        writer.writerow([
            "'" + str(value) if str(value or "").startswith(("=", "+", "-", "@")) else value
            for value in values
        ])
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{module}.csv"'},
    )


@router.post("/field_cleanse/convert", response_model=dict)
def convert_batch(payload: ConvertPayload) -> dict[str, Any]:
    """批量标准码转换：按清洗规则的参考类别逐行改写并落按分区正式数据。"""
    service = FieldCleanseService()
    return service.convert_batch(
        payload.entity_model,
        payload.records,
        rule_id=payload.rule_id,
        partition_field=payload.partition_field,
        record_key_field=payload.record_key_field,
    )


@router.get("/field_cleanse/conversions", response_model=dict)
def list_conversions(entity_model: str | None = Query(default=None),
                     rule_id: int | None = Query(default=None)) -> dict[str, Any]:
    """查询标准码转换批次列表。"""
    service = FieldCleanseService()
    batches = service.query_conversion_batches(entity_model=entity_model, rule_id=rule_id)
    return {"items": batches, "total": len(batches)}


@router.get("/field_cleanse/conversions/{batch_id}", response_model=dict)
def get_conversion(batch_id: int, run_no: int | None = Query(default=None)) -> dict[str, Any]:
    """查询某次转换的逐行改码明细与正式数据。"""
    return FieldCleanseService().query_conversion_detail(batch_id, run_no=run_no)


@router.post("/field_cleanse/conversions/{batch_id}/rerun", response_model=dict)
def rerun_conversion(batch_id: int, payload: RerunPayload) -> dict[str, Any]:
    """再操作一次原批次：同一批次号重跑并核对改码明细与正式数据。"""
    return FieldCleanseService().rerun_conversion_batch(batch_id, input_mode=payload.input_mode)


@router.get("/field_cleanse/conversions/{batch_id}/delivery", response_model=dict)
def deliver_conversion(batch_id: int) -> dict[str, Any]:
    """按分区交付：报送系统逐分区接收可生效的标准码记录。"""
    return FieldCleanseService().deliver_conversion_partitions(batch_id)


@router.post("/mdm_reference/resolve", response_model=dict)
def resolve_reference(payload: ResolvePayload) -> dict[str, Any]:
    """按参考类别解析单个编码：标准码优先，其次别名与映射关系。"""
    return MdmReferenceService().resolve_standard_code(payload.category, payload.code)


@router.post("/mdm_reference/resolve/batch", response_model=dict)
def resolve_reference_batch(payload: ResolveBatchPayload) -> dict[str, Any]:
    """批量解析同一类别下的多个编码。"""
    results = MdmReferenceService().batch_resolve_standard_codes(payload.category, payload.codes)
    return {"category": payload.category, "items": results, "total": len(results)}


@router.get("/{module}/{entry_id}", response_model=dict)
def get_entry(module: str, entry_id: int) -> dict[str, Any]:
    service = require_service(module)
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"{service.ENTITY} {entry_id} 不存在或已归档")
    return entry


@router.post("/{module}", response_model=ActionResult)
def create_entry(module: str, payload: EntryPayload) -> ActionResult:
    service = require_service(module)
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message=f"{service.ENTITY}已登记", entry=entry)


@router.post("/{module}/{entry_id}/actions", response_model=ActionResult)
def run_action(module: str, entry_id: int, payload: ActionPayload) -> ActionResult:
    service = require_service(module)
    entry, message = service.run_action(entry_id, payload.action.strip())
    return ActionResult(ok=entry is not None, message=message, entry=entry)
