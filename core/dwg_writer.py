"""DWG/DXF 回写模块

在原始 DWG/DXF 图纸中标注位置偏移处插入编号文本，
实现图纸标注序号的可视化回写。

增强功能：
- DWG 格式导出（通过 ODA File Converter）
- 序号文字高度自适应
- 自定义序号前缀/后缀
- 序号位置智能避让
- 回写预览数据生成
- 多种序号样式（带圈、括号、短横、点号、自定义）
- 增强预览（含原始标注内容、类型、图层、预计文字高度）
- 批量回写优化（复用 ezdxf document）
- 回写撤销功能（删除指定图层实体）
"""

import logging
import statistics
from pathlib import Path
from typing import Optional, Callable

import ezdxf

from core.models import AnnotationItem, WriteBackConfig, NumberStyle

logger = logging.getLogger(__name__)


class DWGWriter:
    """DWG/DXF 标注编号回写器

    在标注位置附近插入带圈或带括号的序号文本，便于图纸上
    快速定位每条标注记录。

    支持多种序号样式：带圈、括号、短横、点号、自定义。
    支持批量回写优化和回写撤销。
    """

    # 带圈数字映射表
    # ①-⑳ (1-20): U+2460 起
    # ㉑-㉟ (21-35): U+3251 起
    # ㊱-㊿ (36-50): U+32B1 起
    CIRCLED_NUMBERS: dict[int, str] = {}

    # 初始化带圈数字映射
    for _i in range(1, 21):
        CIRCLED_NUMBERS[_i] = chr(0x2460 + _i - 1)
    for _i in range(21, 36):
        CIRCLED_NUMBERS[_i] = chr(0x3251 + _i - 21)
    for _i in range(36, 51):
        CIRCLED_NUMBERS[_i] = chr(0x32B1 + _i - 36)

    def __init__(self, config: Optional[WriteBackConfig] = None) -> None:
        """初始化回写器

        Args:
            config: 回写配置，若为 None 则使用默认配置
        """
        self.config: WriteBackConfig = config if config is not None else WriteBackConfig()

    def write_back(
        self,
        file_path: str,
        items: list[AnnotationItem],
        output_path: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> str:
        """将标注序号回写到 DWG/DXF 文件

        流程：
        1. 确定输出路径（默认在原文件名后加 _indexed 后缀）
        2. 以只读方式打开原始文件（不修改原文件）
        3. 筛选出属于当前文件的标注项
        4. 计算文字高度（如果启用自适应）
        5. 在每个标注位置的偏移处插入编号文本（支持智能避让）
        6. 保存为新文件
        7. 如果启用 DWG 导出，将 DXF 转换为 DWG

        Args:
            file_path: 原始 DWG/DXF 文件路径
            items: 全部标注项列表（仅处理 source_file 匹配的项）
            output_path: 输出文件路径，为 None 时自动生成
            progress_callback: 进度回调，签名为 callback(current_index, total_count)

        Returns:
            输出文件的绝对路径字符串

        Raises:
            FileNotFoundError: 原始文件不存在
            ValueError: 文件格式不支持或无匹配标注项
            ezdxf.DXFError: DXF 文件解析错误
        """
        src = Path(file_path).resolve()

        # 1. 确定输出路径
        if output_path is None:
            output = src.with_stem(src.stem + "_indexed")
        else:
            output = Path(output_path).resolve()

        # 确保输出目录存在
        output.parent.mkdir(parents=True, exist_ok=True)

        # 2. 打开原始文件（不修改原文件）
        doc = ezdxf.readfile(str(src))
        msp = doc.modelspace()

        # 3. 筛选属于当前文件的标注项
        src_name = str(src)
        matched_items = [
            item for item in items
            if item.source_file == src_name or Path(item.source_file).resolve() == src
        ]

        total = len(matched_items)

        # 4. 计算文字高度（自适应）
        text_height = self._compute_text_height(matched_items)

        # 5. 收集已有文字实体位置（用于智能避让）
        existing_positions = self._collect_existing_text_positions(msp)

        # 6. 遍历并插入编号文本
        for idx, item in enumerate(matched_items, start=1):
            label = self._format_number(item.index)

            insert_x = item.x + self.config.offset_x
            insert_y = item.y + self.config.offset_y

            # 智能避让：检测并偏移
            insert_x, insert_y = self._avoid_collision(
                insert_x, insert_y, text_height, existing_positions
            )

            msp.add_text(
                label,
                dxfattribs={
                    "insert": (insert_x, insert_y),
                    "height": text_height,
                    "layer": self.config.layer_name,
                    "color": self.config.color,
                    "style": "Standard",
                },
            )

            # 记录已插入位置，避免后续序号互相冲突
            existing_positions.append((insert_x, insert_y, text_height))

            # 7. 进度回调
            if progress_callback is not None:
                progress_callback(idx, total)

        # 8. 保存输出文件（DXF 格式）
        dxf_output = output
        if self.config.export_dwg:
            # 保存为临时 DXF，稍后转换为 DWG
            dxf_output = output.with_suffix(".dxf")

        doc.saveas(str(dxf_output))

        # 9. 如果需要导出 DWG 格式
        if self.config.export_dwg:
            dwg_output = output.with_suffix(".dwg")
            dwg_path = self._export_to_dwg(str(dxf_output), str(dwg_output))
            if dwg_path:
                return dwg_path

        return str(output.resolve())

    def write_back_batch(
        self,
        file_items_map: dict[str, list[AnnotationItem]],
        output_dir: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int, int], None]] = None,
    ) -> list[str]:
        """批量回写多个文件

        对多个文件进行批量回写，内部复用 ezdxf document 以减少重复加载开销。
        适用于同时处理多个 DWG/DXF 文件的场景。

        Args:
            file_items_map: 文件路径到标注项列表的映射。
                key 为原始 DWG/DXF 文件路径，
                value 为该文件对应的标注项列表。
            output_dir: 输出目录，为 None 时输出到原文件同目录。
                输出文件名自动添加 _indexed 后缀。
            progress_callback: 进度回调，签名为
                callback(file_index, total_files, current_item_index)

        Returns:
            输出文件绝对路径的列表，顺序与 file_items_map 的插入顺序一致。
            某个文件处理失败时对应位置为空字符串。

        Raises:
            ValueError: file_items_map 为空
        """
        if not file_items_map:
            raise ValueError("file_items_map 不能为空")

        total_files = len(file_items_map)
        output_paths: list[str] = []

        for file_idx, (file_path, items) in enumerate(file_items_map.items(), start=1):
            src = Path(file_path).resolve()

            if not src.exists():
                logger.error("文件不存在，跳过: %s", file_path)
                output_paths.append("")
                continue

            # 确定输出路径
            if output_dir is not None:
                out_dir = Path(output_dir)
                out_dir.mkdir(parents=True, exist_ok=True)
                output = out_dir / (src.stem + "_indexed" + src.suffix)
            else:
                output = src.with_stem(src.stem + "_indexed")

            try:
                doc = ezdxf.readfile(str(src))
                msp = doc.modelspace()

                # 筛选属于当前文件的标注项
                src_name = str(src)
                matched_items = [
                    item for item in items
                    if item.source_file == src_name or Path(item.source_file).resolve() == src
                ]

                text_height = self._compute_text_height(matched_items)
                existing_positions = self._collect_existing_text_positions(msp)

                for item_idx, item in enumerate(matched_items, start=1):
                    label = self._format_number(item.index)

                    insert_x = item.x + self.config.offset_x
                    insert_y = item.y + self.config.offset_y

                    insert_x, insert_y = self._avoid_collision(
                        insert_x, insert_y, text_height, existing_positions
                    )

                    msp.add_text(
                        label,
                        dxfattribs={
                            "insert": (insert_x, insert_y),
                            "height": text_height,
                            "layer": self.config.layer_name,
                            "color": self.config.color,
                            "style": "Standard",
                        },
                    )

                    existing_positions.append((insert_x, insert_y, text_height))

                    if progress_callback is not None:
                        progress_callback(file_idx, total_files, item_idx)

                # 保存输出
                dxf_output = output
                if self.config.export_dwg:
                    dxf_output = output.with_suffix(".dxf")

                doc.saveas(str(dxf_output))

                if self.config.export_dwg:
                    dwg_output = output.with_suffix(".dwg")
                    dwg_path = self._export_to_dwg(str(dxf_output), str(dwg_output))
                    if dwg_path:
                        output_paths.append(dwg_path)
                        continue

                output_paths.append(str(output.resolve()))

            except Exception as e:
                logger.error("批量回写文件失败 [%s]: %s", file_path, e)
                output_paths.append("")

        return output_paths

    def generate_preview_data(
        self,
        file_path: str,
        items: list[AnnotationItem],
    ) -> list[dict]:
        """生成回写预览数据，供 GUI 预览序号位置和内容

        增强版：返回更丰富的预览信息，包含原始标注内容、
        标注类型、图层名和预计的文字高度。

        不实际修改文件，仅计算序号将出现的位置和内容。

        Args:
            file_path: 原始 DWG/DXF 文件路径
            items: 全部标注项列表（仅处理 source_file 匹配的项）

        Returns:
            预览数据列表，每个元素为 dict，包含：
            - x: 插入 X 坐标
            - y: 插入 Y 坐标
            - text: 格式化后的序号文本
            - height: 预计的文字高度
            - original_content: 原始标注内容
            - annotation_type: 标注类型
            - layer: 图层名
            - estimated_height: 预计的文字高度（与 height 相同，语义更明确）
        """
        src = Path(file_path).resolve()
        src_name = str(src)

        matched_items = [
            item for item in items
            if item.source_file == src_name or Path(item.source_file).resolve() == src
        ]

        text_height = self._compute_text_height(matched_items)

        # 收集已有文字位置用于避让模拟
        try:
            doc = ezdxf.readfile(str(src))
            msp = doc.modelspace()
            existing_positions = self._collect_existing_text_positions(msp)
        except Exception:
            existing_positions = []

        preview_data: list[dict] = []
        for item in matched_items:
            label = self._format_number(item.index)

            insert_x = item.x + self.config.offset_x
            insert_y = item.y + self.config.offset_y

            # 模拟避让
            insert_x, insert_y = self._avoid_collision(
                insert_x, insert_y, text_height, existing_positions
            )

            preview_data.append({
                "x": round(insert_x, 4),
                "y": round(insert_y, 4),
                "text": label,
                "height": text_height,
                "original_content": item.content,
                "annotation_type": item.annotation_type.value,
                "layer": item.layer,
                "estimated_height": text_height,
            })

            # 记录到已存在列表，模拟后续避让
            existing_positions.append((insert_x, insert_y, text_height))

        return preview_data

    # ------------------------------------------------------------------
    # 序号格式化
    # ------------------------------------------------------------------

    def _format_number(self, index: int) -> str:
        """根据配置的序号样式格式化编号，支持前缀和后缀

        支持的样式：
        - CIRCLED: 带圈序号 ①②③（超出范围降级为括号）
        - BRACKETED: 带括号序号 (1)(2)(3)
        - DASH: 短横序号 -1- -2- -3-
        - DOT: 点号序号 1. 2. 3.
        - CUSTOM: 自定义格式（使用 config.custom_format 模板）

        Args:
            index: 序号（从 1 开始）

        Returns:
            格式化后的序号字符串，例如 "N-①" 或 "(1)-DN200"
        """
        style = self.config.number_style

        if style == NumberStyle.CIRCLED:
            # 带圈样式：查映射表，超出范围降级为括号样式
            circled = self.CIRCLED_NUMBERS.get(index)
            if circled is not None:
                number_str = circled
            else:
                # 降级为括号
                number_str = f"({index})"
        elif style == NumberStyle.BRACKETED:
            # 括号样式: (1)(2)(3)
            number_str = f"({index})"
        elif style == NumberStyle.DASH:
            # 短横样式: -1- -2- -3-
            number_str = f"-{index}-"
        elif style == NumberStyle.DOT:
            # 点号样式: 1. 2. 3.
            number_str = f"{index}."
        elif style == NumberStyle.CUSTOM:
            # 自定义格式模板：使用 {index} 作为占位符
            fmt = self.config.custom_format
            if fmt and "{index}" in fmt:
                number_str = fmt.format(index=index)
            else:
                # 无有效模板时降级为带圈样式
                circled = self.CIRCLED_NUMBERS.get(index)
                if circled is not None:
                    number_str = circled
                else:
                    number_str = f"({index})"
        else:
            # 未知样式降级为括号
            number_str = f"({index})"

        # 添加前缀和后缀
        result = number_str
        if self.config.prefix:
            result = f"{self.config.prefix}{result}"
        if self.config.suffix:
            result = f"{result}{self.config.suffix}"

        return result

    # ------------------------------------------------------------------
    # 文字高度自适应
    # ------------------------------------------------------------------

    def _compute_text_height(self, items: list[AnnotationItem]) -> float:
        """计算序号文字高度

        如果 config.auto_text_height 为 True 且有有效的标注高度数据，
        使用所有标注项文字高度的中位数作为回写高度。
        否则使用 config.text_height 固定值。

        Args:
            items: 当前文件的匹配标注项

        Returns:
            计算后的文字高度值
        """
        if not self.config.auto_text_height:
            return self.config.text_height

        heights = [item.height for item in items if item.height > 0]
        if not heights:
            return self.config.text_height

        # 使用中位数避免极端值干扰
        median_height = statistics.median(heights)
        if median_height > 0:
            return round(median_height, 4)

        return self.config.text_height

    # ------------------------------------------------------------------
    # 智能避让
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_existing_text_positions(msp) -> list[tuple[float, float, float]]:
        """收集模型空间中已有文字实体的位置和高度

        Args:
            msp: ezdxf 模型空间对象

        Returns:
            位置列表，每个元素为 (x, y, height)
        """
        positions = []
        try:
            for entity in msp:
                dxftype = entity.dxftype()
                if dxftype == "TEXT":
                    insert = entity.dxf.get("insert", None)
                    height = entity.dxf.get("height", 3.0)
                    if insert is not None:
                        positions.append((insert.x, insert.y, height))
                elif dxftype == "MTEXT":
                    insert = entity.dxf.get("insert", None)
                    height = entity.dxf.get("char_height", 3.0)
                    if insert is not None:
                        positions.append((insert.x, insert.y, height))
        except Exception as e:
            logger.debug("收集已有文字位置时出错: %s", e)

        return positions

    @staticmethod
    def _avoid_collision(
        x: float,
        y: float,
        height: float,
        existing_positions: list[tuple[float, float, float]],
        tolerance_factor: float = 1.5,
    ) -> tuple[float, float]:
        """检测并避免与已有文字实体的位置冲突

        简单实现：在四个方向（右上、右下、左上、左下）尝试偏移，
        找到第一个不冲突的位置。

        Args:
            x: 计划插入的 X 坐标
            y: 计划插入的 Y 坐标
            height: 文字高度
            existing_positions: 已有文字位置列表 (x, y, height)
            tolerance_factor: 碰撞检测的容差系数

        Returns:
            调整后的 (x, y) 坐标
        """
        def _is_colliding(px: float, py: float) -> bool:
            """检查给定位置是否与已有文字冲突"""
            for ex, ey, eh in existing_positions:
                threshold = max(height, eh) * tolerance_factor
                if abs(px - ex) < threshold and abs(py - ey) < threshold:
                    return True
            return False

        # 如果当前位置无冲突，直接返回
        if not _is_colliding(x, y):
            return x, y

        # 四个方向偏移尝试
        offset_distance = height * 2.0
        directions = [
            (offset_distance, offset_distance),      # 右上
            (offset_distance, -offset_distance),     # 右下
            (-offset_distance, offset_distance),     # 左上
            (-offset_distance, -offset_distance),    # 左下
            (offset_distance * 2, 0),                # 右
            (-offset_distance * 2, 0),               # 左
            (0, offset_distance * 2),                # 上
            (0, -offset_distance * 2),               # 下
        ]

        for dx, dy in directions:
            new_x = x + dx
            new_y = y + dy
            if not _is_colliding(new_x, new_y):
                return new_x, new_y

        # 所有方向都冲突，返回原位置（降级处理）
        logger.debug("所有避让方向均冲突，使用原位置 (%.2f, %.2f)", x, y)
        return x, y

    # ------------------------------------------------------------------
    # 回写撤销
    # ------------------------------------------------------------------

    @staticmethod
    def remove_annotations(
        input_path: str,
        layer_name: str,
        output_path: Optional[str] = None,
    ) -> str:
        """从 DWG/DXF 文件中删除指定图层上的所有实体（撤销回写操作）

        打开文件，删除指定图层上的所有实体，然后保存为新文件。
        通常用于撤销之前 write_back 操作插入的序号标注。

        Args:
            input_path: 输入 DWG/DXF 文件路径
            layer_name: 要清除的图层名称（如 "ANNOTATION_IDX"）
            output_path: 输出文件路径，为 None 时在原文件名后加 _cleaned 后缀

        Returns:
            输出文件的绝对路径字符串

        Raises:
            FileNotFoundError: 输入文件不存在
            ezdxf.DXFError: DXF 文件解析错误
        """
        src = Path(input_path).resolve()

        if not src.exists():
            raise FileNotFoundError(f"文件不存在: {src}")

        # 确定输出路径
        if output_path is None:
            output = src.with_stem(src.stem + "_cleaned")
        else:
            output = Path(output_path).resolve()

        output.parent.mkdir(parents=True, exist_ok=True)

        # 打开文件
        doc = ezdxf.readfile(str(src))
        msp = doc.modelspace()

        # 收集并删除指定图层上的所有实体
        entities_to_remove = []
        for entity in msp:
            try:
                entity_layer = entity.dxf.get("layer", "")
                if entity_layer == layer_name:
                    entities_to_remove.append(entity)
            except Exception:
                continue

        # 执行删除
        removed_count = 0
        for entity in entities_to_remove:
            try:
                msp.delete_entity(entity)
                removed_count += 1
            except Exception as e:
                logger.debug("删除实体失败: %s", e)

        logger.info(
            "已从图层 '%s' 删除 %d 个实体（共匹配 %d 个）",
            layer_name, removed_count, len(entities_to_remove),
        )

        # 如果指定图层没有任何实体，也删除图层定义
        if layer_name in doc.layers:
            # 检查是否还有其他空间使用此图层
            remaining_on_layer = False
            for entity in msp:
                try:
                    if entity.dxf.get("layer", "") == layer_name:
                        remaining_on_layer = True
                        break
                except Exception:
                    continue

            if not remaining_on_layer:
                try:
                    doc.layers.remove(layer_name)
                    logger.info("已删除图层定义: %s", layer_name)
                except Exception as e:
                    logger.debug("删除图层定义失败: %s", e)

        doc.saveas(str(output))

        return str(output.resolve())

    # ------------------------------------------------------------------
    # DWG 格式导出
    # ------------------------------------------------------------------

    def _export_to_dwg(self, dxf_path: str, dwg_path: str) -> Optional[str]:
        """将 DXF 文件转换为 DWG 格式

        使用 ezdxf 的 odafc addon，需要安装 ODA File Converter。
        自动检测并配置 odafc 路径。

        Args:
            dxf_path: 输入 DXF 文件路径
            dwg_path: 输出 DWG 文件路径

        Returns:
            成功返回 DWG 文件路径字符串，失败返回 None
        """
        try:
            # 导入并配置 odafc 路径
            from core.dwg_parser import _configure_odafc_path
            from ezdxf.addons import odafc

            if not _configure_odafc_path():
                logger.warning("ODA File Converter 未安装或未找到，无法导出 DWG 格式")
                return None

            if not odafc.is_installed():
                logger.warning("odafc 不可用，无法导出 DWG 格式")
                return None

            # 执行转换
            result = odafc.convert(
                str(dxf_path),
                output=str(Path(dwg_path).parent),
                export_format="dwg",
                replace=True,
            )

            if Path(dwg_path).exists():
                logger.info("DWG 导出成功: %s", dwg_path)
                return str(Path(dwg_path).resolve())

            logger.warning("DWG 导出未生成目标文件: %s", dwg_path)
            return None

        except Exception as e:
            logger.error("DWG 导出失败: %s", e)
            return None
