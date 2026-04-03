"""管线数据处理引擎

统一管理管线数据的导入、查询、校验和导出。
支持多源数据（XLS/DWG/DAT）的管线点数据汇聚与处理。

主要功能:
1. 批量导入XLS物探成果表
2. 多源数据融合（按优先级合并相同管线点）
3. 管线数据查询与筛选
4. 数据质量校验
5. 导出为Excel/CSV/JSON
"""

import os
import time
import logging
from typing import Optional
from collections import defaultdict
from pathlib import Path

from core.models import (
    PipeSource,
    PipelinePoint,
    PipelineConnection,
    PipelineStats,
    PipelineParseResult,
)
from core.xls_parser import parse_xls_file, parse_xls_batch
from config.pipeline_config import PIPE_CATEGORY_MAP

logger = logging.getLogger(__name__)


class PipelineEngine:
    """管线数据处理引擎

    用法:
        engine = PipelineEngine()
        result = engine.import_xls("管线点成果表.xls")
        print(engine.summary())
    """

    def __init__(self):
        self._points: list[PipelinePoint] = []
        self._connections: list[PipelineConnection] = []
        self._parse_results: list[PipelineParseResult] = []

    # -----------------------------------------------------------------------
    # 数据导入
    # -----------------------------------------------------------------------

    def import_xls(self, xls_path: str) -> PipelineParseResult:
        """导入单个XLS物探成果表文件。

        Args:
            xls_path: XLS文件路径

        Returns:
            PipelineParseResult
        """
        logger.info(f"PipelineEngine: 导入XLS -> {os.path.basename(xls_path)}")
        result = parse_xls_file(xls_path)

        if result.error_message:
            logger.error(f"  导入失败: {result.error_message}")
            return result

        self._merge_result(result)
        self._parse_results.append(result)

        logger.info(
            f"  成功导入 {len(result.points)} 个管线点, "
            f"{len(result.connections)} 条连接"
        )
        return result

    def import_xls_batch(self, xls_paths: list[str]) -> list[PipelineParseResult]:
        """批量导入多个XLS文件。

        Args:
            xls_paths: XLS文件路径列表

        Returns:
            PipelineParseResult列表
        """
        logger.info(f"PipelineEngine: 批量导入 {len(xls_paths)} 个XLS文件")
        results = parse_xls_batch(xls_paths)

        for result in results:
            if not result.error_message:
                self._merge_result(result)
            self._parse_results.append(result)

        success_count = sum(1 for r in results if not r.error_message)
        total_points = sum(len(r.points) for r in results if not r.error_message)
        logger.info(
            f"  批量导入完成: {success_count}/{len(xls_paths)} 成功, "
            f"共 {total_points} 个管线点"
        )

        return results

    def import_xls_directory(self, dir_path: str,
                             recursive: bool = True) -> list[PipelineParseResult]:
        """扫描目录中的所有XLS文件并导入。

        Args:
            dir_path: 目录路径
            recursive: 是否递归搜索子目录

        Returns:
            PipelineParseResult列表
        """
        xls_files = self._find_xls_files(dir_path, recursive)
        if not xls_files:
            logger.warning(f"未找到XLS文件: {dir_path}")
            return []

        logger.info(f"在 {dir_path} 中找到 {len(xls_files)} 个XLS文件")
        return self.import_xls_batch(xls_files)

    # -----------------------------------------------------------------------
    # 数据查询
    # -----------------------------------------------------------------------

    @property
    def points(self) -> list[PipelinePoint]:
        """获取所有管线点"""
        return self._points

    @property
    def connections(self) -> list[PipelineConnection]:
        """获取所有连接关系"""
        return self._connections

    @property
    def total_points(self) -> int:
        return len(self._points)

    @property
    def total_connections(self) -> int:
        return len(self._connections)

    def get_point_by_id(self, point_id: str) -> Optional[PipelinePoint]:
        """按点号查找管线点"""
        for p in self._points:
            if p.point_id == point_id or p.map_point_id == point_id:
                return p
        return None

    def query_points(self, pipe_type: str = None,
                     feature_type: str = None,
                     material: str = None,
                     source_file: str = None) -> list[PipelinePoint]:
        """按条件查询管线点。

        Args:
            pipe_type: 管种（标准化后名称）
            feature_type: 特征点类型
            material: 材质
            source_file: 来源文件名

        Returns:
            匹配的管线点列表
        """
        results = self._points
        if pipe_type:
            results = [p for p in results if p.pipe_type == pipe_type]
        if feature_type:
            results = [p for p in results if p.feature_type == feature_type]
        if material:
            results = [p for p in results if p.material == material]
        if source_file:
            results = [p for p in results if source_file in p.source_file]
        return results

    def get_pipe_types(self) -> list[str]:
        """获取所有管种（去重排序）"""
        types = set(p.pipe_type for p in self._points if p.pipe_type)
        return sorted(types)

    def get_feature_types(self) -> list[str]:
        """获取所有特征点类型（去重排序）"""
        types = set(p.feature_type for p in self._points if p.feature_type)
        return sorted(types)

    def get_materials(self) -> list[str]:
        """获取所有材质（去重排序）"""
        materials = set(p.material for p in self._points if p.material)
        return sorted(materials)

    def get_connections_for_point(self, point_id: str) -> list[PipelineConnection]:
        """获取指定点的所有连接关系"""
        return [
            c for c in self._connections
            if c.from_point_id == point_id or c.to_point_id == point_id
        ]

    # -----------------------------------------------------------------------
    # 统计
    # -----------------------------------------------------------------------

    def compute_stats(self) -> PipelineStats:
        """计算当前所有管线数据的统计摘要"""
        stats = PipelineStats()
        stats.total_points = len(self._points)
        stats.total_connections = len(self._connections)

        pipe_type_counts: dict[str, int] = defaultdict(int)
        feature_type_counts: dict[str, int] = defaultdict(int)
        material_counts: dict[str, int] = defaultdict(int)
        source_file_counts: dict[str, int] = defaultdict(int)

        for p in self._points:
            if p.pipe_type:
                pipe_type_counts[p.pipe_type] += 1
            if p.feature_type:
                feature_type_counts[p.feature_type] += 1
            if p.material:
                material_counts[p.material] += 1
            if p.source_file:
                source_file_counts[p.source_file] += 1

        stats.pipe_type_counts = dict(pipe_type_counts)
        stats.feature_type_counts = dict(feature_type_counts)
        stats.material_counts = dict(material_counts)
        stats.source_file_counts = dict(source_file_counts)

        valid_x = [p.coord_x for p in self._points if p.coord_x is not None]
        valid_y = [p.coord_y for p in self._points if p.coord_y is not None]
        if valid_x:
            stats.coord_x_range = (min(valid_x), max(valid_x))
        if valid_y:
            stats.coord_y_range = (min(valid_y), max(valid_y))

        valid_depth = [p.burial_depth for p in self._points if p.burial_depth is not None]
        if valid_depth:
            stats.depth_range = (min(valid_depth), max(valid_depth))

        valid_diam = [p.diameter_info.diameter_mm
                      for p in self._points if p.diameter_info.diameter_mm is not None]
        if valid_diam:
            stats.diameter_range = (min(valid_diam), max(valid_diam))

        return stats

    def summary(self) -> str:
        """生成可读的统计摘要文本"""
        stats = self.compute_stats()
        lines = [
            "=" * 60,
            "管线数据统计摘要",
            "=" * 60,
            f"总管线点数: {stats.total_points}",
            f"总连接数:   {stats.total_connections}",
            "",
        ]

        if stats.pipe_type_counts:
            lines.append("管种分布:")
            for pt, count in sorted(stats.pipe_type_counts.items(),
                                     key=lambda x: -x[1]):
                pct = count / stats.total_points * 100
                lines.append(f"  {pt}: {count} ({pct:.1f}%)")
            lines.append("")

        if stats.feature_type_counts:
            lines.append("特征点类型分布:")
            for ft, count in sorted(stats.feature_type_counts.items(),
                                     key=lambda x: -x[1]):
                lines.append(f"  {ft}: {count}")
            lines.append("")

        if stats.material_counts:
            lines.append("材质分布:")
            for mat, count in sorted(stats.material_counts.items(),
                                      key=lambda x: -x[1]):
                lines.append(f"  {mat}: {count}")
            lines.append("")

        if stats.coord_x_range[0] is not None:
            lines.append(f"X坐标范围: {stats.coord_x_range[0]:.2f} ~ {stats.coord_x_range[1]:.2f}")
        if stats.coord_y_range[0] is not None:
            lines.append(f"Y坐标范围: {stats.coord_y_range[0]:.2f} ~ {stats.coord_y_range[1]:.2f}")
        if stats.depth_range[0] is not None:
            lines.append(f"埋深范围:   {stats.depth_range[0]:.2f} ~ {stats.depth_range[1]:.2f}")
        if stats.diameter_range[0] is not None:
            lines.append(f"管径范围:   {stats.diameter_range[0]:.0f} ~ {stats.diameter_range[1]:.0f} mm")

        lines.append("=" * 60)
        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # 数据校验
    # -----------------------------------------------------------------------

    def validate(self) -> list[str]:
        """校验数据质量，返回问题列表。

        检查项:
        - 重复点号
        - 缺少坐标
        - 缺少管种
        - 孤立点（无连接）
        - 连接目标不存在
        """
        issues: list[str] = []

        # 1. 重复点号检查
        id_counts: dict[str, int] = defaultdict(int)
        for p in self._points:
            if p.point_id:
                id_counts[p.point_id] += 1
        for pid, count in id_counts.items():
            if count > 1:
                issues.append(f"重复点号: {pid} (出现{count}次)")

        # 2. 缺少坐标
        no_coord = sum(1 for p in self._points
                       if p.coord_x is None or p.coord_y is None)
        if no_coord:
            issues.append(f"缺少坐标的管线点: {no_coord}个")

        # 3. 缺少管种
        no_type = sum(1 for p in self._points if not p.pipe_type)
        if no_type:
            issues.append(f"缺少管种的管线点: {no_type}个")

        # 4. 孤立点检查
        connected_ids = set()
        for c in self._connections:
            connected_ids.add(c.from_point_id)
            connected_ids.add(c.to_point_id)
        isolated = sum(1 for p in self._points
                       if p.point_id and p.point_id not in connected_ids)
        if isolated:
            issues.append(f"孤立点（无连接关系）: {isolated}个")

        # 5. 连接目标不存在
        all_ids = set(p.point_id for p in self._points if p.point_id)
        all_ids.update(p.map_point_id for p in self._points if p.map_point_id)
        dangling = 0
        for c in self._connections:
            if c.to_point_id and c.to_point_id not in all_ids:
                dangling += 1
        if dangling:
            issues.append(f"连接目标不存在的连接: {dangling}条")

        return issues

    # -----------------------------------------------------------------------
    # 导出
    # -----------------------------------------------------------------------

    def export_to_dicts(self, points: list[PipelinePoint] = None) -> list[dict]:
        """将管线点数据导出为字典列表（用于DataFrame/JSON/CSV）。

        Args:
            points: 指定导出的点，None则导出全部

        Returns:
            字典列表
        """
        target_points = points or self._points
        rows = []
        for p in target_points:
            row = {
                "点号": p.point_id,
                "图上点号": p.map_point_id,
                "管种": p.pipe_type,
                "原始管种": p.pipe_type_raw,
                "管种大类": p.pipe_category,
                "特征点": p.feature_type,
                "材质": p.material,
                "管径原始": p.diameter_info.raw,
                "管径mm": p.diameter_info.diameter_mm,
                "管径类型": p.diameter_info.diameter_type,
                "总孔数": p.diameter_info.hole_count,
                "占用孔数": p.diameter_info.hole_used,
                "套管宽度": p.diameter_info.casing_width,
                "套管高度": p.diameter_info.casing_height,
                "电缆条数": p.diameter_info.cable_count,
                "管径摘要": p.diameter_info.to_summary(),
                "X坐标": p.coord_x,
                "Y坐标": p.coord_y,
                "地面高程": p.ground_elevation,
                "管顶高程": p.pipe_top_elev,
                "管底高程": p.pipe_bot_elev,
                "埋深": p.burial_depth,
                "方向点号": ";".join(p.direction_point_ids),
                "来源文件": p.source_file,
                "来源类型": p.source_type.value,
                "状态": p.status.value,
                "备注": p.remark,
            }
            rows.append(row)
        return rows

    def export_to_dataframe(self, points: list[PipelinePoint] = None):
        """导出为pandas DataFrame。

        Args:
            points: 指定导出的点，None则导出全部

        Returns:
            pandas.DataFrame
        """
        import pandas as pd
        rows = self.export_to_dicts(points)
        return pd.DataFrame(rows)

    def export_connections_to_dicts(self) -> list[dict]:
        """将连接关系导出为字典列表。"""
        rows = []
        for c in self._connections:
            rows.append({
                "起点号": c.from_point_id,
                "终点号": c.to_point_id,
                "起点图上号": c.from_map_id,
                "终点图上号": c.to_map_id,
                "管种": c.pipe_type,
                "来源文件": c.source_file,
            })
        return rows

    # -----------------------------------------------------------------------
    # 内部方法
    # -----------------------------------------------------------------------

    def _merge_result(self, result: PipelineParseResult) -> None:
        """将解析结果合并到引擎数据中"""
        self._points.extend(result.points)
        self._connections.extend(result.connections)

    @staticmethod
    def _find_xls_files(dir_path: str, recursive: bool = True) -> list[str]:
        """在目录中查找XLS文件"""
        xls_files: list[str] = []
        dir_path = Path(dir_path)
        if not dir_path.exists():
            return xls_files

        if recursive:
            for f in dir_path.rglob("*.xls"):
                # 排除xlsx（xlrd旧格式不支持xlsx）
                if not f.name.endswith(".xlsx"):
                    xls_files.append(str(f))
        else:
            for f in dir_path.glob("*.xls"):
                if not f.name.endswith(".xlsx"):
                    xls_files.append(str(f))

        return sorted(xls_files)

    def query_by_pipe_type(self, pipe_type: str) -> list[PipelinePoint]:
        """按管种筛选管线点。

        Args:
            pipe_type: 管种名称（标准化后）

        Returns:
            匹配的管线点列表
        """
        return [p for p in self._points if p.pipe_type == pipe_type]

    def query_by_feature_type(self, feature_type: str) -> list[PipelinePoint]:
        """按特征点类型筛选管线点。"""
        return [p for p in self._points if p.feature_type == feature_type]

    def query_by_source(self, source_file: str) -> list[PipelinePoint]:
        """按来源文件筛选管线点。"""
        return [p for p in self._points if source_file in p.source_file]

    def get_pipe_types(self) -> list[str]:
        """获取所有管种列表（去重排序）。"""
        return sorted(set(p.pipe_type for p in self._points if p.pipe_type))

    def get_feature_types(self) -> list[str]:
        """获取所有特征点类型列表。"""
        return sorted(set(p.feature_type for p in self._points if p.feature_type))

    def clear(self) -> None:
        """清空所有数据"""
        self._points.clear()
        self._connections.clear()
        self._parse_results.clear()
