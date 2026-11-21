"""字段清洗领域服务：标准化函数执行、修正字典匹配与字段完整性校验。"""
from __future__ import annotations

import copy
import datetime
import re
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class FieldCleanseService(BaseModuleService):
    MODULE = "field_cleanse"
    ENTITY = "清洗规则"
    OPERATION_TERM = "清洗"
    LIST_FIELDS = ["规则编号", "实体模型", "目标字段", "参考类别", "标准化函数", "修正字典", "异常处理", "先后顺序", "规则版本"]
    REQUIRED_FIELDS = ["规则编号", "实体模型", "目标字段"]
    STATUS_ORDER = ["草稿", "待校验", "已生效", "已停用"]
    ACTION_RULES = {"提交校验": "待校验", "标记生效": "已生效", "停用规则": "已停用"}
    NEGATIVE_ACTIONS = ["停用规则"]

    # 转换批次、逐行改写明细和分区正式数据放在辅助表里：它们不是业务模块条目，
    # 不能混进 18 个模块的清单和概览统计。
    BATCH_TABLE = "field_cleanse_conversion_batches"
    DETAIL_TABLE = "field_cleanse_conversion_rows"
    FORMAL_TABLE = "field_cleanse_formal_records"

    STANDARD_FUNCTIONS: dict[str, Any] = {
        "trim": lambda v: v.strip() if isinstance(v, str) else v,
        "lower": lambda v: v.lower() if isinstance(v, str) else v,
        "upper": lambda v: v.upper() if isinstance(v, str) else v,
        "remove_spaces": lambda v: re.sub(r"\s+", "", v) if isinstance(v, str) else v,
        "format_phone": lambda v: re.sub(r"[^\d+]", "", v) if isinstance(v, str) else v,
        "format_id": lambda v: v.replace("-", "").replace(" ", "").upper() if isinstance(v, str) else v,
    }

    def cleanse_field_value(self, rule_id: int, raw_value: str) -> dict[str, Any]:
        """清洗字段值：按清洗规则执行标准化函数和修正字典映射。

        读取字段清洗规则，对原始字段值依次应用标准化函数和修正字典，
        校验清洗结果并返回清洗前值、清洗后值和采用的标准化函数。
        """
        rule = self.get_entry(rule_id)
        if not rule or rule.get("status") != "已生效":
            return {"ok": False, "reason": "清洗规则不可用", "raw": raw_value, "cleansed": raw_value}
        value = raw_value
        applied = []
        func_names = [f.strip() for f in str(rule.get("标准化函数") or "").split(",") if f.strip()]
        for func_name in func_names:
            if func_name in self.STANDARD_FUNCTIONS:
                value = self.STANDARD_FUNCTIONS[func_name](value)
                applied.append(func_name)
        # 清洗字段值：应用标准化函数和修正字典完成字段转换
        dict_entries = [
            d.strip() for d in str(rule.get("修正字典") or "").split(",")
            if ":" in d
        ]
        for entry in dict_entries:
            wrong, correct = entry.split(":", 1)
            if isinstance(value, str) and wrong.strip() in value:
                value = value.replace(wrong.strip(), correct.strip())
                applied.append(f"dict:{wrong.strip()}->{correct.strip()}")
        return {"ok": True, "raw": raw_value, "cleansed": value, "applied_functions": applied}

    def batch_cleanse_records(self, rule_id: int, records: list[dict[str, Any]],
                               target_field: str) -> list[dict[str, Any]]:
        """批量清洗记录指定字段：遍历记录列表对目标字段执行清洗规则。

        读取清洗规则，对传入记录列表逐条清洗目标字段值，
        校验字段完整性并标准化字段内容，返回清洗后的记录列表。
        """
        rule = self.get_entry(rule_id)
        if not rule:
            return records
        for record in records:
            if target_field in record:
                result = self.cleanse_field_value(rule_id, str(record[target_field]))
                if result["ok"]:
                    # 清洗目标字段：标准化字段值并更新记录
                    record[target_field] = result["cleansed"]
                    record["_cleansed_fields"] = record.get("_cleansed_fields", [])
                    record["_cleansed_fields"].append(target_field)
        return records

    def validate_field_completeness(self, entity_model: str, records: list[dict[str, Any]],
                                     required_fields: list[str]) -> dict[str, Any]:
        """验证字段完整性：检查清洗后每条记录的必填字段是否均已填充。

        遍历清洗后的记录列表，逐一验证必填字段完整性，
        统计完备率、缺失字段分布和异常记录列表。
        """
        total = len(records)
        complete = 0
        field_missing: dict[str, int] = {}
        incomplete_records: list[dict[str, Any]] = []
        for i, record in enumerate(records):
            missing = [f for f in required_fields if not str(record.get(f, "")).strip()]
            if missing:
                incomplete_records.append({"index": i, "missing_fields": missing})
                for f in missing:
                    field_missing[f] = field_missing.get(f, 0) + 1
            else:
                complete += 1
        # 验证字段完整性：统计完备率和缺失字段分布
        completeness = round(complete / max(total, 1) * 100, 2)
        return {
            "entity_model": entity_model,
            "total_records": total,
            "complete_records": complete,
            "completeness_pct": completeness,
            "field_missing_distribution": field_missing,
            "incomplete_detail": incomplete_records,
        }

    def query_cleanse_rules_for_model(self, entity_model: str) -> list[dict[str, Any]]:
        """查询指定实体模型的所有已生效清洗规则，按先后顺序排列。

        遍历清洗规则存储，筛选已生效且匹配实体模型的规则，
        按先后顺序字段排序返回清洗规则执行序列。
        """
        rows = store.rows(self.MODULE)
        rules = [
            row for row in rows
            if row.get("实体模型") == entity_model and row.get("status") == "已生效"
        ]
        # 查询清洗规则并按先后顺序排序
        rules.sort(key=lambda r: int(r.get("先后顺序", "0") or "0"))
        return rules

    def standardize_field_values(self, records: list[dict[str, Any]],
                                  entity_model: str) -> list[dict[str, Any]]:
        """标准化字段值：对实体模型的所有记录执行完整清洗流水线。

        查询该实体模型的所有清洗规则，按先后顺序依次对每条记录的
        各目标字段执行标准化函数和修正字典转换，完成全链路清洗。
        """
        rules = self.query_cleanse_rules_for_model(entity_model)
        for rule in rules:
            target_field = rule.get("目标字段", "")
            if not target_field:
                continue
            for record in records:
                if target_field in record:
                    result = self.cleanse_field_value(rule["id"], str(record[target_field]))
                    if result["ok"]:
                        # 标准化字段值：执行完整清洗流水线并更新记录
                        record[target_field] = result["cleansed"]
        return records

    # ── 参考数据标准码转换 ──────────────────────────────────────────

    def _reference_service(self):
        from app.services.mdm_reference import MdmReferenceService
        return MdmReferenceService()

    def _effective_conversion_rules(self, entity_model: str,
                                    rule_id: int | None = None) -> list[dict[str, Any]]:
        """挑出可参与标准码转换的规则：已生效、配了目标字段和参考类别。"""
        if rule_id is not None:
            rule = self.get_entry(rule_id)
            candidates = [rule] if rule else []
        else:
            candidates = self.query_cleanse_rules_for_model(entity_model)
        return [
            rule for rule in candidates
            if rule.get("status") == "已生效"
            and str(rule.get("目标字段", "") or "").strip()
            and str(rule.get("参考类别", "") or "").strip()
        ]

    def _missing_categories(self, rules: list[dict[str, Any]]) -> set[str]:
        """列出没有任何可用字典的参考类别，用于标记转换规则与分区。"""
        reference_svc = self._reference_service()
        missing: set[str] = set()
        for rule in rules:
            category = str(rule.get("参考类别", "")).strip()
            if category and not reference_svc.is_category_available(category):
                missing.add(category)
        return missing

    def _prepare_value(self, rule: dict[str, Any], raw_value: Any) -> str:
        """先执行标准化函数和修正字典，得到可交给参考字典的编码。"""
        result = self.cleanse_field_value(int(rule["id"]), "" if raw_value is None else str(raw_value))
        if result.get("ok"):
            return result.get("cleansed")
        return "" if raw_value is None else str(raw_value)

    def _run_pipeline(self, rules: list[dict[str, Any]],
                      records: list[dict[str, Any]],
                      partition_field: str,
                      record_key_field: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """对每条记录的每个转换字段产出逐行明细，并生成改写后的记录。"""
        reference_svc = self._reference_service()
        detail_rows: list[dict[str, Any]] = []
        converted_records: list[dict[str, Any]] = []
        for index, record in enumerate(records, start=1):
            partition = str(record.get(partition_field, "") or "未分区")
            record_key = str(record.get(record_key_field, "") or f"#{index}")
            rewritten = copy.deepcopy(record)
            for rule in rules:
                field = str(rule.get("目标字段", "")).strip()
                if field not in record:
                    continue
                category = str(rule.get("参考类别", "")).strip()
                raw_value = record.get(field)
                normalized = self._prepare_value(rule, raw_value)
                # 按类别解析：先认标准编码，再认别名/映射，重复执行不会二次改写
                resolution = reference_svc.resolve_standard_code(category, normalized)
                effective = bool(resolution.get("ok")) and resolution.get("standard_code") is not None
                row = {
                    "序号": index,
                    "分区": partition,
                    "记录键": record_key,
                    "字段": field,
                    "参考类别": category,
                    "原编码": raw_value,
                    "清洗后编码": normalized,
                    "标准编码": resolution.get("standard_code"),
                    "标准名称": resolution.get("standard_name"),
                    "命中方式": resolution.get("matched_by"),
                    "处理结果": resolution.get("status"),
                    "是否生效": effective,
                    "原因": resolution.get("reason"),
                    "参考数据编号": resolution.get("reference_id"),
                    "参考版本": resolution.get("version"),
                    "字典缺失": bool(resolution.get("dictionary_missing")),
                    "规则编号": rule.get("规则编号"),
                }
                detail_rows.append(row)
                if effective:
                    rewritten[field] = resolution.get("standard_code")
                    rewritten.setdefault("_standardized_fields", [])
                    if field not in rewritten["_standardized_fields"]:
                        rewritten["_standardized_fields"].append(field)
            converted_records.append(rewritten)
        return detail_rows, converted_records

    @staticmethod
    def _partition_summary(detail_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按分区汇总：统计转换结果并列出该分区可生效的标准编码。"""
        partitions: list[dict[str, Any]] = []
        for name in sorted({row["分区"] for row in detail_rows}):
            rows = [row for row in detail_rows if row["分区"] == name]
            failed = [row for row in rows if not row["是否生效"]]
            partitions.append({
                "分区": name,
                "明细行数": len(rows),
                "转换为标准码": sum(1 for r in rows if r["处理结果"] == "converted"),
                "已是标准码": sum(1 for r in rows if r["处理结果"] == "already_standard"),
                "转换失败": len(failed),
                "可生效编码": sorted({str(r["标准编码"]) for r in rows if r["是否生效"]}),
                "涉及字段": sorted({r["字段"] for r in rows}),
                # 字典缺失只标到具体类别：城市字典在、卡种字典缺失要能分辨
                "字典缺失类别": sorted({r["参考类别"] for r in failed if r.get("字典缺失")}),
            })
        return partitions

    def _batch_records(self) -> list[dict[str, Any]]:
        return store.aux_rows(self.BATCH_TABLE)

    def _detail_storage(self) -> list[dict[str, Any]]:
        return store.aux_rows(self.DETAIL_TABLE)

    def _formal_storage(self) -> list[dict[str, Any]]:
        return store.aux_rows(self.FORMAL_TABLE)

    def _new_batch_no(self, entity_model: str) -> str:
        seq = len(self._batch_records()) + 1
        stamp = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
        label = re.sub(r"[^0-9A-Za-z一-龥]", "", entity_model) or "BATCH"
        return f"CONV-{stamp}-{label}-{seq:04d}"

    def _write_formal_records(self, batch_no: str, run_no: int,
                              detail_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按分区落正式数据：同批次同记录同字段只保留最新一版，重复执行不叠行。"""
        formal = self._formal_storage()
        touched: list[dict[str, Any]] = []
        for row in detail_rows:
            if not row["是否生效"]:
                continue
            payload = {
                "批次号": batch_no,
                "运行次数": run_no,
                "分区": row["分区"],
                "记录键": row["记录键"],
                "字段": row["字段"],
                "参考类别": row["参考类别"],
                "标准编码": row["标准编码"],
                "标准名称": row["标准名称"],
                "原编码": row["原编码"],
                "参考数据编号": row["参考数据编号"],
                "参考版本": row["参考版本"],
            }
            current = next(
                (
                    item for item in formal
                    if item["批次号"] == batch_no
                    and item["记录键"] == row["记录键"]
                    and item["字段"] == row["字段"]
                    and item["参考类别"] == row["参考类别"]
                ),
                None,
            )
            if current is None:
                formal.append(payload)
                touched.append(payload)
            else:
                current.update(payload)
                touched.append(current)
        return touched

    def convert_batch(self, entity_model: str, records: list[dict[str, Any]], *,
                      rule_id: int | None = None,
                      partition_field: str = "区域",
                      record_key_field: str = "记录编号") -> dict[str, Any]:
        """批量标准码转换：字段标准化清洗规则关联参考类别，逐行改写并落正式数据。

        规则通过「参考类别」对齐参考数据管理中的同名类别，转换时先执行
        标准化函数与修正字典，再按类别解析标准码。每条记录、每个转换字段
        都形成一行改码明细，带字段、类别、原编码与映射结果；转换成功的记录
        按分区写入正式数据，供报送系统按分区接收。
        """
        if not records:
            return {"ok": False, "reason": "本次没有可转换的记录", "rows": [], "partitions": []}
        rules = self._effective_conversion_rules(entity_model, rule_id)
        if not rules:
            return {
                "ok": False,
                "reason": f"实体模型「{entity_model}」没有已生效且关联参考类别的清洗规则",
                "rows": [],
                "partitions": [],
            }
        reference_svc = self._reference_service()
        # 字典整体缺失时也要逐行留痕：失败原因落在每一行上，而不是直接报错返回
        missing_categories = self._missing_categories(rules)

        detail_rows, converted_records = self._run_pipeline(
            rules, records, partition_field, record_key_field)
        partitions = self._partition_summary(detail_rows)
        for summary in partitions:
            summary["字典缺失"] = bool(summary["字典缺失类别"])

        batch_no = self._new_batch_no(entity_model)
        now = datetime.datetime.utcnow().isoformat()
        batch = {
            "id": max((int(row.get("id", 0)) for row in self._batch_records()), default=0) + 1,
            "批次号": batch_no,
            "运行次数": 1,
            "实体模型": entity_model,
            "分区字段": partition_field,
            "记录键字段": record_key_field,
            "规则明细": [
                {
                    "规则ID": rule.get("id"),
                    "规则编号": rule.get("规则编号"),
                    "字段": rule.get("目标字段"),
                    "参考类别": rule.get("参考类别"),
                    "字典缺失": str(rule.get("参考类别", "")).strip() in missing_categories,
                }
                for rule in rules
            ],
            "总记录数": len(records),
            "明细行数": len(detail_rows),
            "转换成功数": sum(1 for row in detail_rows if row["是否生效"]),
            "转换失败数": sum(1 for row in detail_rows if not row["是否生效"]),
            "分区": partitions,
            "状态": "已完成",
            "创建时间": now,
            "运行记录": [{
                "运行次数": 1,
                "时间": now,
                "转换成功数": sum(1 for row in detail_rows if row["是否生效"]),
                "转换失败数": sum(1 for row in detail_rows if not row["是否生效"]),
            }],
            "_source_records": copy.deepcopy(records),
            "_converted_records": copy.deepcopy(converted_records),
        }
        self._batch_records().append(batch)
        for row in detail_rows:
            row["批次号"] = batch_no
            row["运行次数"] = 1
        self._detail_storage().extend(detail_rows)
        formal = self._write_formal_records(batch_no, 1, detail_rows)
        return self._conversion_result(batch, detail_rows, formal, batch_no)

    def _conversion_result(self, batch: dict[str, Any], detail_rows: list[dict[str, Any]],
                           formal: list[dict[str, Any]], batch_no: str) -> dict[str, Any]:
        return {
            "ok": True,
            "batch_id": batch["id"],
            "batch_no": batch_no,
            "run_no": batch.get("运行次数", 1),
            "entity_model": batch.get("实体模型"),
            "partition_field": batch.get("分区字段"),
            "rules": copy.deepcopy(batch.get("规则明细", [])),
            "total": batch.get("总记录数"),
            "detail_count": len(detail_rows),
            "converted": batch.get("转换成功数", 0),
            "failed": batch.get("转换失败数", 0),
            "partitions": copy.deepcopy(batch.get("分区", [])),
            "rows": copy.deepcopy(detail_rows),
            "formal_records": copy.deepcopy(formal),
        }

    def query_conversion_batches(self, entity_model: str | None = None,
                                 rule_id: int | None = None) -> list[dict[str, Any]]:
        """查询标准码转换批次：不返回内部寄存的原始记录，避免响应体过大。"""
        rows = self._batch_records()
        if entity_model:
            rows = [row for row in rows if row.get("实体模型") == entity_model]
        if rule_id is not None:
            rows = [
                row for row in rows
                if any(int(item.get("规则ID", 0)) == rule_id for item in row.get("规则明细", []))
            ]
        return [
            {key: copy.deepcopy(value) for key, value in row.items() if not key.startswith("_")}
            for row in rows
        ]

    def _find_batch(self, batch_id: int) -> dict[str, Any] | None:
        return next(
            (row for row in self._batch_records() if int(row.get("id", 0)) == batch_id),
            None,
        )

    def query_conversion_detail(self, batch_id: int,
                                run_no: int | None = None) -> dict[str, Any]:
        """查询改码明细与正式数据：逐行核验到底用了哪一本字典。"""
        batch = self._find_batch(batch_id)
        if batch is None:
            return {"ok": False, "reason": "转换批次不存在", "rows": [], "partitions": []}
        latest = run_no or int(batch.get("运行次数", 1))
        rows = [
            copy.deepcopy(row) for row in self._detail_storage()
            if row.get("批次号") == batch["批次号"] and int(row.get("运行次数", 0)) == latest
        ]
        formal = [
            copy.deepcopy(row) for row in self._formal_storage()
            if row.get("批次号") == batch["批次号"]
        ]
        return {
            "ok": True,
            "batch_id": batch["id"],
            "batch_no": batch["批次号"],
            "run_no": latest,
            "run_count": batch.get("运行次数", 1),
            "runs": copy.deepcopy(batch.get("运行记录", [])),
            "entity_model": batch.get("实体模型"),
            "partition_field": batch.get("分区字段"),
            "rules": copy.deepcopy(batch.get("规则明细", [])),
            # 所选运行次数的统计由明细现算，历史运行和最新运行不会串数
            "total": batch.get("总记录数"),
            "detail_count": len(rows),
            "converted": sum(1 for row in rows if row["是否生效"]),
            "failed": sum(1 for row in rows if not row["是否生效"]),
            "partitions": self._partition_summary(rows),
            "rows": rows,
            "formal_records": formal,
        }

    def rerun_conversion_batch(self, batch_id: int, *,
                               input_mode: str = "converted") -> dict[str, Any]:
        """再操作一次原批次：同一批次号重跑，逐行核对改码明细与正式数据。

        默认把上次转换后的记录作为输入，验证解析器先认标准编码的约束：
        已经转成新码的值不会再被旧别名命中，明细应全部落到「已是标准码」，
        正式数据按同批次同记录同字段覆盖更新，不会产生重复行。
        """
        batch = self._find_batch(batch_id)
        if batch is None:
            return {"ok": False, "reason": "转换批次不存在", "rows": [], "partitions": []}
        if input_mode not in ("converted", "source"):
            return {"ok": False, "reason": "不支持的输入模式", "rows": [], "partitions": []}
        records = copy.deepcopy(
            batch.get("_converted_records" if input_mode == "converted" else "_source_records", [])
        )
        if not records:
            return {"ok": False, "reason": "原批次没有可重跑的记录", "rows": [], "partitions": []}
        rules = self._effective_conversion_rules(
            str(batch.get("实体模型", "")),
            int(batch["规则明细"][0]["规则ID"]) if len(batch.get("规则明细", [])) == 1 else None,
        )
        if not rules:
            return {"ok": False, "reason": "原批次关联的清洗规则已不可用",
                    "rows": [], "partitions": []}

        detail_rows, converted_records = self._run_pipeline(
            rules, records,
            str(batch.get("分区字段", "区域")),
            str(batch.get("记录键字段", "记录编号")),
        )
        run_no = int(batch.get("运行次数", 1)) + 1
        now = datetime.datetime.utcnow().isoformat()
        for row in detail_rows:
            row["批次号"] = batch["批次号"]
            row["运行次数"] = run_no
        self._detail_storage().extend(detail_rows)
        formal = self._write_formal_records(batch["批次号"], run_no, detail_rows)

        partitions = self._partition_summary(detail_rows)
        for summary in partitions:
            summary["字典缺失"] = bool(summary["字典缺失类别"])
        batch.update({
            "运行次数": run_no,
            "分区": partitions,
            "明细行数": len(detail_rows),
            "转换成功数": sum(1 for row in detail_rows if row["是否生效"]),
            "转换失败数": sum(1 for row in detail_rows if not row["是否生效"]),
            "状态": "已重跑",
            "更新时间": now,
            "_converted_records": copy.deepcopy(converted_records),
        })
        batch.setdefault("运行记录", []).append({
            "运行次数": run_no,
            "时间": now,
            "转换成功数": batch["转换成功数"],
            "转换失败数": batch["转换失败数"],
            "已是标准码": sum(1 for row in detail_rows if row["处理结果"] == "already_standard"),
        })
        return {
            "ok": True,
            "batch_id": batch["id"],
            "batch_no": batch["批次号"],
            "run_no": run_no,
            "input_mode": input_mode,
            "rules": copy.deepcopy(batch.get("规则明细", [])),
            "partitions": copy.deepcopy(partitions),
            "rows": copy.deepcopy(detail_rows),
            "formal_records": copy.deepcopy(formal),
            "all_already_standard": all(
                row["处理结果"] == "already_standard" for row in detail_rows),
        }

    def deliver_conversion_partitions(self, batch_id: int) -> dict[str, Any]:
        """按分区交付：报送系统按分区接收，只下发转换成功且可生效的标准码。"""
        batch = self._find_batch(batch_id)
        if batch is None:
            return {"ok": False, "reason": "转换批次不存在", "partitions": []}
        formal = [
            row for row in self._formal_storage() if row.get("批次号") == batch["批次号"]
        ]
        latest = int(batch.get("运行次数", 1))
        details = [
            row for row in self._detail_storage()
            if row.get("批次号") == batch["批次号"] and int(row.get("运行次数", 0)) == latest
        ]
        handoff: list[dict[str, Any]] = []
        for summary in batch.get("分区", []):
            name = summary["分区"]
            accepted = [copy.deepcopy(row) for row in formal if row["分区"] == name]
            rejected = [
                {
                    "记录键": row["记录键"],
                    "字段": row["字段"],
                    "参考类别": row["参考类别"],
                    "原编码": row["原编码"],
                    "原因": row["原因"],
                }
                for row in details
                if row["分区"] == name and not row["是否生效"]
            ]
            handoff.append({
                "分区": name,
                "接收记录数": len(accepted),
                "可生效编码": sorted({row["标准编码"] for row in accepted}),
                "字典缺失": summary.get("字典缺失", False),
                "records": accepted,
                "rejected": rejected,
            })
        return {
            "ok": True,
            "batch_no": batch["批次号"],
            "run_no": latest,
            "entity_model": batch.get("实体模型"),
            "partitions": handoff,
        }
