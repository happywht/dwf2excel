"""文件选择区域组件

提供 DWG/DXF 文件的选择、展示与管理功能。
支持浏览文件、浏览文件夹、多选、去重、右键菜单、
剪贴板粘贴文件路径、键盘快捷键、文件状态显示、
文件大小信息、最近使用目录记忆、双击定位文件等交互。
"""

import os
import platform
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Callable, Optional

from config.settings import SUPPORTED_EXTENSIONS


class FileSelectFrame(ttk.LabelFrame):
    """文件选择区域

    包含路径输入框、文件浏览按钮、最近目录下拉框、文件列表（支持多选）、
    底部操作按钮栏（全选/反选/移除选中）和文件数量标签。
    支持通过右键菜单从剪贴板粘贴文件路径。
    支持键盘快捷键：Delete 删除选中项，Ctrl+A 全选。
    支持文件状态显示（图标表示文件存在/不存在/大小）。
    支持双击文件在文件管理器中定位该文件。
    支持最近使用目录快速选择。
    """

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, text=" 文件选择 ", style="Group.TLabelframe")
        self._files: list[str] = []  # 内部文件路径列表（去重后）
        # 记忆目录回调（由 app.py 设置）
        self._get_last_dir: Optional[Callable[[], str]] = None
        self._set_last_dir: Optional[Callable[[str], None]] = None

        # 最近使用目录（最多记忆5个）
        self._recent_dirs: list[str] = []
        self._max_recent_dirs: int = 5

        # 文件状态图标
        self._status_icons = {
            "exists": "[OK]",       # 文件存在
            "missing": "[??]",      # 文件不存在
        }

        self._setup_ui()
        self._bind_keyboard()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """构建文件选择区域的完整 UI"""
        # ===== 顶部：路径输入 + 最近目录 + 浏览按钮 =====
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, padx=5, pady=(5, 2))

        ttk.Label(top_frame, text="文件路径:").pack(side=tk.LEFT, padx=(0, 5))

        self._path_var = tk.StringVar()
        self._path_entry = ttk.Entry(top_frame, textvariable=self._path_var)
        self._path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        # 回车键添加文件
        self._path_entry.bind("<Return>", self._on_path_entry_return)

        ttk.Button(
            top_frame, text="浏览文件", command=self._on_browse_files
        ).pack(side=tk.LEFT, padx=(0, 3))

        ttk.Button(
            top_frame, text="浏览文件夹", command=self._on_browse_folder
        ).pack(side=tk.LEFT, padx=(0, 3))

        # 第二行：最近使用目录下拉框
        recent_frame = ttk.Frame(self)
        recent_frame.pack(fill=tk.X, padx=5, pady=(0, 2))

        ttk.Label(recent_frame, text="最近目录:", style="Small.TLabel").pack(
            side=tk.LEFT, padx=(0, 3)
        )
        self._recent_dir_var = tk.StringVar()
        self._recent_dir_combo = ttk.Combobox(
            recent_frame,
            textvariable=self._recent_dir_var,
            values=[],
            state="readonly",
            width=60,
            font=("Consolas", 8),
        )
        self._recent_dir_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self._recent_dir_combo.bind("<<ComboboxSelected>>", self._on_recent_dir_selected)

        ttk.Button(
            recent_frame, text="添加此目录文件", command=self._on_add_recent_dir_files,
            style="Small.TButton",
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
        self._context_menu.add_command(label="粘贴文件路径", command=self._on_paste_file_paths)
        self._context_menu.add_command(label="在文件管理器中定位", command=self._on_locate_file)
        self._context_menu.add_separator()
        self._context_menu.add_command(label="移除选中项", command=self.remove_selected)
        self._context_menu.add_command(label="移除不存在的文件", command=self._remove_missing_files)
        self._context_menu.add_command(label="清空列表", command=self.clear_all)
        self._listbox.bind("<Button-3>", self._show_context_menu)

        # 双击在文件管理器中定位
        self._listbox.bind("<Double-Button-1>", self._on_double_click_file)

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
        ).pack(side=tk.LEFT, padx=(0, 3))

        ttk.Button(
            bottom_frame, text="移除无效", command=self._remove_missing_files
        ).pack(side=tk.LEFT)

        self._count_var = tk.StringVar(value="共 0 个文件")
        ttk.Label(
            bottom_frame, textvariable=self._count_var, style="Info.TLabel"
        ).pack(side=tk.RIGHT, padx=5)

    def _bind_keyboard(self) -> None:
        """绑定键盘快捷键"""
        self._listbox.bind("<Delete>", lambda e: self.remove_selected())
        self._listbox.bind("<Control-a>", lambda e: self._select_all())
        # 确保焦点在 listbox 时能接收键盘事件
        self._listbox.bind("<FocusIn>", self._on_listbox_focus_in)

    def _on_listbox_focus_in(self, event: Optional[tk.Event] = None) -> None:
        """Listbox 获得焦点时，绑定全局快捷键"""
        pass  # 快捷键已通过 bind 绑定

    # ------------------------------------------------------------------
    # 目录记忆接口
    # ------------------------------------------------------------------

    def set_dir_callbacks(
        self,
        get_last_dir: Callable[[], str],
        set_last_dir: Callable[[str], None],
    ) -> None:
        """设置目录记忆回调

        Args:
            get_last_dir: 获取上次目录的回调
            set_last_dir: 设置上次目录的回调
        """
        self._get_last_dir = get_last_dir
        self._set_last_dir = set_last_dir

    def _get_initial_dir(self) -> Optional[str]:
        """获取初始目录（记忆的上次目录）"""
        if self._get_last_dir:
            d = self._get_last_dir()
            if d and os.path.isdir(d):
                return d
        return None

    def _save_dir(self, path: str) -> None:
        """保存使用的目录到最近目录列表"""
        directory = os.path.dirname(path) if os.path.isfile(path) else path
        if not directory or not os.path.isdir(directory):
            return

        # 更新最近目录列表
        if directory in self._recent_dirs:
            self._recent_dirs.remove(directory)
        self._recent_dirs.insert(0, directory)
        if len(self._recent_dirs) > self._max_recent_dirs:
            self._recent_dirs = self._recent_dirs[:self._max_recent_dirs]

        # 更新下拉框
        self._update_recent_dir_combo()

        # 通过回调保存
        if self._set_last_dir:
            self._set_last_dir(directory)

    def _update_recent_dir_combo(self) -> None:
        """更新最近目录下拉框"""
        self._recent_dir_combo["values"] = list(self._recent_dirs)

    def _on_recent_dir_selected(self, event: Optional[tk.Event] = None) -> None:
        """选择最近目录时，将路径填入路径输入框"""
        selected = self._recent_dir_var.get()
        if selected:
            self._path_var.set(selected)

    def _on_add_recent_dir_files(self) -> None:
        """从最近目录下拉框选择的目录中添加文件"""
        selected = self._recent_dir_var.get()
        if not selected:
            messagebox.showinfo("提示", "请先从下拉框选择一个目录。", parent=self)
            return
        if not os.path.isdir(selected):
            messagebox.showwarning("警告", f"目录不存在: {selected}", parent=self)
            return

        # 递归收集文件夹中的支持文件
        collected: list[str] = []
        for root_dir, _dirs, files in os.walk(selected):
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    collected.append(os.path.join(root_dir, filename))

        if collected:
            self.add_files(collected)
            self._save_dir(selected)
        else:
            messagebox.showinfo(
                "提示", f"目录中未找到 DWG/DXF 文件:\n{selected}", parent=self
            )

    # ------------------------------------------------------------------
    # 路径输入框回车添加
    # ------------------------------------------------------------------

    def _on_path_entry_return(self, event: Optional[tk.Event] = None) -> None:
        """在路径输入框中按回车时，尝试添加输入的路径"""
        path = self._path_var.get().strip().strip('"').strip("'")
        if not path:
            return

        paths: list[str] = []
        if os.path.isfile(path):
            ext = os.path.splitext(path)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                paths.append(path)
        elif os.path.isdir(path):
            for root_dir, _dirs, files in os.walk(path):
                for filename in files:
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        paths.append(os.path.join(root_dir, filename))

        if paths:
            self.add_files(paths)
            self._path_var.set("")
        else:
            messagebox.showinfo(
                "提示",
                f"未找到有效的 DWG/DXF 文件:\n{path}",
                parent=self,
            )

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def get_selected_files(self) -> list[str]:
        """获取文件列表中所有文件路径

        Returns:
            文件路径列表
        """
        return list(self._files)

    def get_file_count(self) -> int:
        """获取文件数量"""
        return len(self._files)

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

        initialdir = self._get_initial_dir()

        paths = filedialog.askopenfilenames(
            parent=self,
            title="选择 DWG/DXF 文件",
            filetypes=filetypes,
            initialdir=initialdir,
        )

        if paths:
            path_list = list(paths)
            self.add_files(path_list)
            # 记忆目录
            if path_list:
                self._save_dir(path_list[0])

    def _on_browse_folder(self) -> None:
        """浏览文件夹对话框，递归收集其中的 .dxf/.dwg 文件"""
        initialdir = self._get_initial_dir()

        folder = filedialog.askdirectory(
            parent=self,
            title="选择包含 DWG/DXF 文件的文件夹",
            initialdir=initialdir,
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
            self._save_dir(folder)
        else:
            # 在列表中显示提示
            self._path_var.set(f"文件夹中未找到 DWG/DXF 文件: {folder}")

    # ------------------------------------------------------------------
    # 剪贴板粘贴文件路径
    # ------------------------------------------------------------------

    def _on_paste_file_paths(self) -> None:
        """从剪贴板读取文件路径并添加到列表

        支持以下格式：
        - 单个文件路径
        - 多个文件路径（每行一个）
        - Windows 资源管理器复制的文件路径（带换行）
        """
        try:
            clipboard_text = self.clipboard_get()
        except tk.TclError:
            messagebox.showinfo("提示", "剪贴板中没有内容。", parent=self)
            return

        if not clipboard_text or not clipboard_text.strip():
            return

        # 按换行分割，去除空白和引号
        raw_lines = clipboard_text.strip().splitlines()
        paths: list[str] = []

        for line in raw_lines:
            line = line.strip().strip('"').strip("'")
            if not line:
                continue
            # 检查文件是否存在
            if os.path.isfile(line):
                ext = os.path.splitext(line)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    paths.append(line)
            elif os.path.isdir(line):
                # 如果是目录，递归搜索支持的文件
                for root_dir, _dirs, files in os.walk(line):
                    for filename in files:
                        ext = os.path.splitext(filename)[1].lower()
                        if ext in SUPPORTED_EXTENSIONS:
                            paths.append(os.path.join(root_dir, filename))

        if paths:
            self.add_files(paths)
        else:
            messagebox.showinfo(
                "提示",
                "剪贴板中未找到有效的 DWG/DXF 文件路径。\n"
                "请复制文件路径后再试。",
                parent=self,
            )

    # ------------------------------------------------------------------
    # 文件定位与管理
    # ------------------------------------------------------------------

    def _on_double_click_file(self, event: tk.Event) -> None:
        """双击文件列表项，在文件管理器中定位该文件"""
        selection = self._listbox.curselection()
        if not selection:
            return

        idx = selection[0]
        if idx < 0 or idx >= len(self._files):
            return

        file_path = self._files[idx]
        self._locate_in_explorer(file_path)

    def _on_locate_file(self) -> None:
        """右键菜单：在文件管理器中定位选中文件"""
        selection = self._listbox.curselection()
        if not selection:
            return

        idx = selection[0]
        if idx < 0 or idx >= len(self._files):
            return

        file_path = self._files[idx]
        self._locate_in_explorer(file_path)

    def _locate_in_explorer(self, file_path: str) -> None:
        """在系统文件管理器中定位并选中指定文件

        Args:
            file_path: 文件路径
        """
        if not os.path.exists(file_path):
            messagebox.showwarning(
                "文件不存在", f"文件不存在:\n{file_path}", parent=self
            )
            return

        try:
            system = platform.system()
            if system == "Windows":
                # Windows: 使用 explorer /select 定位文件
                subprocess.run(
                    ['explorer', '/select,', os.path.normpath(file_path)],
                    check=False,
                )
            elif system == "Darwin":
                subprocess.run(["open", "-R", file_path], check=True)
            else:
                # Linux: 打开所在目录
                subprocess.run(
                    ["xdg-open", os.path.dirname(file_path)], check=True
                )
        except Exception as e:
            messagebox.showerror(
                "错误", f"无法在文件管理器中定位:\n{e}", parent=self
            )

    def _remove_missing_files(self) -> None:
        """移除列表中不存在的文件路径"""
        original_count = len(self._files)
        self._files = [f for f in self._files if os.path.isfile(f)]
        removed = original_count - len(self._files)
        if removed > 0:
            self._refresh_listbox()
            messagebox.showinfo(
                "清理完成",
                f"已移除 {removed} 个不存在的文件路径。",
                parent=self,
            )
        else:
            messagebox.showinfo("提示", "所有文件路径均有效。", parent=self)

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

    def _format_file_size(self, size_bytes: float) -> str:
        """格式化文件大小为人类可读字符串

        Args:
            size_bytes: 字节数

        Returns:
            格式化后的大小字符串
        """
        if size_bytes < 0:
            return "N/A"
        if size_bytes < 1024:
            return f"{size_bytes:.0f} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"

    def _refresh_listbox(self) -> None:
        """刷新 Listbox 显示内容，包含文件状态图标和大小信息"""
        self._listbox.delete(0, tk.END)

        valid_count = 0
        total_size: float = 0.0

        for file_path in self._files:
            # 文件状态图标
            if os.path.isfile(file_path):
                status = self._status_icons["exists"]
                valid_count += 1
                try:
                    file_size = os.path.getsize(file_path)
                    total_size += file_size
                    size_str = self._format_file_size(file_size)
                except OSError:
                    size_str = "N/A"
            else:
                status = self._status_icons["missing"]
                size_str = "N/A"

            # 格式化显示：状态图标 + 文件大小 + 路径
            display = f"{status} {size_str:>10s}  {file_path}"
            self._listbox.insert(tk.END, display)

            # 根据状态设置前景色
            if status == self._status_icons["missing"]:
                self._listbox.itemconfig(
                    self._listbox.size() - 1, foreground="#e74c3c"
                )

        # 更新计数信息
        missing_count = len(self._files) - valid_count
        size_info = self._format_file_size(total_size)
        if missing_count > 0:
            self._count_var.set(
                f"共 {len(self._files)} 个文件 "
                f"({valid_count} 有效, {missing_count} 无效) | {size_info}"
            )
        else:
            self._count_var.set(
                f"共 {len(self._files)} 个文件 | 总大小: {size_info}"
            )
