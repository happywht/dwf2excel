"""数据模型定义"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AnnotationType(Enum):
    """标注类型枚举"""
    DIM_LINEAR = "线性标注"
    DIM_ALIGNED = "对齐标注"
    DIM_ANGULAR = "角度标注"
    DIM_RADIUS = "半径标注"
    DIM_DIAMETER = "直径标注"
    DIM_ORDINATE = "坐标标注"
    DIM_ARC_LENGTH = "弧长标注"
    DIM_UNKNOWN = "未知标注"
    TEXT = "单行文字"
    MTEXT = "多行文字"


class NumberStyle(Enum):
    """序号样式枚举"""
    CIRCLED = "带圈序号"      # ①②③
    BRACKETED = "带括号序号"  # [1][2][3]


@dataclass
class AnnotationItem:
    """单条标注记录"""
    index: int                          # 序号
    content: str                        # 标注内容（测量值或文字内容）
    x: float                            # 标注位置 X 坐标
    y: float                            # 标注位置 Y 坐标
    annotation_type: AnnotationType     # 标注类型
    layer: str = ""                     # 所在图层
    style: str = ""                     # 标注样式名
    source_file: str = ""               # 来源文件路径
    handle: str = ""                    # 实体句柄（唯一标识）
    raw_entity_type: str = ""           # 原始实体类型字符串


@dataclass
class ParseResult:
    """文件解析结果"""
    file_path: str                                          # 解析的文件路径
    items: list[AnnotationItem] = field(default_factory=list)  # 标注项列表
    error: Optional[str] = None                             # 错误信息
    total_count: int = 0                                    # 标注总数
    dimension_count: int = 0                                # 尺寸标注数
    text_count: int = 0                                     # 文字标注数


@dataclass
class WriteBackConfig:
    """回写配置"""
    number_style: NumberStyle = NumberStyle.CIRCLED  # 序号样式
    offset_x: float = 5.0                            # X 偏移量
    offset_y: float = 5.0                            # Y 偏移量
    text_height: float = 3.0                         # 文字高度
    layer_name: str = "ANNOTATION_IDX"               # 回写图层名
    color: int = 1                                    # 颜色索引（1=红色）
