"""DWG标注提取与回写工具 - 程序入口

启动 Tkinter 主窗口，初始化应用界面。
"""

import sys
from pathlib import Path

# 将项目根目录加入 sys.path，确保各模块可正确导入
sys.path.insert(0, str(Path(__file__).parent))

import tkinter as tk

from gui.app import Application
from config.settings import APP_TITLE, APP_GEOMETRY, APP_MIN_SIZE


def main() -> None:
    """应用程序入口函数"""
    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry(APP_GEOMETRY)
    root.minsize(*APP_MIN_SIZE)

    # 创建并填充主应用组件
    app = Application(root)
    app.pack(fill=tk.BOTH, expand=True)

    # 启动 Tkinter 事件循环
    root.mainloop()


if __name__ == "__main__":
    main()
