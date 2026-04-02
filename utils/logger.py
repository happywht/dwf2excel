"""日志工具模块"""

import logging
import queue
from logging.handlers import RotatingFileHandler
from typing import Optional


class QueueHandler(logging.Handler):
    """将日志消息发送到队列，供 GUI 消费。

    支持设置最低日志级别，低于此级别的日志不入队，减少 GUI 线程压力。
    """

    def __init__(
        self,
        log_queue: Optional[queue.Queue] = None,
        min_level: int = logging.DEBUG,
    ):
        """初始化队列日志处理器。

        Args:
            log_queue: 日志消息队列，为 None 时所有消息被忽略
            min_level: 最低日志级别，低于此级别的日志不入队。
                       默认为 DEBUG（即所有日志都入队）。
                       可设为 logging.INFO、logging.WARNING 等来过滤低级别日志。
        """
        super().__init__()
        self.log_queue = log_queue
        self._min_level = min_level

    def emit(self, record: logging.LogRecord) -> None:
        """将格式化后的日志消息放入队列。

        低于 min_level 的日志将被直接忽略，不会进入队列。
        """
        if self.log_queue is None:
            return
        if record.levelno < self._min_level:
            return
        try:
            msg = self.format(record)
            self.log_queue.put(msg)
        except Exception:
            self.handleError(record)


def setup_logger(
    log_queue: Optional[queue.Queue] = None,
    min_queue_level: int = logging.DEBUG,
) -> logging.Logger:
    """
    配置应用日志器

    Args:
        log_queue: GUI 日志队列，为 None 时仅输出到控制台
        min_queue_level: 队列处理器的最低日志级别，默认 DEBUG。
                         设为 INFO 可过滤 DEBUG 级别日志以减少 GUI 压力。

    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger("dwg_annotool")
    logger.setLevel(logging.DEBUG)

    # 避免重复添加处理器
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # GUI 队列处理器（可选）
    if log_queue is not None:
        queue_handler = QueueHandler(log_queue, min_level=min_queue_level)
        queue_handler.setLevel(logging.DEBUG)
        queue_handler.setFormatter(formatter)
        logger.addHandler(queue_handler)

    return logger


def add_file_handler(
    logger: logging.Logger,
    file_path: str,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    level: int = logging.DEBUG,
) -> Optional[RotatingFileHandler]:
    """为日志器添加文件输出处理器，支持日志轮转。

    使用 RotatingFileHandler 将日志同时输出到文件。当日志文件超过 max_bytes 时，
    自动创建备份文件并进行轮转。

    Args:
        logger: 要添加处理器的日志器实例
        file_path: 日志文件路径
        max_bytes: 单个日志文件最大字节数，默认 10MB
        backup_count: 保留的备份日志文件数量，默认 5 个
        level: 文件处理器的日志级别，默认 DEBUG

    Returns:
        添加的 RotatingFileHandler 实例，添加失败时返回 None
    """
    try:
        # 确保日志文件目录存在
        from pathlib import Path
        log_path = Path(file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        handler = RotatingFileHandler(
            filename=file_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        handler.setLevel(level)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return handler

    except (OSError, ValueError):
        return None


def log_performance(
    logger: logging.Logger,
    operation: str,
    duration: float,
    item_count: Optional[int] = None,
) -> None:
    """统一格式记录操作耗时和性能数据。

    Args:
        logger: 日志器实例
        operation: 操作名称
        duration: 操作耗时（秒）
        item_count: 处理的项目数量，为 None 时不输出数量信息
    """
    if item_count is not None and item_count > 0:
        rate = item_count / duration if duration > 0 else float("inf")
        logger.info(
            "[PERF] %s: %.3fs (%d items, %.1f items/s)",
            operation,
            duration,
            item_count,
            rate,
        )
    else:
        logger.info("[PERF] %s: %.3fs", operation, duration)
