"""参考数据领域服务：标准编码入库、字典映射校验与参考版本管理。"""
from __future__ import annotations

import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class MdmReferenceService(BaseModuleService):
    MODULE = "mdm_reference"
    ENTITY = "参考数据"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["数据编号", "数据类别", "标准编码", "标准名称", "别名列表", "映射关系", "有效日期", "数据版本"]
    REQUIRED_FIELDS = ["数据编号", "数据类别", "标准编码"]
    STATUS_ORDER = ["草稿", "待校验", "已生效", "已废弃"]
    ACTION_RULES = {"提交校验": "待校验", "标记生效": "已生效", "标记废弃": "已废弃"}
    NEGATIVE_ACTIONS = []

    def import_reference_data(self, category: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
        """导入参考数据：将标准编码和字典值导入参考数据存储。

        读取标准编码字典数据，校验编码唯一性和数据类别匹配，
        导入参考数据到mdm_reference存储供字段标准化清洗使用。
        """
        rows = store.rows(self.MODULE)
        imported, skipped = 0, 0
        for entry_data in entries:
            code = entry_data.get("标准编码", "")
            # 编码唯一性只在类别内成立：城市 01 与卡种 01 是两本字典里的两条数据
            exists = any(
                r.get("数据类别") == category and r.get("标准编码") == code
                for r in rows
            )
            if exists:
                skipped += 1
                continue
            category_count = sum(1 for r in rows if r.get("数据类别") == category)
            ref_id = f"REF-{category}-{category_count + 1:04d}"
            ref_entry = {
                "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
                "数据编号": ref_id,
                "数据类别": category,
                "标准编码": code,
                "标准名称": entry_data.get("标准名称", ""),
                "别名列表": entry_data.get("别名列表", ""),
                "映射关系": entry_data.get("映射关系", ""),
                "有效日期": entry_data.get("有效日期", ""),
                "数据版本": "1.0",
                "status": "已生效",
                "pending": False,
                "abnormal": False,
            }
            rows.append(ref_entry)
            imported += 1
        # 导入参考数据：存储参考数据到mdm_reference供字段清洗使用
        return {"imported": imported, "skipped": skipped, "total": len(entries)}

    @staticmethod
    def _split_codes(value: Any) -> list[str]:
        """拆分别名/映射配置：兼容中英文逗号、分号和空白分隔。"""
        if not value:
            return []
        text = str(value)
        for sep in ("，", "；", ";", "\n", "\t"):
            text = text.replace(sep, ",")
        return [part.strip() for part in text.split(",") if part.strip()]

    @staticmethod
    def _active(row: dict[str, Any]) -> bool:
        """参考字典是否可用于转换：未显式标状态的历史数据按可用处理。"""
        return row.get("status") in (None, "", "已生效")

    def is_category_available(self, category: str) -> bool:
        """判断某个参考类别是否至少有一条可用字典数据。"""
        return any(
            row.get("数据类别") == category and self._active(row)
            for row in store.rows(self.MODULE)
        )

    def resolve_standard_code(self, category: str, raw_code: str) -> dict[str, Any]:
        """按数据类别把原始编码解析为标准编码（类别内唯一，不跨字典）。

        解析顺序固定为：标准编码 -> 别名 -> 映射关系。先认标准编码，
        保证同一输入重复执行时，已经转换出来的新码不会被另一条记录的
        旧别名再次改写。类别缺失或编码无命中时返回字典缺失原因。
        """
        raw = "" if raw_code is None else str(raw_code).strip()
        result: dict[str, Any] = {
            "ok": False,
            "category": category,
            "raw_code": raw_code,
            "standard_code": None,
            "standard_name": None,
            "matched_by": None,
            "status": "missing",
            "reason": None,
            "reference_id": None,
            "version": None,
            "dictionary_missing": False,
        }
        if not category:
            result["reason"] = "未关联参考类别"
            return result
        if not raw:
            result["reason"] = "原编码为空"
            return result

        refs = [
            row for row in store.rows(self.MODULE)
            if row.get("数据类别") == category and self._active(row)
        ]
        if not refs:
            # 字典缺失：该类别没有任何可用参考数据
            result["reason"] = f"参考类别「{category}」字典缺失"
            result["dictionary_missing"] = True
            return result

        # 1) 标准编码优先：已转换的新码直接认定为标准码，不再走别名
        for row in refs:
            if str(row.get("标准编码", "")).strip() == raw:
                result.update({
                    "ok": True,
                    "standard_code": row.get("标准编码"),
                    "standard_name": row.get("标准名称"),
                    "matched_by": "standard",
                    "status": "already_standard",
                    "reason": None,
                    "reference_id": row.get("数据编号"),
                    "version": row.get("数据版本"),
                })
                # 解析标准编码：命中本类别标准码，保持原值不做二次改写
                return result

        # 2) 别名列表：兼容一个编码对应多个旧称
        alias_hits: list[dict[str, Any]] = []
        for row in refs:
            if raw in self._split_codes(row.get("别名列表", "")):
                alias_hits.append(row)
        if alias_hits:
            distinct = {str(row.get("标准编码", "")).strip() for row in alias_hits}
            if len(distinct) > 1:
                result["reason"] = f"参考类别「{category}」下别名「{raw}」指向多个标准编码"
                result["status"] = "conflict"
                return result
            row = alias_hits[0]
            result.update({
                "ok": True,
                "standard_code": row.get("标准编码"),
                "standard_name": row.get("标准名称"),
                "matched_by": "alias",
                "status": "converted",
                "reason": None,
                "reference_id": row.get("数据编号"),
                "version": row.get("数据版本"),
            })
            # 解析别名：按类别命中旧别名并改写为标准编码
            return result

        # 3) 映射关系：支持 old->new、old:new 以及裸编码三种写法
        mapping_hits: list[tuple[dict[str, Any], str]] = []
        for row in refs:
            for mapping in self._split_codes(row.get("映射关系", "")):
                if "->" in mapping:
                    source, target = mapping.split("->", 1)
                elif ":" in mapping:
                    source, target = mapping.split(":", 1)
                else:
                    source, target = mapping, str(row.get("标准编码", ""))
                if source.strip() == raw:
                    mapping_hits.append((row, target.strip()))
        if mapping_hits:
            if len({target for _, target in mapping_hits}) > 1:
                result["reason"] = f"参考类别「{category}」下映射编码「{raw}」指向多个标准编码"
                result["status"] = "conflict"
                return result
            row, target = mapping_hits[0]
            target_row = next(
                (r for r in refs if str(r.get("标准编码", "")).strip() == target),
                row,
            )
            result.update({
                "ok": True,
                "standard_code": target_row.get("标准编码"),
                "standard_name": target_row.get("标准名称"),
                "matched_by": "mapping",
                "status": "converted",
                "reason": None,
                "reference_id": row.get("数据编号"),
                "version": row.get("数据版本"),
            })
            # 解析映射关系：按类别把旧映射编码指向标准编码
            return result

        result["reason"] = f"参考类别「{category}」中未找到编码「{raw}」"
        return result

    def batch_resolve_standard_codes(self, category: str,
                                      codes: list[Any]) -> list[dict[str, Any]]:
        """批量按类别解析标准码：逐个编码输出原编码与映射结果。"""
        return [self.resolve_standard_code(category, code) for code in codes]

    def lookup_reference_value(self, category: str, code: str) -> dict[str, Any] | None:
        """查询参考数据：按数据类别和标准编码查找标准名称。

        查询参考数据存储，按标准编码检索对应数据类别的
        标准名称、别名和映射关系，用于字段标准化转换。
        """
        rows = store.rows(self.MODULE)
        for row in rows:
            if not self._active(row):
                continue
            if row.get("数据类别") == category and (
                row.get("标准编码") == code or
                code in self._split_codes(row.get("别名列表", ""))
            ):
                # 查询参考数据：按编码查找标准名称和映射关系
                return {
                    "standard_code": row.get("标准编码"),
                    "standard_name": row.get("标准名称"),
                    "aliases": self._split_codes(row.get("别名列表", "")),
                    "mappings": self._split_codes(row.get("映射关系", "")),
                    "version": row.get("数据版本"),
                }
        return None

    def validate_reference_uniqueness(self, category: str) -> dict[str, Any]:
        """校验参考数据的编码唯一性：检查同类别下是否有重复标准编码。

        读取mdm_reference存储，按数据类别分组检查标准编码
        是否唯一，输出重复编码列表和校验报告。
        """
        rows = store.rows(self.MODULE)
        cat_rows = [r for r in rows if r.get("数据类别") == category]
        seen: dict[str, list[str]] = {}
        for row in cat_rows:
            code = row.get("标准编码", "")
            if code not in seen:
                seen[code] = []
            seen[code].append(row.get("数据编号", ""))
        duplicates = {k: v for k, v in seen.items() if len(v) > 1}
        # 校验参考数据唯一性：检测同类别下重复编码
        return {
            "category": category,
            "total": len(cat_rows),
            "unique_codes": len(seen),
            "duplicate_codes": len(duplicates),
            "duplicates": duplicates,
            "unique_pct": round((len(seen) - len(duplicates)) / max(len(seen), 1) * 100, 2),
        }

    def query_reference_by_category(self, category: str) -> list[dict[str, Any]]:
        """查询指定数据类别的所有已生效参考数据。

        遍历参考数据存储，筛选已生效且匹配数据类别的记录，
        按标准编码排序返回参考数据列表。
        """
        rows = store.rows(self.MODULE)
        refs = [
            row for row in rows
            if row.get("数据类别") == category and row.get("status") == "已生效"
        ]
        # 查询参考数据：按数据类别和编码排序
        refs.sort(key=lambda r: r.get("标准编码", ""))
        return refs

    def merge_reference_versions(self, category: str, old_version: str,
                                   new_version: str) -> dict[str, Any]:
        """归并参考数据版本：将旧版本参考数据迁移到新版本。

        读取参考数据存储，将指定类别的旧版本数据归并到
        新版本，更新数据版本号并归档旧版本记录。
        """
        rows = store.rows(self.MODULE)
        migrated = 0
        for row in rows:
            if row.get("数据类别") == category and row.get("数据版本") == old_version:
                row["数据版本"] = new_version
                row["version_migrated_at"] = datetime.datetime.utcnow().isoformat()
                migrated += 1
        # 归并参考数据版本：将旧版本归档并迁移到新版本
        return {"category": category, "migrated_count": migrated, "from": old_version, "to": new_version}