"""日志与进度条面板组件

显示后台任务执行进度和日志信息，支持不同级别的日志颜色区分。
"""

import tkinter as tk
from tkinter import ttk, scrolledtext
from typing import Optional


# 日志级别到颜色的映射
_LOG_COLORS: dict[str, str] = {
    "INFO": "#2c3e50",      # 深灰 - 普通信息
    "WARNING": "#e67e22",   # 橙色 - 警告
    "ERROR": "#e74c3c",     # 红色 - 错误
    "DEBUG": "#7f8c8d",     # 灰色 - 调试信息
}


class LogPanel(ttk.LabelFrame):
    """日志与进度条面板

    顶部显示进度条和状态文本，下方显示日志文本框（只读）。
    支持按日志级别显示不同颜色。
    """

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, text=" 日志与进度 ", style="Group.TLabelframe")
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
        ).pack(side=tk.LEFT)

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

        Args:
            message: 日志消息内容
            level: 日志级别（INFO/WARNING/ERROR/DEBUG）
        """
        self._log_text.configure(state=tk.NORMAL)

        # 插入文本并应用颜色标签
        tag = level if level in _LOG_COLORS else "INFO"
        self._log_text.insert(tk.END, message + "\n", tag)

        self._log_text.configure(state=tk.DISABLED)

        # 自动滚动到最新日志
        self._log_text.see(tk.END)

    def clear_log(self) -> None:
        """清空日志文本框"""
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        self._log_text.configure(state=tk.DISABLED)
        self._status_var.set("就绪")
        self._percent_var.set("0%")
        self._progress_bar["value"] = 0
