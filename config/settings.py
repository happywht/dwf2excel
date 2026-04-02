"""全局配置常量与应用持久化配置"""

import dataclasses
import json
import msvcrt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.models import NumberStyle, WriteBackConfig

# ---------------------------------------------------------------------------
# 应用信息
# ---------------------------------------------------------------------------
APP_TITLE = "DWG标注提取与回写工具"
APP_VERSION = "1.1.0"
APP_GEOMETRY = "1100x750"
APP_MIN_SIZE = (900, 600)

# ---------------------------------------------------------------------------
# 默认回写配置
# ---------------------------------------------------------------------------
DEFAULT_WRITE_BACK_CONFIG = WriteBackConfig(
    number_style=NumberStyle.CIRCLED,
    offset_x=5.0,
    offset_y=5.0,
    text_height=3.0,
    layer_name="ANNOTATION_IDX",
    color=1,  # 红色
)

# ---------------------------------------------------------------------------
# 默认导出配置
# ---------------------------------------------------------------------------
DEFAULT_EXPORT_CONFIG = {
    "include_summary": True,
    "include_layer_view": True,
    "include_csv": True,
    "include_json": False,
}

# ---------------------------------------------------------------------------
# 支持的文件后缀
# ---------------------------------------------------------------------------
SUPPORTED_EXTENSIONS = {".dwg", ".dxf"}

# ---------------------------------------------------------------------------
# 性能相关常量
# ---------------------------------------------------------------------------
CACHE_ENABLED: bool = True
MAX_WORKERS: int = 4

# ---------------------------------------------------------------------------
# 日志格式
# ---------------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"

# ---------------------------------------------------------------------------
# 配置文件路径
# ---------------------------------------------------------------------------
_CONFIG_PATH = Path.home() / ".dwg_annotool_config.json"

# 配置版本常量
CONFIG_VERSION = "2.0"


# ---------------------------------------------------------------------------
# 文件锁（Windows 平台，使用 msvcrt）
# ---------------------------------------------------------------------------

class _FileLock:
    """Windows 平台文件锁，使用 msvcrt.locking 实现互斥访问。"""

    def __init__(self, lock_path: Path):
        self._lock_path = lock_path
        self._fd = None

    def acquire(self) -> None:
        """获取文件锁，阻塞直到成功。"""
        self._fd = open(self._lock_path, "w")
        while True:
            try:
                msvcrt.locking(self._fd.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                import time
                time.sleep(0.05)

    def release(self) -> None:
        """释放文件锁。"""
        if self._fd is not None:
            try:
                msvcrt.locking(self._fd.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            finally:
                self._fd.close()
                self._fd = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


def _get_config_lock_path() -> Path:
    """获取配置文件锁路径。"""
    return Path(str(_CONFIG_PATH) + ".lock")


# ---------------------------------------------------------------------------
# AppConfig 持久化配置数据类
# ---------------------------------------------------------------------------
@dataclass
class AppConfig:
    """应用持久化配置"""

    # 配置版本
    version: str = CONFIG_VERSION
    # 目录记忆
    last_file_dir: str = ""
    last_output_dir: str = ""
    # 回写配置
    number_style: str = "CIRCLED"
    offset_x: float = 5.0
    offset_y: float = 5.0
    text_height: float = 3.0
    layer_name: str = "ANNOTATION_IDX"
    color: int = 1
    export_dwg: bool = False
    prefix: str = ""
    suffix: str = ""
    auto_text_height: bool = True
    # 导出配置
    include_summary: bool = True
    include_layer_view: bool = True
    include_csv: bool = True
    include_json: bool = False
    # 窗口配置
    window_geometry: str = "1100x750"
    window_maximized: bool = False
    # 外观与语言
    theme: str = "default"
    language: str = "zh_CN"
    # 最近文件与目录
    recent_files: list[str] = field(default_factory=list)
    recent_dirs: list[str] = field(default_factory=list)
    # 日志与缓存
    log_level: str = "INFO"
    max_cache_size_mb: int = 500
    auto_save_config: bool = True


# ---------------------------------------------------------------------------
# 配置版本迁移
# ---------------------------------------------------------------------------

def migrate_config(data: dict, from_version: str) -> dict:
    """处理配置版本迁移，将旧版本配置升级到当前版本。

    Args:
        data: 从文件加载的原始配置字典
        from_version: 原始配置版本号

    Returns:
        迁移后的配置字典
    """
    # 从 1.x（无 version 字段）迁移到 2.0
    if from_version < "2.0":
        # v1.x 没有的字段，添加默认值
        new_fields = {
            "version": CONFIG_VERSION,
            "window_geometry": "1100x750",
            "window_maximized": False,
            "theme": "default",
            "language": "zh_CN",
            "recent_files": [],
            "recent_dirs": [],
            "log_level": "INFO",
            "max_cache_size_mb": 500,
            "auto_save_config": True,
        }
        for key, default_value in new_fields.items():
            if key not in data:
                data[key] = default_value

    # 确保版本号为当前版本
    data["version"] = CONFIG_VERSION

    # 确保 recent_files 和 recent_dirs 不超过限制
    if "recent_files" in data and isinstance(data["recent_files"], list):
        data["recent_files"] = data["recent_files"][:10]
    if "recent_dirs" in data and isinstance(data["recent_dirs"], list):
        data["recent_dirs"] = data["recent_dirs"][:5]

    return data


def save_config(config: AppConfig) -> None:
    """将 AppConfig 保存到用户主目录下的 JSON 文件。

    使用文件锁防止多实例写入冲突。

    Args:
        config: 应用配置实例
    """
    data = dataclasses.asdict(config)
    lock = _FileLock(_get_config_lock_path())
    with lock:
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def load_config() -> AppConfig:
    """从 JSON 文件加载 AppConfig。

    文件不存在时返回默认配置；JSON 中缺少的字段用 AppConfig 默认值填充。
    支持旧版本配置自动迁移。使用文件锁防止多实例读取冲突。

    Returns:
        AppConfig 实例
    """
    if not _CONFIG_PATH.exists():
        return AppConfig()

    lock = _FileLock(_get_config_lock_path())
    with lock:
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return AppConfig()

    # 检测配置版本，执行迁移
    file_version = data.get("version", "1.0")
    if file_version != CONFIG_VERSION:
        data = migrate_config(data, file_version)

    # 获取 AppConfig 所有字段的默认值
    defaults = dataclasses.asdict(AppConfig())

    # 用已保存的数据覆盖默认值，缺失字段保留默认值
    for key, default_value in defaults.items():
        if key not in data:
            data[key] = default_value

    # 只取 AppConfig 已定义的字段，忽略多余的键
    valid_keys = set(defaults.keys())
    filtered = {k: v for k, v in data.items() if k in valid_keys}

    return AppConfig(**filtered)


# ---------------------------------------------------------------------------
# 配置导入导出与重置
# ---------------------------------------------------------------------------

def export_config(config: AppConfig, file_path: str) -> None:
    """导出配置到指定文件。

    Args:
        config: 应用配置实例
        file_path: 导出文件路径（.json）
    """
    data = dataclasses.asdict(config)
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def import_config(file_path: str) -> AppConfig:
    """从文件导入配置。

    如果导入的配置缺少字段，使用默认值填充。支持旧版本配置自动迁移。

    Args:
        file_path: 配置文件路径（.json）

    Returns:
        AppConfig 实例
    """
    path = Path(file_path)
    if not path.exists():
        return AppConfig()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return AppConfig()

    # 检测配置版本，执行迁移
    file_version = data.get("version", "1.0")
    if file_version != CONFIG_VERSION:
        data = migrate_config(data, file_version)

    # 获取 AppConfig 所有字段的默认值
    defaults = dataclasses.asdict(AppConfig())

    # 用已保存的数据覆盖默认值，缺失字段保留默认值
    for key, default_value in defaults.items():
        if key not in data:
            data[key] = default_value

    # 只取 AppConfig 已定义的字段，忽略多余的键
    valid_keys = set(defaults.keys())
    filtered = {k: v for k, v in data.items() if k in valid_keys}

    return AppConfig(**filtered)


def reset_config() -> AppConfig:
    """重置为默认配置并保存。

    Returns:
        重置后的默认 AppConfig 实例
    """
    config = AppConfig()
    save_config(config)
    return config
