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


# ===========================================================================
# 管线数据模型（Pipeline Data Models）
# ===========================================================================


class PipeSource(Enum):
    """管线数据来源类型"""
    XLS = "物探XLS"
    DWG_CENSUS = "普查DWG"
    DWG_DESIGN = "设计DWG"
    DWG_PLAN = "管综DWG"
    DAT = "DAT断面"
    UNKNOWN = "未知"


class PipeStatus(Enum):
    """管线状态"""
    EXISTING = "现状"
    PLANNED = "规划"
    DESIGNED = "设计"
    UNKNOWN = "未知"


@dataclass
class DiameterInfo:
    """管径解析结果

    将多种管径表示方式统一解析为结构化数据:
    - DN300 -> diameter_mm=300, diameter_type="DN"
    - 16孔 -> hole_count=16, diameter_type="孔数"
    - ￠600X400 -> casing_width=600, casing_height=400, diameter_type="套管"
    - 1孔 1根 -> hole_count=1, cable_count=1, diameter_type="孔根"
    """
    raw: str = ""                          # 原始文本
    diameter_mm: Optional[float] = None    # 管径(mm)
    hole_count: Optional[int] = None       # 总孔数（通信/电力）
    hole_used: Optional[int] = None        # 占用孔数
    casing_width: Optional[float] = None   # 套管宽度(mm)
    casing_height: Optional[float] = None  # 套管高度(mm)
    cable_count: Optional[int] = None      # 电缆条数
    diameter_type: str = ""                # 解析类型
    is_valid: bool = False                 # 解析是否成功

    def to_summary(self) -> str:
        """生成摘要文本"""
        if self.diameter_mm is not None:
            return f"{self.diameter_mm:.0f}mm"
        if self.hole_count is not None:
            return f"{self.hole_count}孔"
        if self.casing_width is not None:
            return f"{self.casing_width:.0f}x{self.casing_height:.0f}"
        return self.raw or "未知"


@dataclass
class PipelinePoint:
    """管线点统一数据模型

    适用于所有来源（XLS/DWG/DAT）的管线点数据。
    设计参考：全样本综合分析汇总报告 6.3
    """
    # --- 基础标识 ---
    point_id: str = ""                  # 主点号
    map_point_id: str = ""              # 图上点号
    source_file: str = ""               # 来源文件名
    source_type: PipeSource = field(default=PipeSource.UNKNOWN)

    # --- 管线属性 ---
    pipe_type: str = ""                  # 管种（标准化后）
    pipe_type_raw: str = ""              # 原始管种名称
    feature_type: str = ""               # 特征点类型
    material: str = ""                   # 材质
    diameter_info: DiameterInfo = field(default_factory=DiameterInfo)

    # --- 空间信息 ---
    coord_x: Optional[float] = None     # 纵坐标(X)
    coord_y: Optional[float] = None     # 横坐标(Y)
    ground_elevation: Optional[float] = None  # 地面高程
    pipe_top_elev: Optional[float] = None     # 管顶高程
    pipe_bot_elev: Optional[float] = None     # 管底高程
    burial_depth: Optional[float] = None      # 埋深

    # --- 连接关系 ---
    direction_point_ids: list = field(default_factory=list)

    # --- 元数据 ---
    layer_name: str = ""
    block_name: str = ""
    block_code: str = ""
    station: str = ""
    remark: str = ""

    # --- 计算字段 ---
    pipe_category: str = ""
    status: PipeStatus = field(default=PipeStatus.UNKNOWN)

    def update_computed_fields(self):
        """更新计算字段"""
        from config.pipeline_config import PIPE_CATEGORY_MAP
        self.pipe_category = PIPE_CATEGORY_MAP.get(self.pipe_type, self.pipe_type)


@dataclass
class PipelineConnection:
    """管线连接关系（边）"""
    from_point_id: str = ""
    to_point_id: str = ""
    from_map_id: str = ""
    to_map_id: str = ""
    pipe_type: str = ""
    source_file: str = ""


@dataclass
class PipelineStats:
    """管线数据统计摘要"""
    total_points: int = 0
    total_connections: int = 0
    pipe_type_counts: dict = field(default_factory=dict)
    feature_type_counts: dict = field(default_factory=dict)
    material_counts: dict = field(default_factory=dict)
    source_file_counts: dict = field(default_factory=dict)
    coord_x_range: tuple = (None, None)
    coord_y_range: tuple = (None, None)
    depth_range: tuple = (None, None)
    diameter_range: tuple = (None, None)


@dataclass
class PipelineParseResult:
    """管线数据解析结果"""
    points: list = field(default_factory=list)
    connections: list = field(default_factory=list)
    stats: PipelineStats = field(default_factory=PipelineStats)
    source_file: str = ""
    source_type: PipeSource = PipeSource.UNKNOWN
    error_message: str = ""
    parse_time_ms: float = 0.0
