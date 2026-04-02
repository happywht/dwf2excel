"""数据模型定义

定义标注类型枚举、标注项数据模型、解析结果、回写配置和导出配置等核心数据结构。
所有模块之间的数据交换均通过本文件定义的模型进行。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AnnotationType(Enum):
    """标注类型枚举"""
    # --- 尺寸标注 ---
    DIM_LINEAR = "线性标注"
    DIM_ALIGNED = "对齐标注"
    DIM_ANGULAR = "角度标注"
    DIM_RADIUS = "半径标注"
    DIM_DIAMETER = "直径标注"
    DIM_ORDINATE = "坐标标注"
    DIM_ARC_LENGTH = "弧长标注"
    DIM_UNKNOWN = "未知标注"
    # --- 文字 ---
    TEXT = "单行文字"
    MTEXT = "多行文字"
    # --- 引线标注 ---
    LEADER = "引线标注"
    MULTILEADER = "多重引线"
    # --- 表格 ---
    TABLE = "表格"
    # --- 公差 ---
    TOLERANCE = "公差标注"
    # --- 属性 ---
    ATTDEF = "属性定义"
    ATTRIB = "属性值"


class NumberStyle(Enum):
    """序号样式枚举"""
    CIRCLED = "带圈序号"      # ①②③
    BRACKETED = "带括号序号"  # [1][2][3]
    DASH = "短横序号"         # -1- -2- -3-
    DOT = "点号序号"          # 1. 2. 3.
    CUSTOM = "自定义序号"     # 使用 config.custom_format 模板


class ContentCategory(Enum):
    """标注内容智能分类"""
    DIMENSION = "尺寸值"
    ELEVATION = "标高"
    PIPE_DIAMETER = "管径"
    SLOPE = "坡度"
    ANGLE_VALUE = "角度"
    COORDINATE = "坐标"
    GENERAL_NOTE = "一般注释"
    UNKNOWN = "未分类"


@dataclass
class AnnotationItem:
    """单条标注记录"""
    # --- 基本标识 ---
    index: int                          # 序号
    content: str                        # 标注内容（清洗后的纯文本）
    x: float                            # 标注位置 X 坐标
    y: float                            # 标注位置 Y 坐标
    annotation_type: AnnotationType     # 标注类型
    # --- 来源信息 ---
    layer: str = ""                     # 所在图层
    style: str = ""                     # 标注样式名
    source_file: str = ""               # 来源文件路径
    handle: str = ""                    # 实体句柄（唯一标识）
    raw_entity_type: str = ""           # 原始实体类型字符串
    # --- 扩展位置 ---
    x2: float = 0.0                     # 第二点 X（用于标注范围）
    y2: float = 0.0                     # 第二点 Y
    # --- 文字属性 ---
    height: float = 0.0                 # 文字高度
    rotation: float = 0.0               # 旋转角度（度）
    color: int = -1                     # 颜色索引
    font_name: str = ""                 # 字体名
    # --- 上下文 ---
    block_name: str = ""                # 所属图块名
    paper_space: bool = False           # 是否来自图纸空间
    raw_content: str = ""               # 原始格式文本（MTEXT未清洗的）
    # --- 智能分类 ---
    category: ContentCategory = ContentCategory.UNKNOWN  # 内容自动分类


@dataclass
class ParseResult:
    """文件解析结果"""
    file_path: str                                          # 解析的文件路径
    items: list[AnnotationItem] = field(default_factory=list)  # 标注项列表
    error: Optional[str] = None                             # 错误信息
    total_count: int = 0                                    # 标注总数
    dimension_count: int = 0                                # 尺寸标注数
    text_count: int = 0                                     # 文字标注数
    leader_count: int = 0                                   # 引线标注数
    table_count: int = 0                                    # 表格数
    model_space_count: int = 0                              # 模型空间标注数
    paper_space_count: int = 0                              # 图纸空间标注数


@dataclass
class WriteBackConfig:
    """回写配置"""
    number_style: NumberStyle = NumberStyle.CIRCLED  # 序号样式
    offset_x: float = 5.0                            # X 偏移量
    offset_y: float = 5.0                            # Y 偏移量
    text_height: float = 3.0                         # 文字高度
    layer_name: str = "ANNOTATION_IDX"               # 回写图层名
    color: int = 1                                    # 颜色索引（1=红色）
    export_dwg: bool = False                          # 是否导出为 DWG 格式
    prefix: str = ""                                  # 序号前缀
    suffix: str = ""                                  # 序号后缀
    auto_text_height: bool = True                     # 自动适配文字高度
    custom_format: str = ""                            # 自定义序号格式模板（NumberStyle.CUSTOM 时使用，{index} 为占位符）


@dataclass
class ExportConfig:
    """导出配置"""
    include_summary: bool = True          # 是否包含汇总统计页
    include_layer_view: bool = True       # 是否包含按图层分组页
    include_file_view: bool = True        # 是否包含按文件分组页
    include_csv: bool = True              # 是否同时导出 CSV
    include_json: bool = False            # 是否同时导出 JSON
    selected_columns: list[str] = field(default_factory=list)  # 选中的列，空则全部
    hyperlink_source: bool = True         # 来源文件列是否做超链接


@dataclass
class SummaryStats:
    """标注数据统计摘要"""
    total_items: int = 0
    dimension_count: int = 0
    text_count: int = 0
    leader_count: int = 0
    table_count: int = 0
    layer_counts: dict[str, int] = field(default_factory=dict)        # 图层→数量
    type_counts: dict[str, int] = field(default_factory=dict)         # 类型→数量
    file_counts: dict[str, int] = field(default_factory=dict)         # 文件→数量
    category_counts: dict[str, int] = field(default_factory=dict)     # 分类→数量
    numeric_values: list[float] = field(default_factory=list)         # 所有数值型标注值
    value_min: Optional[float] = None
    value_max: Optional[float] = None
    value_avg: Optional[float] = None
