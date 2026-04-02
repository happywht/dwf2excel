"""可折叠设置面板组件

提供回写配置选项：序号样式、偏移量、文字高度、回写图层、
颜色、导出DWG开关、前缀后缀、自动高度开关等。
提供导出配置选项：汇总页开关、图层分组开关、CSV导出开关、JSON导出开关。
支持折叠/展开切换、配置持久化（加载/保存）、
重置为默认值、导入/导出配置（JSON）、自动保存、键盘快捷键支持。
"""

import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import Optional

from core.models import NumberStyle, WriteBackConfig, ExportConfig
from config.settings import AppConfig, save_config, load_config


class SettingsPanel(ttk.LabelFrame):
    """可折叠设置面板

    默认折叠状态，点击标题标签可切换展开/折叠。
    提供回写配置参数和导出配置参数的编辑界面。
    支持配置的持久化保存与加载、重置为默认值、
    导入/导出配置（JSON文件）、自动保存（脏标记+延迟保存）、
    键盘快捷键（Ctrl+S 保存配置）。
    """

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, text=" 设置 ", style="Group.TLabelframe")
        self._collapsed: bool = True  # 默认折叠
        self._content_frame: Optional[ttk.Frame] = None
        self._export_frame: Optional[ttk.LabelFrame] = None

        # 脏标记与自动保存
        self._dirty: bool = False
        self._auto_save_delay: int = 3000  # 自动保存延迟（毫秒）
        self._auto_save_after_id: Optional[str] = None

        # 折叠/展开动画
        self._animation_steps: int = 5
        self._animation_delay: int = 20  # 毫秒

        # 绑定标题点击事件（折叠/展开）
        self.bind("<Button-1>", self._on_header_click)
        # 获取 LabelFrame 内部的标签控件并绑定点击
        self._bind_label_click()

        self._setup_ui()
        self._load_config()
        self._bind_shortcuts()

        # 监听配置变更
        self._setup_change_listeners()

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

        # ===== 第一行：序号样式 =====
        ttk.Label(content, text="序号样式:").grid(
            row=row, column=0, sticky=tk.W, padx=(10, 5), pady=3
        )
        style_frame = ttk.Frame(content)
        style_frame.grid(row=row, column=1, columnspan=3, sticky=tk.W, padx=5, pady=3)

        self._number_style_var = tk.StringVar(value=NumberStyle.CIRCLED.value)
        for style_enum in NumberStyle:
            ttk.Radiobutton(
                style_frame,
                text=style_enum.value,
                variable=self._number_style_var,
                value=style_enum.value,
            ).pack(side=tk.LEFT, padx=(0, 15))

        row += 1

        # ===== 第二行：偏移X / 偏移Y =====
        ttk.Label(content, text="偏移 X:").grid(
            row=row, column=0, sticky=tk.W, padx=(10, 5), pady=3
        )
        self._offset_x_var = tk.DoubleVar(value=5.0)
        ttk.Spinbox(
            content,
            from_=0,
            to=50,
            increment=0.5,
            textvariable=self._offset_x_var,
            width=8,
        ).grid(row=row, column=1, sticky=tk.W, padx=5, pady=3)

        ttk.Label(content, text="偏移 Y:").grid(
            row=row, column=2, sticky=tk.W, padx=(10, 5), pady=3
        )
        self._offset_y_var = tk.DoubleVar(value=5.0)
        ttk.Spinbox(
            content,
            from_=0,
            to=50,
            increment=0.5,
            textvariable=self._offset_y_var,
            width=8,
        ).grid(row=row, column=3, sticky=tk.W, padx=5, pady=3)

        row += 1

        # ===== 第三行：文字高度 =====
        ttk.Label(content, text="文字高度:").grid(
            row=row, column=0, sticky=tk.W, padx=(10, 5), pady=3
        )
        self._text_height_var = tk.DoubleVar(value=3.0)
        ttk.Spinbox(
            content,
            from_=1,
            to=20,
            increment=0.5,
            textvariable=self._text_height_var,
            width=8,
        ).grid(row=row, column=1, sticky=tk.W, padx=5, pady=3)

        # 自动文字高度
        self._auto_text_height_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            content, text="自动适配", variable=self._auto_text_height_var
        ).grid(row=row, column=2, columnspan=2, sticky=tk.W, padx=5, pady=3)

        row += 1

        # ===== 第四行：回写图层 + 颜色 =====
        ttk.Label(content, text="回写图层:").grid(
            row=row, column=0, sticky=tk.W, padx=(10, 5), pady=3
        )
        self._layer_name_var = tk.StringVar(value="ANNOTATION_IDX")
        ttk.Entry(content, textvariable=self._layer_name_var, width=20).grid(
            row=row, column=1, sticky=tk.W, padx=5, pady=3
        )

        ttk.Label(content, text="颜色:").grid(
            row=row, column=2, sticky=tk.W, padx=(10, 5), pady=3
        )
        self._color_var = tk.IntVar(value=1)
        ttk.Spinbox(
            content,
            from_=0,
            to=256,
            increment=1,
            textvariable=self._color_var,
            width=8,
        ).grid(row=row, column=3, sticky=tk.W, padx=5, pady=3)

        row += 1

        # ===== 第五行：前缀 / 后缀 =====
        ttk.Label(content, text="前缀:").grid(
            row=row, column=0, sticky=tk.W, padx=(10, 5), pady=3
        )
        self._prefix_var = tk.StringVar(value="")
        ttk.Entry(content, textvariable=self._prefix_var, width=10).grid(
            row=row, column=1, sticky=tk.W, padx=5, pady=3
        )

        ttk.Label(content, text="后缀:").grid(
            row=row, column=2, sticky=tk.W, padx=(10, 5), pady=3
        )
        self._suffix_var = tk.StringVar(value="")
        ttk.Entry(content, textvariable=self._suffix_var, width=10).grid(
            row=row, column=3, sticky=tk.W, padx=5, pady=3
        )

        row += 1

        # ===== 第六行：导出DWG + 操作按钮 =====
        self._export_dwg_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            content, text="导出 DWG 格式", variable=self._export_dwg_var
        ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=(10, 5), pady=3)

        # 操作按钮区域
        btn_frame = ttk.Frame(content)
        btn_frame.grid(row=row, column=2, columnspan=2, sticky=tk.E, padx=(10, 5), pady=3)

        ttk.Button(
            btn_frame, text="保存配置", command=self._save_config
        ).pack(side=tk.RIGHT, padx=(3, 0))

        ttk.Button(
            btn_frame, text="重置默认", command=self._reset_to_defaults
        ).pack(side=tk.RIGHT, padx=(3, 0))

        row += 1

        # ===== 第七行：导入/导出配置按钮 =====
        io_frame = ttk.Frame(content)
        io_frame.grid(row=row, column=0, columnspan=4, sticky=tk.W, padx=(10, 5), pady=3)

        ttk.Button(
            io_frame, text="导入配置", command=self._on_import_config
        ).pack(side=tk.LEFT, padx=(0, 5))

        ttk.Button(
            io_frame, text="导出配置", command=self._on_export_config
        ).pack(side=tk.LEFT, padx=(0, 5))

        # 脏标记标签
        self._dirty_var = tk.StringVar(value="")
        ttk.Label(
            io_frame, textvariable=self._dirty_var, style="Small.TLabel"
        ).pack(side=tk.LEFT, padx=(10, 0))

        row += 1

        # ===== 分隔线 =====
        ttk.Separator(content, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=4, sticky=tk.EW, padx=10, pady=8
        )

        row += 1

        # ===== 导出设置区域 =====
        self._export_frame = ttk.LabelFrame(
            content, text=" 导出设置 ", style="Group.TLabelframe"
        )
        self._export_frame.grid(
            row=row, column=0, columnspan=4, sticky=tk.EW, padx=10, pady=(0, 5)
        )

        self._include_summary_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            self._export_frame, text="包含汇总统计页", variable=self._include_summary_var
        ).pack(anchor=tk.W, padx=10, pady=2)

        self._include_layer_view_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            self._export_frame, text="包含图层分组页", variable=self._include_layer_view_var
        ).pack(anchor=tk.W, padx=10, pady=2)

        self._include_csv_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            self._export_frame, text="同时导出 CSV", variable=self._include_csv_var
        ).pack(anchor=tk.W, padx=10, pady=2)

        self._include_json_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self._export_frame, text="同时导出 JSON", variable=self._include_json_var
        ).pack(anchor=tk.W, padx=10, pady=2)

        # 折叠提示标签
        self._hint_var = tk.StringVar(value="  [ 点击展开设置 ]")
        self._hint_label = ttk.Label(
            self, textvariable=self._hint_var, style="Small.TLabel"
        )
        self._hint_label.pack(anchor=tk.W, padx=10, pady=2)
        self._hint_label.bind("<Button-1>", self._on_header_click)

        # 初始折叠状态 - 不显示内容

    # ------------------------------------------------------------------
    # 键盘快捷键
    # ------------------------------------------------------------------

    def _bind_shortcuts(self) -> None:
        """绑定键盘快捷键"""
        self.after(100, self._do_bind_shortcuts)

    def _do_bind_shortcuts(self) -> None:
        """实际绑定快捷键到顶层窗口"""
        root = self.winfo_toplevel()
        root.bind("<Control-s>", lambda e: self._save_config())
        root.bind("<Control-S>", lambda e: self._save_config())

    # ------------------------------------------------------------------
    # 配置变更监听与自动保存
    # ------------------------------------------------------------------

    def _setup_change_listeners(self) -> None:
        """监听所有配置变量的变更"""
        variables = [
            self._number_style_var,
            self._offset_x_var,
            self._offset_y_var,
            self._text_height_var,
            self._layer_name_var,
            self._color_var,
            self._export_dwg_var,
            self._prefix_var,
            self._suffix_var,
            self._auto_text_height_var,
            self._include_summary_var,
            self._include_layer_view_var,
            self._include_csv_var,
            self._include_json_var,
        ]
        for var in variables:
            var.trace_add("write", self._on_config_changed)

    def _on_config_changed(self, *args) -> None:
        """配置变更回调：设置脏标记并启动自动保存定时器"""
        self._dirty = True
        self._dirty_var.set("(未保存)")

        # 取消之前的自动保存定时器
        if self._auto_save_after_id:
            self.after_cancel(self._auto_save_after_id)

        # 启动新的自动保存定时器
        self._auto_save_after_id = self.after(
            self._auto_save_delay, self._auto_save
        )

    def _auto_save(self) -> None:
        """自动保存配置"""
        if self._dirty:
            self._save_config_silent()
            self._dirty = False
            self._dirty_var.set("")
            self._auto_save_after_id = None

    # ------------------------------------------------------------------
    # 重置为默认值
    # ------------------------------------------------------------------

    def _reset_to_defaults(self) -> None:
        """重置所有配置为默认值"""
        if not messagebox.askyesno(
            "确认重置", "确定要重置所有设置为默认值吗？", parent=self
        ):
            return

        default_config = AppConfig()
        self._apply_config(default_config)
        self._save_config()
        messagebox.showinfo("成功", "已重置为默认配置。", parent=self)

    # ------------------------------------------------------------------
    # 导入/导出配置
    # ------------------------------------------------------------------

    def _on_import_config(self) -> None:
        """从 JSON 文件导入配置"""
        file_path = filedialog.askopenfilename(
            parent=self,
            title="导入配置文件",
            filetypes=[
                ("JSON 文件", "*.json"),
                ("所有文件", "*.*"),
            ],
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 构建 AppConfig
            config = AppConfig(**data) if data else AppConfig()
            self._apply_config(config)
            self._save_config()
            messagebox.showinfo("成功", f"已从文件导入配置:\n{file_path}", parent=self)
        except (json.JSONDecodeError, TypeError, OSError) as e:
            messagebox.showerror("错误", f"导入配置失败:\n{e}", parent=self)

    def _on_export_config(self) -> None:
        """导出当前配置到 JSON 文件"""
        file_path = filedialog.asksaveasfilename(
            parent=self,
            title="导出配置文件",
            defaultextension=".json",
            filetypes=[
                ("JSON 文件", "*.json"),
                ("所有文件", "*.*"),
            ],
            initialfile="dwg_annotool_config.json",
        )
        if not file_path:
            return

        try:
            config = self._collect_config()
            data = {
                "number_style": config.number_style,
                "offset_x": config.offset_x,
                "offset_y": config.offset_y,
                "text_height": config.text_height,
                "layer_name": config.layer_name,
                "color": config.color,
                "export_dwg": config.export_dwg,
                "prefix": config.prefix,
                "suffix": config.suffix,
                "auto_text_height": config.auto_text_height,
                "include_summary": config.include_summary,
                "include_layer_view": config.include_layer_view,
                "include_csv": config.include_csv,
                "include_json": config.include_json,
            }
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("成功", f"配置已导出到:\n{file_path}", parent=self)
        except OSError as e:
            messagebox.showerror("错误", f"导出配置失败:\n{e}", parent=self)

    # ------------------------------------------------------------------
    # 折叠/展开（带动画效果）
    # ------------------------------------------------------------------

    def _on_header_click(self, event: Optional[tk.Event] = None) -> None:
        """处理标题/提示标签点击事件，切换折叠状态"""
        self.toggle_collapse()

    def toggle_collapse(self) -> None:
        """切换面板的折叠/展开状态（带简单动画效果）"""
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

    # ------------------------------------------------------------------
    # 配置持久化
    # ------------------------------------------------------------------

    def _save_config(self) -> None:
        """保存当前面板配置到 JSON 文件"""
        config = self._collect_config()
        save_config(config)
        self._dirty = False
        self._dirty_var.set("")

    def _save_config_silent(self) -> None:
        """静默保存配置（不显示提示）"""
        try:
            config = self._collect_config()
            save_config(config)
        except Exception:
            pass

    def _load_config(self) -> None:
        """从 JSON 文件加载配置并填充到界面"""
        config = load_config()
        self._apply_config(config)

    def _collect_config(self) -> AppConfig:
        """从界面控件收集所有配置值

        Returns:
            AppConfig 实例
        """
        # 安全读取数值
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

        try:
            color = self._color_var.get()
        except (tk.TclError, ValueError):
            color = 1

        # 序号样式转枚举名
        style_value = self._number_style_var.get()
        style_name = "CIRCLED"
        for ns in NumberStyle:
            if ns.value == style_value:
                style_name = ns.name
                break

        return AppConfig(
            number_style=style_name,
            offset_x=offset_x,
            offset_y=offset_y,
            text_height=text_height,
            layer_name=self._layer_name_var.get().strip() or "ANNOTATION_IDX",
            color=color,
            export_dwg=self._export_dwg_var.get(),
            prefix=self._prefix_var.get(),
            suffix=self._suffix_var.get(),
            auto_text_height=self._auto_text_height_var.get(),
            include_summary=self._include_summary_var.get(),
            include_layer_view=self._include_layer_view_var.get(),
            include_csv=self._include_csv_var.get(),
            include_json=self._include_json_var.get(),
        )

    def _apply_config(self, config: AppConfig) -> None:
        """将配置应用到界面控件

        Args:
            config: AppConfig 实例
        """
        # 序号样式
        style_name = config.number_style
        for ns in NumberStyle:
            if ns.name == style_name:
                self._number_style_var.set(ns.value)
                break

        self._offset_x_var.set(config.offset_x)
        self._offset_y_var.set(config.offset_y)
        self._text_height_var.set(config.text_height)
        self._layer_name_var.set(config.layer_name)
        self._color_var.set(config.color)
        self._export_dwg_var.set(config.export_dwg)
        self._prefix_var.set(config.prefix)
        self._suffix_var.set(config.suffix)
        self._auto_text_height_var.set(config.auto_text_height)
        self._include_summary_var.set(config.include_summary)
        self._include_layer_view_var.set(config.include_layer_view)
        self._include_csv_var.set(config.include_csv)
        self._include_json_var.set(config.include_json)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

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

        # 安全读取数值
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

        try:
            color = self._color_var.get()
        except (tk.TclError, ValueError):
            color = 1

        layer_name = self._layer_name_var.get().strip()
        if not layer_name:
            layer_name = "ANNOTATION_IDX"

        return WriteBackConfig(
            number_style=number_style,
            offset_x=offset_x,
            offset_y=offset_y,
            text_height=text_height,
            layer_name=layer_name,
            color=color,
            export_dwg=self._export_dwg_var.get(),
            prefix=self._prefix_var.get(),
            suffix=self._suffix_var.get(),
            auto_text_height=self._auto_text_height_var.get(),
        )

    def get_export_config(self) -> ExportConfig:
        """根据当前面板设置构造 ExportConfig 对象

        Returns:
            ExportConfig: 导出配置对象
        """
        return ExportConfig(
            include_summary=self._include_summary_var.get(),
            include_layer_view=self._include_layer_view_var.get(),
            include_csv=self._include_csv_var.get(),
            include_json=self._include_json_var.get(),
        )

    def save_current_config(self) -> None:
        """保存当前配置（供外部调用）"""
        self._save_config()
