"""全局 ttk 样式配置模块

提供统一的视觉风格：按钮、标签、进度条、Treeview 行交替色、
Tooltip、状态栏、成功/警告/错误标签等。
支持高 DPI 检测并自动调整字体大小。
"""

import ctypes
import sys
import tkinter as tk
from tkinter import ttk
from typing import Optional


def _get_system_dpi() -> float:
    """检测系统 DPI 缩放比例

    Returns:
        DPI 缩放比例（1.0 为 100%）
    """
    try:
        if sys.platform == "win32":
            # Windows: 通过 GetDeviceCaps 获取真实 DPI
            user32 = ctypes.windll.user32
            hdc = user32.GetDC(0)
            if hdc:
                gdi32 = ctypes.windll.gdi32
                dpi_x = gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
                user32.ReleaseDC(0, hdc)
                if dpi_x > 0:
                    return dpi_x / 96.0
        # 其他平台或检测失败，使用 Tk 自身 DPI
        root_temp = tk._default_root  # type: ignore[attr-defined]
        if root_temp:
            return root_temp.tk.call("tk", "scaling") / 1.33333
    except Exception:
        pass
    return 1.0


def _adjust_font_size(base_size: int, dpi_scale: float) -> int:
    """根据 DPI 缩放调整字体大小

    Args:
        base_size: 基础字体大小
        dpi_scale: DPI 缩放比例

    Returns:
        调整后的字体大小
    """
    adjusted = int(base_size * dpi_scale)
    return max(adjusted, base_size)  # 不缩小，只放大


def setup_styles(root: tk.Tk) -> None:
    """配置全局 ttk 样式

    使用 clam 主题作为基础，自定义按钮、标签、进度条等控件样式，
    确保整个应用视觉风格统一。支持高 DPI 自适应字体。

    Args:
        root: Tkinter 根窗口实例
    """
    style = ttk.Style(root)
    style.theme_use("clam")

    # 检测 DPI 并计算字体缩放
    dpi_scale = _get_system_dpi()
    _apply_styles(style, dpi_scale)

    # 尝试启用高 DPI 感知（Windows）
    _enable_dpi_awareness(root)


def _apply_styles(style: ttk.Style, dpi_scale: float = 1.0) -> None:
    """应用所有样式配置

    Args:
        style: ttk.Style 实例
        dpi_scale: DPI 缩放比例
    """
    # 基础字体大小（根据 DPI 调整）
    f10 = _adjust_font_size(10, dpi_scale)
    f9 = _adjust_font_size(9, dpi_scale)
    f8 = _adjust_font_size(8, dpi_scale)
    f12 = _adjust_font_size(12, dpi_scale)

    # 主按钮 - 用于核心操作（提取标注、生成报表、序号回写）
    style.configure(
        "Primary.TButton",
        padding=(15, 8),
        font=("微软雅黑", f10, "bold"),
    )

    # 危险按钮 - 用于辅助操作（打开输出目录等）
    style.configure(
        "Danger.TButton",
        padding=(10, 5),
        font=("微软雅黑", f9),
    )

    # 标题标签
    style.configure(
        "Title.TLabel",
        font=("微软雅黑", f12, "bold"),
        foreground="#2c3e50",
    )

    # 信息标签
    style.configure(
        "Info.TLabel",
        font=("微软雅黑", f9),
        foreground="#7f8c8d",
    )

    # 小号信息标签
    style.configure(
        "Small.TLabel",
        font=("微软雅黑", f8),
        foreground="#95a5a6",
    )

    # 自定义进度条
    style.configure(
        "Custom.Horizontal.TProgressbar",
        troughcolor="#ecf0f1",
        background="#3498db",
    )

    # 文件列表容器背景
    style.configure(
        "FileList.TFrame",
        background="#f8f9fa",
    )

    # 强调按钮 - 用于一键完成等高亮操作
    style.configure(
        "Accent.TButton",
        padding=(15, 8),
        font=("微软雅黑", f10, "bold"),
        foreground="#ffffff",
    )
    style.map(
        "Accent.TButton",
        background=[("active", "#2471a3"), ("!active", "#2e86c1")],
        foreground=[("active", "#ffffff"), ("!active", "#ffffff")],
    )

    # 分组标签框架
    style.configure(
        "Group.TLabelframe",
        font=("微软雅黑", f10, "bold"),
    )
    style.configure(
        "Group.TLabelframe.Label",
        font=("微软雅黑", f10, "bold"),
        foreground="#2c3e50",
    )

    # 状态栏样式
    style.configure(
        "StatusBar.TFrame",
        background="#ecf0f1",
        relief=tk.SUNKEN,
    )
    style.configure(
        "StatusBar.TLabel",
        font=("微软雅黑", f9),
        foreground="#2c3e50",
        background="#ecf0f1",
        padding=(5, 2),
    )
    style.configure(
        "StatusBarSeparator.TLabel",
        font=("微软雅黑", f9),
        foreground="#bdc3c7",
        background="#ecf0f1",
        padding=(3, 2),
    )

    # ---- 新增样式 ----

    # 成功标签 - 用于操作成功提示
    style.configure(
        "Success.TLabel",
        font=("微软雅黑", f9),
        foreground="#27ae60",
        background="#eafaf1",
        padding=(5, 2),
    )

    # 警告标签 - 用于操作警告提示
    style.configure(
        "Warning.TLabel",
        font=("微软雅黑", f9),
        foreground="#e67e22",
        background="#fef9e7",
        padding=(5, 2),
    )

    # 错误标签 - 用于操作失败提示
    style.configure(
        "Error.TLabel",
        font=("微软雅黑", f9),
        foreground="#e74c3c",
        background="#fdedec",
        padding=(5, 2),
    )

    # 成功按钮
    style.configure(
        "Success.TButton",
        padding=(10, 5),
        font=("微软雅黑", f9),
    )
    style.map(
        "Success.TButton",
        background=[("active", "#1e8449"), ("!active", "#27ae60")],
        foreground=[("active", "#ffffff"), ("!active", "#ffffff")],
    )

    # 警告按钮
    style.configure(
        "Warning.TButton",
        padding=(10, 5),
        font=("微软雅黑", f9),
    )
    style.map(
        "Warning.TButton",
        background=[("active", "#ca6f1e"), ("!active", "#e67e22")],
        foreground=[("active", "#ffffff"), ("!active", "#ffffff")],
    )

    # 取消按钮（红色风格，用于取消操作）
    style.configure(
        "Cancel.TButton",
        padding=(10, 5),
        font=("微软雅黑", f9),
    )
    style.map(
        "Cancel.TButton",
        background=[("active", "#c0392b"), ("!active", "#e74c3c")],
        foreground=[("active", "#ffffff"), ("!active", "#ffffff")],
    )

    # Treeview 行交替色
    style.configure(
        "Treeview",
        background="#ffffff",
        foreground="#2c3e50",
        fieldbackground="#ffffff",
        font=("微软雅黑", f9),
        rowheight=max(24, int(24 * dpi_scale)),
    )
    style.configure(
        "Treeview.Heading",
        font=("微软雅黑", f9, "bold"),
        background="#ecf0f1",
        foreground="#2c3e50",
    )
    style.map(
        "Treeview",
        background=[("selected", "#3498db")],
        foreground=[("selected", "#ffffff")],
    )

    # 交替行 tag 样式（在 Treeview 中使用 tag_configure 设置）
    # 注意：交替色通过 Treeview 的 tag_configure 实现，见各组件

    # Tooltip 样式
    style.configure(
        "Tooltip.TLabel",
        font=("微软雅黑", f9),
        foreground="#2c3e50",
        background="#ffffe0",
        relief=tk.SOLID,
        borderwidth=1,
        padding=(6, 3),
    )

    # Tooltip 边框
    style.configure(
        "Tooltip.TFrame",
        background="#d4d4d4",
        relief=tk.SOLID,
        borderwidth=1,
    )

    # 日志级别筛选下拉框
    style.configure(
        "LogFilter.TCombobox",
        font=("微软雅黑", f9),
    )


def _enable_dpi_awareness(root: tk.Tk) -> None:
    """启用 Windows 高 DPI 感知

    Args:
        root: Tkinter 根窗口实例
    """
    try:
        if sys.platform == "win32":
            # Windows 8.1+ DPI 感知
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
    except Exception:
        pass

    try:
        # 设置 Tk 缩放因子
        dpi_scale = _get_system_dpi()
        root.tk.call("tk", "scaling", dpi_scale * 1.33333)
    except Exception:
        pass


def apply_treeview_alternating_rows(tree: ttk.Treeview) -> None:
    """为 Treeview 配置交替行颜色

    在数据加载后调用此函数，为奇偶行设置不同的背景色。

    Args:
        tree: ttk.Treeview 实例
    """
    tree.tag_configure("odd_row", background="#f8f9fa")
    tree.tag_configure("even_row", background="#ffffff")
    tree.tag_configure("odd_row_selected", background="#3498db", foreground="#ffffff")
    tree.tag_configure("even_row_selected", background="#3498db", foreground="#ffffff")


class ToolTip:
    """轻量级 Tooltip 提示框

    鼠标悬停在控件上时显示提示文字，移开后自动隐藏。

    用法::

        tip = ToolTip(button, "这是一个按钮")
        tip.show()  # 或自动在悬停时显示
    """

    def __init__(
        self,
        widget: tk.Widget,
        text: str,
        delay: int = 500,
    ) -> None:
        """初始化 Tooltip

        Args:
            widget: 关联的控件
            text: 提示文本
            delay: 显示延迟（毫秒）
        """
        self._widget = widget
        self._text = text
        self._delay = delay
        self._tip_window: Optional[tk.Toplevel] = None
        self._after_id: Optional[str] = None

        # 绑定鼠标事件
        self._widget.bind("<Enter>", self._on_enter)
        self._widget.bind("<Leave>", self._on_leave)
        self._widget.bind("<ButtonPress>", self._on_leave)

    def _on_enter(self, event: Optional[tk.Event] = None) -> None:
        """鼠标进入控件时启动延迟显示"""
        self._cancel()
        self._after_id = self._widget.after(self._delay, self._show_tip)

    def _on_leave(self, event: Optional[tk.Event] = None) -> None:
        """鼠标离开控件时隐藏提示"""
        self._cancel()
        self._hide_tip()

    def _cancel(self) -> None:
        """取消待执行的显示计划"""
        if self._after_id:
            self._widget.after_cancel(self._after_id)
            self._after_id = None

    def _show_tip(self) -> None:
        """显示提示窗口"""
        if self._tip_window:
            return

        x = self._widget.winfo_rootx() + 20
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 5

        self._tip_window = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)

        label = tk.Label(
            tw,
            text=self._text,
            justify=tk.LEFT,
            font=("微软雅黑", 9),
            background="#ffffe0",
            foreground="#2c3e50",
            relief=tk.SOLID,
            borderwidth=1,
            padx=6,
            pady=3,
        )
        label.pack()

    def _hide_tip(self) -> None:
        """隐藏提示窗口"""
        if self._tip_window:
            self._tip_window.destroy()
            self._tip_window = None

    def update_text(self, new_text: str) -> None:
        """更新提示文本

        Args:
            new_text: 新的提示文本
        """
        self._text = new_text
