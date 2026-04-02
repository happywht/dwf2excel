"""DWG/DXF 文件标注提取核心解析模块

使用 ezdxf 库解析 DWG/DXF 文件，提取尺寸标注、单行文字、多行文字等标注实体，
并转换为统一的 AnnotationItem 数据模型。

DWG 文件读取策略：
  1. 优先使用 ezdxf odafc addon（需要安装 ODA File Converter）
  2. 回退到 ezdxf recover 模式（部分 DWG 可能支持）
  3. 均失败时提示用户安装 ODA File Converter 或转换文件格式
"""

import re
import os
import glob
import hashlib
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

import ezdxf
from ezdxf.entities import Dimension, Text, MText

from core.models import (
    AnnotationItem, AnnotationType, ContentCategory, ParseResult,
)
from utils.file_utils import load_cache, save_cache

# DWG 文件无法读取时的安装提示信息
_DWG_INSTALL_HINT = (
    "DWG 格式文件无法直接解析。请执行以下任一操作后重试：\n"
    "  方式1：安装 ODA File Converter（免费工具），下载地址：\n"
    "         https://www.opendesign.com/guestfiles/oda_file_converter\n"
    "         安装后默认路径：C:\\Program Files\\ODA\\ODAFileConverter\\\n"
    "  方式2：在 CAD 软件中将 DWG 文件另存为 DXF 格式（文件 → 另存为 → .dxf）"
)

# ODA File Converter 可能的安装目录（优先级从高到低）
_ODA_SEARCH_PATTERNS = [
    r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe",
    r"C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe",
    r"C:\Program Files (x86)\ODA\ODAFileConverter\ODAFileConverter.exe",
    r"C:\Program Files (x86)\ODA\ODAFileConverter*\ODAFileConverter.exe",
]


def _find_odafc_path() -> Optional[str]:
    """自动搜索 ODA File Converter 的安装路径

    ODA 新版安装程序会将文件安装到带版本号的目录（如 ODAFileConverter 27.1.0），
    而 ezdxf 默认查找不带版本号的路径。本函数通过 glob 搜索来适配两种情况。

    Returns:
        str | None: 找到的可执行文件完整路径，未找到返回 None
    """
    for pattern in _ODA_SEARCH_PATTERNS:
        matches = glob.glob(pattern)
        if matches:
            # 返回第一个匹配（优先精确匹配）
            return matches[0]
    return None


def _configure_odafc_path() -> bool:
    """配置 ezdxf odafc addon 的可执行文件路径

    如果 ODA File Converter 已安装但不在 ezdxf 默认路径，自动设置正确路径。

    Returns:
        bool: True 表示 odafc 可用
    """
    from ezdxf.addons import odafc

    # 先检查默认路径是否可用
    if odafc.is_installed():
        return True

    # 搜索实际安装路径
    actual_path = _find_odafc_path()
    if actual_path:
        ezdxf.options.set("odafc-addon", "win_exec_path", f'"{actual_path}"')
        return odafc.is_installed()

    return False


class DWGParser:
    """DWG/DXF 标注提取解析器

    负责从 DWG/DXF 文件中提取尺寸标注（线性、对齐、角度、直径、半径、坐标等）、
    单行文字（TEXT）和多行文字（MTEXT），统一封装为 AnnotationItem 列表。
    """

    # dimtype 值到 AnnotationType 的映射表
    DIMTYPE_MAP: dict[int, AnnotationType] = {
        0: AnnotationType.DIM_LINEAR,     # 线性标注
        1: AnnotationType.DIM_ALIGNED,    # 对齐标注
        2: AnnotationType.DIM_ANGULAR,    # 角度标注
        3: AnnotationType.DIM_DIAMETER,   # 直径标注
        4: AnnotationType.DIM_RADIUS,     # 半径标注
        5: AnnotationType.DIM_ANGULAR,    # 3点角度标注
        6: AnnotationType.DIM_ORDINATE,   # 坐标标注
    }

    # MTEXT 格式控制符的正则表达式，编译一次重复使用
    _MTEXT_FORMAT_PATTERN = re.compile(
        r"\\[A-Za-z][^;]*;|"   # \A1; \H2.5; 等格式指令
        r"\\P|"                 # \P 换行
        r"\\O|"                 # \O 上划线开始
        r"\\o|"                 # \o 上划线结束
        r"\\L|"                 # \L 下划线开始
        r"\\l|"                 # \l 下划线结束
        r"\\[~_]|"              # \~ 不间断空格 \_ 下划线转义
        r"\\W[^;]*;|"           # \W...; 宽度因子
        r"\\Q[^;]*;|"           # \Q...; 倾斜角
        r"\\T[^;]*;|"           # \T...; 字符间距
        r"\\f[^;]*;|"           # \f...; 字体
        r"\\S[^;]*;|"           # \S...; 堆叠
        r"\\C\d{1,3};|"         # \C2; 颜色索引
        r"\\H[^;]*;|"           # \H...; 字高
        r"\\p[^;]*;|"           # \p...; 段落
        r"\{|\}"                # 大括号
    )

    # ---- 智能内容分类正则 ----
    # 纯数字或数字+单位（如 "150", "3.5mm", "±0.00" 归到 DIMENSION）
    _RE_NUMERIC = re.compile(r"^[±+\-]?\d+\.?\d*\s*[a-zA-Z%°‰]*$")
    # 标高特征
    _RE_ELEVATION = re.compile(r"%%p|±|H\s*=", re.IGNORECASE)
    # 管径特征
    _RE_PIPE_DIAMETER = re.compile(r"(?:DN|dn|De|de|Φ|φ)\s*\d+")
    # 坡度特征
    _RE_SLOPE = re.compile(r"i\s*=|坡度|‰")
    # 角度特征
    _RE_ANGLE = re.compile(r"\d+\.?\d*\s*°|度")
    # 坐标特征
    _RE_COORDINATE = re.compile(r"^[XY]\s*=", re.IGNORECASE)
    # 含中英文字符（一般注释）
    _RE_GENERAL_NOTE = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z]{2,}")

    def __init__(self) -> None:
        self._index_counter: int = 0

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def parse_file(self, file_path: str) -> ParseResult:
        """解析单个 DWG/DXF 文件，提取所有标注实体

        同时从模型空间（ModelSpace）和图纸空间（PaperSpace）提取实体，
        并通过 item.paper_space 标志区分来源。

        Args:
            file_path: DWG/DXF 文件的绝对路径或相对路径

        Returns:
            ParseResult: 包含提取到的标注列表及统计信息，
                         如发生异常则 error 字段非空
        """
        result = ParseResult(file_path=file_path)
        self._index_counter = 0

        try:
            ext = Path(file_path).suffix.lower()

            if ext == ".dwg":
                doc = self._load_dwg(file_path, result)
                if doc is None:
                    # _load_dwg 已设置 result.error
                    return result
            else:
                doc = ezdxf.readfile(file_path)

            # 从模型空间提取
            msp = doc.modelspace()
            self._extract_all_spaces(msp, result, paper_space=False)

            # 从图纸空间提取
            for layout in doc.layouts:
                if layout.name in ("Model", "model"):
                    continue
                try:
                    psp = layout
                    self._extract_all_spaces(psp, result, paper_space=True)
                except Exception:  # pylint: disable=broad-except
                    continue

            # 智能内容分类
            for item in result.items:
                item.category = self._classify_content(item)

            # 统计计数
            result.dimension_count = sum(
                1 for item in result.items
                if item.annotation_type
                not in (AnnotationType.TEXT, AnnotationType.MTEXT,
                        AnnotationType.LEADER, AnnotationType.MULTILEADER,
                        AnnotationType.TABLE, AnnotationType.ATTDEF,
                        AnnotationType.ATTRIB)
            )
            result.text_count = sum(
                1 for item in result.items
                if item.annotation_type in (AnnotationType.TEXT, AnnotationType.MTEXT)
            )
            result.leader_count = sum(
                1 for item in result.items
                if item.annotation_type in (AnnotationType.LEADER, AnnotationType.MULTILEADER)
            )
            result.table_count = sum(
                1 for item in result.items
                if item.annotation_type == AnnotationType.TABLE
            )
            result.model_space_count = sum(
                1 for item in result.items if not item.paper_space
            )
            result.paper_space_count = sum(
                1 for item in result.items if item.paper_space
            )
            result.total_count = len(result.items)

        except ezdxf.DXFStructureError as exc:
            result.error = f"DXF 结构错误: {exc}"
        except ezdxf.DXFVersionError as exc:
            result.error = f"不支持的 DXF 版本: {exc}"
        except IOError as exc:
            result.error = f"文件读取失败: {exc}"
        except Exception as exc:  # pylint: disable=broad-except
            result.error = f"解析异常: {exc}"

        return result

    def _extract_all_spaces(self, space, result: ParseResult,
                            paper_space: bool = False) -> None:
        """从指定空间提取所有标注实体

        Args:
            space: ezdxf 空间对象（modelspace 或 paperspace layout）
            result: 用于收集 AnnotationItem 的 ParseResult 实例
            paper_space: 是否来自图纸空间
        """
        self._extract_dimensions(space, result, paper_space=paper_space)
        self._extract_text(space, result, paper_space=paper_space)
        self._extract_mtext(space, result, paper_space=paper_space)
        self._extract_leaders(space, result, paper_space=paper_space)
        self._extract_multileaders(space, result, paper_space=paper_space)
        self._extract_tables(space, result, paper_space=paper_space)
        self._extract_attributes(space, result, paper_space=paper_space)
        self._extract_tolerances(space, result, paper_space=paper_space)
        self._extract_block_annotations(space, result, paper_space=paper_space)

    def parse_batch(
        self,
        file_paths: list[str],
        progress_callback: Optional[Callable] = None,
        use_cache: bool = True,
    ) -> list[ParseResult]:
        """批量解析多个文件

        第一阶段串行加载缓存（快速），第二阶段对未缓存文件使用线程池并行解析，
        每个线程使用独立的 DWGParser 实例以避免 self._index_counter 共享状态冲突。

        Args:
            file_paths: 要解析的文件路径列表
            progress_callback: 进度回调，签名为 callback(current, total, file_path)
            use_cache: 是否使用缓存

        Returns:
            ParseResult 列表，顺序与输入的 file_paths 对应
        """
        total = len(file_paths)
        results: list[Optional[ParseResult]] = [None] * total

        # 第一阶段：串行加载缓存（快速）
        uncached_indices: list[int] = []
        for i, file_path in enumerate(file_paths):
            if use_cache:
                cached = self._try_load_cache(file_path)
                if cached is not None:
                    results[i] = cached
                    if progress_callback:
                        progress_callback(i + 1, total, file_path)
                    continue
            uncached_indices.append(i)

        if not uncached_indices:
            return [r for r in results if r is not None]

        # 第二阶段：并行解析未缓存文件
        completed = total - len(uncached_indices)

        def _parse_one(idx: int, fpath: str) -> tuple[int, ParseResult]:
            """每个线程使用独立的 DWGParser 实例，避免共享状态冲突"""
            parser = DWGParser()
            return (idx, parser.parse_file(fpath))

        max_workers = min(4, len(uncached_indices))

        if max_workers <= 1 or len(uncached_indices) <= 2:
            # 少量文件时串行处理，避免线程开销
            for i in uncached_indices:
                idx, result = _parse_one(i, file_paths[i])
                results[idx] = result
                completed += 1
                if use_cache and result.error is None:
                    self._try_save_cache(file_paths[idx], result)
                if progress_callback:
                    progress_callback(completed, total, file_paths[idx])
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(_parse_one, i, file_paths[i]): i
                    for i in uncached_indices
                }
                for future in as_completed(futures):
                    idx, result = future.result()
                    results[idx] = result
                    completed += 1
                    if use_cache and result.error is None:
                        self._try_save_cache(file_paths[idx], result)
                    if progress_callback:
                        progress_callback(completed, total, file_paths[idx])

        return [r for r in results if r is not None]

    # ------------------------------------------------------------------
    # 缓存辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _try_load_cache(file_path: str) -> Optional[ParseResult]:
        """尝试从缓存加载解析结果

        Args:
            file_path: 原始文件路径

        Returns:
            ParseResult | None: 缓存命中时返回反序列化的结果，否则返回 None
        """
        try:
            data = load_cache(file_path)
            if data is None:
                return None
            return _deserialize_parse_result(data, file_path)
        except Exception:  # pylint: disable=broad-except
            return None

    @staticmethod
    def _try_save_cache(file_path: str, result: ParseResult) -> None:
        """尝试将解析结果保存到缓存

        Args:
            file_path: 原始文件路径
            result: 解析结果
        """
        try:
            data = _serialize_parse_result(result)
            save_cache(file_path, data)
        except Exception:  # pylint: disable=broad-except
            pass

    # ------------------------------------------------------------------
    # DWG 文件加载策略
    # ------------------------------------------------------------------

    @staticmethod
    def _load_dwg(file_path: str, result: ParseResult):
        """加载 DWG 文件（多层回退策略）

        策略优先级：
        1. 使用 ezdxf odafc addon（需要 ODA File Converter 已安装）
        2. 使用 ezdxf recover 模式（部分低版本 DWG 可能支持）
        3. 均失败时设置错误信息并返回 None

        Args:
            file_path: DWG 文件路径
            result: ParseResult 实例，用于设置错误信息

        Returns:
            ezdxf.document.Drawing | None: 成功返回文档对象，失败返回 None
        """
        # ---- 第一层：odafc addon（推荐方式） ----
        try:
            if _configure_odafc_path():
                from ezdxf.addons import odafc
                doc = odafc.readfile(file_path)
                return doc
        except Exception:  # pylint: disable=broad-except
            pass  # odafc 安装但转换失败，继续尝试下一层

        # ---- 第二层：ezdxf recover 模式 ----
        try:
            from ezdxf import recover
            doc, _auditor = recover.readfile(file_path)
            return doc
        except Exception:  # pylint: disable=broad-except
            pass

        # ---- 全部失败 ----
        result.error = _DWG_INSTALL_HINT
        return None

    @staticmethod
    def check_dwg_support() -> dict:
        """检查 DWG 文件读取支持状态

        Returns:
            dict: 包含 odafc_installed (bool) 和 status (str) 的字典
        """
        installed = _configure_odafc_path()

        if installed:
            return {"odafc_installed": True, "status": "已安装 ODA File Converter，支持 DWG 文件"}
        return {
            "odafc_installed": False,
            "status": (
                "未安装 ODA File Converter，不支持直接读取 DWG 文件。\n"
                "请安装 ODA File Converter 或将 DWG 文件转为 DXF 格式。"
            ),
        }

    # ------------------------------------------------------------------
    # 尺寸标注提取
    # ------------------------------------------------------------------

    def _extract_dimensions(self, msp, result: ParseResult,
                            paper_space: bool = False) -> None:
        """从空间中提取所有尺寸标注实体

        Args:
            msp: ezdxf 空间对象（modelspace 或 paperspace layout）
            result: 用于收集 AnnotationItem 的 ParseResult 实例
            paper_space: 是否来自图纸空间
        """
        for dim in msp.query("DIMENSION"):
            if not isinstance(dim, Dimension):
                continue

            try:
                # 获取标注文本内容
                text = self._get_dimension_text(dim)
                if not text:
                    text = "(空标注)"

                # 获取标注位置坐标
                x, y = self._get_dimension_position(dim)

                # 通过 dimtype 映射获取标注类型
                # dimtype 高位是标志位(bit5=块参照, bit6=外部参照)
                # 实际类型由低4位决定，需要用掩码提取
                dimtype = dim.dxf.get("dimtype", 0)
                base_type = dimtype & 0x0F
                annotation_type = self.DIMTYPE_MAP.get(base_type, None)
                if annotation_type is None:
                    # 尝试识别弧长标注（Arc Length Dimension）
                    entity_type = dim.dxftype() if hasattr(dim, 'dxftype') else ''
                    if 'ARC_LENGTH' in entity_type.upper() or 'ARCLENGTH' in entity_type.upper():
                        annotation_type = AnnotationType.DIM_ARC_LENGTH
                    else:
                        annotation_type = AnnotationType.DIM_UNKNOWN

                # 读取图层和样式
                layer = dim.dxf.get("layer", "")
                style = dim.dxf.get("dimstyle", "")
                handle = dim.dxf.get("handle", "")

                # 额外属性
                height = dim.dxf.get("dimtxt", 0.0) if dim.dxf.hasattr("dimtxt") else 0.0
                rotation = dim.dxf.get("rotation", 0.0) if dim.dxf.hasattr("rotation") else 0.0
                color = dim.dxf.get("color", -1) if dim.dxf.hasattr("color") else -1
                block_name = dim.dxf.get("block", "") if dim.dxf.hasattr("block") else ""

                item = AnnotationItem(
                    index=self._index_counter,
                    content=text,
                    x=x,
                    y=y,
                    annotation_type=annotation_type,
                    layer=layer,
                    style=style,
                    source_file=result.file_path,
                    handle=handle,
                    raw_entity_type="DIMENSION",
                    height=height,
                    rotation=rotation,
                    color=color,
                    block_name=block_name,
                    paper_space=paper_space,
                )
                result.items.append(item)
                self._index_counter += 1

            except Exception:  # pylint: disable=broad-except
                # 单个实体提取失败不中断整体解析
                continue

    def _get_dimension_text(self, dim: Dimension) -> str:
        """获取标注实体的文本内容（三层回退策略）

        策略优先级：
        1. 直接读取 dim.dxf.text 字段（非空且非占位符）
        2. 从 geometry block（匿名块）中查找 TEXT/MTEXT 实体
        3. 调用 dim.get_measurement() 获取测量计算值

        Args:
            dim: ezdxf Dimension 实体

        Returns:
            str: 标注文本内容，全部失败时返回占位字符串
        """
        # ---- 第一层：直接读取 text 属性 ----
        text = dim.dxf.get("text", "")
        if text and text.strip() and text not in ("<>", " ", "{}"):
            return text.strip()

        # ---- 第二层：从 geometry block 中获取文本 ----
        block_text = self._get_text_from_geometry_block(dim)
        if block_text:
            return block_text

        # ---- 第三层：尝试获取测量值 ----
        try:
            measurement = dim.get_measurement()
            if measurement is not None:
                return str(round(measurement, 4))
        except Exception:  # pylint: disable=broad-except
            pass

        return "(无法获取标注文本)"

    @staticmethod
    def _get_text_from_geometry_block(dim: Dimension) -> str:
        """从标注实体的匿名块中提取文字内容

        某些标注实体的文本存储在关联的匿名块（geometry block）中，
        本方法遍历块内的 TEXT 和 MTEXT 实体，拼接其文本内容。

        Args:
            dim: ezdxf Dimension 实体

        Returns:
            str: 拼接后的文本内容，如未找到返回空字符串
        """
        try:
            virtual_block = dim.virtual_entities()
            if virtual_block is None:
                return ""

            texts: list[str] = []
            for entity in virtual_block:
                dxftype = entity.dxftype()
                if dxftype == "TEXT":
                    content = entity.dxf.get("text", "")
                    if content:
                        texts.append(content)
                elif dxftype == "MTEXT":
                    content = entity.text
                    if content:
                        texts.append(_clean_mtext_content(content))

            return " ".join(texts).strip() if texts else ""

        except Exception:  # pylint: disable=broad-except
            return ""

    def _get_dimension_position(self, dim: Dimension) -> tuple[float, float]:
        """获取标注实体的位置坐标（带回退策略）

        优先级：
        1. insert 点（标注文字的插入点）
        2. defpoint（标注定义点）
        3. geometry block 中 TEXT/MTEXT 的 insert 点

        Args:
            dim: ezdxf Dimension 实体

        Returns:
            tuple[float, float]: (x, y) 坐标
        """
        # 优先使用 insert 点
        if dim.dxf.hasattr("insert"):
            insert = dim.dxf.insert
            return (insert.x, insert.y)

        # 回退到 defpoint
        if dim.dxf.hasattr("defpoint"):
            defpoint = dim.dxf.defpoint
            return (defpoint.x, defpoint.y)

        # 从 geometry block 中的 TEXT/MTEXT 获取位置
        try:
            virtual_block = dim.virtual_entities()
            if virtual_block is not None:
                for entity in virtual_block:
                    dxftype = entity.dxftype()
                    if dxftype in ("TEXT", "MTEXT") and entity.dxf.hasattr("insert"):
                        pt = entity.dxf.insert
                        return (pt.x, pt.y)
        except Exception:  # pylint: disable=broad-except
            pass

        return (0.0, 0.0)

    # ------------------------------------------------------------------
    # 单行文字提取
    # ------------------------------------------------------------------

    def _extract_text(self, msp, result: ParseResult,
                      paper_space: bool = False) -> None:
        """从空间中提取所有单行文字（TEXT）实体

        Args:
            msp: ezdxf 空间对象（modelspace 或 paperspace layout）
            result: 用于收集 AnnotationItem 的 ParseResult 实例
            paper_space: 是否来自图纸空间
        """
        for text_entity in msp.query("TEXT"):
            if not isinstance(text_entity, Text):
                continue

            try:
                content = text_entity.dxf.get("text", "")
                if not content or not content.strip():
                    continue

                insert = text_entity.dxf.get("insert", None)
                if insert is not None:
                    x, y = insert.x, insert.y
                else:
                    x, y = 0.0, 0.0

                layer = text_entity.dxf.get("layer", "")
                style = text_entity.dxf.get("style", "")
                handle = text_entity.dxf.get("handle", "")

                # 额外属性
                height = text_entity.dxf.get("height", 0.0) if text_entity.dxf.hasattr("height") else 0.0
                rotation = text_entity.dxf.get("rotation", 0.0) if text_entity.dxf.hasattr("rotation") else 0.0
                color = text_entity.dxf.get("color", -1) if text_entity.dxf.hasattr("color") else -1

                item = AnnotationItem(
                    index=self._index_counter,
                    content=content.strip(),
                    x=x,
                    y=y,
                    annotation_type=AnnotationType.TEXT,
                    layer=layer,
                    style=style,
                    source_file=result.file_path,
                    handle=handle,
                    raw_entity_type="TEXT",
                    height=height,
                    rotation=rotation,
                    color=color,
                    paper_space=paper_space,
                )
                result.items.append(item)
                self._index_counter += 1

            except Exception:  # pylint: disable=broad-except
                continue

    # ------------------------------------------------------------------
    # 多行文字提取
    # ------------------------------------------------------------------

    def _extract_mtext(self, msp, result: ParseResult,
                       paper_space: bool = False) -> None:
        """从空间中提取所有多行文字（MTEXT）实体

        Args:
            msp: ezdxf 空间对象（modelspace 或 paperspace layout）
            result: 用于收集 AnnotationItem 的 ParseResult 实例
            paper_space: 是否来自图纸空间
        """
        for mtext_entity in msp.query("MTEXT"):
            if not isinstance(mtext_entity, MText):
                continue

            try:
                raw_content = mtext_entity.text
                if not raw_content:
                    continue

                # 清理 MTEXT 格式控制符
                content = _clean_mtext_content(raw_content)
                if not content.strip():
                    continue

                insert = mtext_entity.dxf.get("insert", None)
                if insert is not None:
                    x, y = insert.x, insert.y
                else:
                    x, y = 0.0, 0.0

                layer = mtext_entity.dxf.get("layer", "")
                style = mtext_entity.dxf.get("style", "")
                handle = mtext_entity.dxf.get("handle", "")

                # 额外属性
                height = mtext_entity.dxf.get("char_height", 0.0) if mtext_entity.dxf.hasattr("char_height") else 0.0
                rotation = mtext_entity.dxf.get("rotation", 0.0) if mtext_entity.dxf.hasattr("rotation") else 0.0
                color = mtext_entity.dxf.get("color", -1) if mtext_entity.dxf.hasattr("color") else -1

                item = AnnotationItem(
                    index=self._index_counter,
                    content=content.strip(),
                    x=x,
                    y=y,
                    annotation_type=AnnotationType.MTEXT,
                    layer=layer,
                    style=style,
                    source_file=result.file_path,
                    handle=handle,
                    raw_entity_type="MTEXT",
                    height=height,
                    rotation=rotation,
                    color=color,
                    paper_space=paper_space,
                    raw_content=raw_content,
                )
                result.items.append(item)
                self._index_counter += 1

            except Exception:  # pylint: disable=broad-except
                continue

    # ------------------------------------------------------------------
    # 引线标注提取
    # ------------------------------------------------------------------

    def _extract_leaders(self, msp, result: ParseResult,
                         paper_space: bool = False) -> None:
        """从空间中提取所有 LEADER（引线标注）实体

        LEADER 实体包含引线和一个关联的标注文字。通过 virtual_entities
        或直接属性获取关联的文字内容。

        Args:
            msp: ezdxf 空间对象
            result: 用于收集 AnnotationItem 的 ParseResult 实例
            paper_space: 是否来自图纸空间
        """
        try:
            for entity in msp.query("LEADER"):
                try:
                    content = ""
                    x, y = 0.0, 0.0

                    # 尝试从关联的注释获取文字
                    # LEADER 可能关联 MTEXT 或 TEXT
                    try:
                        virtual_entities = entity.virtual_entities()
                        for ve in virtual_entities:
                            ve_type = ve.dxftype()
                            if ve_type == "MTEXT":
                                raw = ve.text
                                if raw:
                                    content = _clean_mtext_content(raw)
                            elif ve_type == "TEXT":
                                raw = ve.dxf.get("text", "")
                                if raw:
                                    content = raw.strip()
                    except Exception:  # pylint: disable=broad-except
                        pass

                    # 如果 virtual_entities 未获取到文字，尝试直接属性
                    if not content:
                        # 某些版本的 ezdxf 可能支持 annotation 属性
                        annotation = entity.dxf.get("annotation", None)
                        if annotation is not None:
                            content = str(annotation).strip()

                    # 位置：使用引线的第一个顶点或 insert 点
                    if entity.dxf.hasattr("insert"):
                        pt = entity.dxf.insert
                        x, y = pt.x, pt.y
                    elif entity.dxf.hasattr("vertex"):
                        # 尝试从引线顶点获取位置
                        try:
                            pts = entity.vertices
                            if pts:
                                x, y = pts[0][0], pts[0][1]
                        except Exception:  # pylint: disable=broad-except
                            pass

                    if not content:
                        content = "(引线标注-无文字)"

                    layer = entity.dxf.get("layer", "")
                    style = entity.dxf.get("dimstyle", "") if entity.dxf.hasattr("dimstyle") else ""
                    handle = entity.dxf.get("handle", "")

                    # 额外属性
                    color = entity.dxf.get("color", -1) if entity.dxf.hasattr("color") else -1

                    item = AnnotationItem(
                        index=self._index_counter,
                        content=content,
                        x=x,
                        y=y,
                        annotation_type=AnnotationType.LEADER,
                        layer=layer,
                        style=style,
                        source_file=result.file_path,
                        handle=handle,
                        raw_entity_type="LEADER",
                        color=color,
                        paper_space=paper_space,
                    )
                    result.items.append(item)
                    self._index_counter += 1

                except Exception:  # pylint: disable=broad-except
                    continue
        except Exception:  # pylint: disable=broad-except
            # LEADER 查询本身可能失败（版本不兼容等）
            pass

    # ------------------------------------------------------------------
    # 多重引线提取
    # ------------------------------------------------------------------

    def _extract_multileaders(self, msp, result: ParseResult,
                              paper_space: bool = False) -> None:
        """从空间中提取所有 MULTILEADER（多重引线）实体

        MULTILEADER 是 AutoCAD 2008+ 引入的实体类型。
        ezdxf 对 MULTILEADER 的支持有限，需要使用 try-except 安全处理。

        Args:
            msp: ezdxf 空间对象
            result: 用于收集 AnnotationItem 的 ParseResult 实例
            paper_space: 是否来自图纸空间
        """
        try:
            for entity in msp.query("MULTILEADER"):
                try:
                    content = ""
                    x, y = 0.0, 0.0

                    # MULTILEADER 的文字可能在 context.mtext 或 context.block
                    # ezdxf 不同版本 API 差异较大，使用安全访问
                    try:
                        # 尝试通过 mtext 属性获取文字
                        if hasattr(entity, "mtext"):
                            mtext_obj = entity.mtext
                            if mtext_obj is not None and hasattr(mtext_obj, "content"):
                                content = mtext_obj.content
                                if content:
                                    content = _clean_mtext_content(content)
                    except Exception:  # pylint: disable=broad-except
                        pass

                    # 尝试通过 context 获取
                    if not content:
                        try:
                            if hasattr(entity, "context"):
                                ctx = entity.context
                                if ctx is not None:
                                    if hasattr(ctx, "mtext"):
                                        mtext_data = ctx.mtext
                                        if mtext_data is not None:
                                            raw = getattr(mtext_data, "content", "")
                                            if raw:
                                                content = _clean_mtext_content(raw)
                        except Exception:  # pylint: disable=broad-except
                            pass

                    # 尝试从 dxf 属性直接读取
                    if not content:
                        content = entity.dxf.get("text_content", "")
                        if content:
                            content = _clean_mtext_content(content)

                    # 获取位置
                    if entity.dxf.hasattr("insert"):
                        pt = entity.dxf.insert
                        x, y = pt.x, pt.y
                    elif entity.dxf.hasattr("leader_start_point"):
                        pt = entity.dxf.leader_start_point
                        x, y = pt.x, pt.y

                    if not content:
                        content = "(多重引线-无文字)"

                    layer = entity.dxf.get("layer", "")
                    handle = entity.dxf.get("handle", "")
                    color = entity.dxf.get("color", -1) if entity.dxf.hasattr("color") else -1

                    # 额外属性
                    height = 0.0
                    try:
                        if hasattr(entity, "context") and entity.context is not None:
                            if hasattr(entity.context, "mtext") and entity.context.mtext is not None:
                                height = getattr(entity.context.mtext, "height", 0.0)
                    except Exception:  # pylint: disable=broad-except
                        pass

                    item = AnnotationItem(
                        index=self._index_counter,
                        content=content,
                        x=x,
                        y=y,
                        annotation_type=AnnotationType.MULTILEADER,
                        layer=layer,
                        source_file=result.file_path,
                        handle=handle,
                        raw_entity_type="MULTILEADER",
                        height=height,
                        color=color,
                        paper_space=paper_space,
                    )
                    result.items.append(item)
                    self._index_counter += 1

                except Exception:  # pylint: disable=broad-except
                    continue
        except Exception:  # pylint: disable=broad-except
            # MULTILEADER 查询本身可能失败（版本不支持等）
            pass

    # ------------------------------------------------------------------
    # 表格提取
    # ------------------------------------------------------------------

    def _extract_tables(self, msp, result: ParseResult,
                        paper_space: bool = False) -> None:
        """从空间中提取所有 TABLE（表格）实体中的文字

        遍历表格的每一行每一列，提取单元格中的文字内容。
        每个非空单元格生成一个独立的 AnnotationItem。

        Args:
            msp: ezdxf 空间对象
            result: 用于收集 AnnotationItem 的 ParseResult 实例
            paper_space: 是否来自图纸空间
        """
        try:
            for entity in msp.query("TABLE"):
                try:
                    layer = entity.dxf.get("layer", "")
                    handle = entity.dxf.get("handle", "")
                    color = entity.dxf.get("color", -1) if entity.dxf.hasattr("color") else -1

                    # 获取表格的插入点作为基准位置
                    base_x, base_y = 0.0, 0.0
                    if entity.dxf.hasattr("insert"):
                        pt = entity.dxf.insert
                        base_x, base_y = pt.x, pt.y

                    # 遍历表格的行和列
                    has_content = False
                    try:
                        # ezdxf 的 TABLE 实体支持 rows 属性
                        if hasattr(entity, "rows"):
                            for row_idx, row in enumerate(entity.rows):
                                if not hasattr(row, "cells"):
                                    continue
                                for col_idx, cell in enumerate(row.cells):
                                    cell_text = self._get_table_cell_text(cell)
                                    if not cell_text or not cell_text.strip():
                                        continue

                                    has_content = True

                                    # 计算单元格位置（近似）
                                    cell_x, cell_y = self._get_cell_position(
                                        entity, row_idx, col_idx, base_x, base_y
                                    )

                                    item = AnnotationItem(
                                        index=self._index_counter,
                                        content=cell_text.strip(),
                                        x=cell_x,
                                        y=cell_y,
                                        annotation_type=AnnotationType.TABLE,
                                        layer=layer,
                                        source_file=result.file_path,
                                        handle=f"{handle}_R{row_idx}C{col_idx}",
                                        raw_entity_type="TABLE",
                                        color=color,
                                        paper_space=paper_space,
                                    )
                                    result.items.append(item)
                                    self._index_counter += 1

                        # 如果 rows 属性不可用，尝试 virtual_entities
                        if not has_content:
                            self._extract_table_from_virtual(
                                entity, result, layer, handle,
                                base_x, base_y, paper_space,
                            )

                    except Exception:  # pylint: disable=broad-except
                        # 表格遍历可能因版本差异失败，尝试 virtual_entities
                        self._extract_table_from_virtual(
                            entity, result, layer, handle,
                            base_x, base_y, paper_space,
                        )

                except Exception:  # pylint: disable=broad-except
                    continue
        except Exception:  # pylint: disable=broad-except
            # TABLE 查询本身可能失败
            pass

    @staticmethod
    def _get_table_cell_text(cell) -> str:
        """从表格单元格中提取文字内容

        Args:
            cell: ezdxf 表格单元格对象

        Returns:
            str: 单元格文字内容
        """
        try:
            # 尝试 content 属性
            if hasattr(cell, "content"):
                content = cell.content
                if isinstance(content, str):
                    return content.strip()
                # content 可能是列表（多内容单元格）
                if isinstance(content, (list, tuple)):
                    texts = []
                    for item in content:
                        text = getattr(item, "text", "") or str(item)
                        if text.strip():
                            texts.append(text.strip())
                    return " ".join(texts)

            # 尝试 text 属性
            if hasattr(cell, "text"):
                text = cell.text
                if isinstance(text, str):
                    return text.strip()

            # 尝试 get_content 方法
            if hasattr(cell, "get_content"):
                contents = cell.get_content()
                if contents:
                    texts = []
                    for c in contents:
                        t = getattr(c, "text", "") or str(c)
                        if t.strip():
                            texts.append(t.strip())
                    return " ".join(texts)

        except Exception:  # pylint: disable=broad-except
            pass

        return ""

    @staticmethod
    def _get_cell_position(entity, row_idx: int, col_idx: int,
                           base_x: float, base_y: float) -> tuple[float, float]:
        """计算表格单元格的近似位置

        基于表格插入点和行列索引计算单元格的近似坐标。
        如果表格有实际的列宽和行高信息，则使用精确值。

        Args:
            entity: TABLE 实体
            row_idx: 行索引
            col_idx: 列索引
            base_x: 表格插入点 X
            base_y: 表格插入点 Y

        Returns:
            tuple[float, float]: 单元格近似 (x, y) 坐标
        """
        try:
            # 尝试获取列宽和行高
            col_width = 10.0  # 默认列宽
            row_height = 5.0  # 默认行高

            if hasattr(entity, "columns"):
                columns = entity.columns
                if hasattr(columns, "width"):
                    col_width = columns.width

            if hasattr(entity, "rows"):
                rows = entity.rows
                if hasattr(rows, "height"):
                    row_height = rows.height

            # 从插入点偏移计算
            cell_x = base_x + col_idx * col_width
            cell_y = base_y - row_idx * row_height
            return (cell_x, cell_y)

        except Exception:  # pylint: disable=broad-except
            return (base_x, base_y)

    def _extract_table_from_virtual(self, entity, result: ParseResult,
                                    layer: str, handle: str,
                                    base_x: float, base_y: float,
                                    paper_space: bool) -> None:
        """从 TABLE 实体的 virtual_entities 中提取文字

        当无法直接遍历 rows/cells 时的回退策略。

        Args:
            entity: TABLE 实体
            result: ParseResult 实例
            layer: 图层名
            handle: 实体句柄
            base_x: 基准 X 坐标
            base_y: 基准 Y 坐标
            paper_space: 是否来自图纸空间
        """
        try:
            virtual_entities = entity.virtual_entities()
            for ve in virtual_entities:
                ve_type = ve.dxftype()
                content = ""
                vx, vy = base_x, base_y

                if ve_type == "MTEXT":
                    raw = ve.text
                    if raw:
                        content = _clean_mtext_content(raw)
                    if ve.dxf.hasattr("insert"):
                        pt = ve.dxf.insert
                        vx, vy = pt.x, pt.y
                elif ve_type == "TEXT":
                    content = ve.dxf.get("text", "")
                    if ve.dxf.hasattr("insert"):
                        pt = ve.dxf.insert
                        vx, vy = pt.x, pt.y

                if content and content.strip():
                    item = AnnotationItem(
                        index=self._index_counter,
                        content=content.strip(),
                        x=vx,
                        y=vy,
                        annotation_type=AnnotationType.TABLE,
                        layer=layer,
                        source_file=result.file_path,
                        handle=handle,
                        raw_entity_type="TABLE",
                        paper_space=paper_space,
                    )
                    result.items.append(item)
                    self._index_counter += 1
        except Exception:  # pylint: disable=broad-except
            pass

    # ------------------------------------------------------------------
    # 属性定义/值提取
    # ------------------------------------------------------------------

    def _extract_attributes(self, msp, result: ParseResult,
                            paper_space: bool = False) -> None:
        """从空间中提取所有 ATTDEF（属性定义）和 ATTRIB（属性值）实体

        ATTDEF 是块定义中的属性定义，ATTRIB 是块插入后的属性值。
        两者通常出现在 BLOCK 中，但某些情况下也可能出现在模型空间。

        Args:
            msp: ezdxf 空间对象
            result: 用于收集 AnnotationItem 的 ParseResult 实例
            paper_space: 是否来自图纸空间
        """
        # 提取 ATTDEF
        try:
            for entity in msp.query("ATTDEF"):
                try:
                    content = entity.dxf.get("text", "")
                    if not content or not content.strip():
                        continue

                    insert = entity.dxf.get("insert", None)
                    if insert is not None:
                        x, y = insert.x, insert.y
                    else:
                        x, y = 0.0, 0.0

                    layer = entity.dxf.get("layer", "")
                    handle = entity.dxf.get("handle", "")
                    tag = entity.dxf.get("tag", "")

                    # 额外属性
                    height = entity.dxf.get("height", 0.0) if entity.dxf.hasattr("height") else 0.0
                    rotation = entity.dxf.get("rotation", 0.0) if entity.dxf.hasattr("rotation") else 0.0
                    color = entity.dxf.get("color", -1) if entity.dxf.hasattr("color") else -1
                    prompt = entity.dxf.get("prompt", "") if entity.dxf.hasattr("prompt") else ""

                    # 如果有 tag 和 prompt，拼接到内容中以便完整展示
                    display_content = content.strip()
                    if tag and tag.strip():
                        display_content = f"[{tag.strip()}] {display_content}"
                    if prompt and prompt.strip():
                        display_content = f"{display_content} (提示: {prompt.strip()})"

                    item = AnnotationItem(
                        index=self._index_counter,
                        content=display_content,
                        x=x,
                        y=y,
                        annotation_type=AnnotationType.ATTDEF,
                        layer=layer,
                        source_file=result.file_path,
                        handle=handle,
                        raw_entity_type="ATTDEF",
                        height=height,
                        rotation=rotation,
                        color=color,
                        paper_space=paper_space,
                    )
                    result.items.append(item)
                    self._index_counter += 1

                except Exception:  # pylint: disable=broad-except
                    continue
        except Exception:  # pylint: disable=broad-except
            pass

        # 提取 ATTRIB
        try:
            for entity in msp.query("ATTRIB"):
                try:
                    content = entity.dxf.get("text", "")
                    if not content or not content.strip():
                        continue

                    insert = entity.dxf.get("insert", None)
                    if insert is not None:
                        x, y = insert.x, insert.y
                    else:
                        x, y = 0.0, 0.0

                    layer = entity.dxf.get("layer", "")
                    handle = entity.dxf.get("handle", "")
                    tag = entity.dxf.get("tag", "")

                    # 额外属性
                    height = entity.dxf.get("height", 0.0) if entity.dxf.hasattr("height") else 0.0
                    rotation = entity.dxf.get("rotation", 0.0) if entity.dxf.hasattr("rotation") else 0.0
                    color = entity.dxf.get("color", -1) if entity.dxf.hasattr("color") else -1

                    # 拼接 tag 信息
                    display_content = content.strip()
                    if tag and tag.strip():
                        display_content = f"[{tag.strip()}] {display_content}"

                    item = AnnotationItem(
                        index=self._index_counter,
                        content=display_content,
                        x=x,
                        y=y,
                        annotation_type=AnnotationType.ATTRIB,
                        layer=layer,
                        source_file=result.file_path,
                        handle=handle,
                        raw_entity_type="ATTRIB",
                        height=height,
                        rotation=rotation,
                        color=color,
                        paper_space=paper_space,
                    )
                    result.items.append(item)
                    self._index_counter += 1

                except Exception:  # pylint: disable=broad-except
                    continue
        except Exception:  # pylint: disable=broad-except
            pass

    # ------------------------------------------------------------------
    # 公差标注提取
    # ------------------------------------------------------------------

    def _extract_tolerances(self, msp, result: ParseResult,
                           paper_space: bool = False) -> None:
        """从空间中提取所有 TOLERANCE（公差标注）实体

        TOLERANCE 实体包含形位公差信息，如对称度、同轴度等。
        文本内容可能通过 entity.text 或 entity.dxf.text 获取。

        Args:
            msp: ezdxf 空间对象（modelspace 或 paperspace layout）
            result: 用于收集 AnnotationItem 的 ParseResult 实例
            paper_space: 是否来自图纸空间
        """
        try:
            for entity in msp.query("TOLERANCE"):
                try:
                    content = ""
                    # 尝试获取公差文本
                    if hasattr(entity, 'text') and entity.text:
                        content = str(entity.text)
                    elif hasattr(entity, 'dxf') and entity.dxf.hasattr('text'):
                        text_val = entity.dxf.get('text', '')
                        if text_val:
                            content = str(text_val)
                    if not content.strip():
                        continue

                    # 清理可能的 MTEXT 格式控制符
                    content = _clean_mtext_content(content)

                    # 获取插入点
                    insert_point = self._get_tolerance_insert_point(entity)
                    if insert_point is None:
                        continue

                    layer = entity.dxf.get("layer", "")
                    handle = entity.dxf.get("handle", "")

                    # 额外属性
                    height = entity.dxf.get("height", 0.0) if entity.dxf.hasattr("height") else 0.0
                    rotation = entity.dxf.get("rotation", 0.0) if entity.dxf.hasattr("rotation") else 0.0
                    color = entity.dxf.get("color", -1) if entity.dxf.hasattr("color") else -1

                    item = AnnotationItem(
                        index=self._index_counter,
                        content=content,
                        x=insert_point[0],
                        y=insert_point[1],
                        annotation_type=AnnotationType.TOLERANCE,
                        layer=layer,
                        style="",
                        source_file=result.file_path,
                        handle=handle,
                        raw_entity_type="TOLERANCE",
                        height=height,
                        rotation=rotation,
                        color=color,
                        paper_space=paper_space,
                        raw_content=content,
                    )
                    result.items.append(item)
                    self._index_counter += 1

                except Exception:  # pylint: disable=broad-except
                    continue
        except Exception:  # pylint: disable=broad-except
            # TOLERANCE 查询本身可能失败（版本不支持等）
            pass

    @staticmethod
    def _get_tolerance_insert_point(entity) -> Optional[tuple]:
        """获取 TOLERANCE 实体的插入点坐标

        Args:
            entity: TOLERANCE 实体

        Returns:
            tuple[float, float] | None: (x, y) 坐标，获取失败返回 None
        """
        try:
            if entity.dxf.hasattr("insert"):
                pt = entity.dxf.insert
                return (pt.x, pt.y)
        except Exception:  # pylint: disable=broad-except
            pass
        return None

    # ------------------------------------------------------------------
    # INSERT 块参照内嵌标注提取
    # ------------------------------------------------------------------

    def _extract_block_annotations(self, msp, result: ParseResult,
                                   paper_space: bool = False) -> None:
        """从 INSERT（块参照）实体中提取嵌套的文字标注

        INSERT 实体引用一个块定义，块定义内可能包含 TEXT、MTEXT 等文字实体。
        本方法通过 virtual_entities() 遍历块参照内部的虚拟实体，
        提取其中的文字内容并标记所属块名。

        Args:
            msp: ezdxf 空间对象（modelspace 或 paperspace layout）
            result: 用于收集 AnnotationItem 的 ParseResult 实例
            paper_space: 是否来自图纸空间
        """
        try:
            for entity in msp.query("INSERT"):
                try:
                    self._extract_from_insert_entity(entity, result, paper_space)
                except Exception:  # pylint: disable=broad-except
                    continue
        except Exception:  # pylint: disable=broad-except
            # INSERT 查询本身可能失败
            pass

    def _extract_from_insert_entity(self, insert_entity, result: ParseResult,
                                    paper_space: bool = False) -> None:
        """从单个 INSERT 实体中提取嵌套文字

        Args:
            insert_entity: INSERT 实体
            result: ParseResult 实例
            paper_space: 是否来自图纸空间
        """
        block_name = ""
        if hasattr(insert_entity, 'dxf') and insert_entity.dxf.hasattr('name'):
            block_name = insert_entity.dxf.get('name', '')
        elif hasattr(insert_entity, 'name'):
            block_name = insert_entity.name

        if not block_name:
            return

        try:
            if not hasattr(insert_entity, 'virtual_entities'):
                return

            for child in insert_entity.virtual_entities():
                child_type = child.dxftype() if hasattr(child, 'dxftype') else ''

                if child_type == 'TEXT':
                    self._extract_text_from_entity(
                        child, result, paper_space, block_name
                    )
                elif child_type == 'MTEXT':
                    self._extract_mtext_from_entity(
                        child, result, paper_space, block_name
                    )
        except Exception:  # pylint: disable=broad-except
            pass

    def _extract_text_from_entity(self, text_entity, result: ParseResult,
                                  paper_space: bool, block_name: str) -> None:
        """从单个 TEXT 实体中提取文字内容（供块参照内嵌提取复用）

        Args:
            text_entity: TEXT 实体
            result: ParseResult 实例
            paper_space: 是否来自图纸空间
            block_name: 所属块参照名称
        """
        try:
            content = text_entity.dxf.get("text", "")
            if not content or not content.strip():
                return

            insert = text_entity.dxf.get("insert", None)
            if insert is not None:
                x, y = insert.x, insert.y
            else:
                x, y = 0.0, 0.0

            layer = text_entity.dxf.get("layer", "")
            handle = text_entity.dxf.get("handle", "")
            height = text_entity.dxf.get("height", 0.0) if text_entity.dxf.hasattr("height") else 0.0
            rotation = text_entity.dxf.get("rotation", 0.0) if text_entity.dxf.hasattr("rotation") else 0.0
            color = text_entity.dxf.get("color", -1) if text_entity.dxf.hasattr("color") else -1

            item = AnnotationItem(
                index=self._index_counter,
                content=content.strip(),
                x=x,
                y=y,
                annotation_type=AnnotationType.TEXT,
                layer=layer,
                style="",
                source_file=result.file_path,
                handle=handle,
                raw_entity_type="TEXT",
                height=height,
                rotation=rotation,
                color=color,
                block_name=block_name,
                paper_space=paper_space,
            )
            result.items.append(item)
            self._index_counter += 1

        except Exception:  # pylint: disable=broad-except
            pass

    def _extract_mtext_from_entity(self, mtext_entity, result: ParseResult,
                                   paper_space: bool, block_name: str) -> None:
        """从单个 MTEXT 实体中提取文字内容（供块参照内嵌提取复用）

        Args:
            mtext_entity: MTEXT 实体
            result: ParseResult 实例
            paper_space: 是否来自图纸空间
            block_name: 所属块参照名称
        """
        try:
            raw_content = mtext_entity.text
            if not raw_content:
                return

            content = _clean_mtext_content(raw_content)
            if not content.strip():
                return

            insert = mtext_entity.dxf.get("insert", None)
            if insert is not None:
                x, y = insert.x, insert.y
            else:
                x, y = 0.0, 0.0

            layer = mtext_entity.dxf.get("layer", "")
            handle = mtext_entity.dxf.get("handle", "")
            height = mtext_entity.dxf.get("char_height", 0.0) if mtext_entity.dxf.hasattr("char_height") else 0.0
            rotation = mtext_entity.dxf.get("rotation", 0.0) if mtext_entity.dxf.hasattr("rotation") else 0.0
            color = mtext_entity.dxf.get("color", -1) if mtext_entity.dxf.hasattr("color") else -1

            item = AnnotationItem(
                index=self._index_counter,
                content=content.strip(),
                x=x,
                y=y,
                annotation_type=AnnotationType.MTEXT,
                layer=layer,
                style="",
                source_file=result.file_path,
                handle=handle,
                raw_entity_type="MTEXT",
                height=height,
                rotation=rotation,
                color=color,
                block_name=block_name,
                paper_space=paper_space,
                raw_content=raw_content,
            )
            result.items.append(item)
            self._index_counter += 1

        except Exception:  # pylint: disable=broad-except
            pass

    # ------------------------------------------------------------------
    # 智能内容分类
    # ------------------------------------------------------------------

    def _classify_content(self, item: AnnotationItem) -> ContentCategory:
        """根据标注内容自动分类

        分类优先级（从高到低）：
        1. PIPE_DIAMETER - 包含 DN/dn/De/de/Phi + 数字
        2. ELEVATION - 包含 %%p / +- 符号 或 H= 开头
        3. SLOPE - 包含 i= / 坡度 / 千分号
        4. COORDINATE - X= 或 Y= 开头
        5. ANGLE_VALUE - 包含度数符号
        6. DIMENSION - 纯数字或数字+单位
        7. GENERAL_NOTE - 包含中文或英文文字说明
        8. UNKNOWN - 无法分类

        Args:
            item: 标注项

        Returns:
            ContentCategory: 内容分类枚举值
        """
        content = item.content.strip()
        if not content:
            return ContentCategory.UNKNOWN

        # 1. 管径检测
        if self._RE_PIPE_DIAMETER.search(content):
            return ContentCategory.PIPE_DIAMETER

        # 2. 标高检测
        if self._RE_ELEVATION.search(content):
            return ContentCategory.ELEVATION

        # 3. 坡度检测
        if self._RE_SLOPE.search(content):
            return ContentCategory.SLOPE

        # 4. 坐标检测
        if self._RE_COORDINATE.search(content):
            return ContentCategory.COORDINATE

        # 5. 角度检测
        if self._RE_ANGLE.search(content):
            return ContentCategory.ANGLE_VALUE

        # 6. 纯数字/数值检测（尺寸值）
        if self._RE_NUMERIC.match(content):
            return ContentCategory.DIMENSION

        # 7. 一般注释检测
        if self._RE_GENERAL_NOTE.search(content):
            return ContentCategory.GENERAL_NOTE

        return ContentCategory.UNKNOWN

def _clean_mtext_content(text: str) -> str:
    """清除 MTEXT 格式控制符，返回纯文本内容

    支持清除的控制符包括：
    - \\P 换行 -> 实际换行符
    - \\A1; 等对齐指令
    - \\O / \\o 上划线开关
    - \\L / \\l 下划线开关
    - \\H...; 字高指令
    - \\f...; 字体指令
    - \\C...; 颜色指令
    - \\W...; \\Q...; \\T...; 宽度/倾斜/间距
    - \\S...; 堆叠
    - \\p...; 段落
    - { } 大括号

    Args:
        text: 含有 MTEXT 格式控制符的原始文本

    Returns:
        str: 清理后的纯文本
    """
    if not text:
        return ""

    # 先将 \P 替换为换行符（在正则移除之前处理）
    cleaned = text.replace("\\P", "\n")

    # 移除其余格式控制符
    cleaned = DWGParser._MTEXT_FORMAT_PATTERN.sub("", cleaned)

    # 将 \\ 连续反斜杠合并（转义反斜杠 -> 单反斜杠）
    cleaned = cleaned.replace("\\\\", "\\")

    # 去除首尾空白及多余换行
    cleaned = cleaned.strip()

    return cleaned


# ------------------------------------------------------------------
# 缓存序列化 / 反序列化辅助函数
# ------------------------------------------------------------------

def _serialize_parse_result(result: ParseResult) -> dict:
    """将 ParseResult 序列化为可 JSON 化的字典

    Args:
        result: 解析结果

    Returns:
        dict: 序列化后的字典
    """
    items = []
    for item in result.items:
        items.append({
            "index": item.index,
            "content": item.content,
            "x": item.x,
            "y": item.y,
            "annotation_type": item.annotation_type.value,
            "layer": item.layer,
            "style": item.style,
            "source_file": item.source_file,
            "handle": item.handle,
            "raw_entity_type": item.raw_entity_type,
            "x2": item.x2,
            "y2": item.y2,
            "height": item.height,
            "rotation": item.rotation,
            "color": item.color,
            "font_name": item.font_name,
            "block_name": item.block_name,
            "paper_space": item.paper_space,
            "raw_content": item.raw_content,
            "category": item.category.value,
        })

    return {
        "file_path": result.file_path,
        "items": items,
        "total_count": result.total_count,
        "dimension_count": result.dimension_count,
        "text_count": result.text_count,
        "leader_count": result.leader_count,
        "table_count": result.table_count,
        "model_space_count": result.model_space_count,
        "paper_space_count": result.paper_space_count,
    }


def _deserialize_parse_result(data: dict, file_path: str) -> ParseResult:
    """从缓存字典反序列化 ParseResult

    Args:
        data: 缓存字典（payload 部分）
        file_path: 原始文件路径

    Returns:
        ParseResult: 反序列化后的解析结果
    """
    result = ParseResult(file_path=file_path)
    result.total_count = data.get("total_count", 0)
    result.dimension_count = data.get("dimension_count", 0)
    result.text_count = data.get("text_count", 0)
    result.leader_count = data.get("leader_count", 0)
    result.table_count = data.get("table_count", 0)
    result.model_space_count = data.get("model_space_count", 0)
    result.paper_space_count = data.get("paper_space_count", 0)

    for item_data in data.get("items", []):
        # 反向查找枚举值
        annotation_type = AnnotationType.DIM_UNKNOWN
        at_value = item_data.get("annotation_type", "")
        for at in AnnotationType:
            if at.value == at_value:
                annotation_type = at
                break

        category = ContentCategory.UNKNOWN
        cat_value = item_data.get("category", "")
        for cat in ContentCategory:
            if cat.value == cat_value:
                category = cat
                break

        item = AnnotationItem(
            index=item_data.get("index", 0),
            content=item_data.get("content", ""),
            x=item_data.get("x", 0.0),
            y=item_data.get("y", 0.0),
            annotation_type=annotation_type,
            layer=item_data.get("layer", ""),
            style=item_data.get("style", ""),
            source_file=item_data.get("source_file", file_path),
            handle=item_data.get("handle", ""),
            raw_entity_type=item_data.get("raw_entity_type", ""),
            x2=item_data.get("x2", 0.0),
            y2=item_data.get("y2", 0.0),
            height=item_data.get("height", 0.0),
            rotation=item_data.get("rotation", 0.0),
            color=item_data.get("color", -1),
            font_name=item_data.get("font_name", ""),
            block_name=item_data.get("block_name", ""),
            paper_space=item_data.get("paper_space", False),
            raw_content=item_data.get("raw_content", ""),
            category=category,
        )
        result.items.append(item)

    return result
