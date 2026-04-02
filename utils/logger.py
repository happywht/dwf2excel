"""日志工具模块"""

import logging
import queue
from typing import Optional


class QueueHandler(logging.Handler):
    """将日志消息发送到队列，供 GUI 消费"""

    def __init__(self, log_queue: Optional[queue.Queue] = None):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        """将格式化后的日志消息放入队列"""
        if self.log_queue is None:
            return
        try:
            msg = self.format(record)
            self.log_queue.put(msg)
        except Exception:
            self.handleError(record)


def setup_logger(log_queue: Optional[queue.Queue] = None) -> logging.Logger:
    """
    配置应用日志器

    Args:
        log_queue: GUI 日志队列，为 None 时仅输出到控制台

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
        queue_handler = QueueHandler(log_queue)
        queue_handler.setLevel(logging.DEBUG)
        queue_handler.setFormatter(formatter)
        logger.addHandler(queue_handler)

    return logger
