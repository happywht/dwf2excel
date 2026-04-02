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
from pathlib import Path
from typing import Optional

import ezdxf
from ezdxf.entities import Dimension, Text, MText

from core.models import AnnotationItem, AnnotationType, ParseResult

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

    def __init__(self) -> None:
        self._index_counter: int = 0

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def parse_file(self, file_path: str) -> ParseResult:
        """解析单个 DWG/DXF 文件，提取所有标注实体

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

            msp = doc.modelspace()

            # 按顺序提取各类标注实体
            self._extract_dimensions(msp, result)
            self._extract_text(msp, result)
            self._extract_mtext(msp, result)

            # 统计计数
            result.dimension_count = sum(
                1 for item in result.items
                if item.annotation_type
                not in (AnnotationType.TEXT, AnnotationType.MTEXT)
            )
            result.text_count = sum(
                1 for item in result.items
                if item.annotation_type in (AnnotationType.TEXT, AnnotationType.MTEXT)
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

    def parse_batch(
        self,
        file_paths: list[str],
        progress_callback: Optional[callable] = None,
    ) -> list[ParseResult]:
        """批量解析多个 DWG/DXF 文件

        Args:
            file_paths: 待解析文件路径列表
            progress_callback: 进度回调函数，签名为
                               callback(current: int, total: int, file_path: str)

        Returns:
            list[ParseResult]: 每个文件对应的解析结果列表，顺序与输入一致
        """
        results: list[ParseResult] = []
        total = len(file_paths)

        for current, file_path in enumerate(file_paths, start=1):
            if progress_callback is not None:
                progress_callback(current, total, file_path)

            result = self.parse_file(file_path)
            results.append(result)

        return results

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

    def _extract_dimensions(self, msp, result: ParseResult) -> None:
        """从模型空间中提取所有尺寸标注实体

        Args:
            msp: ezdxf 模型空间对象
            result: 用于收集 AnnotationItem 的 ParseResult 实例
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
                annotation_type = self.DIMTYPE_MAP.get(
                    base_type, AnnotationType.DIM_UNKNOWN
                )

                # 读取图层和样式
                layer = dim.dxf.get("layer", "")
                style = dim.dxf.get("dimstyle", "")
                handle = dim.dxf.get("handle", "")

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

    def _extract_text(self, msp, result: ParseResult) -> None:
        """从模型空间中提取所有单行文字（TEXT）实体

        Args:
            msp: ezdxf 模型空间对象
            result: 用于收集 AnnotationItem 的 ParseResult 实例
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
                )
                result.items.append(item)
                self._index_counter += 1

            except Exception:  # pylint: disable=broad-except
                continue

    # ------------------------------------------------------------------
    # 多行文字提取
    # ------------------------------------------------------------------

    def _extract_mtext(self, msp, result: ParseResult) -> None:
        """从模型空间中提取所有多行文字（MTEXT）实体

        Args:
            msp: ezdxf 模型空间对象
            result: 用于收集 AnnotationItem 的 ParseResult 实例
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
                )
                result.items.append(item)
                self._index_counter += 1

            except Exception:  # pylint: disable=broad-except
                continue


# ------------------------------------------------------------------
# 模块级辅助函数
# ------------------------------------------------------------------

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
