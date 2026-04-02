"""文件选择区域组件

提供 DWG/DXF 文件的选择、展示与管理功能。
支持浏览文件、浏览文件夹、多选、去重、右键菜单等交互。
"""

import os
import tkinter as tk
from tkinter import ttk, filedialog
from typing import Callable, Optional

from config.settings import SUPPORTED_EXTENSIONS


class FileSelectFrame(ttk.LabelFrame):
    """文件选择区域

    包含路径输入框、文件浏览按钮、文件列表（支持多选）、
    底部操作按钮栏（全选/反选/移除选中）和文件数量标签。
    """

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, text=" 文件选择 ", style="Group.TLabelframe")
        self._files: list[str] = []  # 内部文件路径列表（去重后）
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """构建文件选择区域的完整 UI"""
        # ===== 顶部：路径输入 + 浏览按钮 =====
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, padx=5, pady=(5, 2))

        ttk.Label(top_frame, text="文件路径:").pack(side=tk.LEFT, padx=(0, 5))

        self._path_var = tk.StringVar()
        self._path_entry = ttk.Entry(top_frame, textvariable=self._path_var)
        self._path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        ttk.Button(
            top_frame, text="浏览文件", command=self._on_browse_files
        ).pack(side=tk.LEFT, padx=(0, 3))

        ttk.Button(
            top_frame, text="浏览文件夹", command=self._on_browse_folder
        ).pack(side=tk.LEFT)

        # ===== 中部：文件列表 + 滚动条 =====
        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

        self._listbox = tk.Listbox(
            list_frame,
            selectmode=tk.EXTENDED,
            height=6,
            font=("Consolas", 9),
            activestyle="none",
        )

        scrollbar_y = ttk.Scrollbar(
            list_frame, orient=tk.VERTICAL, command=self._listbox.yview
        )
        scrollbar_x = ttk.Scrollbar(
            list_frame, orient=tk.HORIZONTAL, command=self._listbox.xview
        )

        self._listbox.configure(
            yscrollcommand=scrollbar_y.set,
            xscrollcommand=scrollbar_x.set,
        )

        self._listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        scrollbar_x.grid(row=1, column=0, sticky="ew")

        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        # 右键菜单
        self._context_menu = tk.Menu(self._listbox, tearoff=0)
        self._context_menu.add_command(label="移除选中项", command=self.remove_selected)
        self._context_menu.add_command(label="清空列表", command=self.clear_all)
        self._listbox.bind("<Button-3>", self._show_context_menu)

        # ===== 底部：操作按钮 + 文件数量 =====
        bottom_frame = ttk.Frame(self)
        bottom_frame.pack(fill=tk.X, padx=5, pady=(2, 5))

        ttk.Button(
            bottom_frame, text="全选", command=self._select_all
        ).pack(side=tk.LEFT, padx=(0, 3))

        ttk.Button(
            bottom_frame, text="反选", command=self._invert_selection
        ).pack(side=tk.LEFT, padx=(0, 3))

        ttk.Button(
            bottom_frame, text="移除选中", command=self.remove_selected
        ).pack(side=tk.LEFT)

        self._count_var = tk.StringVar(value="共 0 个文件")
        ttk.Label(
            bottom_frame, textvariable=self._count_var, style="Info.TLabel"
        ).pack(side=tk.RIGHT, padx=5)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def get_selected_files(self) -> list[str]:
        """获取文件列表中所有文件路径

        Returns:
            文件路径列表
        """
        return list(self._files)

    def add_files(self, paths: list[str]) -> None:
        """向列表中添加文件路径（自动去重）

        Args:
            paths: 要添加的文件路径列表
        """
        existing_set = set(self._files)
        added = False
        for path in paths:
            abs_path = os.path.abspath(path)
            if abs_path not in existing_set:
                self._files.append(abs_path)
                existing_set.add(abs_path)
                added = True

        if added:
            self._refresh_listbox()

    def remove_selected(self) -> None:
        """移除列表中当前选中的文件"""
        selected_indices = list(self._listbox.curselection())
        if not selected_indices:
            return

        # 从后往前删除，避免索引偏移
        for idx in sorted(selected_indices, reverse=True):
            if 0 <= idx < len(self._files):
                del self._files[idx]

        self._refresh_listbox()

    def clear_all(self) -> None:
        """清空所有文件"""
        self._files.clear()
        self._refresh_listbox()

    # ------------------------------------------------------------------
    # 浏览操作
    # ------------------------------------------------------------------

    def _on_browse_files(self) -> None:
        """浏览文件对话框，筛选支持的文件后缀"""
        # 构建文件类型过滤器
        ext_list = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))
        filetypes = [
            ("DWG/DXF 文件", ext_list),
            ("DWG 文件", "*.dwg"),
            ("DXF 文件", "*.dxf"),
            ("所有文件", "*.*"),
        ]

        paths = filedialog.askopenfilenames(
            parent=self,
            title="选择 DWG/DXF 文件",
            filetypes=filetypes,
        )

        if paths:
            self.add_files(list(paths))

    def _on_browse_folder(self) -> None:
        """浏览文件夹对话框，递归收集其中的 .dxf/.dwg 文件"""
        folder = filedialog.askdirectory(
            parent=self,
            title="选择包含 DWG/DXF 文件的文件夹",
        )

        if not folder:
            return

        # 递归收集文件夹中的支持文件
        collected: list[str] = []
        for root_dir, _dirs, files in os.walk(folder):
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    collected.append(os.path.join(root_dir, filename))

        if collected:
            self.add_files(collected)
        else:
            # 在列表中显示提示
            self._path_var.set(f"文件夹中未找到 DWG/DXF 文件: {folder}")

    # ------------------------------------------------------------------
    # 列表操作
    # ------------------------------------------------------------------

    def _select_all(self) -> None:
        """全选列表中的所有文件"""
        self._listbox.select_set(0, tk.END)
        self._listbox.focus_set()

    def _invert_selection(self) -> None:
        """反选列表中的文件"""
        total = self._listbox.size()
        for i in range(total):
            if self._listbox.selection_includes(i):
                self._listbox.selection_clear(i)
            else:
                self._listbox.selection_set(i)

    def _show_context_menu(self, event: tk.Event) -> None:
        """显示右键上下文菜单"""
        # 先选中右键点击的项
        clicked_index = self._listbox.nearest(event.y)
        if clicked_index >= 0:
            if not self._listbox.selection_includes(clicked_index):
                self._listbox.selection_clear(0, tk.END)
                self._listbox.selection_set(clicked_index)
            self._context_menu.tk_popup(event.x_root, event.y_root)

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _refresh_listbox(self) -> None:
        """刷新 Listbox 显示内容"""
        self._listbox.delete(0, tk.END)
        for file_path in self._files:
            self._listbox.insert(tk.END, file_path)
        self._count_var.set(f"共 {len(self._files)} 个文件")
