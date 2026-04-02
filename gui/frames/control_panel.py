"""操作按钮面板组件

提供核心操作的按钮入口：提取标注、生成报表、序号回写、打开输出目录。
"""

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional


class ControlPanel(ttk.Frame):
    """操作按钮区域

    四个主按钮水平排列，通过回调函数与主应用逻辑解耦。
    支持整体启用/禁用按钮状态。
    """

    def __init__(
        self,
        parent: tk.Widget,
        on_extract: Optional[Callable] = None,
        on_generate: Optional[Callable] = None,
        on_writeback: Optional[Callable] = None,
        on_open_output: Optional[Callable] = None,
    ) -> None:
        """初始化操作面板

        Args:
            parent: 父容器
            on_extract: 提取标注按钮回调
            on_generate: 生成报表按钮回调
            on_writeback: 序号回写按钮回调
            on_open_output: 打开输出目录按钮回调
        """
        super().__init__(parent)
        self._on_extract = on_extract
        self._on_generate = on_generate
        self._on_writeback = on_writeback
        self._on_open_output = on_open_output

        self._buttons: list[ttk.Button] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建操作面板 UI"""
        # 左侧按钮区域
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=8)

        btn_extract = ttk.Button(
            btn_frame,
            text="提取标注",
            style="Primary.TButton",
            command=self._safe_call(self._on_extract),
        )
        btn_extract.pack(side=tk.LEFT, padx=(0, 8))
        self._buttons.append(btn_extract)

        btn_generate = ttk.Button(
            btn_frame,
            text="生成报表",
            style="Primary.TButton",
            command=self._safe_call(self._on_generate),
        )
        btn_generate.pack(side=tk.LEFT, padx=(0, 8))
        self._buttons.append(btn_generate)

        btn_writeback = ttk.Button(
            btn_frame,
            text="序号回写",
            style="Primary.TButton",
            command=self._safe_call(self._on_writeback),
        )
        btn_writeback.pack(side=tk.LEFT, padx=(0, 8))
        self._buttons.append(btn_writeback)

        btn_open_output = ttk.Button(
            btn_frame,
            text="打开输出目录",
            style="Danger.TButton",
            command=self._safe_call(self._on_open_output),
        )
        btn_open_output.pack(side=tk.LEFT)
        self._buttons.append(btn_open_output)

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
