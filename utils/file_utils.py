"""文件操作辅助工具"""

import os
from pathlib import Path
from typing import Optional


def collect_files(paths: list[str], extensions: set[str]) -> list[str]:
    """
    从路径列表收集所有支持格式的文件

    Args:
        paths: 输入路径列表（可以是文件路径或目录路径）
        extensions: 允许的文件后缀集合，如 {".dxf", ".dwg"}

    Returns:
        符合后缀要求的文件绝对路径列表
    """
    result = []
    for path in paths:
        p = Path(path)
        if p.is_file():
            if p.suffix.lower() in extensions:
                result.append(str(p.resolve()))
        elif p.is_dir():
            for ext in extensions:
                # 使用 rglob 递归搜索
                for f in p.rglob(f"*{ext}"):
                    result.append(str(f.resolve()))
    return result


def get_output_path(
    input_path: str,
    suffix: str,
    output_dir: Optional[str] = None,
) -> str:
    """
    生成输出文件路径

    Args:
        input_path: 输入文件路径
        suffix: 输出文件后缀，如 "_annotated"
        output_dir: 输出目录，为 None 时与输入文件同目录

    Returns:
        输出文件的完整路径
    """
    p = Path(input_path)
    stem = p.stem + suffix
    ext = p.suffix

    if output_dir:
        out = Path(output_dir)
        ensure_dir(str(out))
        return str(out / f"{stem}{ext}")
    else:
        return str(p.parent / f"{stem}{ext}")


def ensure_dir(path: str) -> None:
    """
    确保目录存在，不存在则创建

    Args:
        path: 目录路径
    """
    os.makedirs(path, exist_ok=True)
