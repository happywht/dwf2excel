"""后台线程管理模块"""

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class WorkerTask:
    """后台任务封装"""
    func: Callable                       # 要执行的函数
    args: tuple = field(default_factory=tuple)    # 位置参数
    kwargs: dict = field(default_factory=dict)    # 关键字参数
    on_complete: Optional[Callable] = None   # 完成回调，接收 (result, error)
    on_progress: Optional[Callable] = None   # 进度回调，接收 (current, total, message)
    result: Any = None                       # 执行结果
    error: Optional[str] = None              # 错误信息


class BackgroundWorker:
    """后台线程工作者"""

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def run(self, task: WorkerTask) -> None:
        """
        在后台线程中执行任务

        Args:
            task: WorkerTask 任务对象
        """
        if self.is_running():
            return

        self._stop_event.clear()

        def _execute():
            try:
                task.result = task.func(*task.args, **task.kwargs)
            except Exception as e:
                task.error = str(e)
            finally:
                if task.on_complete:
                    task.on_complete(task.result, task.error)

        self._thread = threading.Thread(target=_execute, daemon=True)
        self._thread.start()

    def is_running(self) -> bool:
        """检查后台线程是否正在运行"""
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        """请求停止后台任务"""
        self._stop_event.set()
