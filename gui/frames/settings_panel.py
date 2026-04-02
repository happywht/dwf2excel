"""可折叠设置面板组件

提供回写配置选项：序号样式、偏移量、文字高度、回写图层等。
支持折叠/展开切换。
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional

from core.models import NumberStyle, WriteBackConfig


class SettingsPanel(ttk.LabelFrame):
    """可折叠设置面板

    默认折叠状态，点击标题标签可切换展开/折叠。
    提供回写配置参数的编辑界面。
    """

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, text=" 回写设置 ", style="Group.TLabelframe")
        self._collapsed: bool = True  # 默认折叠
        self._content_frame: Optional[ttk.Frame] = None

        # 绑定标题点击事件（折叠/展开）
        self.bind("<Button-1>", self._on_header_click)
        # 获取 LabelFrame 内部的标签控件并绑定点击
        self._bind_label_click()

        self._setup_ui()

    def _bind_label_click(self) -> None:
        """绑定 LabelFrame 标题标签的点击事件"""
        # 使用 after 延迟绑定，确保内部标签已创建
        self.after(10, self._do_bind_label)

    def _do_bind_label(self) -> None:
        """实际绑定标题标签的点击事件"""
        try:
            # LabelFrame 的内部标签是第一个子控件
            for child in self.winfo_children():
                if isinstance(child, ttk.Label):
                    child.bind("<Button-1>", self._on_header_click)
                    break
        except Exception:
            pass

    def _setup_ui(self) -> None:
        """构建设置面板 UI"""
        self._content_frame = ttk.Frame(self)

        # 使用 grid 布局设置表单
        content = self._content_frame
        row = 0

        # 第一行：序号样式
        ttk.Label(content, text="序号样式:").grid(
            row=row, column=0, sticky=tk.W, padx=(10, 5), pady=3
        )
        style_frame = ttk.Frame(content)
        style_frame.grid(row=row, column=1, sticky=tk.W, padx=5, pady=3)

        self._number_style_var = tk.StringVar(value=NumberStyle.CIRCLED.value)
        for style_enum in NumberStyle:
            ttk.Radiobutton(
                style_frame,
                text=style_enum.value,
                variable=self._number_style_var,
                value=style_enum.value,
            ).pack(side=tk.LEFT, padx=(0, 15))

        row += 1

        # 第二行：偏移X / 偏移Y
        ttk.Label(content, text="偏移 X:").grid(
            row=row, column=0, sticky=tk.W, padx=(10, 5), pady=3
        )
        self._offset_x_var = tk.DoubleVar(value=5.0)
        offset_x_spin = ttk.Spinbox(
            content,
            from_=0,
            to=50,
            increment=0.5,
            textvariable=self._offset_x_var,
            width=8,
        )
        offset_x_spin.grid(row=row, column=1, sticky=tk.W, padx=5, pady=3)

        row += 1

        ttk.Label(content, text="偏移 Y:").grid(
            row=row, column=0, sticky=tk.W, padx=(10, 5), pady=3
        )
        self._offset_y_var = tk.DoubleVar(value=5.0)
        offset_y_spin = ttk.Spinbox(
            content,
            from_=0,
            to=50,
            increment=0.5,
            textvariable=self._offset_y_var,
            width=8,
        )
        offset_y_spin.grid(row=row, column=1, sticky=tk.W, padx=5, pady=3)

        row += 1

        # 第三行：文字高度
        ttk.Label(content, text="文字高度:").grid(
            row=row, column=0, sticky=tk.W, padx=(10, 5), pady=3
        )
        self._text_height_var = tk.DoubleVar(value=3.0)
        text_height_spin = ttk.Spinbox(
            content,
            from_=1,
            to=20,
            increment=0.5,
            textvariable=self._text_height_var,
            width=8,
        )
        text_height_spin.grid(row=row, column=1, sticky=tk.W, padx=5, pady=3)

        row += 1

        # 第四行：回写图层
        ttk.Label(content, text="回写图层:").grid(
            row=row, column=0, sticky=tk.W, padx=(10, 5), pady=3
        )
        self._layer_name_var = tk.StringVar(value="ANNOTATION_IDX")
        layer_entry = ttk.Entry(content, textvariable=self._layer_name_var, width=20)
        layer_entry.grid(row=row, column=1, sticky=tk.W, padx=5, pady=3)

        # 折叠提示标签
        self._hint_var = tk.StringVar(value="  [ 点击展开设置 ]")
        self._hint_label = ttk.Label(
            self, textvariable=self._hint_var, style="Small.TLabel"
        )
        self._hint_label.pack(anchor=tk.W, padx=10, pady=2)
        self._hint_label.bind("<Button-1>", self._on_header_click)

        # 初始折叠状态 - 不显示内容
        # _content_frame 不 pack 即为折叠状态

    def _on_header_click(self, event: Optional[tk.Event] = None) -> None:
        """处理标题/提示标签点击事件，切换折叠状态"""
        self.toggle_collapse()

    def toggle_collapse(self) -> None:
        """切换面板的折叠/展开状态"""
        if self._collapsed:
            # 展开：显示内容区域，隐藏提示标签
            self._hint_label.pack_forget()
            self._content_frame.pack(fill=tk.X, padx=5, pady=5)
            self._hint_var.set("  [ 点击折叠设置 ]")
            self._hint_label.pack(anchor=tk.W, padx=10, pady=(0, 2))
            self._collapsed = False
        else:
            # 折叠：隐藏内容区域，更新提示文本
            self._content_frame.pack_forget()
            self._hint_label.pack_forget()
            self._hint_var.set("  [ 点击展开设置 ]")
            self._hint_label.pack(anchor=tk.W, padx=10, pady=2)
            self._collapsed = True

    def get_write_config(self) -> WriteBackConfig:
        """根据当前面板设置构造 WriteBackConfig 对象

        Returns:
            WriteBackConfig: 回写配置对象
        """
        # 解析序号样式
        style_value = self._number_style_var.get()
        number_style = NumberStyle.CIRCLED
        for ns in NumberStyle:
            if ns.value == style_value:
                number_style = ns
                break

        # 安全读取数值，Spinbox 内容可能为空或非法
        try:
            offset_x = self._offset_x_var.get()
        except (tk.TclError, ValueError):
            offset_x = 5.0

        try:
            offset_y = self._offset_y_var.get()
        except (tk.TclError, ValueError):
            offset_y = 5.0

        try:
            text_height = self._text_height_var.get()
        except (tk.TclError, ValueError):
            text_height = 3.0

        layer_name = self._layer_name_var.get().strip()
        if not layer_name:
            layer_name = "ANNOTATION_IDX"

        return WriteBackConfig(
            number_style=number_style,
            offset_x=offset_x,
            offset_y=offset_y,
            text_height=text_height,
            layer_name=layer_name,
        )
