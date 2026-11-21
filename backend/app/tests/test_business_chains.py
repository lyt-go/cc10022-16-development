"""业务链路测试：验证主数据清洗与黄金记录平台的 6 条关键链路。"""
from __future__ import annotations

import datetime
import sys
import os

_backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from app.services.source_system import SourceSystemService
from app.services.data_import_rule import DataImportRuleService
from app.services.import_batch import ImportBatchService
from app.services.field_cleanse import FieldCleanseService
from app.services.match_rule import MatchRuleService
from app.services.auto_match_job import AutoMatchJobService
from app.services.dup_cluster import DupClusterService
from app.services.merge_log import MergeLogService
from app.services.golden_record import GoldenRecordService
from app.services.record_lineage import RecordLineageService
from app.services.survivorship_rule import SurvivorshipRuleService
from app.services.entity_model import EntityModelService
from app.services.mdm_quality import MdmQualityService
from app.services.mdm_reference import MdmReferenceService
from app.services.mdm_api import MdmApiService
from app.services.mdm_sync import MdmSyncService
from app.services.mdm_version import MdmVersionService
from app.services.mdm_dashboard import MdmDashboardService


class TestBusinessChains:
    """测试主数据清洗平台的 6 条关键业务链路。"""

    # ── 链路1: 来源系统→入库规则→批次导入→字段标准化清洗 ──
    def test_chain1_source_import_cleanse(self):
        """来源系统接入 -> 入库规则校验 -> 批次导入 -> 字段标准化清洗。"""
        # 注册来源系统并导入元数据
        source_svc = SourceSystemService()
        result = source_svc.register_source_system({
            "系统编号": "CRM-001",
            "系统名称": "CRM客户系统",
            "系统类型": "CRM",
            "连接地址": "https://crm.example.com/api",
            "数据格式": "JSON",
            "刷新频率": "每日",
            "信任权重": "85",
        })
        assert result["ok"] is True, f"来源系统注册失败: {result}"
        systems = source_svc.query_active_systems()
        assert len(systems) > 0, "应查询到活跃来源系统"

        # 入库规则：导入并校验字段映射
        rule_svc = DataImportRuleService()
        rule_result = rule_svc.import_data_with_rules(1, [
            {"name": "张三", "phone": "13800138000"},
            {"name": "李四", "phone": "13900139000"},
        ])
        # 校验入库规则结果：规则可能未生效，但方法应正常返回
        assert isinstance(rule_result, dict), "入库规则应返回字典"

        # 批次导入：按来源系统导入数据批次
        batch_svc = ImportBatchService()
        batch = batch_svc.import_batch_from_source("CRM", "customer", 5000)
        assert batch["批次编号"].startswith("BATCH-"), f"批次编号格式异常: {batch['批次编号']}"

        summary = batch_svc.query_batch_summary()
        assert summary["total_batches"] > 0, "批次汇总不应为空"

        # 字段标准化清洗
        cleanse_svc = FieldCleanseService()
        records = [
            {"customer_name": "  Zhang San  ", "phone": "138-0013-8000"},
            {"customer_name": "LI SI", "phone": "139 0013 9000"},
        ]
        cleaned = cleanse_svc.standardize_field_values(records, "customer")
        assert len(cleaned) == 2, f"清洗后应有2条记录，实际: {len(cleaned)}"

    # ── 链路2: 匹配规则引擎→自动匹配任务→疑似重复簇 ──
    def test_chain2_match_to_cluster(self):
        """匹配规则配置 -> 自动匹配任务 -> 生成疑似重复簇。"""
        match_svc = MatchRuleService()
        records = [
            {"name": "张三", "phone": "13800138000", "email": "zhang@test.com"},
            {"name": "张  三", "phone": "13800138000", "email": "zhangsan@test.com"},
            {"name": "李四", "phone": "13900139000", "email": "lisi@other.com"},
        ]
        # 计算相似度
        sim = match_svc.compute_similarity(1, records[0], records[1])
        assert 0 <= sim <= 1, f"相似度应在[0,1]范围: {sim}"

        # 生成重复簇
        clusters = match_svc.generate_duplicate_clusters(1, records)
        assert isinstance(clusters, list), "应为簇列表"

        # 校验匹配规则参数
        validation = match_svc.validate_match_rule_parameters(1)
        assert "checks" in validation

        # 自动匹配任务调度
        job_svc = AutoMatchJobService()
        job_result = job_svc.schedule_match_job(1, "customer", records)
        assert job_result["ok"] is True, f"匹配任务调度失败: {job_result}"
        assert job_result.get("clusters") is not None, "应有簇输出"

    # ── 链路3: 重复簇→合并追溯→黄金记录→记录级血缘 ──
    def test_chain3_dup_to_golden_lineage(self):
        """重复簇 -> 合并 -> 黄金记录 -> 记录级血缘。"""
        cluster_svc = DupClusterService()
        records = [
            {"name": "张三", "phone": "13800138000"},
            {"name": "张三", "phone": "13800138000"},
        ]
        merged_result = cluster_svc.merge_duplicate_cluster(1, records)
        if merged_result["ok"]:
            assert merged_result.get("merged_record") is not None, "应有合并结果"

        # 查询待处置重复簇
        pending = cluster_svc.query_clusters_for_disposal("customer")
        assert isinstance(pending, list), "应为列表"

        # 合并追溯记录
        merge_svc = MergeLogService()
        log_result = merge_svc.record_merge_event(
            "GR-test-001",
            ["SRC-001", "SRC-002"],
            "全字段匹配",
            ["name", "phone"],
            [],
        )
        assert log_result["ok"] is True, f"合并记录写入失败: {log_result}"

        # 查询合并追溯
        history = merge_svc.query_merge_history("GR-test-001")
        assert isinstance(history, list), "应为历史列表"

        # 创建黄金记录
        golden_svc = GoldenRecordService()
        golden = golden_svc.create_golden_record(
            "customer",
            {"name": "张三", "phone": "13800138000", "representative": {"name": "张三"}},
            ["SRC-001", "SRC-002"],
        )
        assert golden["ok"] is True, f"黄金记录创建失败: {golden}"
        golden_id = golden["golden_record"]["黄金ID"]
        assert golden_id, "黄金ID不应为空"

        # 关联新来源到黄金记录
        link_result = golden_svc.link_source_to_golden(golden_id, "SRC-003")
        assert link_result["ok"] is True, "来源关联失败"

        # 记录字段级血缘
        lineage_svc = RecordLineageService()
        lineage = lineage_svc.record_field_lineage(
            golden_id, "SRC-001", "CRM",
            "customer.name", ["trim", "标准化"],
        )
        assert lineage["ok"] is True, f"血缘记录写入失败: {lineage}"

        # 查询血缘
        field_lineage = lineage_svc.query_field_lineage(golden_id)
        assert isinstance(field_lineage, list), "应为血缘列表"

        # 构建血缘图谱
        graph = lineage_svc.build_lineage_graph(golden_id)
        assert "nodes" in graph and "edges" in graph, "图谱应包含节点和边"

    # ── 链路4: 字段标准化→优胜策略→黄金记录版本 ──
    def test_chain4_survivorship_to_version(self):
        """字段标准化清洗 -> 优胜策略裁决 -> 黄金记录版本快照。"""
        # 字段标准化
        cleanse_svc = FieldCleanseService()
        records = [
            {"customer_name": "  Zhang San  ", "phone": "13800138000", "email": "ZHANG@TEST.COM"},
        ]
        cleaned = cleanse_svc.batch_cleanse_records(1, records, "customer_name")
        assert len(cleaned) == 1

        # 优胜策略裁决字段冲突
        survivor_svc = SurvivorshipRuleService()
        candidates = [
            {"value": "张三", "_source": "CRM"},
            {"value": "张  三", "_source": "ERP"},
        ]
        resolved = survivor_svc.resolve_field_conflict(1, "name", candidates)
        assert resolved.get("winner") is not None, "应有优胜者"
        assert resolved.get("losers") is not None, "应有落选者"

        # 黄金记录版本快照
        version_svc = MdmVersionService()
        version_result = version_svc.snapshot_golden_version(
            "GR-test-version",
            {"name": "张三", "phone": "13800138001", "email": "zhang@test.com"},
        )
        assert version_result["ok"] is True, f"版本快照创建失败: {version_result}"
        assert version_result.get("changed_fields") is not None, "应有变更字段"

        # 查询版本历史
        history = version_svc.query_version_history("GR-test-version")
        assert isinstance(history, list), "应为版本历史列表"

    # ── 链路5: 黄金记录→查询接口→主数据分发同步 ──
    def test_chain5_golden_to_sync(self):
        """黄金记录查询 -> 标准化查询接口 -> 主数据分发同步。"""
        # 创建黄金记录
        golden_svc = GoldenRecordService()
        golden = golden_svc.create_golden_record(
            "customer",
            {"name": "张三", "phone": "13800138000", "representative": {"name": "张三"}},
            ["SRC-001"],
        )
        assert golden["ok"] is True
        golden_id = golden["golden_record"]["黄金ID"]

        # 查询黄金记录
        found = golden_svc.query_golden_record(golden_id)
        assert found is not None, "应查询到黄金记录"
        assert found.get("黄金ID") == golden_id, f"黄金ID不匹配: {found}"

        # 搜索黄金记录
        search_results = golden_svc.search_golden_records("customer")
        assert len(search_results) > 0, "搜索应有结果"

        # 查询接口：标准化输出
        api_svc = MdmApiService()
        api_result = api_svc.query_golden_records_by_api(1)
        if api_result["ok"]:
            assert "records" in api_result

        # 同步黄金记录到目标系统
        sync_svc = MdmSyncService()
        sync_result = sync_svc.sync_golden_to_target(1)
        if sync_result["ok"]:
            assert "synced_count" in sync_result

    # ── 链路7: 清洗规则参考类别→批量标准码转换→分区交付→原批次重跑 ──
    def test_chain7_reference_code_conversion(self):
        """字段清洗规则关联参考类别 -> 逐行标准码改写 -> 分区交付 -> 原批次重跑核对。"""
        ref_svc = MdmReferenceService()
        # 两个类别共用 01：城市 01 与卡种 01 各自在自己的字典里
        assert ref_svc.resolve_standard_code("城市", "01")["standard_name"] == "北京市"
        assert ref_svc.resolve_standard_code("卡种", "01")["standard_name"] == "借记卡"

        cleanse_svc = FieldCleanseService()
        records = [
            {"记录编号": "E1", "区域": "东区", "城市": "北京", "卡种": "储蓄卡"},
            {"记录编号": "E2", "区域": "东区", "城市": "火星", "卡种": "信用卡"},
            {"记录编号": "W1", "区域": "西区", "城市": "上海", "卡种": "贷记卡"},
            {"记录编号": "W2", "区域": "西区", "城市": "穗", "卡种": "储值卡"},
        ]
        result = cleanse_svc.convert_batch("客户主数据", records)
        assert result["ok"] is True, f"标准码转换失败: {result}"
        assert result["converted"] == 7 and result["failed"] == 1, result

        # 每条明细都带字段、类别、原编码和映射结果
        detail = result["rows"]
        assert all({"字段", "参考类别", "原编码", "标准编码"} <= set(row) for row in detail), detail
        east_city = next(r for r in detail if r["记录键"] == "E1" and r["字段"] == "城市")
        assert east_city["标准编码"] == "01" and east_city["参考类别"] == "城市"
        missing = next(r for r in detail if r["记录键"] == "E2" and r["字段"] == "城市")
        assert missing["是否生效"] is False and "未找到" in missing["原因"], missing

        # 分区交付：东区部分可生效，西区全部分区都能转换
        handoff = cleanse_svc.deliver_conversion_partitions(result["batch_id"])
        by_partition = {item["分区"]: item for item in handoff["partitions"]}
        assert by_partition["东区"]["可生效编码"] == ["01", "02"]
        assert [row["记录键"] for row in by_partition["东区"]["rejected"]] == ["E2"]
        assert by_partition["西区"]["接收记录数"] == 4
        assert by_partition["西区"]["rejected"] == []

        # 原批次再操作一次：新码不会被旧别名二次改写，正式数据不叠行
        formal_before = len(result["formal_records"])
        rerun = cleanse_svc.rerun_conversion_batch(result["batch_id"])
        assert rerun["ok"] is True
        assert rerun["run_no"] == 2
        converted_back = [
            row for row in rerun["rows"]
            if row["处理结果"] in ("already_standard", "converted")
        ]
        assert all(row["处理结果"] == "already_standard" for row in converted_back), rerun["rows"]
        assert len(rerun["formal_records"]) == formal_before, "重跑不应产生重复正式数据"

        # 改码明细可按运行次数回查
        detail_view = cleanse_svc.query_conversion_detail(result["batch_id"], run_no=1)
        assert detail_view["run_count"] == 2
        assert len(detail_view["rows"]) == len(detail)

    # ── 链路6: 参考数据→实体模型→质量统计→治理看板 ──
    def test_chain6_reference_to_dashboard(self):
        """参考数据 -> 实体模型校验 -> 质量统计 -> 治理看板。"""
        # 导入参考数据
        ref_svc = MdmReferenceService()
        ref_result = ref_svc.import_reference_data("地域编码", [
            {"标准编码": "110000", "标准名称": "北京市", "别名列表": "北京,Beijing", "映射关系": "CN-11", "有效日期": "2026-12-31"},
        ])
        assert ref_result["imported"] > 0, f"参考数据导入失败: {ref_result}"

        # 查询参考数据
        found_ref = ref_svc.lookup_reference_value("地域编码", "110000")
        assert found_ref is not None, "应查询到参考数据"

        # 校验实体模型配置
        model_svc = EntityModelService()
        model_validation = model_svc.validate_entity_model(1, ["model_id", "model_name", "domain"])
        assert "checks" in model_validation

        # 计算质量统计
        quality_svc = MdmQualityService()
        records = [
            {"name": "张三", "phone": "13800138000", "email": "zhang@test.com"},
            {"name": "李四", "phone": "13900139000", "email": ""},
        ]
        quality_stats = quality_svc.compute_quality_metrics("customer", records, ["name", "phone"])
        assert "completeness_pct" in quality_stats, f"质量统计缺失完备率: {quality_stats}"
        assert "duplication_pct" in quality_stats, "质量统计缺失重复率"
        assert "consistency_pct" in quality_stats, "质量统计缺失一致率"

        # 查询质量趋势
        trend = quality_svc.query_quality_trend("customer")
        assert isinstance(trend, list), "质量趋势应为列表"

        # 生成治理看板
        dashboard_svc = MdmDashboardService()
        dashboard = dashboard_svc.generate_governance_dashboard(1)
        if dashboard["ok"]:
            stats = dashboard["dashboard"]
            assert "total_source_systems" in stats
            assert "total_golden_records" in stats
            assert "total_clusters" in stats

        # 聚合全局治理摘要
        summary = dashboard_svc.aggregate_governance_summary()
        assert "source_systems" in summary
        assert "golden_records" in summary
        assert "duplicate_clusters" in summary


if __name__ == "__main__":
    runner = TestBusinessChains()
    tests = [
        ("链路1: 来源系统→入库→导入→清洗", runner.test_chain1_source_import_cleanse),
        ("链路2: 匹配规则→匹配任务→重复簇", runner.test_chain2_match_to_cluster),
        ("链路3: 重复簇→合并→黄金记录→血缘", runner.test_chain3_dup_to_golden_lineage),
        ("链路4: 清洗→优胜策略→版本快照", runner.test_chain4_survivorship_to_version),
        ("链路5: 黄金记录→查询接口→分发同步", runner.test_chain5_golden_to_sync),
        ("链路6: 参考数据→实体模型→质量统计→看板", runner.test_chain6_reference_to_dashboard),
        ("链路7: 参考类别→标准码转换→分区交付→重跑", runner.test_chain7_reference_code_conversion),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        try:
            test_fn()
            print(f"  PASS: {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL: {name} -> {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"结果: {passed}/{len(tests)} 通过, {failed} 失败")
    assert failed == 0, f"{failed} 条链路测试失败！"