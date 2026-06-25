"""跨平台桌面 RPA 抽象层。

本包提供 Windows 与 macOS 双平台的桌面自动化（窗口/输入/点击）与
视觉栈（截图/DPI/主题/锁屏/OCR）的统一接口，由工厂函数按
`sys.platform` 自动装配实现。

外部消费方应只导入 :func:`get_desktop_adapter` / :func:`get_ocr_adapter`，
而非直接 import `windows` / `macos` 子模块。

设计依据：`2026-06-17-wechat-rpa-adaptive-vision-ocr-evolution.md` §2.2 / §5
以及 `eager-cuddling-pond.md` 落地方案 §B.1。
"""
from __future__ import annotations

import sys
import threading
from typing import Optional

from backend.app.services.platform.base import (
    DesktopAdapter,
    OcrAdapter,
    OcrWord,
    SystemContext,
    WindowHandle,
    WindowSpec,
)

__all__ = [
    "DesktopAdapter",
    "OcrAdapter",
    "OcrWord",
    "SystemContext",
    "WindowHandle",
    "WindowSpec",
    "get_desktop_adapter",
    "get_ocr_adapter",
    "reset_adapters",
]


_desktop_lock = threading.Lock()
_ocr_lock = threading.Lock()
_desktop_singleton: Optional[DesktopAdapter] = None
_ocr_singleton: Optional[OcrAdapter] = None


def _platform_key() -> str:
    """归一化平台标识，仅区分 win32 / darwin / other。"""
    if sys.platform.startswith("win"):
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    return sys.platform


def _load_desktop() -> DesktopAdapter:
    key = _platform_key()
    if key == "win32":
        from backend.app.services.platform.windows import WindowsDesktopAdapter

        return WindowsDesktopAdapter()
    if key == "darwin":
        from backend.app.services.platform.macos import MacDesktopAdapter

        return MacDesktopAdapter()
    # Linux 与其它平台目前仅有最小骨架，足以让单测/导入不报错。
    from backend.app.services.platform.base import NullDesktopAdapter

    return NullDesktopAdapter()


def _load_ocr() -> OcrAdapter:
    key = _platform_key()
    if key == "win32":
        from backend.app.services.platform.windows import WindowsOcrAdapter

        return WindowsOcrAdapter()
    if key == "darwin":
        from backend.app.services.platform.macos import MacOcrAdapter

        return MacOcrAdapter()
    from backend.app.services.platform.base import NullOcrAdapter

    return NullOcrAdapter()


def get_desktop_adapter() -> DesktopAdapter:
    """返回当前平台的桌面适配器（进程内单例）。"""
    global _desktop_singleton
    if _desktop_singleton is None:
        with _desktop_lock:
            if _desktop_singleton is None:
                _desktop_singleton = _load_desktop()
    return _desktop_singleton


def get_ocr_adapter() -> OcrAdapter:
    """返回当前平台的 OCR/视觉环境适配器（进程内单例）。"""
    global _ocr_singleton
    if _ocr_singleton is None:
        with _ocr_lock:
            if _ocr_singleton is None:
                _ocr_singleton = _load_ocr()
    return _ocr_singleton


def reset_adapters() -> None:
    """重置单例缓存，供单元测试在不同平台之间切换时调用。"""
    global _desktop_singleton, _ocr_singleton
    with _desktop_lock:
        _desktop_singleton = None
    with _ocr_lock:
        _ocr_singleton = None
