"""DWG/DXF 回写模块

在原始 DWG/DXF 图纸中标注位置偏移处插入编号文本，
实现图纸标注序号的可视化回写。
"""

from pathlib import Path
from typing import Optional, Callable

import ezdxf

from core.models import AnnotationItem, WriteBackConfig, NumberStyle


class DWGWriter:
    """DWG/DXF 标注编号回写器

    在标注位置附近插入带圈或带括号的序号文本，便于图纸上
    快速定位每条标注记录。
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
        4. 在每个标注位置的偏移处插入编号文本
        5. 保存为新文件

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

        # 4. 遍历并插入编号文本
        for idx, item in enumerate(matched_items, start=1):
            label = self._format_number(item.index)

            insert_x = item.x + self.config.offset_x
            insert_y = item.y + self.config.offset_y

            msp.add_text(
                label,
                dxfattribs={
                    "insert": (insert_x, insert_y),
                    "height": self.config.text_height,
                    "layer": self.config.layer_name,
                    "color": self.config.color,
                    "style": "Standard",
                },
            )

            # 5. 进度回调
            if progress_callback is not None:
                progress_callback(idx, total)

        # 6. 保存输出文件
        doc.saveas(str(output))

        return str(output)

    def _format_number(self, index: int) -> str:
        """根据配置的序号样式格式化编号

        Args:
            index: 序号（从 1 开始）

        Returns:
            格式化后的序号字符串，例如 "①" 或 "(1)"
        """
        if self.config.number_style == NumberStyle.CIRCLED:
            # 带圈样式：查映射表，超出范围降级为括号样式
            circled = self.CIRCLED_NUMBERS.get(index)
            if circled is not None:
                return circled
            # 降级为括号
            return f"({index})"
        else:
            # BRACKETED 样式
            return f"({index})"
