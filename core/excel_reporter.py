"""Excel 报告生成器模块

将解析结果（ParseResult 列表）输出为格式化的 Excel 报表，
包含表头样式、列宽、冻结首行、自动筛选等格式化功能。
支持汇总统计页、按图层分组视图、按文件分组视图、CSV/JSON 导出、列配置和超链接。

增强功能：
- 条件格式：数值列右对齐、标注类型颜色区分、空值灰色标记、超长文本截断
- 按文件分组 Sheet
- 按内容分类统计展示
- 大数据量分批写入与行数限制警告
"""

import csv
import json
import logging
import statistics
from pathlib import Path
from typing import Optional, Callable

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from core.models import ParseResult, ExportConfig, SummaryStats, ContentCategory

logger = logging.getLogger(__name__)


class ExcelReporter:
    """Excel 报告生成器

    将多个文件的标注解析结果汇总为一份格式化的 Excel 报表。
    支持多 Sheet 输出（明细、汇总统计、按图层分组）、CSV/JSON 同步导出。
    """

    # 列定义：(列标题, 列宽, 字段名)
    ALL_COLUMNS: list[tuple[str, int, str]] = [
        ("序号", 8, "index"),
        ("标注内容", 35, "content"),
        ("X坐标", 15, "x"),
        ("Y坐标", 15, "y"),
        ("标注类型", 15, "annotation_type"),
        ("图层名", 20, "layer"),
        ("来源文件", 30, "source_file"),
        ("内容分类", 15, "category"),
        ("文字高度", 12, "height"),
        ("旋转角度", 12, "rotation"),
        ("样式名", 18, "style"),
    ]

    # 保留旧接口兼容
    COLUMNS: list[tuple[str, int]] = [(col[0], col[1]) for col in ALL_COLUMNS[:7]]

    # 表头字体：微软雅黑 11号 加粗 白色
    HEADER_FONT = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")

    # 表头填充：蓝色背景 #4472C4
    HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")

    # 表头对齐：居中 自动换行
    HEADER_ALIGNMENT = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # 数据单元格字体：微软雅黑 10号
    CELL_FONT = Font(name="微软雅黑", size=10)

    # 数据单元格对齐：垂直居中 自动换行
    CELL_ALIGNMENT = Alignment(vertical="center", wrap_text=True)

    # 四边细线边框
    THIN_BORDER = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    # 汇总页分组标题填充：浅蓝色
    GROUP_HEADER_FILL = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")

    # 汇总页分组标题字体
    GROUP_HEADER_FONT = Font(name="微软雅黑", size=11, bold=True, color="1F4E79")

    # 数值型标注子标题填充：浅绿色
    NUMERIC_HEADER_FILL = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")

    # 条件格式柱状图用的填充色（蓝色渐变）
    BAR_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")

    # 异常值标红字体
    OUTLIER_FONT = Font(name="微软雅黑", size=10, bold=True, color="FF0000")

    # 图层分组的交替背景色
    LAYER_FILLS = [
        PatternFill(start_color="F2F7FB", end_color="F2F7FB", fill_type="solid"),
        PatternFill(start_color="FFF8E1", end_color="FFF8E1", fill_type="solid"),
    ]

    # 文件分组的交替背景色
    FILE_FILLS = [
        PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid"),
        PatternFill(start_color="F3E5F5", end_color="F3E5F5", fill_type="solid"),
    ]

    # 空值单元格标记背景色
    EMPTY_CELL_FILL = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")

    # 数值列右对齐样式
    NUMBER_ALIGNMENT = Alignment(horizontal="right", vertical="center", wrap_text=True)

    # 标注类型颜色映射（用于数据行中的标注类型列着色）
    TYPE_COLOR_MAP: dict[str, str] = {
        "线性标注": "4472C4",
        "对齐标注": "5B9BD5",
        "角度标注": "70AD47",
        "半径标注": "ED7D31",
        "直径标注": "FFC000",
        "坐标标注": "A5A5A5",
        "弧长标注": "9DC3E6",
        "未知标注": "BFBFBF",
        "单行文字": "7030A0",
        "多行文字": "843C0C",
        "引线标注": "C00000",
        "多重引线": "FF0000",
        "表格": "00B050",
        "公差标注": "BF8F00",
        "属性定义": "375623",
        "属性值": "2F5496",
    }

    # 数值列字段名集合（用于右对齐判断）
    NUMERIC_FIELDS = {"x", "y", "height", "rotation"}

    # 超长文本截断阈值
    TRUNCATE_THRESHOLD = 50

    # 大数据量阈值
    LARGE_DATA_THRESHOLD = 10000
    ROW_LIMIT_WARNING = 50000

    # 分批写入的批次大小
    BATCH_SIZE = 5000

    def generate_report(
        self,
        results: list[ParseResult],
        output_path: str,
        progress_callback: Optional[Callable] = None,
        export_config: Optional[ExportConfig] = None,
    ) -> str:
        """生成 Excel 汇总报告

        Args:
            results: 多个文件的解析结果列表
            output_path: 输出文件路径
            progress_callback: 进度回调函数，签名为 callback(current, total)
            export_config: 导出配置，控制输出的 Sheet、列、超链接等

        Returns:
            输出文件的绝对路径字符串
        """
        config = export_config if export_config is not None else ExportConfig()

        # 1. 收集所有 ParseResult 中的 items 为扁平列表
        all_items = []
        for result in results:
            if result.error is not None:
                continue
            all_items.extend(result.items)

        # 2. 重新全局连续编号
        for i, item in enumerate(all_items, start=1):
            item.index = i

        total = len(all_items)

        # 2.1 大数据量性能警告
        if total > self.ROW_LIMIT_WARNING:
            logger.warning(
                "标注数据量达到 %d 行，超过 %d 行阈值，Excel 报表性能可能受到影响。",
                total, self.ROW_LIMIT_WARNING,
            )

        # 3. 确定要导出的列
        active_columns = self._resolve_columns(config.selected_columns)

        # 4. 构建 pandas DataFrame（大数据量时分批写入以减少内存峰值）
        col_titles = [col[0] for col in active_columns]

        if total > self.LARGE_DATA_THRESHOLD:
            # 分批构建 records 并写入 Excel
            output = Path(output_path)
            output.parent.mkdir(parents=True, exist_ok=True)

            with pd.ExcelWriter(str(output), engine="openpyxl") as writer:
                # 先写入空表头
                pd.DataFrame(columns=col_titles).to_excel(
                    writer, sheet_name="标注明细", index=False,
                )
                wb = writer.book
                ws = writer.sheets["标注明细"]

                batch_records = []
                for i, item in enumerate(all_items):
                    batch_records.append(self._item_to_record(item, active_columns))

                    if len(batch_records) >= self.BATCH_SIZE or i == total - 1:
                        # 将当前批次追加到工作表
                        start_row = ws.max_row
                        for rec_idx, record in enumerate(batch_records):
                            row_num = start_row + rec_idx
                            for col_idx, title in enumerate(col_titles, start=1):
                                ws.cell(
                                    row=row_num + 1, column=col_idx,
                                    value=record.get(title, ""),
                                )

                        # 进度回调
                        if progress_callback is not None:
                            progress_callback(i + 1, total)

                        # 清空批次，释放内存
                        batch_records.clear()
        else:
            # 小数据量：一次性构建
            records = []
            for i, item in enumerate(all_items):
                records.append(self._item_to_record(item, active_columns))

                # 进度回调：收集阶段
                if progress_callback is not None:
                    progress_callback(i + 1, total)

            df = pd.DataFrame(records, columns=col_titles)

            # 5. 确保输出目录存在
            output = Path(output_path)
            output.parent.mkdir(parents=True, exist_ok=True)

            # 6. 写入 Excel（使用 openpyxl 引擎）
            with pd.ExcelWriter(str(output), engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name="标注明细", index=False)

        # 7. 打开工作簿一次，后续所有操作共用，避免反复 open/save/close
        wb = load_workbook(str(output))

        # 8. 应用格式化（主 Sheet）
        self._apply_formatting(wb, active_columns, all_items)

        # 9. 汇总统计页
        if config.include_summary:
            stats = self._compute_stats(all_items)
            self._write_summary_sheet(wb, all_items, stats)

        # 10. 按图层分组视图
        if config.include_layer_view:
            self._write_layer_sheet(wb, all_items, active_columns)

        # 10.1 按文件分组视图
        if config.include_file_view:
            self._write_file_sheet(wb, all_items, active_columns)

        # 11. 来源文件超链接
        if config.hyperlink_source:
            source_col_idx = self._find_column_index(active_columns, "来源文件")
            if source_col_idx is not None:
                self._apply_hyperlinks(wb, "标注明细", source_col_idx)

        # 12. 统一保存一次
        wb.save(str(output))
        wb.close()

        # 13. CSV 和 JSON 导出
        if config.include_csv:
            csv_path = str(output.with_suffix(".csv"))
            self.export_csv(results, csv_path)

        if config.include_json:
            json_path = str(output.with_suffix(".json"))
            self.export_json(results, json_path)

        return str(output.resolve())

    # ------------------------------------------------------------------
    # 公共导出方法
    # ------------------------------------------------------------------

    def export_csv(self, results: list[ParseResult], output_path: str) -> str:
        """将解析结果导出为 CSV 文件

        Args:
            results: 多个文件的解析结果列表
            output_path: 输出 CSV 文件路径

        Returns:
            输出文件的绝对路径字符串
        """
        all_items = []
        for result in results:
            if result.error is not None:
                continue
            all_items.extend(result.items)

        records = []
        for i, item in enumerate(all_items, start=1):
            item.index = i
            records.append({
                "序号": item.index,
                "标注内容": item.content,
                "X坐标": round(item.x, 4),
                "Y坐标": round(item.y, 4),
                "标注类型": item.annotation_type.value,
                "图层名": item.layer,
                "来源文件": item.source_file,
                "内容分类": item.category.value,
                "文字高度": item.height,
                "旋转角度": round(item.rotation, 2),
                "样式名": item.style,
            })

        df = pd.DataFrame(records)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(str(output), index=False, encoding="utf-8-sig")

        return str(output.resolve())

    def export_json(self, results: list[ParseResult], output_path: str) -> str:
        """将解析结果导出为 JSON 文件

        Args:
            results: 多个文件的解析结果列表
            output_path: 输出 JSON 文件路径

        Returns:
            输出文件的绝对路径字符串
        """
        all_items = []
        for result in results:
            if result.error is not None:
                continue
            all_items.extend(result.items)

        records = []
        for i, item in enumerate(all_items, start=1):
            item.index = i
            records.append({
                "序号": item.index,
                "标注内容": item.content,
                "X坐标": round(item.x, 4),
                "Y坐标": round(item.y, 4),
                "标注类型": item.annotation_type.value,
                "图层名": item.layer,
                "来源文件": item.source_file,
                "内容分类": item.category.value,
                "文字高度": item.height,
                "旋转角度": round(item.rotation, 2),
                "样式名": item.style,
            })

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(str(output), "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

        return str(output.resolve())

    # ------------------------------------------------------------------
    # 列配置辅助方法
    # ------------------------------------------------------------------

    def _resolve_columns(
        self, selected_columns: list[str]
    ) -> list[tuple[str, int, str]]:
        """根据 selected_columns 过滤要导出的列

        Args:
            selected_columns: 选中的列标题列表，为空则返回全部列

        Returns:
            过滤后的列定义列表
        """
        if not selected_columns:
            return list(self.ALL_COLUMNS)

        # 以列标题匹配
        result = []
        for col in self.ALL_COLUMNS:
            if col[0] in selected_columns:
                result.append(col)
        # 如果全部未匹配则回退到全部列
        return result if result else list(self.ALL_COLUMNS)

    def _item_to_record(
        self, item, columns: list[tuple[str, int, str]]
    ) -> dict:
        """将 AnnotationItem 转换为一条记录字典

        Args:
            item: 标注项
            columns: 要输出的列定义

        Returns:
            以列标题为 key 的字典
        """
        record = {}
        for title, _, field_name in columns:
            if field_name == "index":
                record[title] = item.index
            elif field_name == "content":
                record[title] = item.content
            elif field_name == "x":
                record[title] = round(item.x, 4)
            elif field_name == "y":
                record[title] = round(item.y, 4)
            elif field_name == "annotation_type":
                record[title] = item.annotation_type.value
            elif field_name == "layer":
                record[title] = item.layer
            elif field_name == "source_file":
                record[title] = item.source_file
            elif field_name == "category":
                record[title] = item.category.value
            elif field_name == "height":
                record[title] = round(item.height, 4)
            elif field_name == "rotation":
                record[title] = round(item.rotation, 2)
            elif field_name == "style":
                record[title] = item.style
            else:
                record[title] = ""
        return record

    @staticmethod
    def _find_column_index(
        columns: list[tuple[str, int, str]], title: str
    ) -> Optional[int]:
        """查找指定列标题在列定义中的 1-based 索引

        Args:
            columns: 列定义列表
            title: 列标题

        Returns:
            1-based 列索引，未找到返回 None
        """
        for idx, (col_title, _, _) in enumerate(columns, start=1):
            if col_title == title:
                return idx
        return None

    # ------------------------------------------------------------------
    # 统计计算
    # ------------------------------------------------------------------

    def _compute_stats(self, all_items: list) -> SummaryStats:
        """从标注项列表中计算统计摘要

        Args:
            all_items: 所有标注项列表

        Returns:
            SummaryStats 实例
        """
        stats = SummaryStats()
        stats.total_items = len(all_items)

        type_counts: dict[str, int] = {}
        layer_counts: dict[str, int] = {}
        file_counts: dict[str, int] = {}
        category_counts: dict[str, int] = {}
        numeric_values: list[float] = []

        for item in all_items:
            # 类型统计
            t = item.annotation_type.value
            type_counts[t] = type_counts.get(t, 0) + 1

            # 图层统计
            layer = item.layer if item.layer else "(未命名图层)"
            layer_counts[layer] = layer_counts.get(layer, 0) + 1

            # 文件统计
            fname = Path(item.source_file).name if item.source_file else "(未知文件)"
            file_counts[fname] = file_counts.get(fname, 0) + 1

            # 分类统计
            cat = item.category.value
            category_counts[cat] = category_counts.get(cat, 0) + 1

            # 尝试提取数值
            val = self._try_parse_float(item.content)
            if val is not None:
                numeric_values.append(val)

        # 按类型大类统计
        dim_count = sum(
            v for k, v in type_counts.items()
            if "标注" in k and "注释" not in k
        )
        text_count = sum(
            v for k, v in type_counts.items()
            if "文字" in k
        )
        leader_count = sum(
            v for k, v in type_counts.items()
            if "引线" in k
        )
        table_count = sum(
            v for k, v in type_counts.items()
            if "表格" in k
        )
        stats.dimension_count = dim_count
        stats.text_count = text_count
        stats.leader_count = leader_count
        stats.table_count = table_count

        stats.type_counts = type_counts
        stats.layer_counts = layer_counts
        stats.file_counts = file_counts
        stats.category_counts = category_counts
        stats.numeric_values = numeric_values

        if numeric_values:
            stats.value_min = min(numeric_values)
            stats.value_max = max(numeric_values)
            stats.value_avg = round(statistics.mean(numeric_values), 4)

        return stats

    @staticmethod
    def _try_parse_float(text: str) -> Optional[float]:
        """尝试从文本中提取数值

        支持纯数字、带逗号的数字、以及包含数字的文本。
        首先尝试直接转换整个字符串，失败则尝试提取第一个连续数字段。

        Args:
            text: 输入文本

        Returns:
            解析成功的浮点数，或 None
        """
        if not text:
            return None
        text = text.strip()
        # 尝试直接转换
        try:
            return float(text.replace(",", ""))
        except ValueError:
            pass
        # 提取第一个数字段
        import re
        match = re.search(r"[-+]?\d[\d,]*\.?\d*", text)
        if match:
            try:
                return float(match.group().replace(",", ""))
            except ValueError:
                pass
        return None

    # ------------------------------------------------------------------
    # Sheet 2: 汇总统计页
    # ------------------------------------------------------------------

    def _write_summary_sheet(
        self,
        wb,
        all_items: list,
        stats: SummaryStats,
    ) -> None:
        """写入汇总统计 Sheet

        包含：按类型统计、按图层统计、按文件统计、按内容分类统计、
        数值型标注统计（min/max/avg/median）、异常值标红。

        Args:
            wb: openpyxl Workbook 对象
            all_items: 所有标注项
            stats: 统计摘要
        """
        ws = wb.create_sheet("汇总统计")

        row = 1

        # ---- 按标注类型统计 ----
        row = self._write_stats_section(
            ws, row, "按标注类型统计", stats.type_counts, stats.total_items,
        )

        row += 1  # 空行

        # ---- 按图层统计 ----
        row = self._write_stats_section(
            ws, row, "按图层统计", stats.layer_counts, stats.total_items,
        )

        row += 1

        # ---- 按文件统计 ----
        row = self._write_stats_section(
            ws, row, "按文件统计", stats.file_counts, stats.total_items,
        )

        row += 1

        # ---- 按内容分类统计 ----
        row = self._write_stats_section(
            ws, row, "按内容分类统计", stats.category_counts, stats.total_items,
        )

        row += 1

        # ---- 数值型标注统计 ----
        row = self._write_numeric_stats(ws, row, all_items, stats)

        # 列宽自适应
        ws.column_dimensions["A"].width = 25
        ws.column_dimensions["B"].width = 12
        ws.column_dimensions["C"].width = 15
        ws.column_dimensions["D"].width = 15

    def _write_stats_section(
        self,
        ws,
        start_row: int,
        title: str,
        counts: dict[str, int],
        total: int,
    ) -> int:
        """写入一个统计分组（标题行 + 数据行）

        数据行包含名称、数量、占比、以及条件格式柱状图。

        Args:
            ws: 工作表
            start_row: 起始行号
            title: 分组标题
            counts: 名称到数量的映射
            total: 总数（用于计算占比）

        Returns:
            写入完成后的下一行行号
        """
        row = start_row

        # 分组标题行
        cell = ws.cell(row=row, column=1, value=title)
        cell.font = self.GROUP_HEADER_FONT
        cell.fill = self.GROUP_HEADER_FILL
        cell.border = self.THIN_BORDER
        for col in range(2, 5):
            c = ws.cell(row=row, column=col)
            c.fill = self.GROUP_HEADER_FILL
            c.border = self.THIN_BORDER
        row += 1

        # 列头
        for col_idx, header in enumerate(["名称", "数量", "占比", "分布"], start=1):
            cell = ws.cell(row=row, column=col_idx, value=header)
            cell.font = Font(name="微软雅黑", size=10, bold=True)
            cell.alignment = Alignment(horizontal="center")
            cell.border = self.THIN_BORDER
        row += 1

        # 找到最大值用于柱状图比例
        max_count = max(counts.values()) if counts else 1

        # 按数量降序排列
        sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)

        for name, count in sorted_items:
            pct = count / total if total > 0 else 0
            ws.cell(row=row, column=1, value=name).border = self.THIN_BORDER

            c_count = ws.cell(row=row, column=2, value=count)
            c_count.border = self.THIN_BORDER
            c_count.alignment = Alignment(horizontal="center")

            c_pct = ws.cell(row=row, column=3, value=f"{pct:.1%}")
            c_pct.border = self.THIN_BORDER
            c_pct.alignment = Alignment(horizontal="center")

            # 条件格式柱状图：在 D 列用背景色填充宽度表示占比
            bar_len = int(pct * 20)  # 最多 20 个字符宽
            bar_cell = ws.cell(row=row, column=4, value="█" * bar_len if bar_len > 0 else "")
            bar_cell.font = Font(name="Consolas", size=9, color="4472C4")

            row += 1

        return row

    def _write_numeric_stats(
        self,
        ws,
        start_row: int,
        all_items: list,
        stats: SummaryStats,
    ) -> int:
        """写入数值型标注统计区段

        包含 min/max/avg/median 总览和异常值检测列表。

        Args:
            ws: 工作表
            start_row: 起始行号
            all_items: 所有标注项
            stats: 统计摘要

        Returns:
            写入完成后的下一行行号
        """
        row = start_row

        # 区段标题
        cell = ws.cell(row=row, column=1, value="数值型标注统计")
        cell.font = self.GROUP_HEADER_FONT
        cell.fill = self.NUMERIC_HEADER_FILL
        cell.border = self.THIN_BORDER
        for col in range(2, 5):
            c = ws.cell(row=row, column=col)
            c.fill = self.NUMERIC_HEADER_FILL
            c.border = self.THIN_BORDER
        row += 1

        numeric_values = stats.numeric_values
        if not numeric_values:
            ws.cell(row=row, column=1, value="(无数值型标注)").border = self.THIN_BORDER
            return row + 1

        median_val = statistics.median(numeric_values)
        std_val = statistics.stdev(numeric_values) if len(numeric_values) > 1 else 0.0
        avg_val = statistics.mean(numeric_values)

        summary_data = [
            ("最小值", stats.value_min),
            ("最大值", stats.value_max),
            ("平均值", round(avg_val, 4)),
            ("中位数", round(median_val, 4)),
            ("标准差", round(std_val, 4)),
            ("数值标注数", len(numeric_values)),
        ]
        for label, val in summary_data:
            ws.cell(row=row, column=1, value=label).border = self.THIN_BORDER
            c = ws.cell(row=row, column=2, value=val)
            c.border = self.THIN_BORDER
            c.alignment = Alignment(horizontal="center")
            row += 1

        row += 1  # 空行

        # 异常值检测
        cell = ws.cell(row=row, column=1, value="异常值检测（偏离均值 > 2倍标准差）")
        cell.font = Font(name="微软雅黑", size=10, bold=True, color="C00000")
        cell.border = self.THIN_BORDER
        for col in range(2, 5):
            ws.cell(row=row, column=col).border = self.THIN_BORDER
        row += 1

        # 列头
        for col_idx, header in enumerate(["标注内容", "数值", "偏差量", "序号"], start=1):
            cell = ws.cell(row=row, column=col_idx, value=header)
            cell.font = Font(name="微软雅黑", size=10, bold=True)
            cell.alignment = Alignment(horizontal="center")
            cell.border = self.THIN_BORDER
        row += 1

        outlier_count = 0
        if std_val > 0:
            threshold = 2 * std_val
            for item in all_items:
                val = self._try_parse_float(item.content)
                if val is not None and abs(val - avg_val) > threshold:
                    deviation = val - avg_val
                    ws.cell(row=row, column=1, value=item.content).border = self.THIN_BORDER
                    c_val = ws.cell(row=row, column=2, value=round(val, 4))
                    c_val.font = self.OUTLIER_FONT
                    c_val.border = self.THIN_BORDER
                    c_val.alignment = Alignment(horizontal="center")

                    c_dev = ws.cell(row=row, column=3, value=round(deviation, 4))
                    c_dev.font = self.OUTLIER_FONT
                    c_dev.border = self.THIN_BORDER
                    c_dev.alignment = Alignment(horizontal="center")

                    c_idx = ws.cell(row=row, column=4, value=item.index)
                    c_idx.border = self.THIN_BORDER
                    c_idx.alignment = Alignment(horizontal="center")

                    row += 1
                    outlier_count += 1

        if outlier_count == 0:
            ws.cell(row=row, column=1, value="(未检测到异常值)").border = self.THIN_BORDER
            row += 1

        return row

    # ------------------------------------------------------------------
    # Sheet 3: 按图层分组视图
    # ------------------------------------------------------------------

    def _write_layer_sheet(
        self,
        wb,
        all_items: list,
        columns: list[tuple[str, int, str]],
    ) -> None:
        """写入按图层分组 Sheet

        每个图层一个区域，列出该图层的所有标注项。图层名作为分组标题，
        用不同背景色区分图层。

        Args:
            wb: openpyxl Workbook 对象
            all_items: 所有标注项
            columns: 列定义
        """
        ws = wb.create_sheet("按图层分组")

        # 按图层分组
        layer_items: dict[str, list] = {}
        for item in all_items:
            layer = item.layer if item.layer else "(未命名图层)"
            if layer not in layer_items:
                layer_items[layer] = []
            layer_items[layer].append(item)

        row = 1
        col_count = len(columns)
        fill_idx = 0

        for layer_name, items in sorted(layer_items.items(), key=lambda x: x[0]):
            # 图层分组标题
            group_fill = self.LAYER_FILLS[fill_idx % len(self.LAYER_FILLS)]
            fill_idx += 1

            cell = ws.cell(row=row, column=1, value=f"图层: {layer_name} ({len(items)} 条)")
            cell.font = self.GROUP_HEADER_FONT
            cell.fill = group_fill
            cell.border = self.THIN_BORDER
            for col in range(2, col_count + 1):
                c = ws.cell(row=row, column=col)
                c.fill = group_fill
                c.border = self.THIN_BORDER
            row += 1

            # 列头
            for col_idx, (title, width, _) in enumerate(columns, start=1):
                cell = ws.cell(row=row, column=col_idx, value=title)
                cell.font = Font(name="微软雅黑", size=10, bold=True)
                cell.alignment = Alignment(horizontal="center")
                cell.border = self.THIN_BORDER
            row += 1

            # 数据行
            for item in items:
                record = self._item_to_record(item, columns)
                for col_idx, (title, _, _) in enumerate(columns, start=1):
                    cell = ws.cell(row=row, column=col_idx, value=record.get(title, ""))
                    cell.font = self.CELL_FONT
                    cell.alignment = self.CELL_ALIGNMENT
                    cell.border = self.THIN_BORDER
                row += 1

            row += 1  # 图层间空行

        # 列宽
        for col_idx, (_, width, _) in enumerate(columns, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        # 冻结首行
        ws.freeze_panes = "A2"

    # ------------------------------------------------------------------
    # 来源文件超链接
    # ------------------------------------------------------------------

    def _apply_hyperlinks(
        self,
        wb,
        sheet_name: str,
        col_idx: int,
    ) -> None:
        """将指定 Sheet 的指定列做 HYPERLINK 公式

        将来源文件路径转换为 =HYPERLINK("file:///path", "filename") 格式。

        Args:
            wb: openpyxl Workbook 对象
            sheet_name: 工作表名称
            col_idx: 列索引（1-based）
        """
        ws = wb[sheet_name]

        max_row = ws.max_row
        for row_idx in range(2, max_row + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            raw_path = cell.value
            if raw_path and isinstance(raw_path, str) and raw_path.strip():
                file_uri = raw_path.replace("\\", "/")
                if not file_uri.startswith("/"):
                    file_uri = "/" + file_uri
                display_name = Path(raw_path).name
                cell.value = f'=HYPERLINK("file://{file_uri}", "{display_name}")'
                cell.font = Font(name="微软雅黑", size=10, color="0563C1", underline="single")

    # ------------------------------------------------------------------
    # Sheet 4: 按文件分组视图
    # ------------------------------------------------------------------

    def _write_file_sheet(
        self,
        wb,
        all_items: list,
        columns: list[tuple[str, int, str]],
    ) -> None:
        """写入按文件分组 Sheet

        每个来源文件一个区域，列出该文件的所有标注项。文件名作为分组标题，
        用不同背景色区分文件。

        Args:
            wb: openpyxl Workbook 对象
            all_items: 所有标注项
            columns: 列定义
        """
        ws = wb.create_sheet("按文件分组")

        # 按来源文件分组
        file_items: dict[str, list] = {}
        for item in all_items:
            fname = item.source_file if item.source_file else "(未知文件)"
            # 显示友好文件名
            display_name = Path(fname).name if fname != "(未知文件)" else fname
            if display_name not in file_items:
                file_items[display_name] = []
            file_items[display_name].append(item)

        row = 1
        col_count = len(columns)
        fill_idx = 0

        for file_name, items in sorted(file_items.items(), key=lambda x: x[0]):
            # 文件分组标题
            group_fill = self.FILE_FILLS[fill_idx % len(self.FILE_FILLS)]
            fill_idx += 1

            cell = ws.cell(row=row, column=1, value=f"文件: {file_name} ({len(items)} 条)")
            cell.font = self.GROUP_HEADER_FONT
            cell.fill = group_fill
            cell.border = self.THIN_BORDER
            for col in range(2, col_count + 1):
                c = ws.cell(row=row, column=col)
                c.fill = group_fill
                c.border = self.THIN_BORDER
            row += 1

            # 列头
            for col_idx, (title, width, _) in enumerate(columns, start=1):
                cell = ws.cell(row=row, column=col_idx, value=title)
                cell.font = Font(name="微软雅黑", size=10, bold=True)
                cell.alignment = Alignment(horizontal="center")
                cell.border = self.THIN_BORDER
            row += 1

            # 数据行
            for item in items:
                record = self._item_to_record(item, columns)
                for col_idx, (title, _, field_name) in enumerate(columns, start=1):
                    value = record.get(title, "")
                    cell = ws.cell(row=row, column=col_idx, value=value)
                    cell.font = self.CELL_FONT
                    cell.alignment = self.CELL_ALIGNMENT
                    cell.border = self.THIN_BORDER

                    # 数值列右对齐
                    if field_name in self.NUMERIC_FIELDS:
                        cell.alignment = self.NUMBER_ALIGNMENT
                        if isinstance(value, (int, float)):
                            if field_name in ("x", "y", "height"):
                                cell.number_format = "0.0000"
                            elif field_name == "rotation":
                                cell.number_format = "0.00"

                    # 标注类型列颜色区分
                    if field_name == "annotation_type" and isinstance(value, str):
                        color = self.TYPE_COLOR_MAP.get(value)
                        if color:
                            cell.font = Font(
                                name="微软雅黑", size=10, bold=True, color=color,
                            )

                    # 空值标记
                    if value is None or (isinstance(value, str) and str(value).strip() == ""):
                        cell.fill = self.EMPTY_CELL_FILL

                row += 1

            row += 1  # 文件间空行

        # 列宽
        for col_idx, (_, width, _) in enumerate(columns, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        # 冻结首行
        ws.freeze_panes = "A2"

    # ------------------------------------------------------------------
    # 格式化（保留原有功能 + 条件格式增强）
    # ------------------------------------------------------------------

    def _apply_formatting(
        self,
        wb,
        columns: Optional[list[tuple[str, int, str]]] = None,
        all_items: Optional[list] = None,
    ) -> None:
        """对已生成的 Excel 文件应用格式化样式

        增强功能：
        - 数值列（X坐标、Y坐标、文字高度、旋转角度）右对齐并保留适当小数位
        - 标注类型列添加颜色区分
        - 空值单元格用浅灰色背景标记
        - 超长文本（>50字符）截断显示，鼠标悬停提示完整内容

        Args:
            wb: openpyxl Workbook 对象
            columns: 列定义，为 None 时使用默认 COLUMNS
            all_items: 所有标注项列表（用于条件格式化时获取原始值）
        """
        active_columns = columns if columns is not None else self.ALL_COLUMNS[:7]
        col_count = len(active_columns)

        ws = wb["标注明细"]

        # 预计算每个列索引对应的字段名
        col_field_map: dict[int, str] = {}
        for col_idx, (_, _, field_name) in enumerate(active_columns, start=1):
            col_field_map[col_idx] = field_name

        # 找到标注类型列索引
        type_col_idx: Optional[int] = None
        for col_idx, (_, _, field_name) in enumerate(active_columns, start=1):
            if field_name == "annotation_type":
                type_col_idx = col_idx
                break

        # 2. 表头行设置：字体、填充、对齐、边框
        for col_idx in range(1, col_count + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = self.HEADER_FONT
            cell.fill = self.HEADER_FILL
            cell.alignment = self.HEADER_ALIGNMENT
            cell.border = self.THIN_BORDER

        # 3. 数据行设置：字体、对齐、边框 + 条件格式增强
        max_row = ws.max_row
        for row_idx in range(2, max_row + 1):
            for col_idx in range(1, col_count + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.font = self.CELL_FONT
                cell.alignment = self.CELL_ALIGNMENT
                cell.border = self.THIN_BORDER

                field_name = col_field_map.get(col_idx, "")
                cell_value = cell.value

                # 3.1 数值列右对齐并保留适当小数位
                if field_name in self.NUMERIC_FIELDS:
                    cell.alignment = self.NUMBER_ALIGNMENT
                    if isinstance(cell_value, (int, float)):
                        if field_name in ("x", "y", "height"):
                            cell.number_format = "0.0000"
                        elif field_name == "rotation":
                            cell.number_format = "0.00"

                # 3.2 标注类型列颜色区分
                if col_idx == type_col_idx and cell_value and isinstance(cell_value, str):
                    color = self.TYPE_COLOR_MAP.get(cell_value)
                    if color:
                        cell.font = Font(
                            name="微软雅黑", size=10, bold=True, color=color,
                        )

                # 3.3 空值单元格浅灰色背景标记
                if cell_value is None or (isinstance(cell_value, str) and cell_value.strip() == ""):
                    cell.fill = self.EMPTY_CELL_FILL

                # 3.4 超长文本截断显示，添加批注作为悬停提示
                if isinstance(cell_value, str) and len(cell_value) > self.TRUNCATE_THRESHOLD:
                    full_text = cell_value
                    truncated = cell_value[: self.TRUNCATE_THRESHOLD - 3] + "..."
                    cell.value = truncated
                    from openpyxl.comments import Comment
                    cell.comment = Comment(full_text, "ExcelReporter", width=400, height=200)

        # 4. 列宽按列定义设置
        for col_idx, (_, width, _) in enumerate(active_columns, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        # 5. 冻结首行 A2
        ws.freeze_panes = "A2"

        # 6. 添加自动筛选
        ws.auto_filter.ref = ws.dimensions
