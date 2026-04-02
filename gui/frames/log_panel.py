"""日志与进度条面板组件

显示后台任务执行进度和日志信息，支持不同级别的日志颜色区分、
日志级别筛选、日志搜索、复制全部日志、日志导出、
自动限制行数、时间戳显示开关等功能。
"""

import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
from typing import Optional


# 日志级别到颜色的映射
_LOG_COLORS: dict[str, str] = {
    "INFO": "#2c3e50",      # 深灰 - 普通信息
    "WARNING": "#e67e22",   # 橙色 - 警告
    "ERROR": "#e74c3c",     # 红色 - 错误
    "DEBUG": "#7f8c8d",     # 灰色 - 调试信息
}

# 日志级别筛选选项
_LOG_LEVEL_OPTIONS = ["全部", "信息", "警告", "错误"]

# 日志级别中文到英文的映射
_LOG_LEVEL_CN_TO_EN = {
    "信息": "INFO",
    "警告": "WARNING",
    "错误": "ERROR",
}

# 最大保留日志行数
MAX_LOG_LINES = 1000


class LogPanel(ttk.LabelFrame):
    """日志与进度条面板

    顶部显示进度条和状态文本、日志级别筛选、日志搜索、
    复制全部日志按钮，下方显示日志文本框（只读）。
    支持按日志级别显示不同颜色、级别筛选、日志搜索、
    日志自动限制行数（超过1000行截断旧日志）、时间戳显示开关。
    """

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, text=" 日志与进度 ", style="Group.TLabelframe")

        # 内部日志存储（用于级别筛选和搜索）
        self._log_entries: list[tuple[str, str, str]] = []  # [(timestamp, message, level), ...]
        self._current_filter: str = "全部"
        self._show_timestamp: bool = True
        self._max_lines: int = MAX_LOG_LINES

        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建日志面板 UI"""
        # ===== 顶部：进度条 + 百分比 + 状态文本 =====
        progress_frame = ttk.Frame(self)
        progress_frame.pack(fill=tk.X, padx=5, pady=(5, 2))

        self._progress_bar = ttk.Progressbar(
            progress_frame,
            style="Custom.Horizontal.TProgressbar",
            mode="determinate",
            length=300,
        )
        self._progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        self._percent_var = tk.StringVar(value="0%")
        ttk.Label(
            progress_frame, textvariable=self._percent_var, width=6
        ).pack(side=tk.LEFT, padx=(0, 10))

        self._status_var = tk.StringVar(value="就绪")
        ttk.Label(
            progress_frame, textvariable=self._status_var, style="Info.TLabel"
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # ===== 日志工具栏 =====
        toolbar_frame = ttk.Frame(self)
        toolbar_frame.pack(fill=tk.X, padx=5, pady=(2, 2))

        # 日志级别筛选
        ttk.Label(toolbar_frame, text="级别:", style="Small.TLabel").pack(
            side=tk.LEFT, padx=(0, 3)
        )
        self._level_filter_var = tk.StringVar(value="全部")
        self._level_filter_combo = ttk.Combobox(
            toolbar_frame,
            textvariable=self._level_filter_var,
            values=_LOG_LEVEL_OPTIONS,
            state="readonly",
            width=8,
        )
        self._level_filter_combo.pack(side=tk.LEFT, padx=(0, 8))
        self._level_filter_combo.bind("<<ComboboxSelected>>", self._on_filter_changed)

        # 日志搜索
        ttk.Label(toolbar_frame, text="搜索:", style="Small.TLabel").pack(
            side=tk.LEFT, padx=(0, 3)
        )
        self._search_var = tk.StringVar()
        self._search_entry = ttk.Entry(
            toolbar_frame, textvariable=self._search_var, width=20
        )
        self._search_entry.pack(side=tk.LEFT, padx=(0, 8))
        self._search_var.trace_add("write", lambda *_: self._on_search_changed)

        # 时间戳开关
        self._timestamp_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            toolbar_frame, text="时间戳", variable=self._timestamp_var,
            command=self._on_timestamp_toggle,
        ).pack(side=tk.LEFT, padx=(0, 8))

        # 复制全部日志按钮
        ttk.Button(
            toolbar_frame, text="复制全部", command=self._on_copy_all_log
        ).pack(side=tk.RIGHT, padx=(3, 0))

        # 导出日志按钮
        ttk.Button(
            toolbar_frame, text="导出日志", command=self._on_export_log
        ).pack(side=tk.RIGHT, padx=(3, 0))

        # ===== 下方：日志文本框 =====
        self._log_text = scrolledtext.ScrolledText(
            self,
            height=8,
            state=tk.DISABLED,
            font=("Consolas", 9),
            wrap=tk.WORD,
            background="#fafafa",
        )
        self._log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=(2, 5))

        # 预配置日志颜色标签
        for level, color in _LOG_COLORS.items():
            self._log_text.tag_configure(level, foreground=color)

        # 通用颜色标签（处理日志消息中的级别关键字）
        self._log_text.tag_configure("WARNING", foreground="#e67e22")
        self._log_text.tag_configure("ERROR", foreground="#e74c3c")

        # 搜索高亮标签
        self._log_text.tag_configure("search_highlight", background="#ffff00", foreground="#000000")

    # ------------------------------------------------------------------
    # 日志级别筛选
    # ------------------------------------------------------------------

    def _on_filter_changed(self, event: Optional[tk.Event] = None) -> None:
        """日志级别筛选下拉框变更事件"""
        self._current_filter = self._level_filter_var.get()
        self._refresh_log_display()

    def _on_search_changed(self) -> None:
        """日志搜索内容变更时刷新显示"""
        self._refresh_log_display()

    def _on_timestamp_toggle(self) -> None:
        """时间戳显示开关切换"""
        self._show_timestamp = self._timestamp_var.get()
        self._refresh_log_display()

    def _should_show_entry(self, level: str, message: str) -> bool:
        """判断日志条目是否应该显示

        Args:
            level: 日志级别
            message: 日志消息

        Returns:
            是否显示
        """
        # 级别筛选
        if self._current_filter != "全部":
            target_level = _LOG_LEVEL_CN_TO_EN.get(self._current_filter, "")
            if target_level and level != target_level:
                return False

        # 搜索筛选
        keyword = self._search_var.get().strip()
        if keyword:
            if keyword.lower() not in message.lower():
                return False

        return True

    def _refresh_log_display(self) -> None:
        """根据筛选条件重新刷新日志显示"""
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)

        search_keyword = self._search_var.get().strip().lower()

        for timestamp, message, level in self._log_entries:
            if not self._should_show_entry(level, message):
                continue

            # 构建显示文本
            if self._show_timestamp:
                display_text = f"[{timestamp}] {message}\n"
            else:
                display_text = f"{message}\n"

            tag = level if level in _LOG_COLORS else "INFO"
            start_pos = self._log_text.index(tk.END)
            self._log_text.insert(tk.END, display_text, tag)

            # 搜索高亮
            if search_keyword and search_keyword in display_text.lower():
                line_start = self._log_text.index(f"{start_pos} linestart")
                line_end = self._log_text.index(f"{start_pos} lineend")
                # 简化高亮：对整行高亮
                self._log_text.tag_add("search_highlight", line_start, line_end)

        self._log_text.configure(state=tk.DISABLED)
        self._log_text.see(tk.END)

    # ------------------------------------------------------------------
    # 复制全部日志
    # ------------------------------------------------------------------

    def _on_copy_all_log(self) -> None:
        """复制全部日志到剪贴板"""
        if not self._log_entries:
            messagebox.showinfo("提示", "当前没有日志内容。", parent=self)
            return

        # 构建完整日志文本
        lines: list[str] = []
        for timestamp, message, level in self._log_entries:
            if self._show_timestamp:
                lines.append(f"[{timestamp}] {message}")
            else:
                lines.append(message)

        full_text = "\n".join(lines)

        try:
            self.clipboard_clear()
            self.clipboard_append(full_text)
            messagebox.showinfo(
                "成功", f"已复制 {len(self._log_entries)} 条日志到剪贴板。", parent=self
            )
        except tk.TclError:
            messagebox.showerror("错误", "无法写入剪贴板。", parent=self)

    # ------------------------------------------------------------------
    # 日志导出
    # ------------------------------------------------------------------

    def _on_export_log(self) -> None:
        """导出日志到 .log 文件"""
        if not self._log_entries:
            messagebox.showinfo("提示", "当前没有日志内容可导出。", parent=self)
            return

        # 构建完整日志文本
        lines: list[str] = []
        for timestamp, message, level in self._log_entries:
            lines.append(f"[{timestamp}] [{level}] {message}")

        log_content = "\n".join(lines)

        # 生成默认文件名
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"dwg_annotool_{timestamp}.log"

        # 弹出保存对话框
        file_path = filedialog.asksaveasfilename(
            parent=self,
            title="保存日志文件",
            defaultextension=".log",
            initialfile=default_name,
            filetypes=[
                ("日志文件", "*.log"),
                ("文本文件", "*.txt"),
                ("所有文件", "*.*"),
            ],
        )

        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"# DWG标注工具日志 - 导出时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("# " + "=" * 60 + "\n\n")
                f.write(log_content)
                f.write("\n")
            messagebox.showinfo("成功", f"日志已导出到:\n{file_path}", parent=self)
        except OSError as e:
            messagebox.showerror("错误", f"导出日志失败:\n{e}", parent=self)

    # ------------------------------------------------------------------
    # 日志行数限制
    # ------------------------------------------------------------------

    def _trim_log_entries(self) -> None:
        """当日志条目超过最大行数时，截断旧日志"""
        if len(self._log_entries) > self._max_lines:
            # 保留最新的日志
            self._log_entries = self._log_entries[-self._max_lines:]

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def set_progress(self, current: int, total: int, status_text: str = "") -> None:
        """更新进度条和状态文本

        Args:
            current: 当前进度值
            total: 总进度值
            status_text: 状态文本（可选）
        """
        if total > 0:
            self._progress_bar["maximum"] = total
            self._progress_bar["value"] = current
            percent = int(current / total * 100)
            self._percent_var.set(f"{percent}%")
        else:
            self._progress_bar["value"] = 0
            self._percent_var.set("0%")

        if status_text:
            self._status_var.set(status_text)

    def append_log(self, message: str, level: str = "INFO") -> None:
        """向日志文本框追加一条日志

        根据日志级别自动着色：
        - INFO: 黑色
        - WARNING: 橙色
        - ERROR: 红色
        - DEBUG: 灰色

        日志条目超过1000行时自动截断旧日志。

        Args:
            message: 日志消息内容
            level: 日志级别（INFO/WARNING/ERROR/DEBUG）
        """
        # 生成时间戳
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")

        # 存储到内部列表
        self._log_entries.append((timestamp, message, level))

        # 自动截断旧日志
        self._trim_log_entries()

        # 判断是否应该显示
        if not self._should_show_entry(level, message):
            return

        # 构建显示文本
        if self._show_timestamp:
            display_text = f"[{timestamp}] {message}\n"
        else:
            display_text = f"{message}\n"

        # 插入文本并应用颜色标签
        self._log_text.configure(state=tk.NORMAL)
        tag = level if level in _LOG_COLORS else "INFO"
        self._log_text.insert(tk.END, display_text, tag)
        self._log_text.configure(state=tk.DISABLED)

        # 自动滚动到最新日志
        self._log_text.see(tk.END)

    def clear_log(self) -> None:
        """清空日志文本框"""
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        self._log_text.configure(state=tk.DISABLED)
        self._log_entries.clear()
        self._status_var.set("就绪")
        self._percent_var.set("0%")
        self._progress_bar["value"] = 0
