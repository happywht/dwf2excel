"""后台线程管理模块"""

import heapq
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    # 任务优先级（数值越大越优先执行）
    priority: int = 0
    # 任务超时（秒），None 表示不限时
    timeout: Optional[float] = None
    # 重试机制
    max_retries: int = 0                     # 最大重试次数
    retry_delay: float = 1.0                 # 重试间隔（秒）
    # 内部字段（不由用户设置）
    _retry_count: int = field(default=0, repr=False)  # 已重试次数


class BackgroundWorker:
    """后台线程工作者

    支持单任务执行（run）和任务队列（enqueue）。任务队列按优先级排序，
    高优先级任务优先执行。支持任务超时和失败重试。
    """

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        # 任务队列（优先级堆）
        self._queue: list[tuple[int, int, WorkerTask]] = []  # (-priority, seq, task)
        self._queue_lock = threading.Lock()
        self._queue_event = threading.Event()  # 通知队列有新任务
        self._sequence = 0  # 用于同优先级任务的 FIFO 排序

    def run(self, task: WorkerTask) -> None:
        """
        在后台线程中执行任务（兼容旧接口，不使用队列）

        Args:
            task: WorkerTask 任务对象
        """
        if self.is_running():
            return

        self._stop_event.clear()

        def _execute():
            self._execute_task_with_retry(task)

        self._thread = threading.Thread(target=_execute, daemon=True)
        self._thread.start()

    def enqueue(self, task: WorkerTask) -> None:
        """将任务加入队列。

        如果当前没有正在执行的任务，自动启动队列处理线程。
        任务按优先级排序（数值越大越优先），同优先级按入队顺序执行。

        Args:
            task: WorkerTask 任务对象
        """
        with self._queue_lock:
            # 使用负优先级实现最大堆（heapq 是最小堆）
            self._sequence += 1
            heapq.heappush(self._queue, (-task.priority, self._sequence, task))
            self._queue_event.set()

        # 如果当前没有运行任务，启动队列处理线程
        if not self.is_running():
            self._start_queue_processor()

    def cancel_all(self) -> int:
        """取消所有排队任务。

        正在执行的任务不受影响。

        Returns:
            被取消的任务数量
        """
        with self._queue_lock:
            count = len(self._queue)
            self._queue.clear()
            self._queue_event.clear()
        return count

    def get_pending_count(self) -> int:
        """获取当前排队等待的任务数。

        Returns:
            排队任务数
        """
        with self._queue_lock:
            return len(self._queue)

    def _start_queue_processor(self) -> None:
        """启动队列处理线程。"""
        if self.is_running():
            return

        self._stop_event.clear()

        def _process():
            while not self._stop_event.is_set():
                task = None
                with self._queue_lock:
                    if self._queue:
                        _, _, task = heapq.heappop(self._queue)
                        if not self._queue:
                            self._queue_event.clear()

                if task is not None:
                    self._execute_task_with_retry(task)
                else:
                    # 等待新任务或停止信号
                    self._queue_event.wait(timeout=1.0)
                    if self._stop_event.is_set():
                        break
                    # 再次检查队列
                    with self._queue_lock:
                        if not self._queue:
                            # 队列为空且没有新任务，退出线程
                            self._queue_event.clear()
                            return

        self._thread = threading.Thread(target=_process, daemon=True)
        self._thread.start()

    def _execute_task_with_retry(self, task: WorkerTask) -> None:
        """执行任务，支持超时检测和失败重试。

        Args:
            task: WorkerTask 任务对象
        """
        attempts = task.max_retries + 1
        for attempt in range(attempts):
            if self._stop_event.is_set():
                task.error = "任务已取消"
                break

            task.error = None
            task.result = None

            if task.timeout is not None:
                self._execute_with_timeout(task)
            else:
                try:
                    task.result = task.func(*task.args, **task.kwargs)
                except Exception as e:
                    task.error = str(e)

            # 执行成功，退出重试循环
            if task.error is None:
                break

            # 还有剩余重试次数
            if attempt < attempts - 1:
                task._retry_count = attempt + 1
                # 等待重试延迟，期间检查停止信号
                if self._stop_event.wait(timeout=task.retry_delay):
                    task.error = "任务已取消"
                    break
                continue

        # 所有尝试完成（成功或失败），触发回调
        if task.on_complete:
            try:
                task.on_complete(task.result, task.error)
            except Exception:
                pass  # 回调异常不应影响后续任务

    def _execute_with_timeout(self, task: WorkerTask) -> None:
        """在子线程中执行任务并检测超时。

        Args:
            task: WorkerTask 任务对象（需已设置 timeout）
        """
        result_holder: list[Any] = [None]
        error_holder: list[Optional[str]] = [None]
        done_event = threading.Event()

        def _target():
            try:
                result_holder[0] = task.func(*task.args, **task.kwargs)
            except Exception as e:
                error_holder[0] = str(e)
            finally:
                done_event.set()

        worker_thread = threading.Thread(target=_target, daemon=True)
        worker_thread.start()

        # 等待完成或超时
        finished = done_event.wait(timeout=task.timeout)
        if finished:
            task.result = result_holder[0]
            task.error = error_holder[0]
        else:
            task.error = f"任务超时（{task.timeout}秒）"

    def is_running(self) -> bool:
        """检查后台线程是否正在运行"""
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        """请求停止后台任务"""
        self._stop_event.set()
        self._queue_event.set()  # 唤醒可能正在等待的队列处理线程


class ParallelWorker:
    """并行任务执行器

    使用 ThreadPoolExecutor 对一批任务进行并行处理，支持逐项回调与全部完成回调，
    并可通过 stop() 方法提前终止。
    """

    def __init__(self, max_workers: Optional[int] = None):
        """
        Args:
            max_workers: 线程池最大工作线程数。
                         默认为 min(os.cpu_count() or 4, 8)。
        """
        if max_workers is None:
            max_workers = min(os.cpu_count() or 4, 8)
        self._max_workers = max_workers
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._running = False

    def run_batch(
        self,
        func: Callable,
        items: list,
        on_item_complete: Optional[Callable] = None,
        on_all_complete: Optional[Callable] = None,
    ) -> None:
        """并行执行批量任务

        Args:
            func: 对每个 item 执行的函数，签名为 func(item) -> result
            items: 待处理的列表
            on_item_complete: 单项完成回调，签名 callback(item, result, error)
            on_all_complete: 全部完成回调，签名 callback(results: list)
        """
        self._stop_event.clear()
        with self._lock:
            self._running = True

        results: list = [None] * len(items)

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            # 提交所有任务，记录 future -> index 映射
            future_to_index: dict = {}
            for idx, item in enumerate(items):
                if self._stop_event.is_set():
                    break
                future = executor.submit(func, item)
                future_to_index[future] = idx

            # 按完成顺序收集结果
            for future in as_completed(future_to_index):
                if self._stop_event.is_set():
                    break

                idx = future_to_index[future]
                item = items[idx]
                error = None
                result = None

                try:
                    result = future.result()
                except Exception as exc:
                    error = str(exc)

                results[idx] = result

                # 单项完成回调（注意：此回调在 ThreadPoolExecutor 的线程中执行）
                if on_item_complete is not None:
                    try:
                        on_item_complete(item, result, error)
                    except Exception:
                        pass  # 回调异常不应中断其他任务

        with self._lock:
            self._running = False

        # 全部完成回调
        if on_all_complete is not None and not self._stop_event.is_set():
            try:
                on_all_complete(results)
            except Exception:
                pass

    def stop(self) -> None:
        """请求提前终止所有任务"""
        self._stop_event.set()

    def is_running(self) -> bool:
        """检查是否有正在执行的批量任务"""
        with self._lock:
            return self._running
