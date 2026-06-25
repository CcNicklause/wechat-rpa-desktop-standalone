"""平台适配器抽象协议与共享数据类。

所有平台实现 (`windows.py`, `macos.py`) 都实现此模块定义的协议。
外部消费方应该通过 `platform/__init__.py` 的工厂函数获取实例，
而非直接导入此模块。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Protocol,
    Tuple,
    runtime_checkable,
)

# ---------------------------------------------------------------------------
# 共享数据类
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WindowSpec:
    """描述一个窗口查找候选条件（与 UI 自动化框架无关）。

    所有字段均为可选 —— 匹配时对非 None 字段做 AND 判定。

    Attributes:
        control_type: UI 自动化控件类型名，如 ``"WindowControl"``、
            ``"EditControl"``、``"DocumentControl"``、``"ButtonControl"`` 等。
            默认为 ``"WindowControl"``。适配器根据此字段调用对应的
            uiautomation 构造方法。
    """

    class_name: Optional[str] = None
    name: Optional[str] = None
    name_regex: Optional[str] = None
    control_type: str = "WindowControl"
    search_depth: int = 1
    max_search_seconds: float = 2.0



@dataclass(frozen=True)
class WindowHandle:
    """平台无关的窗口句柄。

    Attributes:
        native_id: Windows 上是 HWND (int)，macOS 上是 AXUIElement 的
                   hash 或 pid+window-index 组合。
        name: 窗口标题文本。
        class_name: 窗口类名 (Windows) 或 AXRole (macOS)。
        rect: 窗口边界 (left, top, right, bottom)。
        platform_data: 平台私有数据，由适配器实现自由使用。
    """

    native_id: int
    name: str = ""
    class_name: str = ""
    rect: Tuple[int, int, int, int] = (0, 0, 0, 0)
    platform_data: Any = None


@dataclass(frozen=True)
class OcrWord:
    """单条 OCR 识别结果。"""

    text: str
    x: int
    y: int
    width: int
    height: int


@dataclass
class SystemContext:
    """运行环境快照，在 `VisionLocator.find_first` 入口一次性构造。"""

    resolution: Tuple[int, int] = (0, 0)
    dpi_scale: float = 1.0
    is_dark_mode: bool = False
    language: str = "zh-CN"
    is_locked: bool = False


# ---------------------------------------------------------------------------
# 适配器协议
# ---------------------------------------------------------------------------


@runtime_checkable
class DesktopAdapter(Protocol):
    """桌面自动化适配器：窗口发现、点击、键盘输入、剪贴板。"""

    # ---- 窗口 ----

    def find_window(self, candidates: List[WindowSpec]) -> Optional[WindowHandle]:
        """按候选列表顺序查找第一个匹配的窗口，未找到返回 None。"""
        ...

    def find_child_window(
        self, parent: WindowHandle, candidates: List[WindowSpec]
    ) -> Optional[WindowHandle]:
        """在 parent 窗口内查找子控件。"""
        ...

    def list_top_level_windows(self) -> List[WindowHandle]:
        """枚举所有顶层窗口。"""
        ...

    def get_bounding_rectangle(self, handle: WindowHandle) -> Tuple[int, int, int, int]:
        """返回 (left, top, right, bottom)。"""
        ...

    # ---- 操作 ----

    def set_active(self, handle: WindowHandle) -> None:
        """激活（聚焦）窗口。"""
        ...

    def set_topmost(self, handle: WindowHandle, on: bool) -> None:
        """设置窗口置顶。"""
        ...

    def close_window(self, handle: WindowHandle) -> None:
        """关闭窗口（用于清理遗留的添加朋友/验证申请窗口）。"""
        ...

    def click(self, x: int, y: int) -> None:
        """在当前活动桌面点击指定坐标。"""
        ...

    def send_keys(
        self, text: str, per_char_delay: Tuple[float, float] = (0.05, 0.15)
    ) -> None:
        """逐字符输入文本（模拟人类打字）。"""
        ...

    def hotkey(self, *keys: str) -> None:
        """发送组合键（如 `ctrl`, `v`）。"""
        ...

    def paste_text(self, text: str) -> None:
        """将文本写入剪贴板并粘贴到当前焦点控件。"""
        ...

    def clear_field(self) -> None:
        """全选并删除当前焦点字段内容。"""
        ...


@runtime_checkable
class OcrAdapter(Protocol):
    """OCR / 视觉环境适配器：截图、DPI、主题、锁屏检测、文本识别。"""

    def screenshot(
        self, region: Tuple[int, int, int, int]
    ) -> Any:  # pragma: no cover – 返回 PIL Image，实际消费方是 matplotlib/numpy
        """截取屏幕指定区域，返回 PIL Image 对象。"""
        ...

    def get_dpi_scale(self, handle: Optional[WindowHandle] = None) -> float:
        """获取当前屏幕或指定窗口的 DPI 缩放比。"""
        ...

    def get_theme(self) -> Literal["light", "dark"]:
        """获取当前系统主题（明/暗）。"""
        ...

    def is_locked(self) -> bool:
        """检测屏幕是否被锁屏或 RDP 会话断开/最小化。"""
        ...

    def recognize(
        self, image: Any, lang_tag: str = ""
    ) -> List[OcrWord]:
        """对图像执行 OCR，返回识别词块列表。"""
        ...

    def detect_app_language(
        self, handle: Optional[WindowHandle] = None
    ) -> str:
        """探测微信客户端的运行时语言。返回 BCP-47 标签如 `zh-CN`。"""
        ...

    def enable_dpi_awareness(self) -> bool:
        """启用进程级 DPI 感知。返回是否成功。"""
        ...


# ---------------------------------------------------------------------------
# Null 实现（用于不支持平台，如 Linux，保证 import 不炸）
# ---------------------------------------------------------------------------


class NullDesktopAdapter:
    """桌面适配器空实现 —— 所有方法返回 None / False / 空列表。"""

    def find_window(self, candidates: List[WindowSpec]) -> Optional[WindowHandle]:
        return None

    def find_child_window(
        self, parent: WindowHandle, candidates: List[WindowSpec]
    ) -> Optional[WindowHandle]:
        return None

    def list_top_level_windows(self) -> List[WindowHandle]:
        return []

    def get_bounding_rectangle(self, handle: WindowHandle) -> Tuple[int, int, int, int]:
        return handle.rect

    def set_active(self, handle: WindowHandle) -> None:
        pass

    def set_topmost(self, handle: WindowHandle, on: bool) -> None:
        pass

    def close_window(self, handle: WindowHandle) -> None:
        pass

    def click(self, x: int, y: int) -> None:
        pass

    def send_keys(
        self, text: str, per_char_delay: Tuple[float, float] = (0.05, 0.15)
    ) -> None:
        pass

    def hotkey(self, *keys: str) -> None:
        pass

    def paste_text(self, text: str) -> None:
        pass

    def clear_field(self) -> None:
        pass


class NullOcrAdapter:
    """OCR 适配器空实现 —— 所有方法返回默认值。"""

    def screenshot(self, region: Tuple[int, int, int, int]) -> Any:
        return None

    def get_dpi_scale(self, handle: Optional[WindowHandle] = None) -> float:
        return 1.0

    def get_theme(self) -> Literal["light", "dark"]:
        return "light"

    def is_locked(self) -> bool:
        return False

    def recognize(self, image: Any, lang_tag: str = "") -> List[OcrWord]:
        return []

    def detect_app_language(
        self, handle: Optional[WindowHandle] = None
    ) -> str:
        return "zh-CN"

    def enable_dpi_awareness(self) -> bool:
        return False