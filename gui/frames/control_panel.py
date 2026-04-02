"""操作按钮面板组件

提供核心操作的按钮入口：提取标注、生成报表、序号回写、打开输出目录、一键完成、取消操作。
支持按钮状态提示（Tooltip）、快捷键绑定（F5-F8）、
按钮状态与数据联动、取消操作按钮。
"""

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from gui.styles import ToolTip


class ControlPanel(ttk.Frame):
    """操作按钮区域

    六个主按钮水平排列（一键完成、提取标注、生成报表、序号回写、
    打开输出目录、取消操作），通过回调函数与主应用逻辑解耦。
    支持整体启用/禁用按钮状态、Tooltip 提示、快捷键绑定。
    """

    def __init__(
        self,
        parent: tk.Widget,
        on_extract: Optional[Callable] = None,
        on_generate: Optional[Callable] = None,
        on_writeback: Optional[Callable] = None,
        on_open_output: Optional[Callable] = None,
        on_one_click: Optional[Callable] = None,
        on_cancel: Optional[Callable] = None,
    ) -> None:
        """初始化操作面板

        Args:
            parent: 父容器
            on_extract: 提取标注按钮回调
            on_generate: 生成报表按钮回调
            on_writeback: 序号回写按钮回调
            on_open_output: 打开输出目录按钮回调
            on_one_click: 一键完成按钮回调
            on_cancel: 取消操作按钮回调
        """
        super().__init__(parent)
        self._on_extract = on_extract
        self._on_generate = on_generate
        self._on_writeback = on_writeback
        self._on_open_output = on_open_output
        self._on_one_click = on_one_click
        self._on_cancel = on_cancel

        self._buttons: list[ttk.Button] = []
        self._data_dependent_buttons: list[ttk.Button] = []  # 依赖数据的按钮
        self._cancel_button: Optional[ttk.Button] = None
        self._is_busy: bool = False

        self._setup_ui()
        self._setup_tooltips()
        self._bind_shortcuts(parent)

    def _setup_ui(self) -> None:
        """构建操作面板 UI"""
        # 左侧按钮区域
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=8)

        # 一键完成按钮
        btn_one_click = ttk.Button(
            btn_frame,
            text="一键完成(F8)",
            style="Accent.TButton",
            command=self._safe_call(self._on_one_click),
        )
        btn_one_click.pack(side=tk.LEFT, padx=(0, 8))
        self._buttons.append(btn_one_click)

        # 提取标注按钮
        btn_extract = ttk.Button(
            btn_frame,
            text="提取标注(F5)",
            style="Primary.TButton",
            command=self._safe_call(self._on_extract),
        )
        btn_extract.pack(side=tk.LEFT, padx=(0, 8))
        self._buttons.append(btn_extract)

        # 生成报表按钮（依赖数据）
        btn_generate = ttk.Button(
            btn_frame,
            text="生成报表(F6)",
            style="Primary.TButton",
            command=self._safe_call(self._on_generate),
        )
        btn_generate.pack(side=tk.LEFT, padx=(0, 8))
        self._buttons.append(btn_generate)
        self._data_dependent_buttons.append(btn_generate)

        # 序号回写按钮（依赖数据）
        btn_writeback = ttk.Button(
            btn_frame,
            text="序号回写(F7)",
            style="Primary.TButton",
            command=self._safe_call(self._on_writeback),
        )
        btn_writeback.pack(side=tk.LEFT, padx=(0, 8))
        self._buttons.append(btn_writeback)
        self._data_dependent_buttons.append(btn_writeback)

        # 打开输出目录按钮
        btn_open_output = ttk.Button(
            btn_frame,
            text="打开输出目录",
            style="Danger.TButton",
            command=self._safe_call(self._on_open_output),
        )
        btn_open_output.pack(side=tk.LEFT, padx=(0, 8))
        self._buttons.append(btn_open_output)

        # 取消操作按钮（仅在任务执行中显示）
        self._cancel_button = ttk.Button(
            btn_frame,
            text="取消操作(Esc)",
            style="Cancel.TButton",
            command=self._safe_call(self._on_cancel),
        )
        # 初始隐藏
        # self._cancel_button 不添加到 self._buttons，不受 set_buttons_enabled 管理

    def _setup_tooltips(self) -> None:
        """为每个按钮设置 Tooltip 状态提示"""
        self._tooltips: list[ToolTip] = []

        if len(self._buttons) >= 5:
            self._tooltips.append(ToolTip(
                self._buttons[0], "一键完成：依次执行提取标注 -> 生成报表 -> 序号回写（F8）"
            ))
            self._tooltips.append(ToolTip(
                self._buttons[1], "从选中的 DWG/DXF 文件中提取标注数据（F5）"
            ))
            self._tooltips.append(ToolTip(
                self._buttons[2], "将提取的标注数据生成 Excel 报表（F6）"
            ))
            self._tooltips.append(ToolTip(
                self._buttons[3], "将序号回写到原始 DWG/DXF 文件中（F7）"
            ))
            self._tooltips.append(ToolTip(
                self._buttons[4], "使用系统文件管理器打开输出目录"
            ))

        if self._cancel_button:
            self._tooltips.append(ToolTip(
                self._cancel_button, "取消当前正在执行的后台任务（Esc）"
            ))

    def _bind_shortcuts(self, parent: tk.Widget) -> None:
        """绑定全局快捷键

        Args:
            parent: 父容器（用于向上查找顶层窗口绑定快捷键）
        """
        # 延迟绑定，确保顶层窗口已创建
        self.after(50, self._do_bind_shortcuts)

    def _do_bind_shortcuts(self) -> None:
        """实际绑定快捷键到顶层窗口"""
        root = self.winfo_toplevel()

        root.bind("<F5>", lambda e: self._trigger_button(1))   # 提取标注
        root.bind("<F6>", lambda e: self._trigger_button(2))   # 生成报表
        root.bind("<F7>", lambda e: self._trigger_button(3))   # 序号回写
        root.bind("<F8>", lambda e: self._trigger_button(0))   # 一键完成
        root.bind("<Escape>", lambda e: self._trigger_cancel())  # 取消操作

    def _trigger_button(self, index: int) -> None:
        """触发指定索引的按钮点击

        Args:
            index: 按钮索引
        """
        if 0 <= index < len(self._buttons):
            btn = self._buttons[index]
            if str(btn.cget("state")) != "disabled":
                btn.invoke()

    def _trigger_cancel(self) -> None:
        """触发取消按钮"""
        if self._cancel_button and self._is_busy:
            self._cancel_button.invoke()

    def _safe_call(self, callback: Optional[Callable]) -> Callable:
        """将回调包装为安全的空操作（防止 None 回调）

        Args:
            callback: 原始回调函数，可能为 None

        Returns:
            包装后的安全回调函数
        """
        if callback is None:
            return lambda: None
        return callback

    def set_buttons_enabled(self, enabled: bool) -> None:
        """批量设置所有按钮的启用/禁用状态

        Args:
            enabled: True 启用，False 禁用
        """
        state = "normal" if enabled else "disabled"
        for btn in self._buttons:
            btn.configure(state=state)

        # 管理取消按钮的显示/隐藏
        self._is_busy = not enabled
        if self._cancel_button:
            if self._is_busy:
                self._cancel_button.pack(side=tk.RIGHT, padx=(8, 0))
                self._cancel_button.configure(state="normal")
            else:
                self._cancel_button.pack_forget()

    def set_data_state(self, has_data: bool) -> None:
        """设置数据状态，联动按钮可用性

        当无数据时，禁用"生成报表"和"序号回写"按钮；
        当有数据且不处于忙碌状态时，启用这些按钮。

        Args:
            has_data: True 表示已有提取数据
        """
        if not self._is_busy:
            state = "normal" if has_data else "disabled"
            for btn in self._data_dependent_buttons:
                btn.configure(state=state)

            # 更新 Tooltip 提示文本
            tooltip_idx_start = 2  # 生成报表和序号回写的 tooltip 索引
            for i, btn in enumerate(self._data_dependent_buttons):
                tip_idx = tooltip_idx_start + i
                if tip_idx < len(self._tooltips):
                    if has_data:
                        if i == 0:
                            self._tooltips[tip_idx].update_text(
                                "将提取的标注数据生成 Excel 报表（F6）"
                            )
                        elif i == 1:
                            self._tooltips[tip_idx].update_text(
                                "将序号回写到原始 DWG/DXF 文件中（F7）"
                            )
                    else:
                        if i == 0:
                            self._tooltips[tip_idx].update_text(
                                "请先执行「提取标注」获取数据后再生成报表（F6）"
                            )
                        elif i == 1:
                            self._tooltips[tip_idx].update_text(
                                "请先执行「提取标注」获取数据后再进行序号回写（F7）"
                            )
