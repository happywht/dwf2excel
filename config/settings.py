"""全局配置常量"""

from core.models import NumberStyle, WriteBackConfig

# 应用信息
APP_TITLE = "DWG标注提取与回写工具"
APP_VERSION = "1.0.0"
APP_GEOMETRY = "1100x750"
APP_MIN_SIZE = (900, 600)

# 默认回写配置
DEFAULT_WRITE_BACK_CONFIG = WriteBackConfig(
    number_style=NumberStyle.CIRCLED,
    offset_x=5.0,
    offset_y=5.0,
    text_height=3.0,
    layer_name="ANNOTATION_IDX",
    color=1,  # 红色
)

# 支持的文件后缀
SUPPORTED_EXTENSIONS = {".dxf", ".dwg"}

# 日志格式
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"
