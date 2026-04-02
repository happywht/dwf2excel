"""数据预览表格组件

使用 ttk.Treeview 展示标注提取结果，支持列排序、筛选、搜索、
双击编辑、删除、去重、类型颜色区分、行交替色、
正则表达式搜索、行号显示、复制选中内容、右键导出、
列显示/隐藏、统计摘要、全屏预览等功能。
"""

import csv
import io
import math
import os
import re
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Optional

from core.models import AnnotationItem, AnnotationType, ContentCategory
from gui.styles import apply_treeview_alternating_rows


# 标注类型 -> 前景色映射（用于 Treeview tag）
_TYPE_COLORS: dict[str, str] = {
    "线性标注": "#2c3e50",
    "对齐标注": "#2c3e50",
    "角度标注": "#8e44ad",
    "半径标注": "#2980b9",
    "直径标注": "#2980b9",
    "坐标标注": "#2980b9",
    "弧长标注": "#2980b9",
    "未知标注": "#7f8c8d",
    "单行文字": "#27ae60",
    "多行文字": "#27ae60",
    "引线标注": "#d35400",
    "多重引线": "#d35400",
    "表格": "#c0392b",
    "公差标注": "#8e44ad",
    "属性定义": "#16a085",
    "属性值": "#16a085",
}


class DataPreviewFrame(ttk.LabelFrame):
    """数据预览表格

    以表格形式展示从 DWG/DXF 文件中提取的标注数据，
    包含序号、标注内容、坐标、类型、图层、来源文件、文字高度、
    旋转角度、所属图层、空间、分类等列。
    支持列头排序、类型筛选、图层筛选、关键字搜索（支持正则）、
    双击编辑、删除选中、清空全部、数据去重等操作。
    支持右键导出选中行、列显示/隐藏切换、统计摘要、
    全屏预览、复制选中内容到剪贴板。
    """

    # 列定义：(列标识, 列标题, 列宽, 对齐方式)
    COLUMNS: list[tuple[str, str, int, str]] = [
        ("index", "序号", 50, tk.CENTER),
        ("content", "标注内容", 200, tk.W),
        ("x", "X坐标", 80, tk.CENTER),
        ("y", "Y坐标", 80, tk.CENTER),
        ("type", "标注类型", 80, tk.W),
        ("layer", "图层名", 100, tk.W),
        ("source", "来源文件", 120, tk.W),
        ("height", "文字高度", 70, tk.CENTER),
        ("rotation", "旋转角度", 70, tk.CENTER),
        ("space", "空间", 60, tk.CENTER),
        ("category", "分类", 70, tk.W),
    ]

    # 分页参数
    PAGE_SIZE = 2000  # 每页显示的记录数

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, text=" 数据预览 ", style="Group.TLabelframe")
        self._items: list[AnnotationItem] = []  # 当前展示的完整数据
        self._filtered_items: list[AnnotationItem] = []  # 筛选后的数据

        # 排序状态
        self._sort_column: str = ""
        self._sort_reverse: bool = False

        # 列可见性（默认全部可见）
        self._visible_columns: dict[str, bool] = {
            col[0]: True for col in self.COLUMNS
        }

        # 正则搜索开关
        self._regex_search: bool = False

        # 全屏模式状态
        self._is_fullscreen: bool = False
        self._fullscreen_window: Optional[tk.Toplevel] = None

        # 分页状态
        self._current_page: int = 1
        self._total_pages: int = 1

        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建数据预览区域的 UI"""
        # ===== 筛选工具栏 =====
        filter_frame = ttk.Frame(self)
        filter_frame.pack(fill=tk.X, padx=5, pady=(5, 2))

        ttk.Label(filter_frame, text="类型:").pack(side=tk.LEFT, padx=(0, 3))
        self._type_filter_var = tk.StringVar(value="全部")
        self._type_filter_combo = ttk.Combobox(
            filter_frame,
            textvariable=self._type_filter_var,
            values=self._get_type_filter_options(),
            state="readonly",
            width=12,
        )
        self._type_filter_combo.pack(side=tk.LEFT, padx=(0, 10))
        self._type_filter_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_filters())

        ttk.Label(filter_frame, text="图层:").pack(side=tk.LEFT, padx=(0, 3))
        self._layer_filter_var = tk.StringVar(value="全部")
        self._layer_filter_combo = ttk.Combobox(
            filter_frame,
            textvariable=self._layer_filter_var,
            values=["全部"],
            state="readonly",
            width=16,
        )
        self._layer_filter_combo.pack(side=tk.LEFT, padx=(0, 10))
        self._layer_filter_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_filters())

        ttk.Label(filter_frame, text="搜索:").pack(side=tk.LEFT, padx=(0, 3))
        self._search_var = tk.StringVar()
        self._search_entry = ttk.Entry(filter_frame, textvariable=self._search_var, width=20)
        self._search_entry.pack(side=tk.LEFT, padx=(0, 3))
        # 实时搜索：绑定 trace
        self._search_var.trace_add("write", lambda *_: self._apply_filters())

        # 正则搜索开关
        self._regex_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            filter_frame, text="正则", variable=self._regex_var,
            command=self._apply_filters,
        ).pack(side=tk.LEFT, padx=(0, 10))

        # 操作按钮
        ttk.Button(
            filter_frame, text="统计", command=self._show_statistics
        ).pack(side=tk.RIGHT, padx=(3, 0))

        ttk.Button(
            filter_frame, text="全屏", command=self._toggle_fullscreen
        ).pack(side=tk.RIGHT, padx=(3, 0))

        ttk.Button(
            filter_frame, text="去重", command=self._on_deduplicate
        ).pack(side=tk.RIGHT, padx=(3, 0))

        ttk.Button(
            filter_frame, text="清空全部", command=self._on_clear_all_data
        ).pack(side=tk.RIGHT, padx=(3, 0))

        ttk.Button(
            filter_frame, text="删除选中", command=self._on_delete_selected
        ).pack(side=tk.RIGHT, padx=(3, 0))

        # ===== Treeview + 滚动条 =====
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

        # 列标识列表
        col_ids = [col[0] for col in self.COLUMNS]

        self._tree = ttk.Treeview(
            tree_frame,
            columns=col_ids,
            show="headings",
            selectmode="extended",
        )

        # 配置各列
        for col_id, col_title, col_width, anchor in self.COLUMNS:
            self._tree.heading(
                col_id,
                text=col_title,
                anchor=tk.CENTER,
                command=lambda c=col_id: self._on_column_click(c),
            )
            self._tree.column(
                col_id,
                width=col_width,
                minwidth=40,
                anchor=anchor,
            )

        # 配置 Treeview tag（按标注类型着色 + 行交替色）
        for type_name, color in _TYPE_COLORS.items():
            tag_name = f"type_{type_name}"
            self._tree.tag_configure(tag_name, foreground=color)

        # 行交替色
        apply_treeview_alternating_rows(self._tree)

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

        # 双击编辑
        self._tree.bind("<Double-1>", self._on_double_click)

        # 复制选中内容到剪贴板（Ctrl+C）
        self._tree.bind("<Control-c>", self._on_copy_selected)
        self._tree.bind("<Control-C>", self._on_copy_selected)

        # 右键菜单
        self._setup_context_menu()

        # ===== 底部状态栏 + 分页导航 =====
        status_frame = ttk.Frame(self)
        status_frame.pack(fill=tk.X, padx=5, pady=(2, 5))

        self._status_var = tk.StringVar(value="总计: 0 条记录")
        ttk.Label(
            status_frame, textvariable=self._status_var, style="Info.TLabel"
        ).pack(side=tk.LEFT)

        # 分页导航控件
        nav_frame = ttk.Frame(status_frame)
        nav_frame.pack(side=tk.RIGHT)

        self._btn_prev = ttk.Button(
            nav_frame, text="< 上一页", command=self._prev_page, width=10, state=tk.DISABLED,
        )
        self._btn_prev.pack(side=tk.LEFT, padx=2)

        self._page_var = tk.StringVar(value="1/1")
        self._page_label = ttk.Label(
            nav_frame, textvariable=self._page_var, style="Info.TLabel", width=10, anchor=tk.CENTER,
        )
        self._page_label.pack(side=tk.LEFT, padx=2)

        self._btn_next = ttk.Button(
            nav_frame, text="下一页 >", command=self._next_page, width=10, state=tk.DISABLED,
        )
        self._btn_next.pack(side=tk.LEFT, padx=2)

    def _setup_context_menu(self) -> None:
        """构建右键上下文菜单"""
        self._context_menu = tk.Menu(self._tree, tearoff=0)

        # 导出子菜单
        export_menu = tk.Menu(self._context_menu, tearoff=0)
        export_menu.add_command(label="导出选中行为 CSV", command=self._export_selected_csv)
        export_menu.add_command(label="导出选中行为 Excel (CSV 格式)", command=self._export_selected_excel)
        self._context_menu.add_cascade(label="导出选中行", menu=export_menu)

        self._context_menu.add_command(label="复制选中单元格", command=self._on_copy_selected)
        self._context_menu.add_separator()

        # 列显示/隐藏子菜单
        self._column_menu = tk.Menu(self._context_menu, tearoff=0)
        for col_id, col_title, _, _ in self.COLUMNS:
            self._column_menu.add_command(
                label=f"切换显示: {col_title}",
                command=lambda c=col_id, t=col_title: self._toggle_column_visibility(c, t),
            )
        self._context_menu.add_cascade(label="列显示/隐藏", menu=self._column_menu)

        self._context_menu.add_separator()
        self._context_menu.add_command(label="显示所有列", command=self._show_all_columns)

        self._tree.bind("<Button-3>", self._show_context_menu)

    def _show_context_menu(self, event: tk.Event) -> None:
        """显示右键上下文菜单"""
        # 选中右键点击的行
        item_id = self._tree.identify_row(event.y)
        if item_id:
            if item_id not in self._tree.selection():
                self._tree.selection_set(item_id)
            self._context_menu.tk_popup(event.x_root, event.y_root)

    # ------------------------------------------------------------------
    # 列显示/隐藏
    # ------------------------------------------------------------------

    def _toggle_column_visibility(self, col_id: str, col_title: str) -> None:
        """切换列的显示/隐藏状态

        Args:
            col_id: 列标识
            col_title: 列标题（用于消息提示）
        """
        self._visible_columns[col_id] = not self._visible_columns[col_id]
        visible = self._visible_columns[col_id]
        self._tree.column(col_id, width=0 if not visible else self._get_default_width(col_id))
        if not visible:
            self._tree.column(col_id, minwidth=0, width=0, stretch=False)
        else:
            default_width = self._get_default_width(col_id)
            self._tree.column(col_id, minwidth=40, width=default_width, stretch=True)

    def _show_all_columns(self) -> None:
        """显示所有列"""
        for col_id, col_title, col_width, _ in self.COLUMNS:
            self._visible_columns[col_id] = True
            self._tree.column(col_id, minwidth=40, width=col_width, stretch=True)

    def _get_default_width(self, col_id: str) -> int:
        """获取列的默认宽度

        Args:
            col_id: 列标识

        Returns:
            默认宽度
        """
        for cid, _, w, _ in self.COLUMNS:
            if cid == col_id:
                return w
        return 80

    # ------------------------------------------------------------------
    # 导出功能
    # ------------------------------------------------------------------

    def _export_selected_csv(self) -> None:
        """导出选中行为 CSV 文件"""
        selected_items = self.get_selected_items()
        if not selected_items:
            messagebox.showinfo("提示", "请先选择要导出的行。", parent=self)
            return

        file_path = filedialog.asksaveasfilename(
            parent=self,
            title="导出选中行为 CSV",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
            initialfile="选中数据.csv",
        )
        if not file_path:
            return

        try:
            self._write_items_to_csv(selected_items, file_path)
            messagebox.showinfo("成功", f"已导出 {len(selected_items)} 条记录到:\n{file_path}", parent=self)
        except OSError as e:
            messagebox.showerror("错误", f"导出失败:\n{e}", parent=self)

    def _export_selected_excel(self) -> None:
        """导出选中行为 Excel 兼容的 CSV 文件（UTF-8 BOM）"""
        selected_items = self.get_selected_items()
        if not selected_items:
            messagebox.showinfo("提示", "请先选择要导出的行。", parent=self)
            return

        file_path = filedialog.asksaveasfilename(
            parent=self,
            title="导出选中行为 Excel",
            defaultextension=".csv",
            filetypes=[("CSV 文件 (Excel 兼容)", "*.csv"), ("所有文件", "*.*")],
            initialfile="选中数据_Excel.csv",
        )
        if not file_path:
            return

        try:
            self._write_items_to_csv(selected_items, file_path, bom=True)
            messagebox.showinfo("成功", f"已导出 {len(selected_items)} 条记录到:\n{file_path}", parent=self)
        except OSError as e:
            messagebox.showerror("错误", f"导出失败:\n{e}", parent=self)

    def _write_items_to_csv(
        self, items: list[AnnotationItem], file_path: str, bom: bool = False
    ) -> None:
        """将标注项列表写入 CSV 文件

        Args:
            items: 标注项列表
            file_path: 输出文件路径
            bom: 是否写入 UTF-8 BOM（Excel 兼容）
        """
        headers = [col[1] for col in self.COLUMNS]
        with open(file_path, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for item in items:
                writer.writerow([
                    item.index,
                    item.content,
                    round(item.x, 4),
                    round(item.y, 4),
                    item.annotation_type.value,
                    item.layer,
                    item.source_file,
                    round(item.height, 2) if item.height else "",
                    round(item.rotation, 2) if item.rotation else "",
                    "图纸" if item.paper_space else "模型",
                    item.category.value,
                ])

    # ------------------------------------------------------------------
    # 复制到剪贴板
    # ------------------------------------------------------------------

    def _on_copy_selected(self, event: Optional[tk.Event] = None) -> None:
        """复制选中单元格内容到剪贴板（Ctrl+C）"""
        selection = self._tree.selection()
        if not selection:
            return

        # 收集选中行数据
        rows: list[list[str]] = []
        for item_id in selection:
            values = self._tree.item(item_id, "values")
            rows.append([str(v) for v in values])

        if not rows:
            return

        # 用制表符分隔列，换行分隔行
        text = "\n".join("\t".join(row) for row in rows)

        try:
            self._tree.clipboard_clear()
            self._tree.clipboard_append(text)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # 统计摘要
    # ------------------------------------------------------------------

    def _show_statistics(self) -> None:
        """弹出当前筛选数据的统计摘要对话框"""
        data = self._filtered_items if self._filtered_items else self._items
        if not data:
            messagebox.showinfo("统计", "当前没有数据可统计。", parent=self)
            return

        # 计算统计信息
        total = len(data)
        type_counts: dict[str, int] = {}
        layer_counts: dict[str, int] = {}
        category_counts: dict[str, int] = {}
        file_counts: dict[str, int] = {}
        paper_count = 0
        model_count = 0

        for item in data:
            t = item.annotation_type.value
            type_counts[t] = type_counts.get(t, 0) + 1
            l = item.layer or "(未命名)"
            layer_counts[l] = layer_counts.get(l, 0) + 1
            c = item.category.value
            category_counts[c] = category_counts.get(c, 0) + 1
            f = os.path.basename(item.source_file) if item.source_file else "(未知)"
            file_counts[f] = file_counts.get(f, 0) + 1
            if item.paper_space:
                paper_count += 1
            else:
                model_count += 1

        # 构建统计文本
        lines: list[str] = []
        lines.append(f"{'=' * 50}")
        lines.append(f"  数据统计摘要 (共 {total} 条记录)")
        lines.append(f"{'=' * 50}")

        lines.append(f"\n--- 按标注类型 ---")
        for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
            pct = c / total * 100
            lines.append(f"  {t}: {c} 条 ({pct:.1f}%)")

        lines.append(f"\n--- 按内容分类 ---")
        for cat, c in sorted(category_counts.items(), key=lambda x: -x[1]):
            pct = c / total * 100
            lines.append(f"  {cat}: {c} 条 ({pct:.1f}%)")

        lines.append(f"\n--- 按图层 ---")
        for l, c in sorted(layer_counts.items(), key=lambda x: -x[1]):
            pct = c / total * 100
            lines.append(f"  {l}: {c} 条 ({pct:.1f}%)")

        lines.append(f"\n--- 按来源文件 ---")
        for f, c in sorted(file_counts.items(), key=lambda x: -x[1]):
            pct = c / total * 100
            lines.append(f"  {f}: {c} 条 ({pct:.1f}%)")

        lines.append(f"\n--- 空间分布 ---")
        lines.append(f"  模型空间: {model_count} 条 ({model_count / total * 100:.1f}%)")
        lines.append(f"  图纸空间: {paper_count} 条 ({paper_count / total * 100:.1f}%)")

        stat_text = "\n".join(lines)

        # 弹出对话框
        dialog = tk.Toplevel(self)
        dialog.title("数据统计摘要")
        dialog.geometry("550x500")
        dialog.transient(self)
        dialog.grab_set()

        # 居中
        dialog.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - 550) // 2
        y = self.winfo_rooty() + (self.winfo_height() - 500) // 2
        dialog.geometry(f"+{x}+{y}")

        text_widget = tk.Text(
            dialog, font=("Consolas", 9), wrap=tk.WORD, padx=10, pady=10
        )
        scrollbar = ttk.Scrollbar(dialog, orient=tk.VERTICAL, command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)

        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        text_widget.insert("1.0", stat_text)
        text_widget.configure(state=tk.DISABLED)

        # 复制按钮
        btn_frame = ttk.Frame(dialog)
        btn_frame.place(relx=0.5, rely=0.95, anchor=tk.CENTER)

        def copy_stats() -> None:
            try:
                dialog.clipboard_clear()
                dialog.clipboard_append(stat_text)
                messagebox.showinfo("成功", "统计信息已复制到剪贴板。", parent=dialog)
            except tk.TclError:
                pass

        ttk.Button(btn_frame, text="复制统计信息", command=copy_stats).pack()

    # ------------------------------------------------------------------
    # 全屏预览
    # ------------------------------------------------------------------

    def _toggle_fullscreen(self) -> None:
        """切换全屏预览模式"""
        if self._is_fullscreen and self._fullscreen_window:
            self._fullscreen_window.destroy()
            self._fullscreen_window = None
            self._is_fullscreen = False
            return

        if not self._items:
            messagebox.showinfo("提示", "当前没有数据可预览。", parent=self)
            return

        self._is_fullscreen = True

        # 创建全屏窗口
        win = tk.Toplevel(self)
        win.title("数据预览 - 全屏模式 (按 Esc 退出)")
        win.geometry("1200x700")
        win.state("zoomed")  # Windows 最大化

        self._fullscreen_window = win

        # 复制 Treeview 结构
        col_ids = [col[0] for col in self.COLUMNS]
        fs_tree = ttk.Treeview(
            win, columns=col_ids, show="headings", selectmode="extended"
        )

        for col_id, col_title, col_width, anchor in self.COLUMNS:
            fs_tree.heading(
                col_id, text=col_title, anchor=tk.CENTER,
                command=lambda c=col_id: self._on_column_click(c),
            )
            fs_tree.column(col_id, width=col_width, minwidth=40, anchor=anchor)

        # 配置 tag
        for type_name, color in _TYPE_COLORS.items():
            tag_name = f"type_{type_name}"
            fs_tree.tag_configure(tag_name, foreground=color)
        apply_treeview_alternating_rows(fs_tree)

        # 滚动条
        sb_y = ttk.Scrollbar(win, orient=tk.VERTICAL, command=fs_tree.yview)
        sb_x = ttk.Scrollbar(win, orient=tk.HORIZONTAL, command=fs_tree.xview)
        fs_tree.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)

        fs_tree.grid(row=0, column=0, sticky="nsew")
        sb_y.grid(row=0, column=1, sticky="ns")
        sb_x.grid(row=1, column=0, sticky="ew")
        win.grid_rowconfigure(0, weight=1)
        win.grid_columnconfigure(0, weight=1)

        # 填充数据
        row_idx = 0
        for item in self._filtered_items:
            tag = f"type_{item.annotation_type.value}"
            row_tag = "odd_row" if row_idx % 2 == 0 else "even_row"
            fs_tree.insert("", tk.END, values=(
                item.index,
                item.content,
                round(item.x, 4),
                round(item.y, 4),
                item.annotation_type.value,
                item.layer,
                item.source_file,
                round(item.height, 2) if item.height else "",
                round(item.rotation, 2) if item.rotation else "",
                "图纸" if item.paper_space else "模型",
                item.category.value,
            ), tags=(tag, row_tag))
            row_idx += 1

        # Esc 退出
        win.bind("<Escape>", lambda e: self._toggle_fullscreen())
        win.protocol("WM_DELETE_WINDOW", self._toggle_fullscreen)

    # ------------------------------------------------------------------
    # 筛选工具栏辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _get_type_filter_options() -> list[str]:
        """获取类型筛选下拉框的选项列表"""
        options = ["全部"]
        for t in AnnotationType:
            options.append(t.value)
        return options

    def _update_layer_filter_options(self) -> None:
        """根据当前数据更新图层筛选下拉框的选项"""
        layers: set[str] = set()
        for item in self._items:
            if item.layer:
                layers.add(item.layer)

        current = self._layer_filter_var.get()
        options = ["全部"] + sorted(layers)
        self._layer_filter_combo["values"] = options
        if current in options:
            self._layer_filter_var.set(current)
        else:
            self._layer_filter_var.set("全部")

    # ------------------------------------------------------------------
    # 筛选逻辑
    # ------------------------------------------------------------------

    def _apply_filters(self) -> None:
        """根据筛选条件重新刷新表格显示

        支持正则表达式搜索（当正则开关开启时）。
        """
        type_filter = self._type_filter_var.get()
        layer_filter = self._layer_filter_var.get()
        keyword = self._search_var.get().strip()
        use_regex = self._regex_var.get()

        # 编译正则表达式
        regex_pattern: Optional[re.Pattern] = None
        if keyword and use_regex:
            try:
                regex_pattern = re.compile(keyword, re.IGNORECASE)
            except re.error as e:
                # 正则语法错误时回退为普通搜索
                regex_pattern = None

        filtered: list[AnnotationItem] = []
        for item in self._items:
            # 类型筛选
            if type_filter != "全部" and item.annotation_type.value != type_filter:
                continue
            # 图层筛选
            if layer_filter != "全部" and item.layer != layer_filter:
                continue
            # 关键字搜索（支持正则）
            if keyword:
                if use_regex and regex_pattern:
                    if not regex_pattern.search(item.content):
                        continue
                elif not use_regex:
                    if keyword.lower() not in item.content.lower():
                        continue
            filtered.append(item)

        self._filtered_items = filtered
        self._refresh_tree_display()

    def _refresh_tree_display(self) -> None:
        """根据 _filtered_items 刷新 Treeview 显示，包含行交替色"""
        # 删除所有行
        for child in self._tree.get_children():
            self._tree.delete(child)

        # 插入筛选后的数据（带行交替色）
        total = len(self._filtered_items)
        if total <= self.PAGE_SIZE:
            page_items = self._filtered_items
            self._current_page = 1
            self._total_pages = 1
        else:
            self._total_pages = max(1, math.ceil(total / self.PAGE_SIZE))
            if self._current_page > self._total_pages:
                self._current_page = self._total_pages
            start_idx = (self._current_page - 1) * self.PAGE_SIZE
            end_idx = min(start_idx + self.PAGE_SIZE, total)
            page_items = self._filtered_items[start_idx:end_idx]

        for row_idx, item in enumerate(page_items):
            tag = f"type_{item.annotation_type.value}"
            row_tag = "odd_row" if row_idx % 2 == 0 else "even_row"
            self._tree.insert("", tk.END, values=(
                row_idx + 1,  # 行号显示
                item.content,
                round(item.x, 4),
                round(item.y, 4),
                item.annotation_type.value,
                item.layer,
                item.source_file,
                round(item.height, 2) if item.height else "",
                round(item.rotation, 2) if item.rotation else "",
                "图纸" if item.paper_space else "模型",
                item.category.value,
            ), tags=(tag, row_tag))

        # 更新状态
        self._status_var.set(
            f"总计: {len(self._items)} 条记录"
            f"{f'，筛选显示: {len(self._filtered_items)} 条' if len(self._filtered_items) != len(self._items) else ''}"
        )

        # 自适应列宽
        self._auto_resize_columns()

        # 更新分页导航
        self._update_page_nav()

    def _auto_resize_columns(self) -> None:
        """根据内容自适应调整列宽"""
        for col_id, col_title, default_width, _ in self.COLUMNS:
            if not self._visible_columns.get(col_id, True):
                continue
            # 先设为标题宽度
            max_width = tk.font.nametofont("TkDefaultFont").measure(col_title) + 20
            # 遍历可见行计算最大内容宽度（限制遍历行数避免性能问题）
            children = self._tree.get_children()
            check_count = min(len(children), 200)
            for child in children[:check_count]:
                try:
                    col_index = [c[0] for c in self.COLUMNS].index(col_id)
                    values = self._tree.item(child, "values")
                    if col_index < len(values):
                        text = str(values[col_index])
                        w = tk.font.nametofont("TkDefaultFont").measure(text) + 15
                        if w > max_width:
                            max_width = w
                except (ValueError, IndexError):
                    pass
            # 设置宽度，但不超过合理上限
            final_width = min(max_width, 400)
            self._tree.column(col_id, width=max(final_width, default_width))

    # ------------------------------------------------------------------
    # 分页导航
    # ------------------------------------------------------------------

    def _prev_page(self) -> None:
        """上一页"""
        if self._current_page > 1:
            self._current_page -= 1
            self._refresh_tree_display()

    def _next_page(self) -> None:
        """下一页"""
        if self._current_page < self._total_pages:
            self._current_page += 1
            self._refresh_tree_display()

    def _update_page_nav(self) -> None:
        """更新分页导航按钮状态"""
        self._btn_prev.configure(
            state=tk.NORMAL if self._current_page > 1 else tk.DISABLED,
        )
        self._btn_next.configure(
            state=tk.NORMAL if self._current_page < self._total_pages else tk.DISABLED,
        )
        self._page_var.set(f"{self._current_page}/{self._total_pages}")

    # ------------------------------------------------------------------
    # 列头排序
    # ------------------------------------------------------------------

    def _on_column_click(self, col_id: str) -> None:
        """处理列头点击事件，实现升序/降序切换排序

        Args:
            col_id: 被点击的列标识
        """
        if self._sort_column == col_id:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = col_id
            self._sort_reverse = False

        # 排序 _filtered_items
        self._filtered_items.sort(
            key=lambda item: self._get_sort_key(item, col_id),
            reverse=self._sort_reverse,
        )

        # 刷新显示
        self._refresh_tree_display()

        # 更新列头文本，显示排序方向
        for col_id_i, col_title, _, _ in self.COLUMNS:
            display_title = col_title
            if col_id_i == self._sort_column:
                arrow = " \u25b2" if not self._sort_reverse else " \u25bc"
                display_title = col_title + arrow
            self._tree.heading(col_id_i, text=display_title)

    @staticmethod
    def _get_sort_key(item: AnnotationItem, col_id: str):
        """获取排序键值

        Args:
            item: 标注项
            col_id: 列标识

        Returns:
            用于排序的键值
        """
        mapping = {
            "index": item.index,
            "content": item.content,
            "x": item.x,
            "y": item.y,
            "type": item.annotation_type.value,
            "layer": item.layer,
            "source": item.source_file,
            "height": item.height,
            "rotation": item.rotation,
            "space": 1 if item.paper_space else 0,
            "category": item.category.value,
        }
        return mapping.get(col_id, "")

    # ------------------------------------------------------------------
    # 双击编辑
    # ------------------------------------------------------------------

    def _on_double_click(self, event: tk.Event) -> None:
        """处理双击事件，弹出编辑对话框"""
        selection = self._tree.selection()
        if not selection:
            return

        item_id = selection[0]
        children = list(self._tree.get_children())
        if item_id not in children:
            return

        idx = children.index(item_id)
        if idx < 0 or idx >= len(self._filtered_items):
            return

        annotation_item = self._filtered_items[idx]
        self._show_edit_dialog(annotation_item)

    def _show_edit_dialog(self, item: AnnotationItem) -> None:
        """弹出编辑对话框

        Args:
            item: 要编辑的标注项
        """
        dialog = tk.Toplevel(self)
        dialog.title("编辑标注内容")
        dialog.geometry("450x150")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        # 居中显示
        dialog.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - 450) // 2
        y = self.winfo_rooty() + (self.winfo_height() - 150) // 2
        dialog.geometry(f"+{x}+{y}")

        frame = ttk.Frame(dialog, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="标注内容:").grid(row=0, column=0, sticky=tk.W, pady=5)
        content_var = tk.StringVar(value=item.content)
        content_entry = ttk.Entry(frame, textvariable=content_var, width=50)
        content_entry.grid(row=0, column=1, sticky=tk.EW, padx=(10, 0), pady=5)
        content_entry.select_range(0, tk.END)
        content_entry.focus_set()

        # 显示当前项的一些信息
        info_text = (
            f"类型: {item.annotation_type.value}  |  "
            f"图层: {item.layer}  |  "
            f"坐标: ({round(item.x, 2)}, {round(item.y, 2)})"
        )
        ttk.Label(frame, text=info_text, style="Small.TLabel").grid(
            row=1, column=0, columnspan=2, sticky=tk.W, pady=(5, 10)
        )

        frame.grid_columnconfigure(1, weight=1)

        def on_ok() -> None:
            new_content = content_var.get().strip()
            if new_content:
                item.content = new_content
                self._apply_filters()
            dialog.destroy()

        def on_cancel() -> None:
            dialog.destroy()

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=(5, 0))

        ttk.Button(btn_frame, text="确定", command=on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=on_cancel).pack(side=tk.LEFT, padx=5)

        # 绑定回车键
        dialog.bind("<Return>", lambda e: on_ok())
        dialog.bind("<Escape>", lambda e: on_cancel())

    # ------------------------------------------------------------------
    # 删除与清空
    # ------------------------------------------------------------------

    def _on_delete_selected(self) -> None:
        """删除表格中选中的行（同时从数据中移除）"""
        selection = self._tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择要删除的行。", parent=self)
            return

        children = list(self._tree.get_children())
        items_to_remove: list[AnnotationItem] = []
        for item_id in selection:
            if item_id in children:
                idx = children.index(item_id)
                if 0 <= idx < len(self._filtered_items):
                    items_to_remove.append(self._filtered_items[idx])

        if not items_to_remove:
            return

        count = len(items_to_remove)
        if not messagebox.askyesno(
            "确认删除", f"确定要删除选中的 {count} 条记录吗？", parent=self
        ):
            return

        # 从 _items 中移除
        remove_set = set(id(item) for item in items_to_remove)
        self._items = [item for item in self._items if id(item) not in remove_set]

        # 更新图层筛选选项
        self._update_layer_filter_options()

        # 重新应用筛选
        self._apply_filters()

    def _on_clear_all_data(self) -> None:
        """清空全部数据"""
        if not self._items:
            return

        if not messagebox.askyesno(
            "确认清空", "确定要清空所有数据吗？此操作不可撤销。", parent=self
        ):
            return

        self.clear_data()

    # ------------------------------------------------------------------
    # 数据去重
    # ------------------------------------------------------------------

    def _on_deduplicate(self) -> None:
        """对当前数据进行去重

        去重规则：同一文件中 content 相同且 (x,y) 距离小于阈值（默认 1.0 单位）的标注视为重复。
        使用空间网格索引加速近邻查询，从 O(n²) 降至近似 O(n)。
        """
        if not self._items:
            messagebox.showinfo("提示", "当前没有数据可去重。", parent=self)
            return

        distance_threshold = 1.0
        original_count = len(self._items)

        # 第一步：按 (来源文件, 内容) 分组，大幅缩小比较范围
        from collections import defaultdict

        groups: dict[tuple[str, str], list[AnnotationItem]] = defaultdict(list)
        for item in self._items:
            groups[(item.source_file, item.content)].append(item)

        # 第二步：组内使用空间网格索引进行近距离去重
        unique_items: list[AnnotationItem] = []
        for group_items in groups.values():
            if len(group_items) == 1:
                unique_items.append(group_items[0])
                continue

            # 空间网格：cell_size = 阈值，只需检查当前格 + 8 个相邻格
            cell_size = distance_threshold
            grid: dict[tuple[int, int], list[AnnotationItem]] = {}

            for item in group_items:
                gx = int(item.x / cell_size)
                gy = int(item.y / cell_size)

                is_dup = False
                for dx in (-1, 0, 1):
                    if is_dup:
                        break
                    for dy in (-1, 0, 1):
                        cell_key = (gx + dx, gy + dy)
                        if cell_key in grid:
                            for existing in grid[cell_key]:
                                dist = math.sqrt(
                                    (item.x - existing.x) ** 2 +
                                    (item.y - existing.y) ** 2
                                )
                                if dist < distance_threshold:
                                    is_dup = True
                                    break
                        if is_dup:
                            break

                if not is_dup:
                    grid.setdefault((gx, gy), []).append(item)
                    unique_items.append(item)

        removed_count = original_count - len(unique_items)
        if removed_count == 0:
            messagebox.showinfo("去重结果", "未发现重复数据。", parent=self)
            return

        self._items = unique_items
        self._update_layer_filter_options()
        self._apply_filters()

        messagebox.showinfo(
            "去重结果",
            f"去重完成：移除了 {removed_count} 条重复记录。\n"
            f"原始: {original_count} 条 -> 去重后: {len(unique_items)} 条",
            parent=self,
        )

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
        self._filtered_items = list(items)

        # 更新图层筛选选项
        self._update_layer_filter_options()

        # 重置筛选条件
        self._type_filter_var.set("全部")
        self._layer_filter_var.set("全部")
        self._search_var.set("")

        # 重置排序状态
        self._sort_column = ""
        self._sort_reverse = False

        # 重置分页
        self._current_page = 1
        self._total_pages = 1

        # 刷新显示
        self._refresh_tree_display()

    def clear_data(self) -> None:
        """清空表格所有数据"""
        for child in self._tree.get_children():
            self._tree.delete(child)
        self._items.clear()
        self._filtered_items.clear()
        self._status_var.set("总计: 0 条记录")

        # 重置分页
        self._current_page = 1
        self._total_pages = 1
        self._update_page_nav()

    def get_selected_items(self) -> list[AnnotationItem]:
        """获取表格中当前选中行对应的 AnnotationItem

        Returns:
            选中的 AnnotationItem 列表
        """
        selected_indices: list[int] = []
        children = list(self._tree.get_children())
        for child in self._tree.selection():
            if child in children:
                idx = children.index(child)
                if 0 <= idx < len(self._filtered_items):
                    selected_indices.append(idx)

        return [self._filtered_items[i] for i in selected_indices if i < len(self._filtered_items)]

    def get_item_count(self) -> int:
        """获取当前表格中的数据总条数

        Returns:
            数据条数
        """
        return len(self._items)

    def get_all_items(self) -> list[AnnotationItem]:
        """获取当前所有标注数据

        Returns:
            全部 AnnotationItem 列表
        """
        return list(self._items)
