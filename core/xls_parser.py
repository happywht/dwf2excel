"""XLS物探成果表解析器

解析物探管线点成果表（XLS）文件，输出PipelineParseResult。

支持3种XLS格式（常和路/骊山路/祁连山南路）。
自动检测表头行，匹配列名，构建PipelinePoint和PipelineConnection对象。
解析管径，标准化管种/材质/特征点类型，构建连接关系。
"""

import os
import re
import time
import logging
from typing import Optional
from collections import defaultdict

import xlrd

from config.pipeline_config import (
    PIPE_TYPE_STANDARD_MAP,
    PIPE_CATEGORY_MAP,
    XLS_HEADER_DETECT_KEYWORDS,
    XLS_COLUMN_MAPPING,
    DIAMETER_PATTERNS,
    FEATURE_POINT_MAP,
    MATERIAL_MAP,
)
from core.models import (
    PipeSource,
    PipeStatus,
    DiameterInfo,
    PipelinePoint,
    PipelineConnection,
    PipelineStats,
    PipelineParseResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _safe_float(val) -> Optional[float]:
    """安全地转换为浮点数，失败返回None"""
    if val is None:
        return None
    try:
        f = float(val)
        return f
    except (ValueError, TypeError):
        return None


def _safe_int(val) -> Optional[int]:
    """安全地转换为整数，失败返回None"""
    if val is None:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _cell_str(cell_value) -> str:
    """将xlrd单元格值转为字符串，清理空白"""
    if cell_value is None:
        return ""
    s = str(cell_value).strip()
    # 清理特殊空白字符
    s = s.replace('\u00a0', ' ').replace('\u3000', ' ')
    return s


# ---------------------------------------------------------------------------
# 管径解析
# ---------------------------------------------------------------------------

def parse_diameter(raw_text: str) -> DiameterInfo:
    """解析管径原始文本为DiameterInfo结构化对象。

    优先级: 孔根 > 套管尺寸 > DN/De/Φ前缀+数字 > 纯数字mm > 孔数
    """
    info = DiameterInfo()
    raw = raw_text.strip() if raw_text else ""
    info.raw = raw

    if not raw:
        return info

    # 1. 孔+根（N孔 M根 格式）
    m = re.search(r'(\d+)\s*孔\s*(\d+)\s*根', raw)
    if m:
        info.hole_count = int(m.group(1))
        info.hole_used = int(m.group(2))
        info.cable_count = int(m.group(2))
        info.diameter_type = "孔根"
        info.is_valid = True
        return info

    # 2. 套管尺寸 (￠WxH 或 ΦWxH 格式)
    m = re.search(r'[Φφ￠]?\s*(\d+)\s*[Xx×]\s*(\d+)', raw)
    if m:
        info.casing_width = float(m.group(1))
        info.casing_height = float(m.group(2))
        info.diameter_type = "套管"
        info.is_valid = True
        return info

    # 3. DN/HDN前缀管径
    m = re.match(r'(?:HDN|DN)\s*(\d+)', raw, re.IGNORECASE)
    if m:
        info.diameter_mm = float(m.group(1))
        prefix = raw[:m.start(1)].strip().upper()
        info.diameter_type = prefix if prefix else "DN"
        info.is_valid = True
        return info

    # 4. De前缀管径
    m = re.match(r'[Dd][Ee]\s*(\d+)', raw)
    if m:
        info.diameter_mm = float(m.group(1))
        info.diameter_type = "De"
        info.is_valid = True
        return info

    # 5. Φ前缀管径（非套管格式）
    m = re.match(r'[Φφ]\s*(\d+)', raw)
    if m:
        info.diameter_mm = float(m.group(1))
        info.diameter_type = "Φ"
        info.is_valid = True
        return info

    # 6. 小写d前缀管径
    m = re.match(r'd\s*(\d{2,4})', raw)
    if m:
        info.diameter_mm = float(m.group(1))
        info.diameter_type = "d"
        info.is_valid = True
        return info

    # 7. 纯数字（管径mm）
    m = re.match(r'^(\d{2,5})$', raw)
    if m:
        info.diameter_mm = float(m.group(1))
        info.diameter_type = "纯数字"
        info.is_valid = True
        return info

    # 8. 孔数（N孔）
    m = re.search(r'(\d+)\s*孔', raw)
    if m:
        info.hole_count = int(m.group(1))
        info.diameter_type = "孔数"
        info.is_valid = True
        return info

    return info


# ---------------------------------------------------------------------------
# XLS格式检测与列映射
# ---------------------------------------------------------------------------

def _auto_detect_header(sheet: xlrd.sheet.Sheet) -> tuple[int, list[str]]:
    """自动检测表头行号。

    扫描每行，检查是否包含关键检测关键词。
    匹配成功返回 (表头行号0-based, 表头文本列表)。
    匹配失败返回 (-1, [])。
    """
    max_scan = min(sheet.nrows, 20)
    best_row = -1
    best_count = 0
    best_header = []

    for row_idx in range(max_scan):
        row_values = sheet.row_values(row_idx)
        row_texts = [_cell_str(v) for v in row_values]
        match_count = 0
        for text in row_texts:
            for kw in XLS_HEADER_DETECT_KEYWORDS:
                if kw in text:
                    match_count += 1
                    break
        if match_count > best_count:
            best_count = match_count
            best_row = row_idx
            best_header = row_texts

    return best_row, best_header


def _match_columns(header_row: list[str]) -> dict[str, int]:
    """将表头行映射为 {标准字段名: 列索引} 字典。

    对每种XLS格式尝试精确匹配和模糊匹配。
    """
    col_mapping: dict[str, int] = {}

    # 清理表头文本
    cleaned_header = []
    for text in header_row:
        t = text.replace('\u00a0', '').replace('\u3000', '').strip()
        cleaned_header.append(t)

    for std_field, possible_names in XLS_COLUMN_MAPPING.items():
        matched = False
        for name in possible_names:
            if not name:
                continue
            # 清理候选名称
            clean_name = name.replace('\u00a0', '').replace('\u3000', '').strip()
            if not clean_name:
                continue
            # 精确匹配
            for idx, header_text in enumerate(cleaned_header):
                if clean_name == header_text:
                    col_mapping[std_field] = idx
                    matched = True
                    break
            if matched:
                break
            # 包含匹配（表头文本包含候选名称）
            if not matched:
                for idx, header_text in enumerate(cleaned_header):
                    if clean_name in header_text or header_text in clean_name:
                        col_mapping[std_field] = idx
                        matched = True
                        break
            if matched:
                break

    return col_mapping


# ---------------------------------------------------------------------------
# 核心解析逻辑
# ---------------------------------------------------------------------------

def _parse_single_row(row_values: list, col_idx: dict[str, int],
                      source_name: str) -> Optional[PipelinePoint]:
    """解析单行XLS数据为PipelinePoint。

    Args:
        row_values: xlrd行值列表
        col_idx: 列名映射（标准字段名 -> 列索引）
        source_name: 来源文件名

    Returns:
        PipelinePoint 或 None（数据不完整时）
    """
    def get_str(field_name: str) -> str:
        idx = col_idx.get(field_name)
        if idx is None or idx >= len(row_values):
            return ""
        return _cell_str(row_values[idx])

    def get_float(field_name: str) -> Optional[float]:
        idx = col_idx.get(field_name)
        if idx is None or idx >= len(row_values):
            return None
        return _safe_float(row_values[idx])

    def get_int(field_name: str) -> Optional[int]:
        idx = col_idx.get(field_name)
        if idx is None or idx >= len(row_values):
            return None
        return _safe_int(row_values[idx])

    # --- 基础字段 ---
    point_id = get_str("point_id")
    map_point_id = get_str("map_point_id")

    # 管种标准化
    pipe_type_raw = get_str("pipe_type")
    if not pipe_type_raw:
        return None
    pipe_type = PIPE_TYPE_STANDARD_MAP.get(pipe_type_raw, pipe_type_raw)

    # 特征点标准化
    feature_raw = get_str("feature_type")
    feature_type = FEATURE_POINT_MAP.get(feature_raw, feature_raw) if feature_raw else ""

    # 管径解析
    diameter_raw = get_str("diameter_raw")
    diameter_info = parse_diameter(diameter_raw)

    # 材质标准化
    material_raw = get_str("material")
    material = MATERIAL_MAP.get(material_raw, material_raw) if material_raw else ""

    # --- 坐标 ---
    coord_x = get_float("coord_x")
    coord_y = get_float("coord_y")

    # --- 高程 ---
    ground_elev = get_float("ground_elev")
    pipe_top_elev = get_float("pipe_top_elev")
    pipe_bot_elev = get_float("pipe_bot_elev")
    burial_depth = get_float("depth")

    # --- 连接关系 ---
    direction_ids: list[str] = []
    direction_id1 = get_str("direction_id")
    if direction_id1:
        direction_ids.append(direction_id1)
    direction_id2 = get_str("direction_id2")
    if direction_id2:
        direction_ids.append(direction_id2)

    # --- 孔数/套管扩展字段（骊山路格式） ---
    hole_count = get_int("total_holes")
    hole_used = get_int("used_holes")
    casing_size = get_str("casing_size")
    cable_count = get_int("cable_count")

    # 补充套管尺寸到diameter_info
    if casing_size:
        case_info = parse_diameter(casing_size)
        if case_info.is_valid and case_info.casing_width:
            diameter_info = case_info

    # 补充孔数信息
    if hole_count is not None and diameter_info.hole_count is None:
        diameter_info.hole_count = hole_count
    if hole_used is not None and diameter_info.hole_used is None:
        diameter_info.hole_used = hole_used
    if cable_count is not None and diameter_info.cable_count is None:
        diameter_info.cable_count = cable_count

    # --- 备注 ---
    remark = get_str("remark")

    # --- 构建PipelinePoint ---
    point = PipelinePoint(
        point_id=point_id,
        map_point_id=map_point_id,
        source_file=source_name,
        source_type=PipeSource.XLS,
        pipe_type=pipe_type,
        pipe_type_raw=pipe_type_raw,
        feature_type=feature_type,
        material=material,
        diameter_info=diameter_info,
        coord_x=coord_x,
        coord_y=coord_y,
        ground_elevation=ground_elev,
        pipe_top_elev=pipe_top_elev,
        pipe_bot_elev=pipe_bot_elev,
        burial_depth=burial_depth,
        direction_point_ids=direction_ids,
        remark=remark,
        status=PipeStatus.EXISTING,
    )
    point.update_computed_fields()

    return point


def _build_connections(points: list[PipelinePoint]) -> list[PipelineConnection]:
    """从PipelinePoint列表构建连接关系。

    同一个点号可能有多条方向（多连接），
    每条连接关系创建一个PipelineConnection对象。
    """
    # 建立 point_id -> point 的快速查找
    point_map: dict[str, PipelinePoint] = {}
    for p in points:
        if p.point_id:
            point_map[p.point_id] = p
        if p.map_point_id:
            point_map[p.map_point_id] = p

    connections: list[PipelineConnection] = []
    for point in points:
        for dir_id in point.direction_point_ids:
            if not dir_id:
                continue
            # 查找方向点的 map_id
            to_point = point_map.get(dir_id)
            to_map_id = to_point.point_id if to_point else ""

            conn = PipelineConnection(
                from_point_id=point.point_id,
                to_point_id=dir_id,
                from_map_id=point.map_point_id,
                to_map_id=to_map_id,
                pipe_type=point.pipe_type,
                source_file=point.source_file,
            )
            connections.append(conn)

    return connections


def _compute_stats(points: list[PipelinePoint],
                   connections: list[PipelineConnection]) -> PipelineStats:
    """计算管线数据统计摘要"""
    stats = PipelineStats()
    stats.total_points = len(points)
    stats.total_connections = len(connections)

    # 管种统计
    pipe_type_counts: dict[str, int] = defaultdict(int)
    for p in points:
        if p.pipe_type:
            pipe_type_counts[p.pipe_type] += 1
    stats.pipe_type_counts = dict(pipe_type_counts)

    # 特征点统计
    feature_type_counts: dict[str, int] = defaultdict(int)
    for p in points:
        if p.feature_type:
            feature_type_counts[p.feature_type] += 1
    stats.feature_type_counts = dict(feature_type_counts)

    # 材质统计
    material_counts: dict[str, int] = defaultdict(int)
    for p in points:
        if p.material:
            material_counts[p.material] += 1
    stats.material_counts = dict(material_counts)

    # 来源文件统计
    source_file_counts: dict[str, int] = defaultdict(int)
    for p in points:
        if p.source_file:
            source_file_counts[p.source_file] += 1
    stats.source_file_counts = dict(source_file_counts)

    # 坐标范围
    valid_x = [p.coord_x for p in points if p.coord_x is not None]
    valid_y = [p.coord_y for p in points if p.coord_y is not None]
    if valid_x:
        stats.coord_x_range = (min(valid_x), max(valid_x))
    if valid_y:
        stats.coord_y_range = (min(valid_y), max(valid_y))

    # 埋深范围
    valid_depth = [p.burial_depth for p in points if p.burial_depth is not None]
    if valid_depth:
        stats.depth_range = (min(valid_depth), max(valid_depth))

    # 管径范围
    valid_diam = [p.diameter_info.diameter_mm
                  for p in points if p.diameter_info.diameter_mm is not None]
    if valid_diam:
        stats.diameter_range = (min(valid_diam), max(valid_diam))

    return stats


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def parse_xls_file(xls_path: str) -> PipelineParseResult:
    """解析XLS物探成果表文件。

    支持三种XLS格式:
    - 常和路格式（740行×14列）: 现场点号+图上点号+管种/特征点/管径/坐标/高程/埋深/方向点号/备注
    - 骊山路格式（1950行×17列）: 物探点号+管种/特征点/管径/总孔数/占用孔数/套管尺寸/电缆条数/材质/坐标/高程/埋深/方向点号/备注
    - 祁连山南路格式（4668行×11列）: 管种名称/图上点号/方向图上点号/特征点名/管径/材质/坐标/高程/埋深/备注

    Args:
        xls_path: XLS文件路径

    Returns:
        PipelineParseResult对象
    """
    start_time = time.time()
    source_name = os.path.basename(xls_path)
    logger.info(f"开始解析XLS文件: {source_name}")

    try:
        # 1. 读取XLS文件
        workbook = xlrd.open_workbook(xls_path)
        logger.info(f"  Sheet数量: {workbook.nsheets}, 名称: {workbook.sheet_names()}")

        # 2. 遍历Sheet，找到包含管线数据的那个
        target_sheet = None
        header_row_idx = -1
        header_texts: list[str] = []

        for sheet_idx in range(workbook.nsheets):
            sheet = workbook.sheet_by_index(sheet_idx)
            h_idx, h_texts = _auto_detect_header(sheet)
            if h_idx >= 0:
                target_sheet = sheet
                header_row_idx = h_idx
                header_texts = h_texts
                logger.info(f"  选中Sheet: {sheet.name} (表头行={h_idx})")
                break

        if target_sheet is None:
            return PipelineParseResult(
                error_message=f"无法识别XLS格式（未找到匹配的表头行）: {source_name}",
                source_file=source_name,
            )

        # 3. 构建列映射
        col_mapping = _match_columns(header_texts)
        if not col_mapping:
            return PipelineParseResult(
                error_message=f"列映射为空: {source_name}",
                source_file=source_name,
            )
        logger.info(f"  列映射: {col_mapping}")

        # 检查必须有point_id映射
        if "point_id" not in col_mapping:
            return PipelineParseResult(
                error_message=f"缺少point_id列映射: {source_name}",
                source_file=source_name,
            )

        # 4. 解析每一行
        points: list[PipelinePoint] = []
        error_rows = 0
        for row_idx in range(header_row_idx + 1, target_sheet.nrows):
            row_values = target_sheet.row_values(row_idx)
            # 跳过空行
            if all(v is None or (isinstance(v, float) and v != v)  # NaN check
                   for v in row_values):
                continue

            try:
                point = _parse_single_row(row_values, col_mapping, source_name)
                if point is not None:
                    points.append(point)
            except Exception as e:
                error_rows += 1
                logger.debug(f"  行{row_idx}解析失败: {e}")

        # 5. 构建连接关系
        connections = _build_connections(points)

        # 6. 计算统计
        stats = _compute_stats(points, connections)

        # 7. 构建结果
        elapsed_ms = (time.time() - start_time) * 1000
        result = PipelineParseResult(
            points=points,
            connections=connections,
            stats=stats,
            source_file=source_name,
            source_type=PipeSource.XLS,
            parse_time_ms=elapsed_ms,
        )

        logger.info(
            f"XLS解析完成: {source_name} | "
            f"{len(points)}个管线点, {len(connections)}条连接, "
            f"{error_rows}行跳过 | {elapsed_ms:.0f}ms"
        )

        return result

    except Exception as e:
        logger.error(f"XLS解析失败: {xls_path} - {e}")
        return PipelineParseResult(
            error_message=f"解析异常: {e}",
            source_file=os.path.basename(xls_path) if xls_path else "",
        )


def parse_xls_batch(xls_paths: list[str]) -> list[PipelineParseResult]:
    """批量解析多个XLS文件。

    Args:
        xls_paths: XLS文件路径列表

    Returns:
        PipelineParseResult列表
    """
    results: list[PipelineParseResult] = []
    for path in xls_paths:
        result = parse_xls_file(path)
        results.append(result)
    return results
