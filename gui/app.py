"""主应用窗口组件

组装所有 GUI 子组件，协调核心业务模块（解析器、报告器、回写器）
与界面交互，通过 BackgroundWorker 在后台执行耗时任务，
利用日志队列和 root.after 实现线程安全的 UI 更新。
支持窗口关闭确认、目录记忆回调、export_config 传递、
一键完成功能、状态栏信息、拖拽文件支持（通过剪贴板）。
"""

import logging
import os
import platform
import queue
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional
from collections import defaultdict

from core.dwg_parser import DWGParser
from core.excel_reporter import ExcelReporter
from core.dwg_writer import DWGWriter
from core.models import AnnotationItem, ParseResult, WriteBackConfig
from utils.logger import setup_logger
from utils.worker import WorkerTask, BackgroundWorker
from utils.file_utils import get_output_path
from config.settings import APP_TITLE, APP_VERSION, APP_GEOMETRY, APP_MIN_SIZE, AppConfig, save_config, load_config

from gui.styles import setup_styles
from gui.frames.file_select import FileSelectFrame
from gui.frames.control_panel import ControlPanel
from gui.frames.data_preview import DataPreviewFrame
from gui.frames.settings_panel import SettingsPanel
from gui.frames.log_panel import LogPanel


class Application(ttk.Frame):
    """主应用窗口

    负责组装所有 GUI 子组件，初始化核心业务模块，
    管理数据缓存、日志队列和后台任务执行。
    支持窗口关闭确认、一键完成、状态栏显示、
    目录记忆回调连接、export_config 传递。
    """

    def __init__(self, root: tk.Tk) -> None:
        super().__init__(root)
        self._root = root

        # 核心业务模块
        self._parser = DWGParser()
        self._reporter = ExcelReporter()

        # 后台工作者
        self._worker = BackgroundWorker()

        # 数据缓存
        self._parse_results: list[ParseResult] = []
        self._all_items: list[AnnotationItem] = []

        # 日志队列
        self._log_queue: queue.Queue = queue.Queue()
        self._logger: logging.Logger = setup_logger(self._log_queue)

        # 一键完成状态
        self._one_click_phase: int = 0  # 0=未开始, 1=提取中, 2=生成报表中, 3=回写中
        self._one_click_output_path: str = ""

        # 配置全局样式
        setup_styles(root)

        # 配置窗口属性
        self._setup_window(root)

        # 构建 UI
        self._build_ui()

        # 连接目录记忆回调
        self._connect_dir_callbacks()

        # 连接数据状态联动
        self._update_data_state()

        # 启动日志队列轮询
        self._poll_log_queue()

        self._logger.info(f"{APP_TITLE} v{APP_VERSION} 已启动")

        # 检查 DWG 文件支持状态
        dwg_status = DWGParser.check_dwg_support()
        if dwg_status["odafc_installed"]:
            self._logger.info("ODA File Converter 已安装，支持直接读取 DWG 文件")
        else:
            self._logger.warning(
                "未检测到 ODA File Converter，DWG 文件将无法直接读取。"
                "支持 DXF 格式文件，或将 DWG 文件另存为 DXF 后使用。"
            )

    # ------------------------------------------------------------------
    # 窗口配置
    # ------------------------------------------------------------------

    def _setup_window(self, root: tk.Tk) -> None:
        """配置窗口属性：标题、大小、最小尺寸、关闭事件处理

        Args:
            root: Tkinter 根窗口实例
        """
        root.title(f"{APP_TITLE} v{APP_VERSION}")
        root.geometry(APP_GEOMETRY)
        root.minsize(*APP_MIN_SIZE)

        # 注册窗口关闭事件处理
        root.protocol("WM_DELETE_WINDOW", self._on_window_close)

        # 注册拖拽文件支持（通过剪贴板粘贴实现）
        self._setup_clipboard_drop(root)

    def _setup_clipboard_drop(self, root: tk.Tk) -> None:
        """设置剪贴板监听作为拖拽文件的备选方案

        通过 Ctrl+V 粘贴文件路径到文件选择区域。

        Args:
            root: Tkinter 根窗口实例
        """
        # 绑定 Ctrl+V 到文件添加
        root.bind("<Control-v>", self._on_paste_files)
        root.bind("<Control-V>", self._on_paste_files)

    def _on_paste_files(self, event: Optional[tk.Event] = None) -> None:
        """Ctrl+V 粘贴文件路径到文件选择区域"""
        try:
            clipboard_text = self._root.clipboard_get()
            if not clipboard_text or not clipboard_text.strip():
                return

            from config.settings import SUPPORTED_EXTENSIONS

            # 按换行分割
            raw_lines = clipboard_text.strip().splitlines()
            paths: list[str] = []

            for line in raw_lines:
                line = line.strip().strip('"').strip("'")
                if not line:
                    continue
                if os.path.isfile(line):
                    ext = os.path.splitext(line)[1].lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        paths.append(line)
                elif os.path.isdir(line):
                    for root_dir, _dirs, files in os.walk(line):
                        for filename in files:
                            ext = os.path.splitext(filename)[1].lower()
                            if ext in SUPPORTED_EXTENSIONS:
                                paths.append(os.path.join(root_dir, filename))

            if paths:
                self._file_select.add_files(paths)
                self._logger.info(f"已通过剪贴板添加 {len(paths)} 个文件")
        except tk.TclError:
            pass

    def _on_window_close(self) -> None:
        """窗口关闭事件处理

        如果有正在运行的后台任务，提示用户确认。
        """
        if self._worker.is_running():
            result = messagebox.askyesnocancel(
                "确认退出",
                "有后台任务正在执行中。\n\n"
                "选择「是」强制终止任务并退出。\n"
                "选择「否」等待任务完成后退出。\n"
                "选择「取消」返回应用。",
                parent=self._root,
            )
            if result is True:
                # 强制终止并退出
                self._worker.stop()
                self._root.destroy()
            elif result is False:
                # 等待任务完成后退出
                self._logger.info("等待后台任务完成后退出...")
                self._wait_and_close()
            # result is None: 取消，不做任何操作
        else:
            # 无后台任务，直接退出
            self._root.destroy()

    def _wait_and_close(self) -> None:
        """等待后台任务完成后关闭窗口"""
        if not self._worker.is_running():
            self._root.destroy()
        else:
            # 每 500ms 检查一次
            self._root.after(500, self._wait_and_close)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """按顺序组装所有子组件"""
        # 文件选择区域
        self._file_select = FileSelectFrame(self)
        self._file_select.pack(fill=tk.X, padx=5, pady=(5, 2))

        # 操作按钮面板
        self._control_panel = ControlPanel(
            self,
            on_extract=self._on_extract,
            on_generate=self._on_generate,
            on_writeback=self._on_writeback,
            on_open_output=self._on_open_output,
            on_one_click=self._on_one_click,
            on_cancel=self._on_cancel,
        )
        self._control_panel.pack(fill=tk.X, padx=5, pady=2)

        # 可折叠设置面板
        self._settings_panel = SettingsPanel(self)
        self._settings_panel.pack(fill=tk.X, padx=5, pady=2)

        # 数据预览表格
        self._data_preview = DataPreviewFrame(self)
        self._data_preview.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

        # 日志与进度条
        self._log_panel = LogPanel(self)
        self._log_panel.pack(fill=tk.X, padx=5, pady=(2, 5))

        # 状态栏
        self._build_status_bar()

    def _build_status_bar(self) -> None:
        """构建底部状态栏，显示文件数、标注总数等信息"""
        self._status_bar = ttk.Frame(self, style="StatusBar.TFrame")
        self._status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        self._status_files_var = tk.StringVar(value="文件: 0")
        ttk.Label(
            self._status_bar,
            textvariable=self._status_files_var,
            style="StatusBar.TLabel",
        ).pack(side=tk.LEFT, padx=(10, 5))

        ttk.Label(
            self._status_bar,
            text="|",
            style="StatusBarSeparator.TLabel",
        ).pack(side=tk.LEFT, padx=2)

        self._status_annotations_var = tk.StringVar(value="标注: 0")
        ttk.Label(
            self._status_bar,
            textvariable=self._status_annotations_var,
            style="StatusBar.TLabel",
        ).pack(side=tk.LEFT, padx=(5, 5))

        ttk.Label(
            self._status_bar,
            text="|",
            style="StatusBarSeparator.TLabel",
        ).pack(side=tk.LEFT, padx=2)

        self._status_selected_var = tk.StringVar(value="选中文件: 0")
        ttk.Label(
            self._status_bar,
            textvariable=self._status_selected_var,
            style="StatusBar.TLabel",
        ).pack(side=tk.LEFT, padx=(5, 10))

        # 右侧版本信息
        ttk.Label(
            self._status_bar,
            text=f"v{APP_VERSION}",
            style="StatusBar.TLabel",
        ).pack(side=tk.RIGHT, padx=(5, 10))

    # ------------------------------------------------------------------
    # 目录记忆回调连接
    # ------------------------------------------------------------------

    def _connect_dir_callbacks(self) -> None:
        """连接 file_select 的目录记忆回调到 AppConfig"""
        config = load_config()

        def get_last_dir() -> str:
            cfg = load_config()
            return cfg.last_file_dir

        def set_last_dir(directory: str) -> None:
            cfg = load_config()
            cfg.last_file_dir = directory
            save_config(cfg)

        self._file_select.set_dir_callbacks(get_last_dir, set_last_dir)

    # ------------------------------------------------------------------
    # 数据状态联动
    # ------------------------------------------------------------------

    def _update_data_state(self) -> None:
        """更新数据相关的 UI 状态（按钮可用性、状态栏）"""
        has_data = len(self._all_items) > 0

        # 联动控制面板按钮状态
        self._control_panel.set_data_state(has_data)

        # 更新状态栏
        self._update_status_bar()

    def _update_status_bar(self) -> None:
        """更新状态栏显示信息"""
        file_count = self._file_select.get_file_count()
        annotation_count = len(self._all_items)

        self._status_files_var.set(f"文件: {file_count}")
        self._status_annotations_var.set(f"标注: {annotation_count}")
        self._status_selected_var.set(f"选中文件: {file_count}")

    # ------------------------------------------------------------------
    # 日志队列轮询
    # ------------------------------------------------------------------

    def _poll_log_queue(self) -> None:
        """定时轮询日志队列，将日志消息安全地显示在 UI 上

        由于日志队列由后台线程写入，而 Tkinter 控件只能在主线程操作，
        因此通过 root.after 定时轮询实现线程安全的 UI 更新。
        """
        try:
            while True:
                log_message = self._log_queue.get_nowait()
                # 根据消息内容判断日志级别
                level = self._detect_log_level(log_message)
                self._log_panel.append_log(log_message, level)
        except queue.Empty:
            pass
        finally:
            # 每 100ms 轮询一次
            self._root.after(100, self._poll_log_queue)

    @staticmethod
    def _detect_log_level(message: str) -> str:
        """从日志消息文本中检测日志级别

        Args:
            message: 日志消息文本

        Returns:
            日志级别字符串（INFO/WARNING/ERROR/DEBUG）
        """
        upper = message.upper()
        if "[ERROR" in upper or "[CRITICAL" in upper:
            return "ERROR"
        if "[WARNING" in upper:
            return "WARNING"
        if "[DEBUG" in upper:
            return "DEBUG"
        return "INFO"

    # ------------------------------------------------------------------
    # 事件处理：提取标注
    # ------------------------------------------------------------------

    def _on_extract(self) -> None:
        """提取标注按钮点击事件处理

        流程：
        1. 获取选中的文件列表
        2. 校验是否有文件
        3. 禁用按钮，设置忙碌状态
        4. 创建 WorkerTask 在后台执行 parse_batch
        """
        files = self._file_select.get_selected_files()
        if not files:
            messagebox.showwarning("提示", "请先选择要处理的 DWG/DXF 文件。")
            return

        self._set_busy(True)
        self._log_panel.clear_log()
        self._logger.info(f"开始提取标注，共 {len(files)} 个文件...")

        # 进度回调：通过 root.after 调度到主线程
        def on_progress(current: int, total: int, file_path: str) -> None:
            self._root.after(0, self._update_progress, current, total, file_path)

        # 完成回调：通过 root.after 调度到主线程
        def on_complete(results: Optional[list[ParseResult]], error: Optional[str]) -> None:
            self._root.after(0, self._on_extract_complete, results, error)

        task = WorkerTask(
            func=self._parser.parse_batch,
            args=(files,),
            kwargs={"progress_callback": on_progress},
            on_complete=on_complete,
            on_progress=on_progress,
        )
        self._worker.run(task)

    def _on_extract_complete(
        self, results: Optional[list[ParseResult]], error: Optional[str]
    ) -> None:
        """提取标注完成回调

        Args:
            results: 解析结果列表
            error: 错误信息
        """
        self._set_busy(False)

        if error:
            self._logger.error(f"标注提取失败: {error}")
            messagebox.showerror("错误", f"标注提取失败:\n{error}")
            # 一键完成模式下，终止流程
            if self._one_click_phase > 0:
                self._one_click_phase = 0
            return

        if results is None:
            self._logger.error("标注提取返回空结果")
            if self._one_click_phase > 0:
                self._one_click_phase = 0
            return

        # 缓存解析结果
        self._parse_results = results

        # 汇总所有标注项
        self._all_items = []
        for result in results:
            if result.error:
                self._logger.warning(f"文件 {result.file_path} 解析异常: {result.error}")
            else:
                self._all_items.extend(result.items)

        # 刷新数据预览表格
        self._data_preview.load_data(self._all_items)

        # 统计信息
        total_count = sum(r.total_count for r in results)
        success_count = sum(1 for r in results if r.error is None)
        fail_count = len(results) - success_count

        self._log_panel.set_progress(
            len(results), len(results), "提取完成"
        )
        self._logger.info(
            f"标注提取完成: 成功 {success_count} 个文件"
            f"{f', 失败 {fail_count} 个' if fail_count > 0 else ''}"
            f", 共 {total_count} 条标注"
        )

        # 更新数据状态联动
        self._update_data_state()

        # 一键完成模式：继续下一步（生成报表）
        if self._one_click_phase == 1:
            self._one_click_phase = 2
            self._root.after(500, self._one_click_step_generate)

    # ------------------------------------------------------------------
    # 事件处理：生成报表
    # ------------------------------------------------------------------

    def _on_generate(self) -> None:
        """生成报表按钮点击事件处理

        流程：
        1. 校验是否有解析结果
        2. 弹出保存对话框选择输出路径
        3. 后台执行 ExcelReporter.generate_report
        """
        if not self._parse_results:
            messagebox.showwarning("提示", "请先执行「提取标注」获取数据。")
            return

        # 弹出保存对话框
        output_path = filedialog.asksaveasfilename(
            parent=self._root,
            title="保存 Excel 报表",
            defaultextension=".xlsx",
            filetypes=[
                ("Excel 文件", "*.xlsx"),
                ("所有文件", "*.*"),
            ],
            initialfile="标注提取报表.xlsx",
        )

        if not output_path:
            # 一键完成模式下，跳过报表
            if self._one_click_phase == 2:
                self._one_click_phase = 3
                self._root.after(300, self._one_click_step_writeback)
            return

        self._generate_report_to(output_path)

    def _generate_report_to(self, output_path: str) -> None:
        """生成报表到指定路径

        Args:
            output_path: 输出文件路径
        """
        self._set_busy(True)
        self._logger.info(f"开始生成报表: {output_path}")

        # 获取导出配置
        export_config = self._settings_panel.get_export_config()

        # 进度回调
        def on_progress(current: int, total: int) -> None:
            self._root.after(
                0,
                self._log_panel.set_progress,
                current,
                total,
                f"生成报表中 ({current}/{total})",
            )

        # 完成回调
        def on_complete(result: Optional[str], error: Optional[str]) -> None:
            self._root.after(0, self._on_generate_complete, result, error)

        task = WorkerTask(
            func=self._reporter.generate_report,
            args=(self._parse_results, output_path),
            kwargs={
                "progress_callback": on_progress,
                "export_config": export_config,
            },
            on_complete=on_complete,
        )
        self._worker.run(task)

    def _on_generate_complete(
        self, result: Optional[str], error: Optional[str]
    ) -> None:
        """生成报表完成回调"""
        self._set_busy(False)

        if error:
            self._logger.error(f"报表生成失败: {error}")
            if self._one_click_phase > 0:
                # 一键完成模式下跳过报表失败，继续回写
                self._one_click_phase = 3
                self._root.after(300, self._one_click_step_writeback)
            else:
                messagebox.showerror("错误", f"报表生成失败:\n{error}")
            return

        if result:
            self._log_panel.set_progress(1, 1, "报表生成完成")
            self._logger.info(f"报表已生成: {result}")

            if self._one_click_phase == 0:
                messagebox.showinfo("成功", f"报表已生成:\n{result}")

        # 一键完成模式：继续下一步（序号回写）
        if self._one_click_phase == 2:
            self._one_click_phase = 3
            self._root.after(300, self._one_click_step_writeback)

    # ------------------------------------------------------------------
    # 事件处理：序号回写
    # ------------------------------------------------------------------

    def _on_writeback(self) -> None:
        """序号回写按钮点击事件处理

        流程：
        1. 校验是否有解析结果
        2. 获取回写配置
        3. 按文件分组标注项
        4. 对每个文件依次后台执行回写
        """
        if not self._all_items:
            messagebox.showwarning("提示", "请先执行「提取标注」获取数据。")
            return

        config = self._settings_panel.get_write_config()
        writer = DWGWriter(config)

        # 按来源文件分组
        file_groups: dict[str, list[AnnotationItem]] = defaultdict(list)
        for item in self._all_items:
            file_groups[item.source_file].append(item)

        file_list = list(file_groups.keys())
        total_files = len(file_list)

        if total_files == 0:
            messagebox.showwarning("提示", "没有可回写的标注数据。")
            return

        self._set_busy(True)
        self._logger.info(
            f"开始序号回写，共 {total_files} 个文件，"
            f"序号样式: {config.number_style.value}"
        )

        # 逐文件执行回写
        self._writeback_index = 0
        self._writeback_file_list = file_list
        self._writeback_file_groups = file_groups
        self._writeback_writer = writer
        self._writeback_results: list[str] = []
        self._writeback_errors: list[str] = []

        self._execute_next_writeback()

    def _execute_next_writeback(self) -> None:
        """执行下一个文件的回写任务"""
        if self._writeback_index >= len(self._writeback_file_list):
            # 所有文件回写完成
            self._on_writeback_all_complete()
            return

        file_path = self._writeback_file_list[self._writeback_index]
        items = self._writeback_file_groups[file_path]
        idx = self._writeback_index + 1
        total = len(self._writeback_file_list)

        self._log_panel.set_progress(
            idx, total, f"回写中: {os.path.basename(file_path)} ({idx}/{total})"
        )
        self._logger.info(f"正在回写 [{idx}/{total}]: {file_path}")

        # 进度回调
        def on_progress(current: int, total_count: int) -> None:
            self._root.after(
                0,
                self._log_panel.set_progress,
                current,
                total_count,
                f"回写中: {os.path.basename(file_path)}",
            )

        # 完成回调
        def on_complete(result: Optional[str], error: Optional[str]) -> None:
            self._root.after(0, self._on_single_writeback_complete, result, error)

        task = WorkerTask(
            func=self._writeback_writer.write_back,
            args=(file_path, self._all_items),
            kwargs={"progress_callback": on_progress},
            on_complete=on_complete,
        )
        self._worker.run(task)

    def _on_single_writeback_complete(
        self, result: Optional[str], error: Optional[str]
    ) -> None:
        """单个文件回写完成回调"""
        if error:
            self._writeback_errors.append(
                f"{self._writeback_file_list[self._writeback_index]}: {error}"
            )
            self._logger.error(f"回写失败: {error}")
        elif result:
            self._writeback_results.append(result)
            self._logger.info(f"回写成功: {result}")

        # 处理下一个文件
        self._writeback_index += 1
        self._execute_next_writeback()

    def _on_writeback_all_complete(self) -> None:
        """所有文件回写完成"""
        self._set_busy(False)
        total = len(self._writeback_file_list)
        success_count = len(self._writeback_results)
        fail_count = len(self._writeback_errors)

        self._log_panel.set_progress(total, total, "回写完成")
        self._logger.info(
            f"序号回写完成: 成功 {success_count}/{total} 个文件"
            f"{f', 失败 {fail_count} 个' if fail_count > 0 else ''}"
        )

        # 一键完成模式下，显示汇总信息
        if self._one_click_phase == 3:
            self._one_click_phase = 0
            msg = "一键完成操作已全部执行完毕。\n\n"
            msg += f"标注提取: {len(self._all_items)} 条\n"
            if self._one_click_output_path:
                msg += f"报表生成: {self._one_click_output_path}\n"
            msg += f"序号回写: 成功 {success_count}/{total} 个文件"
            if fail_count > 0:
                msg += f"\n失败 {fail_count} 个文件"
            messagebox.showinfo("一键完成", msg)
            return

        msg = f"序号回写完成\n成功: {success_count} 个文件"
        if fail_count > 0:
            msg += f"\n失败: {fail_count} 个文件"
            for err in self._writeback_errors:
                msg += f"\n  - {err}"

        messagebox.showinfo("回写结果", msg)

    # ------------------------------------------------------------------
    # 一键完成功能
    # ------------------------------------------------------------------

    def _on_one_click(self) -> None:
        """一键完成按钮点击事件处理

        依次执行：提取标注 -> 生成报表 -> 序号回写
        """
        files = self._file_select.get_selected_files()
        if not files:
            messagebox.showwarning("提示", "请先选择要处理的 DWG/DXF 文件。")
            return

        # 确认执行
        if not messagebox.askyesno(
            "一键完成",
            f"将对 {len(files)} 个文件依次执行：\n"
            "  1. 提取标注\n"
            "  2. 生成 Excel 报表\n"
            "  3. 序号回写\n\n"
            "是否继续？",
            parent=self._root,
        ):
            return

        self._one_click_phase = 1  # 进入提取阶段
        self._one_click_output_path = ""

        # 弹出保存对话框选择报表输出路径
        output_path = filedialog.asksaveasfilename(
            parent=self._root,
            title="一键完成 - 选择报表保存路径",
            defaultextension=".xlsx",
            filetypes=[
                ("Excel 文件", "*.xlsx"),
                ("所有文件", "*.*"),
            ],
            initialfile="标注提取报表.xlsx",
        )
        if output_path:
            self._one_click_output_path = output_path
        else:
            # 用户取消选择路径，仍然执行提取和回写，跳过报表
            self._one_click_output_path = ""

        # 开始第一步：提取标注
        self._on_extract()

    def _one_click_step_generate(self) -> None:
        """一键完成第二步：生成报表"""
        if self._one_click_phase != 2:
            return

        if self._one_click_output_path:
            self._generate_report_to(self._one_click_output_path)
        else:
            # 跳过报表，直接回写
            self._one_click_phase = 3
            self._root.after(300, self._one_click_step_writeback)

    def _one_click_step_writeback(self) -> None:
        """一键完成第三步：序号回写"""
        if self._one_click_phase != 3:
            return

        if not self._all_items:
            self._logger.warning("一键完成：没有可回写的数据，跳过回写步骤。")
            self._one_click_phase = 0
            messagebox.showinfo("一键完成", "操作完成（无可回写数据）。")
            return

        self._on_writeback()

    # ------------------------------------------------------------------
    # 取消操作
    # ------------------------------------------------------------------

    def _on_cancel(self) -> None:
        """取消操作按钮点击事件处理"""
        if self._worker.is_running():
            if messagebox.askyesno(
                "确认取消", "确定要取消当前正在执行的任务吗？", parent=self._root
            ):
                self._worker.stop()
                self._set_busy(False)
                self._one_click_phase = 0
                self._logger.warning("用户取消了当前操作")
                self._log_panel.set_progress(0, 0, "已取消")

    # ------------------------------------------------------------------
    # 事件处理：打开输出目录
    # ------------------------------------------------------------------

    def _on_open_output(self) -> None:
        """打开输出目录按钮点击事件处理

        使用系统默认程序打开输出目录。
        Windows 使用 os.startfile，其他平台使用 subprocess。
        """
        # 确定输出目录
        output_dir = os.path.join(os.getcwd(), "output")
        if not os.path.isdir(output_dir):
            os.makedirs(output_dir, exist_ok=True)
            self._logger.info(f"已创建输出目录: {output_dir}")

        try:
            self._open_directory(output_dir)
            self._logger.info(f"已打开输出目录: {output_dir}")
        except Exception as e:
            self._logger.error(f"无法打开输出目录: {e}")
            messagebox.showerror("错误", f"无法打开输出目录:\n{e}")

    @staticmethod
    def _open_directory(path: str) -> None:
        """使用系统文件管理器打开目录

        Args:
            path: 目录路径
        """
        system = platform.system()
        if system == "Windows":
            os.startfile(path)
        elif system == "Darwin":
            subprocess.run(["open", path], check=True)
        else:
            subprocess.run(["xdg-open", path], check=True)

    # ------------------------------------------------------------------
    # 进度更新
    # ------------------------------------------------------------------

    def _update_progress(self, current: int, total: int, file_path: str) -> None:
        """更新进度条和状态文本

        Args:
            current: 当前进度值
            total: 总进度值
            file_path: 当前正在处理的文件路径
        """
        filename = os.path.basename(file_path) if file_path else ""
        self._log_panel.set_progress(
            current, total, f"正在处理: {filename} ({current}/{total})"
        )

    # ------------------------------------------------------------------
    # 状态管理
    # ------------------------------------------------------------------

    def _set_busy(self, busy: bool) -> None:
        """设置应用忙碌状态

        禁用/启用操作按钮，设置鼠标样式。
        同时更新状态栏信息。

        Args:
            busy: True 为忙碌（禁用按钮，等待光标），False 为空闲
        """
        self._control_panel.set_buttons_enabled(not busy)

        if busy:
            self._root.configure(cursor="watch")
        else:
            self._root.configure(cursor="")

        # 更新状态栏
        self._update_status_bar()
