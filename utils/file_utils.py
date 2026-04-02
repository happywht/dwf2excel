"""文件操作辅助工具"""

import hashlib
import json
import os
import pickle
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional


def collect_files(paths: list[str], extensions: set[str]) -> list[str]:
    """
    从路径列表收集所有支持格式的文件

    Args:
        paths: 输入路径列表（可以是文件路径或目录路径）
        extensions: 允许的文件后缀集合，如 {".dxf", ".dwg"}

    Returns:
        符合后缀要求的文件绝对路径列表
    """
    result = []
    for path in paths:
        p = Path(path)
        if p.is_file():
            if p.suffix.lower() in extensions:
                result.append(str(p.resolve()))
        elif p.is_dir():
            for ext in extensions:
                # 使用 rglob 递归搜索
                for f in p.rglob(f"*{ext}"):
                    result.append(str(f.resolve()))
    return result


def get_output_path(
    input_path: str,
    suffix: str,
    output_dir: Optional[str] = None,
) -> str:
    """
    生成输出文件路径

    Args:
        input_path: 输入文件路径
        suffix: 输出文件后缀，如 "_annotated"
        output_dir: 输出目录，为 None 时与输入文件同目录

    Returns:
        输出文件的完整路径
    """
    p = Path(input_path)
    stem = p.stem + suffix
    ext = p.suffix

    if output_dir:
        out = Path(output_dir)
        ensure_dir(str(out))
        return str(out / f"{stem}{ext}")
    else:
        return str(p.parent / f"{stem}{ext}")


def ensure_dir(path: str) -> None:
    """
    确保目录存在，不存在则创建

    Args:
        path: 目录路径
    """
    os.makedirs(path, exist_ok=True)


# ---------------------------------------------------------------------------
# 文件信息与变更检测
# ---------------------------------------------------------------------------

def get_file_info(file_path: str) -> dict:
    """获取文件基本信息。

    Args:
        file_path: 文件路径

    Returns:
        包含 size（字节）和 mtime（修改时间戳）的字典。
        文件不存在时返回空字典。
    """
    try:
        stat = os.stat(file_path)
        return {
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        }
    except OSError:
        return {}


def has_file_changed(file_path: str, last_mtime: float) -> bool:
    """检查文件在给定时间戳之后是否被修改。

    Args:
        file_path: 文件路径
        last_mtime: 上次记录的修改时间戳

    Returns:
        True 表示文件已被修改或不存在，False 表示未修改。
    """
    info = get_file_info(file_path)
    if not info:
        return True
    return info["mtime"] > last_mtime


# ---------------------------------------------------------------------------
# 文件哈希计算
# ---------------------------------------------------------------------------

def compute_file_hash(file_path: str, algorithm: str = "md5") -> Optional[str]:
    """计算文件的哈希值，用于精确变更检测。

    Args:
        file_path: 文件路径
        algorithm: 哈希算法，支持 "md5" 或 "sha256"，默认 "md5"

    Returns:
        十六进制哈希字符串，文件不存在或读取失败时返回 None
    """
    try:
        h = hashlib.new(algorithm)
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(65536)  # 64KB 分块读取
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


# ---------------------------------------------------------------------------
# 文件变更监控（轮询方式）
# ---------------------------------------------------------------------------

def watch_file_changes(
    paths: list[str],
    callback: Callable[[str, dict], None],
    poll_interval: float = 2.0,
) -> threading.Thread:
    """通过轮询方式监控文件变更。

    在后台线程中周期性地检查文件列表的修改时间，当检测到变更时调用回调函数。
    线程为守护线程，主线程退出时自动结束。

    Args:
        paths: 要监控的文件路径列表
        callback: 变更回调函数，签名 callback(file_path: str, info: dict)，
                  info 包含 size 和 mtime
        poll_interval: 轮询间隔秒数，默认 2.0

    Returns:
        已启动的守护线程对象，可通过调用 stop()（设置 stop_event）来终止
    """
    stop_event = threading.Event()
    # 记录每个文件的上次 mtime
    last_mtimes: dict[str, float] = {}

    for p in paths:
        info = get_file_info(p)
        if info:
            last_mtimes[p] = info["mtime"]

    def _poll():
        while not stop_event.is_set():
            stop_event.wait(poll_interval)
            if stop_event.is_set():
                break
            for p in paths:
                info = get_file_info(p)
                if not info:
                    continue
                prev = last_mtimes.get(p, 0.0)
                if info["mtime"] > prev:
                    last_mtimes[p] = info["mtime"]
                    try:
                        callback(p, info)
                    except Exception:
                        pass  # 回调异常不应中断监控

    thread = threading.Thread(target=_poll, daemon=True)
    # 将 stop_event 绑定到线程对象上以便外部控制
    thread.stop_event = stop_event  # type: ignore[attr-defined]
    thread.start()
    return thread


# ---------------------------------------------------------------------------
# 批量文件操作
# ---------------------------------------------------------------------------

def batch_get_file_info(
    paths: list[str],
    max_workers: Optional[int] = None,
) -> dict[str, dict]:
    """批量获取文件信息（并行）。

    Args:
        paths: 文件路径列表
        max_workers: 最大并行线程数，默认为 min(len(paths), 8)

    Returns:
        字典，键为文件路径，值为 get_file_info 返回的信息字典
    """
    if not paths:
        return {}

    if max_workers is None:
        max_workers = min(len(paths), 8)

    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_path = {
            executor.submit(get_file_info, p): p for p in paths
        }
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                results[path] = future.result()
            except Exception:
                results[path] = {}

    return results


def validate_files(
    paths: list[str],
    extensions: Optional[set[str]] = None,
) -> dict[str, list[str]]:
    """验证文件列表，检查存在性、可读性和格式。

    Args:
        paths: 待验证的文件路径列表
        extensions: 允许的文件后缀集合，为 None 时不检查格式

    Returns:
        字典，包含两个键：
        - "valid": 有效文件路径列表
        - "invalid": 无效文件路径列表
    """
    valid: list[str] = []
    invalid: list[str] = []

    for p in paths:
        path = Path(p)
        # 检查存在性
        if not path.exists():
            invalid.append(p)
            continue
        # 检查是否为文件
        if not path.is_file():
            invalid.append(p)
            continue
        # 检查可读性
        if not os.access(p, os.R_OK):
            invalid.append(p)
            continue
        # 检查格式
        if extensions is not None and path.suffix.lower() not in extensions:
            invalid.append(p)
            continue
        valid.append(p)

    return {"valid": valid, "invalid": invalid}


# ---------------------------------------------------------------------------
# 解析结果缓存
# ---------------------------------------------------------------------------

_CACHE_DIR = Path.home() / ".dwg_annotool_cache"

# 缓存格式常量
CACHE_FORMAT_JSON = "json"
CACHE_FORMAT_PICKLE = "pickle"


def get_cache_dir() -> Path:
    """获取缓存目录路径，并确保目录存在。

    Returns:
        缓存目录的 Path 对象
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def get_cache_path(file_path: str, fmt: str = CACHE_FORMAT_JSON) -> Path:
    """根据文件路径生成缓存文件路径。

    使用文件绝对路径的 MD5 哈希作为缓存文件名，避免路径中的特殊字符问题。

    Args:
        file_path: 原始文件路径
        fmt: 缓存格式，"json" 或 "pickle"

    Returns:
        缓存文件的 Path 对象
    """
    abs_path = str(Path(file_path).resolve())
    name_hash = hashlib.md5(abs_path.encode("utf-8")).hexdigest()
    ext = ".json" if fmt == CACHE_FORMAT_JSON else ".pkl"
    return get_cache_dir() / f"{name_hash}{ext}"


def save_cache(
    file_path: str,
    data: dict,
    fmt: str = CACHE_FORMAT_JSON,
) -> None:
    """将数据保存到缓存文件。

    自动附加文件的当前修改时间戳作为缓存有效性校验依据。

    Args:
        file_path: 原始文件路径
        data: 要缓存的数据字典
        fmt: 缓存格式，"json" 或 "pickle"。pickle 格式序列化更快且支持更多类型。
    """
    info = get_file_info(file_path)
    if not info:
        return

    cache_data = {
        "_meta": {
            "source": str(Path(file_path).resolve()),
            "mtime": info["mtime"],
            "size": info["size"],
        },
        "payload": data,
    }

    cache_path = get_cache_path(file_path, fmt=fmt)
    try:
        if fmt == CACHE_FORMAT_PICKLE:
            with open(cache_path, "wb") as f:
                pickle.dump(cache_data, f, protocol=pickle.HIGHEST_PROTOCOL)
        else:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False)
    except OSError:
        pass  # 缓存写入失败不应影响主流程


def load_cache(
    file_path: str,
    fmt: str = CACHE_FORMAT_JSON,
) -> Optional[dict]:
    """从缓存文件加载数据。

    缓存中记录的修改时间与文件当前修改时间不一致时视为失效，返回 None。

    Args:
        file_path: 原始文件路径
        fmt: 缓存格式，"json" 或 "pickle"

    Returns:
        缓存的 payload 字典，缓存不存在或已失效时返回 None
    """
    cache_path = get_cache_path(file_path, fmt=fmt)
    if not cache_path.exists():
        return None

    try:
        if fmt == CACHE_FORMAT_PICKLE:
            with open(cache_path, "rb") as f:
                cache_data = pickle.load(f)
        else:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
    except (json.JSONDecodeError, pickle.UnpicklingError, OSError, EOFError):
        return None

    meta = cache_data.get("_meta", {})
    cached_mtime = meta.get("mtime", 0)

    # 比较修改时间，文件已更新则缓存失效
    info = get_file_info(file_path)
    if not info:
        return None

    if info["mtime"] > cached_mtime:
        return None

    return cache_data.get("payload")


# ---------------------------------------------------------------------------
# 缓存管理
# ---------------------------------------------------------------------------

def get_cache_size() -> int:
    """获取缓存目录的总大小（字节）。

    Returns:
        缓存目录中所有文件的总字节数
    """
    cache_dir = get_cache_dir()
    total = 0
    try:
        for f in cache_dir.iterdir():
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def cleanup_cache(max_age_days: int = 30) -> int:
    """清理超过指定天数的缓存文件。

    Args:
        max_age_days: 最大保留天数，默认 30 天

    Returns:
        已删除的缓存文件数量
    """
    cache_dir = get_cache_dir()
    if not cache_dir.exists():
        return 0

    now = time.time()
    cutoff = now - max_age_days * 86400
    removed = 0

    for f in cache_dir.iterdir():
        if not f.is_file():
            continue
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass

    return removed


def cleanup_cache_by_size(max_size_mb: int = 500) -> int:
    """当缓存总大小超过阈值时，按从旧到新的顺序清理缓存文件。

    Args:
        max_size_mb: 最大缓存大小（MB），默认 500MB

    Returns:
        已删除的缓存文件数量
    """
    cache_dir = get_cache_dir()
    if not cache_dir.exists():
        return 0

    max_size_bytes = max_size_mb * 1024 * 1024
    current_size = get_cache_size()

    if current_size <= max_size_bytes:
        return 0

    # 收集所有缓存文件及其 mtime，按修改时间排序（从旧到新）
    files: list[tuple[float, Path]] = []
    for f in cache_dir.iterdir():
        if f.is_file():
            try:
                files.append((f.stat().st_mtime, f))
            except OSError:
                pass

    files.sort(key=lambda x: x[0])

    removed = 0
    for _, f in files:
        if current_size <= max_size_bytes:
            break
        try:
            size = f.stat().st_size
            f.unlink()
            current_size -= size
            removed += 1
        except OSError:
            pass

    return removed
