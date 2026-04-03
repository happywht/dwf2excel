"""集成测试：用真实XLS物探成果表数据验证全流程

测试内容:
1. XLS物探成果表解析（3种格式）
2. 管径解析
3. 管种/材质/特征点标准化
4. 连接关系构建
5. PipelineEngine全流程
6. 数据导出
"""

import os
import sys
import json
import logging

# 设置路径以便直接运行
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 真实XLS文件路径
# ---------------------------------------------------------------------------
XLS_FILES = [
    r"D:/Work/2026/202604/dwg解析/基础数据/物探图纸/解压_temp/常和路成果报告/3、成果报告/管线点成果表.xls",
    r"D:/Work/2026/202604/dwg解析/基础数据/物探图纸/解压_temp/骊山路/骊山路（中山北路-延长西路）及道路交叉口工程地下综合管线探测/2.成果表-骊山路（中山北路-延长西路）及道路交叉口工程地下综合管线探测.xls",
    r"D:/Work/2026/202604/dwg解析/基础数据/物探图纸/解压_temp/祁连山南路物探/祁连山南路（苏州河区界—延川路）架空线入地和合杆整治工程地下管线探测成果表.xls",
]


def test_parse_diameter():
    """测试管径解析"""
    from core.xls_parser import parse_diameter

    test_cases = [
        ("300", "纯数字", 300.0),
        ("DN300", "DN", 300.0),
        ("DN800", "DN", 800.0),
        ("HDN1200", "HDN", 1200.0),
        ("16孔", "孔数", None),
        ("1孔 1根", "孔根", None),
        ("12孔 12根", "孔根", None),
        ("￠600X400", "套管", None),
        ("Φ200", "Φ", 200.0),
        ("De110", "De", 110.0),
        ("d300", "d", 300.0),
        ("", "", None),
        ("管径不详", "", None),
    ]

    logger.info("=" * 60)
    logger.info("测试1: 管径解析")
    logger.info("=" * 60)

    all_pass = True
    for raw, expected_type, expected_mm in test_cases:
        info = parse_diameter(raw)
        passed = info.diameter_type == expected_type
        if expected_mm is not None:
            passed = passed and info.diameter_mm == expected_mm
        if expected_type:
            passed = passed and info.is_valid

        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        logger.info(f"  [{status}] '{raw}' -> type={info.diameter_type}, "
                     f"mm={info.diameter_mm}, valid={info.is_valid}")

    return all_pass


def test_xls_parser():
    """测试XLS解析器（3个文件）"""
    from core.xls_parser import parse_xls_file

    logger.info("\n" + "=" * 60)
    logger.info("测试2: XLS解析器")
    logger.info("=" * 60)

    all_pass = True
    total_points = 0

    for xls_path in XLS_FILES:
        if not os.path.exists(xls_path):
            logger.warning(f"  文件不存在，跳过: {os.path.basename(xls_path)}")
            continue

        result = parse_xls_file(xls_path)
        basename = os.path.basename(xls_path)

        if result.error_message:
            logger.error(f"  [FAIL] {basename}: {result.error_message}")
            all_pass = False
            continue

        total_points += len(result.points)
        logger.info(f"  [OK] {basename}")
        logger.info(f"    管线点: {len(result.points)}")
        logger.info(f"    连接: {len(result.connections)}")
        logger.info(f"    耗时: {result.parse_time_ms:.0f}ms")
        logger.info(f"    管种分布: {result.stats.pipe_type_counts}")
        logger.info(f"    特征点分布: "
                     f"{dict(list(result.stats.feature_type_counts.items())[:5])}")
        logger.info(f"    管径范围: {result.stats.diameter_range}")
        logger.info(f"    埋深范围: {result.stats.depth_range}")
        logger.info(f"    坐标范围 X: {result.stats.coord_x_range}")
        logger.info(f"    坐标范围 Y: {result.stats.coord_y_range}")

        # 展示前3个点的详细信息
        for i, p in enumerate(result.points[:3]):
            logger.info(f"    样本点[{i}]: {p.point_id} | {p.pipe_type} | "
                         f"{p.feature_type} | {p.diameter_info.to_summary()} | "
                         f"X={p.coord_x} Y={p.coord_y} | 埋深={p.burial_depth}")

    logger.info(f"\n  总计解析管线点: {total_points}")
    return all_pass


def test_pipeline_engine():
    """测试PipelineEngine全流程"""
    from core.pipeline_engine import PipelineEngine

    logger.info("\n" + "=" * 60)
    logger.info("测试3: PipelineEngine全流程")
    logger.info("=" * 60)

    engine = PipelineEngine()

    # 批量导入
    existing_files = [f for f in XLS_FILES if os.path.exists(f)]
    if not existing_files:
        logger.warning("  没有可用的XLS文件，跳过")
        return True

    results = engine.import_xls_batch(existing_files)
    success_count = sum(1 for r in results if not r.error_message)

    logger.info(f"  导入结果: {success_count}/{len(existing_files)} 成功")
    logger.info(f"  总管线点: {len(engine.points)}")
    logger.info(f"  总连接: {len(engine.connections)}")

    # 统计
    stats = engine.compute_stats()
    logger.info(f"  全局统计:")
    logger.info(f"    管种分布: {stats.pipe_type_counts}")
    logger.info(f"    特征点分布: {dict(list(stats.feature_type_counts.items())[:8])}")
    logger.info(f"    材质分布: {stats.material_counts}")
    logger.info(f"    来源文件: {stats.source_file_counts}")

    # 数据校验
    issues = engine.validate()
    if issues:
        logger.info(f"  数据校验发现 {len(issues)} 个问题:")
        for issue in issues[:10]:
            logger.info(f"    - {issue}")
        if len(issues) > 10:
            logger.info(f"    ... 共 {len(issues)} 个")
    else:
        logger.info(f"  数据校验: 无问题")

    # 导出测试
    rows = engine.export_to_dicts()
    logger.info(f"  导出字典列表: {len(rows)} 行")

    # 按管种筛选
    for pipe_type in ["给水", "雨水", "污水", "供电"]:
        filtered = engine.query_by_pipe_type(pipe_type)
        logger.info(f"    {pipe_type}: {len(filtered)} 个点")

    # 导出DataFrame（如果pandas可用）
    try:
        df = engine.export_to_dataframe()
        logger.info(f"  导出DataFrame: {df.shape}")
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
        os.makedirs(output_dir, exist_ok=True)
        csv_path = os.path.join(output_dir, "管线数据导出.csv")
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        logger.info(f"  CSV已保存: {csv_path}")
    except ImportError:
        logger.warning("  pandas未安装，跳过DataFrame导出")

    return success_count == len(existing_files)


def test_standardization():
    """测试标准化映射"""
    from config.pipeline_config import (
        PIPE_TYPE_STANDARD_MAP,
        FEATURE_POINT_MAP,
        MATERIAL_MAP,
    )

    logger.info("\n" + "=" * 60)
    logger.info("测试4: 标准化映射")
    logger.info("=" * 60)

    # 管种标准化
    test_pipe_types = [
        ("上水", "给水"), ("给水", "给水"), ("自来水", "给水"),
        ("电力", "供电"), ("dl", "供电"), ("煤气", "燃气"),
        ("信息网络", "通信"), ("交通信号灯", "信号"),
    ]
    all_pass = True
    for raw, expected in test_pipe_types:
        result = PIPE_TYPE_STANDARD_MAP.get(raw, raw)
        if isinstance(result, str) and raw.lower() in PIPE_TYPE_STANDARD_MAP:
            result = PIPE_TYPE_STANDARD_MAP[raw.lower()]
        passed = result == expected or PIPE_TYPE_STANDARD_MAP.get(raw.lower(), raw) == expected
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        logger.info(f"  [{status}] 管种 '{raw}' -> '{result}' (期望: '{expected}')")

    # 特征点标准化
    test_features = [
        ("检查井", "窨井"), ("阀门", "阀门井"), ("雨篦", "雨水篦"),
        ("摄像头", "监控"), ("扪头", "管堵"), ("分线箱", "接线箱"),
    ]
    for raw, expected in test_features:
        result = FEATURE_POINT_MAP.get(raw, raw)
        passed = result == expected
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        logger.info(f"  [{status}] 特征点 '{raw}' -> '{result}' (期望: '{expected}')")

    # 材质标准化
    test_materials = [
        ("混凝土", "砼"), ("钢管", "钢"), ("pe", "PE"), ("光纤", "光缆"),
    ]
    for raw, expected in test_materials:
        result = MATERIAL_MAP.get(raw, raw)
        passed = result == expected
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        logger.info(f"  [{status}] 材质 '{raw}' -> '{result}' (期望: '{expected}')")

    return all_pass


def main():
    logger.info("开始集成测试\n")

    results = {}

    # 运行所有测试
    results["管径解析"] = test_parse_diameter()
    results["标准化映射"] = test_standardization()
    results["XLS解析器"] = test_xls_parser()
    results["PipelineEngine"] = test_pipeline_engine()

    # 汇总
    logger.info("\n" + "=" * 60)
    logger.info("测试结果汇总")
    logger.info("=" * 60)
    all_pass = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        logger.info(f"  [{status}] {name}")
        if not passed:
            all_pass = False

    logger.info(f"\n总结果: {'全部通过' if all_pass else '存在失败'}")
    return all_pass


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
