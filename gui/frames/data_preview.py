"""数据预览表格组件

使用 ttk.Treeview 展示标注提取结果，支持列排序、选择、状态栏显示。
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional

from core.models import AnnotationItem


class DataPreviewFrame(ttk.LabelFrame):
    """数据预览表格

    以表格形式展示从 DWG/DXF 文件中提取的标注数据，
    包含序号、标注内容、坐标、类型、图层、来源文件等列。
    """

    # 列定义：(列标识, 列标题, 列宽)
    COLUMNS: list[tuple[str, str, int]] = [
        ("index", "序号", 50),
        ("content", "标注内容", 200),
        ("x", "X坐标", 80),
        ("y", "Y坐标", 80),
        ("type", "标注类型", 80),
        ("layer", "图层名", 100),
        ("source", "来源文件", 120),
    ]

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, text=" 数据预览 ", style="Group.TLabelframe")
        self._items: list[AnnotationItem] = []  # 当前展示的数据
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建数据预览区域的 UI"""
        # ===== Treeview + 滚动条 =====
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(5, 2))

        # 列标识列表
        col_ids = [col[0] for col in self.COLUMNS]

        self._tree = ttk.Treeview(
            tree_frame,
            columns=col_ids,
            show="headings",
            selectmode="extended",
        )

        # 配置各列
        for col_id, col_title, col_width in self.COLUMNS:
            self._tree.heading(col_id, text=col_title, anchor=tk.CENTER)
            self._tree.column(
                col_id,
                width=col_width,
                minwidth=40,
                anchor=tk.CENTER if col_id in ("index", "x", "y") else tk.W,
            )

        # 垂直滚动条
        scrollbar_y = ttk.Scrollbar(
            tree_frame, orient=tk.VERTICAL, command=self._tree.yview
        )
        # 水平滚动条
        scrollbar_x = ttk.Scrollbar(
            tree_frame, orient=tk.HORIZONTAL, command=self._tree.xview
        )

        self._tree.configure(
            yscrollcommand=scrollbar_y.set,
            xscrollcommand=scrollbar_x.set,
        )

        # 布局
        self._tree.grid(row=0, column=0, sticky="nsew")
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        scrollbar_x.grid(row=1, column=0, sticky="ew")

        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        # ===== 底部状态栏 =====
        status_frame = ttk.Frame(self)
        status_frame.pack(fill=tk.X, padx=5, pady=(2, 5))

        self._status_var = tk.StringVar(value="总计: 0 条记录")
        ttk.Label(
            status_frame, textvariable=self._status_var, style="Info.TLabel"
        ).pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def load_data(self, items: list[AnnotationItem]) -> None:
        """清空并加载标注数据到表格

        Args:
            items: AnnotationItem 列表
        """
        self.clear_data()
        self._items = list(items)

        for item in self._items:
            self._tree.insert("", tk.END, values=(
                item.index,
                item.content,
                round(item.x, 4),
                round(item.y, 4),
                item.annotation_type.value,
                item.layer,
                item.source_file,
            ))

        self._status_var.set(f"总计: {len(self._items)} 条记录")

    def clear_data(self) -> None:
        """清空表格所有数据"""
        # 删除所有行
        for child in self._tree.get_children():
            self._tree.delete(child)
        self._items.clear()
        self._status_var.set("总计: 0 条记录")

    def get_selected_items(self) -> list[AnnotationItem]:
        """获取表格中当前选中行对应的 AnnotationItem

        Returns:
            选中的 AnnotationItem 列表
        """
        selected_indices: list[int] = []
        for child in self._tree.selection():
            # 通过 item 在 children 中的位置找到对应索引
            children = self._tree.get_children()
            if child in children:
                idx = list(children).index(child)
                if 0 <= idx < len(self._items):
                    selected_indices.append(idx)

        return [self._items[i] for i in selected_indices if i < len(self._items)]

    def get_item_count(self) -> int:
        """获取当前表格中的数据总条数

        Returns:
            数据条数
        """
        return len(self._items)
