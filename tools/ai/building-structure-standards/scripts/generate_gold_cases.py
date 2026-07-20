from __future__ import annotations

import json
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = SKILL_ROOT / "references" / "gold_cases.json"


EXACT_CLAUSES = [
    ("1.1.1", "水冷反应堆"),
    ("1.1.2", "厂址特定设计参数"),
    ("1.1.3", "外部自然事件"),
    ("1.2.1", "新建和运行核动力厂"),
    ("1.2.2", "两个阶段"),
    ("1.2.3", "整个寿期内持续进行"),
    ("1.2.4", "非放射性影响评价"),
    ("2.1", "保护公众和环境"),
    ("2.2", "所有阶段"),
    ("2.3", "外部自然事件和人为事件"),
    ("2.4", "人口分布"),
    ("2.5.1", "选址安全分析报告"),
    ("2.5.3", "质量保证"),
    ("3.1.1", "相互影响"),
    ("3.1.2", "厂址特定参数"),
    ("3.2.1", "早期阶段"),
    ("3.2.2", "应急措施"),
    ("3.2.3", "厂址不适宜"),
    ("3.2.4", "类似的其他区域"),
    ("3.2.6", "冷却水"),
    ("3.3.4", "调查区域"),
    ("3.4.1", "筛选过程"),
    ("3.4.2", "低概率"),
    ("3.4.3", "事件组合"),
    ("3.5.3", "不确定性"),
    ("3.5.4", "确定论"),
    ("3.5.5", "概率危险性曲线"),
    ("3.6.2", "假想事故"),
    ("3.7.1", "运输和通讯网络"),
    ("3.7.3", "相邻或相近厂址"),
    ("3.8.2", "最终热阱"),
    ("3.9.2", "定期维护和审查"),
    ("4.1.1", "能动断层"),
    ("4.1.2", "设计基准地震"),
    ("4.3.1", "极端气象灾害"),
    ("4.4.1", "设计基准洪水"),
]

SEARCH_CASES = [
    ("飞机坠毁（非恶意撞击）", "4.8.4"),
    ("爆燃或爆炸的化学品", "4.8.5"),
    ("水母、鱼虾、浒苔", "4.5.2"),
    ("边坡失稳", "4.6.2"),
    ("大气弥散", "5.1.2"),
    ("地下水中迁移", "5.1.4"),
    ("学校、医院、疗养院和监狱", "5.2.2"),
    ("最新人口调查数据", "5.2.3"),
    ("食物链中生物栖息地", "5.3.2"),
    ("辐射环境本底", "5.4"),
    ("非地震原因引起的海啸和假潮", "4.4.2"),
    ("距离效应后以超压表示", "4.8.3"),
]

CATALOG_CASES = [
    ("GB/T 18314-2009", "废止"),
    ("GB/T 16311-2009", "废止"),
    ("GB/T 26941.1-2011", "废止"),
    ("2026JT0106", "内部文控待核验"),
    ("CP 05JT0101", "内部文控待核验"),
    ("23J909", "正版来源待核验"),
    ("NB/T 20401-2017", "现行"),
]

MISSING_CLAUSES = [
    ("GB 12955-2024", "6.1.1"),
    ("GB/T 14684-2022", "6.2.1"),
    ("NB/T 20401-2017", "5.1.1"),
    ("JGJ 63-2006", "3.1.1"),
    ("GB 50207-2012", "4.2.1"),
    ("HAF 101-2023", "9.9.9"),
    ("不存在标准-2026", "1.0.1"),
]

MISSING_CATALOG_CONTENT = [
    "22SG813",
    "1907JT0106",
    "CP 05JT0111",
]

ADVICE_CASES = [
    ("能动断层", ["HAF 101-2023"], "sufficient", []),
    (
        "设计基准地震动",
        ["HAF 101-2023", "GB/T 50011-2010"],
        "partial",
        ["GB/T 50011-2010"],
    ),
    (
        "厂址评价",
        ["HAF 101-2023", "NB/T 20401-2017"],
        "partial",
        ["NB/T 20401-2017"],
    ),
    (
        "混凝土用水",
        ["HAF 101-2023", "JGJ 63-2006"],
        "none",
        ["JGJ 63-2006"],
    ),
    (
        "洪水",
        ["HAF 101-2023", "JTG D 60-2015"],
        "partial",
        ["JTG D 60-2015"],
    ),
    (
        "人口分布",
        ["HAF 101-2023", "NB/T 20200-2013"],
        "partial",
        ["NB/T 20200-2013"],
    ),
]


def build_cases() -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for index, (clause_id, expected_text) in enumerate(EXACT_CLAUSES, start=1):
        cases.append(
            {
                "id": f"exact-{index:03d}",
                "category": "精确条款",
                "operation": "clause",
                "standard_code": "HAF 101-2023",
                "clause_id": clause_id,
                "expected": {
                    "found": True,
                    "contains": expected_text,
                    "citation_required": True,
                },
            }
        )
    for index, (query, clause_id) in enumerate(SEARCH_CASES, start=1):
        cases.append(
            {
                "id": f"search-{index:03d}",
                "category": "概念检索",
                "operation": "search",
                "query": query,
                "expected": {
                    "found": True,
                    "clause_id": clause_id,
                    "citation_required": True,
                },
            }
        )
    for index, (code, status) in enumerate(CATALOG_CASES, start=1):
        cases.append(
            {
                "id": f"status-{index:03d}",
                "category": "版本与废止状态",
                "operation": "catalog",
                "standard_code": code,
                "expected": {
                    "found": True,
                    "official_status": status,
                    "content_evidence_available": False,
                },
            }
        )
    cases.append(
        {
            "id": "status-008",
            "category": "版本与废止状态",
            "operation": "standard",
            "standard_code": "HAF 101-2023",
            "expected": {"found": True, "official_status": "现行"},
        }
    )
    for index, (code, clause_id) in enumerate(MISSING_CLAUSES, start=1):
        cases.append(
            {
                "id": f"insufficient-{index:03d}",
                "category": "证据不足",
                "operation": "clause",
                "standard_code": code,
                "clause_id": clause_id,
                "expected": {"found": False, "evidence_insufficient": True},
            }
        )
    for offset, code in enumerate(MISSING_CATALOG_CONTENT, start=8):
        cases.append(
            {
                "id": f"insufficient-{offset:03d}",
                "category": "证据不足",
                "operation": "catalog",
                "standard_code": code,
                "expected": {
                    "found": True,
                    "content_evidence_available": False,
                },
            }
        )
    for index, (query, codes, level, missing) in enumerate(ADVICE_CASES, start=1):
        cases.append(
            {
                "id": f"advice-{index:03d}",
                "category": "跨规范建议",
                "operation": "advice",
                "query": query,
                "requested_codes": codes,
                "expected": {
                    "evidence_level": level,
                    "missing_content_codes": missing,
                    "design_advice_allowed": level == "sufficient",
                },
            }
        )
    return cases


def main() -> int:
    cases = build_cases()
    if not 50 <= len(cases) <= 100:
        raise ValueError(f"gold case count must be 50-100, got {len(cases)}")
    payload = {
        "schema_version": 1,
        "description": (
            "第一版标准答案验证集；精确条款来自官方社会公开的 HAF 101-2023，"
            "其余类别验证版本状态、缺件和跨规范证据边界。"
        ),
        "case_count": len(cases),
        "cases": cases,
    }
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {len(cases)} cases to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
