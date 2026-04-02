"""全局 ttk 样式配置模块"""

import tkinter as tk
from tkinter import ttk


def setup_styles(root: tk.Tk) -> None:
    """配置全局 ttk 样式

    使用 clam 主题作为基础，自定义按钮、标签、进度条等控件样式，
    确保整个应用视觉风格统一。

    Args:
        root: Tkinter 根窗口实例
    """
    style = ttk.Style(root)
    style.theme_use("clam")

    # 主按钮 - 用于核心操作（提取标注、生成报表、序号回写）
    style.configure(
        "Primary.TButton",
        padding=(15, 8),
        font=("微软雅黑", 10, "bold"),
    )

    # 危险按钮 - 用于辅助操作（打开输出目录等）
    style.configure(
        "Danger.TButton",
        padding=(10, 5),
        font=("微软雅黑", 9),
    )

    # 标题标签
    style.configure(
        "Title.TLabel",
        font=("微软雅黑", 12, "bold"),
        foreground="#2c3e50",
    )

    # 信息标签
    style.configure(
        "Info.TLabel",
        font=("微软雅黑", 9),
        foreground="#7f8c8d",
    )

    # 小号信息标签
    style.configure(
        "Small.TLabel",
        font=("微软雅黑", 8),
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

    # 分组标签框架
    style.configure(
        "Group.TLabelframe",
        font=("微软雅黑", 10, "bold"),
    )
    style.configure(
        "Group.TLabelframe.Label",
        font=("微软雅黑", 10, "bold"),
        foreground="#2c3e50",
    )
