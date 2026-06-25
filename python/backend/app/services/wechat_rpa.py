"""微信 RPA 自动加微流程（跨平台 v2）。

本模块编排"查找微信窗口 → 打开添加朋友 → 搜索 → 添加好友
→ 填写验证语 → 发送"的完整链路。

与 v1 相比，所有 UIAutomation / pyautogui / 剪贴板调用均通过
``backend.app.services.platform`` 适配器完成，使其在 Windows 与
macOS 上共享同一套业务逻辑。

向后兼容：
* 所有模块级函数签名不变（``auto`` 参数保留但已废弃；内部走适配器）。
* ``vision = VisionLocator()`` 模块级单例不变。
* ``execute_single_add_request`` 的 ``update`` 回调签名不变。
"""
from __future__ import annotations

import random
import sys
import threading
import time
from collections.abc import Callable, Iterable
from typing import Any, List, Optional, Tuple

from backend.app.core.errors import AppError
from backend.app.services.platform import (
    OcrWord,
    WindowHandle,
    WindowSpec,
    get_desktop_adapter,
    get_ocr_adapter,
)
from backend.app.services.vision_locator import MatchResult, VisionLocator, fuzzy_text_hit

vision = VisionLocator()

_thread_local = threading.local()

def set_cancel_token(token: threading.Event | None) -> None:
    _thread_local.cancel_token = token

def _sleep(seconds: float) -> None:
    token = getattr(_thread_local, 'cancel_token', None)
    if token is not None:
        if token.wait(timeout=seconds):
            raise AppError("SYS_RPA_TIMEOUT", "加微任务已被取消或超时强杀，中止幽灵操作")
    else:
        time.sleep(seconds)

def _check_cancel() -> None:
    token = getattr(_thread_local, 'cancel_token', None)
    if token is not None and token.is_set():
        raise AppError("SYS_RPA_TIMEOUT", "加微任务已被取消或超时强杀，中止幽灵操作")

# ---------------------------------------------------------------------------
# 业务终态：区别于系统异常（AppError）。
# 链路在读屏判定出"搜不到/已好友/被拒/风控/已发送"等正常业务结果时，
# 抛 RpaBusinessOutcome；编排层据此走 _finalize_business_outcome，
# 不计入系统失败（不进 _fail_job、不告警）。
# ---------------------------------------------------------------------------


class RpaBusinessOutcome(Exception):
    """携带业务终态码的可控中断。

    Attributes:
        code: 业务终态码（如 ``BIZ_TARGET_NOT_FOUND``）。
        message: 人类可读说明。
        terminal: 是否为"成功类"终态（如已是好友也算闭环完成）。
        circuit_break: 是否需要触发当天熔断（风控场景）。
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        circuit_break: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.circuit_break = circuit_break


# 读屏状态关键词表（多语言）。键为状态码，值为该状态下屏幕可能出现的文本片段。
# 与 vision_locator.OCR_INTENT_MAP 同构，复用其 rapidfuzz 模糊匹配能力。
SCREEN_STATE_KEYWORDS: dict[str, List[str]] = {
    "TARGET_NOT_FOUND": [
        "该用户不存在",
        "无法找到相关",
        "无法找到该用户",
        "请检查你填写的账号是否正确",
        "该账号不存在",
        "搜索结果为空",
        "用户不存在",
        "该用户不存在，请检查",
        "你搜索的账号不存在",
        "未找到相关结果",
        "没有找到",
        "查无此人",
        "User not found",
        "No results",
        "not exist",
    ],
    "ALREADY_FRIEND": [
        "发消息",
        "发送消息",
        "音视频通话",
        "Send Message",
        "Message",
    ],
    "ADD_REJECTED": [
        "不是对方好友",
        "需要先添加",
        "对方拒绝",
        "无法添加对方为好友",
        "对方已开启好友验证",
        "你不是对方好友",
        "被对方拒绝",
    ],
    "RISK_CONTROL": [
        "操作过于频繁",
        "账号存在异常",
        "操作频繁",
        "请稍后再试",
        "你的账号存在异常",
        "已被限制",
        "操作太频繁",
    ],
    "SEND_SUCCESS": [
        "已发送",
        "等待验证",
        "好友申请已发送",
        "正在等待验证",
        "Request Sent",
        "Waiting for verification",
    ],
}

# 各业务状态码 → (终态码, 人类可读说明, 是否熔断)
_BUSINESS_OUTCOME_MAP: dict[str, Tuple[str, str, bool]] = {
    "TARGET_NOT_FOUND": ("BIZ_TARGET_NOT_FOUND", "未搜索到该账号，可能号码有误或对方未注册微信", False),
    "ALREADY_FRIEND": ("BIZ_ALREADY_FRIEND", "对方已是好友，无需重复添加", False),
    "ADD_REJECTED": ("BIZ_ADD_REJECTED", "对方限制了添加方式或拒绝陌生人添加", False),
    "RISK_CONTROL": ("BIZ_RISK_CONTROL", "触发微信风控（操作频繁/账号异常），已熔断当天任务", True),
}


def _detect_screen_state(
    window,
    state_keys: Iterable[str],
    *,
    save_path: str | None = None,
    min_ratio: int = 80,
    mark: Callable[[str], None] | None = None,
) -> Optional[str]:
    """OCR 读屏，返回命中的第一个状态键。

    按 ``state_keys`` 的传入顺序逐个判定，命中即返回（顺序即优先级）。
    复用 ``vision.read_window_text`` 的截图 + OCR，再用 rapidfuzz
    做空格不敏感的模糊匹配。

    Args:
        window: 目标窗口（uiautomation 控件或 WindowHandle）。
        state_keys: 待检测的状态键子集（如 ``["TARGET_NOT_FOUND", "ALREADY_FRIEND"]``）。
        save_path: 留痕截图路径。
        min_ratio: rapidfuzz 模糊匹配阈值。
        mark: 可选的步骤回调；若提供，会把 OCR 读到的原文 dump 进日志，
            便于诊断"屏幕有提示但未命中关键字"的情况。

    Returns:
        命中的状态键；未命中返回 None。
    """
    from backend.app.services.vision_locator import fuzzy_text_hit

    words = vision.read_window_text(window, save_path=save_path)
    if mark is not None:
        ocr_dump = " | ".join(w.text for w in words) if words else "(空)"
        # 截断避免日志过长
        if len(ocr_dump) > 300:
            ocr_dump = ocr_dump[:300] + "…"
        mark(f"OCR_RAW_TEXT: {ocr_dump}")
    
    _check_cancel()
    
    if not words:
        return None

    # 把所有词块拼成一整段文本，便于跨词块匹配长句
    full_text = "".join(w.text for w in words)

    for key in state_keys:
        keywords = SCREEN_STATE_KEYWORDS.get(key)
        if not keywords:
            continue
        # 整段匹配
        if fuzzy_text_hit(full_text, keywords, min_ratio=min_ratio) is not None:
            return key
        # 单词块匹配兜底（短词如"发消息"在整段里可能被淹没）
        for w in words:
            if fuzzy_text_hit(w.text, keywords, min_ratio=min_ratio) is not None:
                return key
    return None


def _raise_if_business_outcome(state_key: Optional[str]) -> None:
    """若 state_key 命中业务终态映射，抛 RpaBusinessOutcome。"""
    if state_key and state_key in _BUSINESS_OUTCOME_MAP:
        code, message, circuit_break = _BUSINESS_OUTCOME_MAP[state_key]
        raise RpaBusinessOutcome(code, message, circuit_break=circuit_break)


# ---------------------------------------------------------------------------
# 窗口查询规格 —— 与 UI 框架无关的控件描述
# ---------------------------------------------------------------------------

WECHAT_WINDOW_SPECS: List[WindowSpec] = [
    WindowSpec(class_name="WeChatMainWndForPC", search_depth=1),
    WindowSpec(class_name="Qt51514QWindowIcon", name="微信", search_depth=1),
    WindowSpec(class_name="mmui::MainWindow", name="微信", search_depth=1),
    # 注意：不能加 `WindowSpec(name_regex=".*微信.*")` 这种无 class 约束的兜底，
    # 否则 VS Code 打开标题含"微信"的文件、Chrome 标签页等 Chromium/Electron
    # 应用会误命中（实测 _looks_like_wechat_main_window 已加 class 黑名单兜底，
    # 但 UIA 路径不走那个函数，必须在 spec 层就收紧）。
]

ADD_FRIENDS_WINDOW_SPECS: List[WindowSpec] = [
    WindowSpec(name="添加朋友", search_depth=1),
    WindowSpec(class_name="ContactManagerWindow", search_depth=1),
    WindowSpec(name_regex=".*添加朋友.*", search_depth=1),
]

VERIFY_WINDOW_SPECS: List[WindowSpec] = [
    WindowSpec(name="发送朋友验证申请", search_depth=1),
    WindowSpec(name="申请添加朋友", search_depth=1),
    WindowSpec(name_regex=".*验证.*", search_depth=1),
    WindowSpec(name_regex=".*申请.*朋友.*", search_depth=1),
    WindowSpec(name_regex=".*朋友.*", search_depth=1),
]

ADD_BUTTON_SPECS: List[WindowSpec] = [
    WindowSpec(name="添加", control_type="ButtonControl", search_depth=10),
    WindowSpec(name="+", control_type="ButtonControl", search_depth=10),
    WindowSpec(name_regex=".*添加.*", control_type="ButtonControl", search_depth=10),
]

ADD_FRIENDS_MENU_SPECS: List[WindowSpec] = [
    WindowSpec(name="添加朋友", search_depth=5),
    WindowSpec(name_regex=".*添加朋友.*", search_depth=5),
]

SEARCH_BOX_SPECS: List[WindowSpec] = [
    WindowSpec(name_regex=".*(搜索|微信号|手机号|QQ号).*", control_type="EditControl", search_depth=10),
    WindowSpec(name="搜索", control_type="EditControl", search_depth=10),
    WindowSpec(name_regex=".*搜索.*", control_type="EditControl", search_depth=10),
    WindowSpec(control_type="EditControl", search_depth=10),  # fallback: any EditControl
]

ADD_TO_CONTACTS_SPECS: List[WindowSpec] = [
    WindowSpec(name="添加好友", control_type="ButtonControl", search_depth=10),
    WindowSpec(name="添加到通讯录", control_type="ButtonControl", search_depth=10),
    WindowSpec(name_regex=".*添加.*", control_type="ButtonControl", search_depth=10),
]

VERIFY_INPUT_SPECS: List[WindowSpec] = [
    WindowSpec(name_regex=".*验证.*", control_type="EditControl", search_depth=8, max_search_seconds=0.5),
    WindowSpec(name_regex=".*验证.*", control_type="DocumentControl", search_depth=8, max_search_seconds=0.5),
    WindowSpec(control_type="EditControl", search_depth=8, max_search_seconds=0.5),
    WindowSpec(control_type="DocumentControl", search_depth=8, max_search_seconds=0.5),
]



SEND_BUTTON_SPECS: List[WindowSpec] = [
    WindowSpec(name="确定", control_type="ButtonControl", search_depth=8),
    WindowSpec(name="发送", control_type="ButtonControl", search_depth=8),
    WindowSpec(name_regex=".*(确定|发送).*", control_type="ButtonControl", search_depth=8),
]


# ---------------------------------------------------------------------------
# 窗口查找
# ---------------------------------------------------------------------------


def _is_wework_handle(handle: WindowHandle) -> bool:
    return "企业微信" in handle.name or handle.class_name == "WeWorkWindow"


# 已知的非微信 class 名（含通配前缀）—— 用于排除"标题里恰好带'微信'"
# 的进程，例如 VS Code 打开了名为「微信问题排查.md」的文件、Chrome 标签页、
# QQ/电报/Slack/Discord 等基于 Chromium/Electron 的应用。
_NON_WECHAT_CLASS_BLACKLIST = (
    "Chrome_WidgetWin_",  # VS Code / Chrome / Edge / 各类 Electron 应用
    "MozillaWindowClass",  # Firefox
    "ApplicationFrameWindow",  # UWP 应用框架
    "Windows.UI.Core.CoreWindow",  # UWP 内容窗口
    "CabinetWClass",  # 资源管理器
    "Notepad",
    "WordPadClass",
)

# 已知的微信主窗口 class 名（按版本枚举）。
# WeChat 3.x: WeChatMainWndForPC
# WeChat 4.x (Qt): Qt51514QWindowIcon
# WeChat 4.x (新版): mmui::MainWindow
_KNOWN_WECHAT_CLASSES = frozenset(
    {
        "WeChatMainWndForPC",
        "Qt51514QWindowIcon",
        "mmui::MainWindow",
    }
)


def _looks_like_wechat_main_window(name: str, class_name: str) -> bool:
    """判定一个顶层窗口是否是微信主窗口。

    收紧策略：必须满足 class 在已知微信类名白名单内（或精确等于）。
    不能仅靠"标题里有'微信'"判定，否则 VS Code 打开含"微信"的文件、
    Chrome 标签页等都会误命中。
    """
    if "企业微信" in name or class_name == "WeWorkWindow":
        return False
    # 显式黑名单：Chromium / Electron / Firefox 等
    for prefix in _NON_WECHAT_CLASS_BLACKLIST:
        if class_name.startswith(prefix):
            return False
    if class_name == "WeChatMainWndForPC":
        return True
    if class_name in _KNOWN_WECHAT_CLASSES and ("微信" in name or "Weixin" in name):
        return True
    return False


class _Win32BoundingRectangle:
    def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


class _Win32WindowProxy:
    """少量模拟 uiautomation 控件接口，供现有 WindowsDesktopAdapter 复用。"""

    def __init__(self, hwnd: int, name: str, class_name: str) -> None:
        self.NativeWindowHandle = hwnd
        self.Name = name
        self.ClassName = class_name

    @property
    def BoundingRectangle(self) -> _Win32BoundingRectangle:
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(self.NativeWindowHandle, ctypes.byref(rect))
        return _Win32BoundingRectangle(
            int(rect.left),
            int(rect.top),
            int(rect.right),
            int(rect.bottom),
        )

    def ShowWindow(self, command: int) -> None:
        import ctypes

        ctypes.windll.user32.ShowWindow(self.NativeWindowHandle, command)

    def SetActive(self) -> None:
        import ctypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = self.NativeWindowHandle

        # 1. 恢复并显示窗口（如果最小化了就 SW_RESTORE=9，否则 SW_SHOW=5）
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)
        else:
            user32.ShowWindow(hwnd, 5)

        # 2. 绕过 Windows 的 SetForegroundWindow 限制
        # 获取当前前台窗口的线程 ID
        fore_hwnd = user32.GetForegroundWindow()
        fore_thread = user32.GetWindowThreadProcessId(fore_hwnd, None)
        curr_thread = kernel32.GetCurrentThreadId()

        attached = False
        if fore_hwnd != hwnd and fore_thread != 0 and fore_thread != curr_thread:
            # 将当前线程的输入附加到当前前台窗口线程
            attached = bool(user32.AttachThreadInput(curr_thread, fore_thread, True))

        try:
            # 临时将窗口设为置顶再恢复，以强行激活它
            # HWND_TOPMOST = -1, HWND_NOTOPMOST = -2
            # SWP_NOSIZE = 0x0001, SWP_NOMOVE = 0x0002, SWP_SHOWWINDOW = 0x0040
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
            user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)

            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
        finally:
            if attached:
                # 分离线程输入
                user32.AttachThreadInput(curr_thread, fore_thread, False)

    def SetTopmost(self, on: bool) -> None:
        import ctypes

        hwnd_insert_after = -1 if on else -2  # HWND_TOPMOST / HWND_NOTOPMOST
        flags = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
        ctypes.windll.user32.SetWindowPos(
            self.NativeWindowHandle,
            hwnd_insert_after,
            0,
            0,
            0,
            0,
            flags,
        )


def _find_wechat_window_by_win32() -> Optional[WindowHandle]:
    """Windows 专用的微信主窗口查找，避免 UIAutomation 扫树卡死。"""
    if sys.platform != "win32":
        return None

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    candidates: List[WindowHandle] = []

    def _read_window_text(hwnd) -> str:
        length = int(user32.GetWindowTextLengthW(hwnd))
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def _read_class_name(hwnd) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buffer, 256)
        return buffer.value

    def _window_rect(hwnd) -> Optional[Tuple[int, int, int, int]]:
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        result = (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
        left, top, right, bottom = result
        if right <= left or bottom <= top:
            return None
        return result

    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @enum_proc
    def _collect(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            name = _read_window_text(hwnd)
            class_name = _read_class_name(hwnd)
            if not _looks_like_wechat_main_window(name, class_name):
                return True
            rect = _window_rect(hwnd)
            if rect is None:
                return True
            native_id = int(hwnd)
            candidates.append(
                WindowHandle(
                    native_id=native_id,
                    name=name,
                    class_name=class_name,
                    rect=rect,
                    platform_data=_Win32WindowProxy(native_id, name, class_name),
                )
            )
        except Exception:
            return True
        return True

    user32.EnumWindows(_collect, 0)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda handle: (handle.rect[2] - handle.rect[0]) * (handle.rect[3] - handle.rect[1]),
    )


def _find_wechat_window(auto=None) -> Optional[WindowHandle]:
    """查找微信主窗口。``auto`` 参数 v2 已废弃，保留仅供向后兼容。

    Windows 优先走 Win32 顶层窗口枚举，避免 UIAutomation 在微信窗口
    发现阶段扫树卡死；非 Windows 保留平台适配器路径。
    """
    win32_handle = _find_wechat_window_by_win32()
    if win32_handle is not None:
        return win32_handle
    if sys.platform == "win32":
        return None

    desktop = get_desktop_adapter()

    # Fast path：等价于 `auto.WindowControl(ClassName=...).Exists()`，
    # 每个 spec 独立查询，命中即返回，避免枚举所有顶层窗口。
    handle = desktop.find_window(WECHAT_WINDOW_SPECS)
    if handle is not None and not _is_wework_handle(handle):
        return handle

    # Slow fallback：定向查询命中的是企业微信（极少见），或全部失败时，
    # 才走顶层枚举做精细过滤。
    for handle in desktop.list_top_level_windows():
        if _is_wework_handle(handle):
            continue
        for spec in WECHAT_WINDOW_SPECS:
            if _match_handle(handle, spec):
                return handle
    return None


def _find_add_friends_window(auto=None) -> Optional[WindowHandle]:
    desktop = get_desktop_adapter()
    handle = desktop.find_window(ADD_FRIENDS_WINDOW_SPECS)
    if handle is not None:
        rect = desktop.get_bounding_rectangle(handle)
        if rect and len(rect) >= 4 and isinstance(rect[0], (int, float)) and isinstance(rect[2], (int, float)):
            w = rect[2] - rect[0]
            h = rect[3] - rect[1]
            if w < 250 or h < 250:
                return None
    return handle


def _find_add_friends_window_fast() -> Optional[WindowHandle]:
    """即时探测（0s）—— 用于"窗口是否已开"判定，避免 3×2s 黑洞。"""
    desktop = get_desktop_adapter()
    specs = [WindowSpec(**{**vars(s), "max_search_seconds": 0}) for s in ADD_FRIENDS_WINDOW_SPECS]
    handle = desktop.find_window(specs)
    if handle is not None:
        rect = desktop.get_bounding_rectangle(handle)
        if rect and len(rect) >= 4 and isinstance(rect[0], (int, float)) and isinstance(rect[2], (int, float)):
            w = rect[2] - rect[0]
            h = rect[3] - rect[1]
            if w < 250 or h < 250:
                return None
    return handle


def _find_verify_window(auto=None) -> Optional[WindowHandle]:
    desktop = get_desktop_adapter()
    handle = desktop.find_window(VERIFY_WINDOW_SPECS)
    if handle is not None:
        rect = desktop.get_bounding_rectangle(handle)
        if rect and len(rect) >= 4 and isinstance(rect[0], (int, float)) and isinstance(rect[2], (int, float)):
            w = rect[2] - rect[0]
            h = rect[3] - rect[1]
            if w < 250 or h < 250:
                return None
    return handle


def _current_add_friend_target(auto=None, wx_window: Optional[WindowHandle] = None):
    add_friends = _find_add_friends_window()
    return add_friends or wx_window


def _match_handle(handle: WindowHandle, spec: WindowSpec) -> bool:
    if spec.class_name and handle.class_name != spec.class_name:
        return False
    if spec.name and handle.name != spec.name:
        return False
    if spec.name_regex:
        import re

        if not re.search(spec.name_regex, handle.name):
            return False
    return True


# ---------------------------------------------------------------------------
# 输入
# ---------------------------------------------------------------------------


def _type_human_like(auto, text: str, min_delay: float, max_delay: float) -> None:
    """逐字符输入。``auto`` 参数 v2 已废弃。"""
    get_desktop_adapter().send_keys(text, (min_delay, max_delay))


def _type_human_like_physical(text: str, min_delay: float, max_delay: float) -> None:
    """物理键盘输入（v2 合并到 adapter.send_keys）。"""
    get_desktop_adapter().send_keys(text, (min_delay, max_delay))


def _paste_text_via_clipboard(text: str) -> None:
    get_desktop_adapter().paste_text(text)


def _clear_field() -> None:
    get_desktop_adapter().clear_field()


# ---------------------------------------------------------------------------
# 步骤函数
# ---------------------------------------------------------------------------


def _click_first_existing(
    mark: Callable[[str], None],
    label: str,
    handles: List[WindowHandle],
) -> bool:
    for handle in handles:
        if handle is not None:
            desktop = get_desktop_adapter()
            rect = desktop.get_bounding_rectangle(handle)
            cx = (rect[0] + rect[2]) // 2
            cy = (rect[1] + rect[3]) // 2
            desktop.click(cx, cy)
            mark(f"{label}: 已通过平台桌面适配器点击 {handle.name!r}")
            return True
    return False


def _wait_and_front_verify_window(
    auto, fallback_window: WindowHandle, mark: Callable[[str], None]
) -> Tuple[WindowHandle, bool]:
    """轮询等待独立验证申请窗口。

    Returns:
        (window, found)：found=True 表示找到独立验证窗；False 表示
        超时未找到，window 回退为 fallback_window，由调用方决定是否
        二次读屏判定（A-1）。
    """
    desktop = get_desktop_adapter()
    for _ in range(10):
        verify_window = _find_verify_window()
        if verify_window is not None:
            try:
                desktop.set_topmost(fallback_window, False)
            except Exception:
                pass
            desktop.set_active(verify_window)
            desktop.set_topmost(verify_window, True)
            _sleep(0.3)
            mark(
                f"VERIFY_WINDOW_FOUND: 已定位并置顶验证申请窗口 "
                f"Name={verify_window.name!r} ClassName={verify_window.class_name!r}"
            )
            return verify_window, True
        _sleep(0.3)
    mark("VERIFY_WINDOW_NOT_FOUND: 未发现独立验证申请窗口")
    return fallback_window, False


def _click_wechat_add_button_by_search_anchor(
    wx_window: WindowHandle,
    *,
    mark: Callable[[str], None] | None = None,
) -> MatchResult:
    """先 OCR 定位“搜索”，再在其右侧水平带内用模板匹配点击加号。"""
    def _mark(step: str) -> None:
        if mark is not None:
            mark(step)

    try:
        import cv2
        import numpy as np
    except Exception as exc:  # pragma: no cover - local desktop dependency
        raise AppError(
            "VISION_DRIVER_UNAVAILABLE",
            f"图像识别依赖不可用，请安装 opencv-python/pillow: {exc}",
        ) from exc

    desktop = get_desktop_adapter()
    ocr = get_ocr_adapter()

    try:
        ocr.enable_dpi_awareness()
    except Exception:
        pass
    try:
        if ocr.is_locked():
            raise AppError(
                "VISION_LOCKED_SCREEN",
                "屏幕已锁定或 RDP 会话已断开 / 最小化，无 GUI 渲染可用",
            )
    except AppError:
        raise
    except Exception:
        pass

    left, top, right, bottom = desktop.get_bounding_rectangle(wx_window)
    width = max(right - left, 1)
    height = max(bottom - top, 1)
    _mark(f"ADD_PLUS_WINDOW_RECT: x={left} y={top} w={width} h={height}")

    try:
        screenshot = ocr.screenshot((left, top, width, height))
    except Exception as exc:
        raise AppError("VISION_SCREENSHOT_FAILED", f"截屏失败: {exc}") from exc
    _mark(f"ADD_PLUS_SCREENSHOT_OK: crop={width}x{height}")

    source_bgr = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    gray_source = cv2.cvtColor(source_bgr, cv2.COLOR_BGR2GRAY)

    try:
        handle = WindowHandle(native_id=wx_window.native_id)
        lang_tag = ocr.detect_app_language(handle)
    except Exception:
        lang_tag = ""
    try:
        base_scale = ocr.get_dpi_scale(WindowHandle(native_id=wx_window.native_id))
    except Exception:
        base_scale = 1.0
    try:
        theme = ocr.get_theme()
    except Exception:
        theme = "light"
    if theme not in ("light", "dark"):
        theme = "light"
    if theme != "dark" and hasattr(gray_source, "shape"):
        try:
            h_s, _ = gray_source.shape[:2]
            top_region = gray_source[0 : min(30, h_s), :]
            if hasattr(top_region, "size") and top_region.size > 0:
                if float(top_region.mean()) < 80:
                    theme = "dark"
        except Exception:
            pass
    _mark(f"ADD_PLUS_CONTEXT: lang={lang_tag or 'unknown'} scale={base_scale:.2f} theme={theme}")

    top_band_height = max(1, min(height, int(height * 0.22)))
    left_band_width = max(1, min(width, int(width * 0.65)))
    search_band = source_bgr[0:top_band_height, 0:left_band_width]
    try:
        words = ocr.recognize(search_band, lang_tag)
    except Exception as exc:
        raise AppError("VISION_OCR_FAILED", f"OCR 定位搜索框失败: {exc}") from exc
    preview = " | ".join(word.text for word in words[:12])
    if len(preview) > 120:
        preview = preview[:117] + "..."
    _mark(f"ADD_PLUS_OCR_WORDS: count={len(words)} text={preview}")

    anchors = [
        word
        for word in words
        if fuzzy_text_hit(word.text, ["搜索", "Search"], min_ratio=80) is not None
    ]
    if not anchors:
        _mark("ADD_PLUS_SEARCH_ANCHOR_MISS: OCR 未识别到“搜索”，尝试搜索框模板")
        search_area_gray = gray_source[0:top_band_height, 0:left_band_width]
        for template_name in ["wechat_search_box", "search_input"]:
            template_path = vision._template_path(template_name)
            if not template_path.exists():
                continue
            search_match = vision._match_template_on_image(
                cv2,
                search_area_gray,
                template_path,
                base_scale,
                0.70,
                theme=theme,
            )
            if search_match is not None:
                _mark(
                    "ADD_PLUS_SEARCH_TEMPLATE_HIT: "
                    f"template={template_path.name} score={search_match['score']:.3f} "
                    f"x={search_match['x']} y={search_match['y']} "
                    f"w={search_match['tw']} h={search_match['th']}"
                )
                anchors.append(
                    OcrWord(
                        text="搜索",
                        x=search_match["x"],
                        y=search_match["y"],
                        width=search_match["tw"],
                        height=search_match["th"],
                    )
                )
                break
        if not anchors:
            header_best: tuple[str, dict] | None = None
            for template_name in ["wechat_add_button", "wechat_add_button-tight"]:
                template_path = vision._template_path(template_name)
                if not template_path.exists():
                    continue
                header_match = vision._match_template_on_image(
                    cv2,
                    search_area_gray,
                    template_path,
                    base_scale,
                    0.90,
                    theme=theme,
                )
                if header_match is None:
                    continue
                local_center_x = header_match["x"] + header_match["tw"] // 2
                min_header_x = int(width * 0.18)
                max_header_x = min(left_band_width, int(width * 0.68))
                if local_center_x < min_header_x or local_center_x > max_header_x:
                    _mark(
                        "ADD_PLUS_HEADER_TEMPLATE_REJECTED: "
                        f"template={template_path.name} score={header_match['score']:.3f} "
                        f"local_x={local_center_x} allowed=({min_header_x},{max_header_x})"
                    )
                    continue
                if header_best is None or header_match["score"] > header_best[1]["score"]:
                    header_best = (template_path.name, header_match)
            if header_best is not None:
                template_name, header_match = header_best
                center_x = left + header_match["x"] + header_match["tw"] // 2
                center_y = top + header_match["y"] + header_match["th"] // 2
                _mark(
                    "ADD_PLUS_HEADER_TEMPLATE_HIT: "
                    f"template={template_name} score={header_match['score']:.3f} "
                    f"center=({center_x},{center_y})"
                )
                desktop.click(center_x, center_y)
                return MatchResult(
                    template_name=template_name,
                    center_x=center_x,
                    center_y=center_y,
                    score=header_match["score"],
                )
            _mark("ADD_PLUS_SEARCH_ANCHOR_NOT_FOUND: OCR 与搜索框模板均未定位搜索框")
            raise AppError(
                "VISION_TARGET_NOT_FOUND",
                "未能通过 OCR 或搜索框模板定位微信主界面的“搜索”，无法锚定右侧加号",
            )

    anchor = min(anchors, key=lambda word: (word.y, word.x))
    _mark(
        "ADD_PLUS_SEARCH_ANCHOR_FOUND: "
        f"text={anchor.text!r} x={anchor.x} y={anchor.y} w={anchor.width} h={anchor.height}"
    )
    anchor_center_y = anchor.y + anchor.height // 2
    roi_left = min(width - 1, max(0, anchor.x + anchor.width))
    roi_top = max(0, anchor_center_y - 45)
    roi_right = min(width, max(roi_left + 120, anchor.x + int(width * 0.70)))
    roi_bottom = min(height, anchor_center_y + 45)
    if roi_right <= roi_left or roi_bottom <= roi_top:
        raise AppError(
            "VISION_TARGET_NOT_FOUND",
            "OCR 已定位搜索框，但右侧加号候选区域无效",
        )
    _mark(f"ADD_PLUS_ROI: x={roi_left} y={roi_top} w={roi_right - roi_left} h={roi_bottom - roi_top}")

    roi_gray = gray_source[roi_top:roi_bottom, roi_left:roi_right]

    best: tuple[str, dict] | None = None
    missing: list[str] = []
    unmatched: list[str] = []
    for template_name in ["wechat_add_button", "wechat_add_button-tight"]:
        template_path = vision._template_path(template_name)
        if not template_path.exists():
            missing.append(template_path.name)
            continue
        match = vision._match_template_on_image(
            cv2,
            roi_gray,
            template_path,
            base_scale,
            0.80,
            theme=theme,
        )
        if match is None:
            unmatched.append(f"{template_path.name}(score<0.80)")
            continue
        _mark(
            "ADD_PLUS_TEMPLATE_CANDIDATE: "
            f"template={template_path.name} score={match['score']:.3f} "
            f"x={match['x']} y={match['y']} w={match['tw']} h={match['th']}"
        )
        if best is None or match["score"] > best[1]["score"]:
            best = (template_path.name, match)

    if best is None:
        details = []
        if missing:
            details.append("缺失: " + ", ".join(missing))
        if unmatched:
            details.append("未匹配: " + ", ".join(unmatched))
        _mark("ADD_PLUS_TEMPLATE_MISS: " + "；".join(details or ["未提供模板"]))
        raise AppError(
            "VISION_TARGET_NOT_FOUND",
            "已通过 OCR 定位搜索框，但未能在右侧区域匹配加号模板；"
            + "；".join(details or ["未提供模板"]),
        )

    template_name, match = best
    center_x = left + roi_left + match["x"] + match["tw"] // 2
    center_y = top + roi_top + match["y"] + match["th"] // 2
    _mark(f"ADD_PLUS_TEMPLATE_HIT: template={template_name} score={match['score']:.3f} center=({center_x},{center_y})")
    desktop.click(center_x, center_y)
    return MatchResult(
        template_name=template_name,
        center_x=center_x,
        center_y=center_y,
        score=match["score"],
    )


def _click_wechat_add_button_by_cached_vision(auto, wx_window: WindowHandle) -> Optional[MatchResult]:
    """用缓存/模板快路径点击主界面加号；拒绝 OCR 命中以避免全窗口误点。"""
    try:
        match = vision.find_first(
            auto,
            wx_window,
            ["wechat_add_button", "wechat_add_button-tight"],
            threshold=0.85,
        )
    except AppError:
        return None

    if match.template_name.startswith("ocr_"):
        return None

    desktop = get_desktop_adapter()
    left, top, right, bottom = desktop.get_bounding_rectangle(wx_window)
    width = max(right - left, 1)
    height = max(bottom - top, 1)
    local_x = match.center_x - left
    local_y = match.center_y - top
    top_limit = max(120, int(height * 0.22))
    if local_y > top_limit:
        return None
    if local_x < int(width * 0.35) or local_x > int(width * 0.75):
        return None

    desktop.click(match.center_x, match.center_y)
    return match


def _open_add_friends_entry(
    auto, wx_window: WindowHandle, mark: Callable[[str], None]
) -> None:
    # 第一步：缓存/模板快路径优先；失败后再用 OCR/搜索框锚点局部搜索。
    match = _click_wechat_add_button_by_cached_vision(auto, wx_window)
    if match is not None:
        mark(f"ADD_MENU_OPENED_BY_CACHED_VISION: 模板={match.template_name} score={match.score:.3f}")
    else:
        mark("ADD_PLUS_CACHED_VISION_MISS: 缓存图像识别未命中(冷启动/主题变化)，降级到 OCR 锚点")
        try:
            match = _click_wechat_add_button_by_search_anchor(wx_window, mark=mark)
            mark(f"ADD_MENU_OPENED_BY_SEARCH_ANCHOR: 模板={match.template_name} score={match.score:.3f}")
        except AppError as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            message = detail.get("message", str(exc))
            raise AppError(
                "ADD_PLUS_NOT_FOUND",
                f"缓存图像识别与 OCR 锚点兜底均未找到加号按钮: {message}",
            ) from exc
    _sleep(0.5)

    # 第二步：在弹出菜单中点击"添加朋友"
    try:
        menu_match = vision.click_first(
            auto,
            wx_window,
            ["menu_add_friends", "add_friends_menu_item"],
        )
        mark(f"ADD_FRIENDS_PAGE_OPENED_BY_VISION: 模板={menu_match.template_name} score={menu_match.score:.3f}")
    except AppError:
        desktop = get_desktop_adapter()
        try:
            _left, _top, _right, bottom = desktop.get_bounding_rectangle(wx_window)
            fallback_y = min(match.center_y + 86, bottom - 20)
        except Exception:
            fallback_y = match.center_y + 86
        fallback_x = match.center_x
        desktop.click(fallback_x, fallback_y)
        mark(
            "ADD_FRIENDS_PAGE_OPENED_BY_MENU_OFFSET: "
            f"已按加号菜单固定偏移点击“添加朋友” x={fallback_x} y={fallback_y}"
        )
    _sleep(0.8)


def _focus_search_box(
    auto, target_window: WindowHandle, mark: Callable[[str], None]
) -> Tuple[Optional[WindowHandle], str]:
    match = vision.click_first(
        auto,
        target_window,
        ["add_friends_search_box", "wechat_search_box", "search_input"],
    )
    mark(f"SEARCH_BOX_FOUND_BY_VISION: 模板={match.template_name} score={match.score:.3f}")
    return None, "vision"


def _clear_and_type_target(
    auto, control: Optional[WindowHandle], input_method: str, phone: str
) -> None:
    _clear_field()
    _sleep(0.2)
    _type_human_like_physical(phone, 0.05, 0.15)


def _press_enter(auto, control: Optional[WindowHandle], input_method: str) -> None:
    if control is not None and input_method == "uia":
        get_desktop_adapter().hotkey("enter")
    else:
        get_desktop_adapter().hotkey("enter")


def _click_add_friend(
    auto, target_window: WindowHandle, mark: Callable[[str], None]
) -> bool:
    """点击"添加到通讯录"。

    Returns:
        True 表示成功点击；找不到按钮时返回 False（交由调用方做业务判定），
        而不是直接抛 VISION_TARGET_NOT_FOUND 系统错误。
    """
    try:
        match = vision.click_first(
            auto,
            target_window,
            ["add_to_contacts_button", "add_friend_button", "add_contact_button"],
            threshold=0.70,
        )
    except AppError as exc:
        code = exc.detail.get("code") if isinstance(exc.detail, dict) else None
        if code == "VISION_TARGET_NOT_FOUND":
            # 找不到"添加到通讯录"按钮通常是业务信号（搜不到人/已是好友/账号类型不符），
            # 不当系统故障冒泡，返回 False 让主流程读屏二次判定。
            mark("ADD_BUTTON_NOT_FOUND: 未找到“添加到通讯录”按钮，转入业务状态判定")
            return False
        raise
    mark(f"ADD_BUTTON_FOUND_BY_VISION: 模板={match.template_name} score={match.score:.3f}")
    return True


def _window_name(window: WindowHandle) -> str:
    return str(getattr(window, "name", None) or getattr(window, "Name", "") or "")


def _confirm_friend_profile_window(target_window: WindowHandle, mark: Callable[[str], None]) -> bool:
    if "通过朋友验证" not in _window_name(target_window):
        return False

    desktop = get_desktop_adapter()
    desktop.set_active(target_window)
    desktop.set_topmost(target_window, True)
    _sleep(0.3)

    try:
        match = vision.click_first(
            None,
            target_window,
            ["send_button", "confirm_button", "verify_confirm_button"],
        )
        mark(
            "FRIEND_PROFILE_CONFIRMED_BY_VISION: "
            f"已确认“通过朋友验证”资料页 模板={match.template_name} score={match.score:.3f}"
        )
    except AppError:
        left, top, right, bottom = desktop.get_bounding_rectangle(target_window)
        width = max(right - left, 1)
        height = max(bottom - top, 1)
        click_x = left + int(width * 0.28)
        click_y = bottom - min(40, max(28, int(height * 0.05)))
        desktop.click(click_x, click_y)
        mark(
            "FRIEND_PROFILE_CONFIRMED_BY_OFFSET: "
            f"已按底部按钮固定区域确认“通过朋友验证” x={click_x} y={click_y}"
        )

    _sleep(0.8)
    still_open = _find_verify_window()
    if still_open is not None and "通过朋友验证" in _window_name(still_open):
        raise AppError(
            "FRIEND_PROFILE_CONFIRM_FAILED",
            "已尝试点击“通过朋友验证”确认按钮，但窗口仍未关闭，已中止以避免误报成功",
        )
    return True


def _fill_verify_message(
    auto, target_window: WindowHandle, greeting: str, mark: Callable[[str], None]
) -> None:
    desktop = get_desktop_adapter()
    desktop.set_active(target_window)
    desktop.set_topmost(target_window, True)
    _sleep(0.3)

    # 视觉降级
    match = vision.find_first(
        auto,
        target_window,
        ["verify_message_input", "friend_verify_input"],
        threshold=0.65,
    )
    mark(f"GREETING_INPUT_FOUND_BY_VISION: 模板={match.template_name} score={match.score:.3f}")

    click_x = match.center_x
    click_y = match.center_y
    if "verify_message_input" in match.template_name or "friend_verify_input" in match.template_name:
        try:
            scale_factor = get_ocr_adapter().get_dpi_scale()
        except Exception:
            scale_factor = 1.0
        click_y += int(75 * scale_factor)


    desktop.click(click_x, click_y)
    _sleep(0.3)

    _clear_field()
    _sleep(0.15)
    _paste_text_via_clipboard(greeting)
    mark("GREETING_FILLED_BY_VISION: 已精确定位输入框、清空默认文本并粘贴验证语")



def _click_send_verify(
    auto, target_window: WindowHandle, mark: Callable[[str], None]
) -> None:
    desktop = get_desktop_adapter()
    desktop.set_active(target_window)
    desktop.set_topmost(target_window, True)
    _sleep(0.2)

    # 扩展窗口边界，向下扩展，防止 DPI 缩放或边框阴影导致底部的“确定”按钮被截断。
    # 通过创建一个 platform_data=None 且 rect 底部增加 120 像素 of WindowHandle 来绕过实时 BoundingRectangle of 限制。
    rect = desktop.get_bounding_rectangle(target_window)
    left, top, right, bottom = rect
    extended_rect = (left, top, right, bottom + 120)
    
    extended_window = WindowHandle(
        native_id=target_window.native_id,
        name=target_window.name,
        class_name=target_window.class_name,
        rect=extended_rect,
        platform_data=None  # 设为 None 强制 _window_rect 使用 rect
    )

    match = vision.click_first(
        auto,
        extended_window,
        ["send_button", "confirm_button", "verify_confirm_button"],
    )
    mark(f"SEND_CLICKED_BY_VISION: 模板={match.template_name} score={match.score:.3f}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def _cleanup_stale_windows_by_win32() -> int:
    """Windows 下用 Win32 关闭遗留子窗口，避免 UIAutomation 扫树卡死。"""
    if sys.platform != "win32":
        return 0

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    candidates = [*VERIFY_WINDOW_SPECS, *ADD_FRIENDS_WINDOW_SPECS]
    closed = 0

    def _read_window_text(hwnd) -> str:
        length = int(user32.GetWindowTextLengthW(hwnd))
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def _read_class_name(hwnd) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buffer, 256)
        return buffer.value

    def _window_rect(hwnd) -> Optional[Tuple[int, int, int, int]]:
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        result = (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
        left, top, right, bottom = result
        if right <= left or bottom <= top:
            return None
        return result

    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @enum_proc
    def _collect(hwnd, _lparam):
        nonlocal closed
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            rect = _window_rect(hwnd)
            if rect is None:
                return True
            handle = WindowHandle(
                native_id=int(hwnd),
                name=_read_window_text(hwnd),
                class_name=_read_class_name(hwnd),
                rect=rect,
            )
            if any(_match_handle(handle, spec) for spec in candidates):
                user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                closed += 1
        except Exception:
            return True
        return True

    user32.EnumWindows(_collect, 0)
    return closed


def _cleanup_stale_windows(mark: Callable[[str], None]) -> None:
    """关闭上一次任务遗留的"添加朋友"/验证申请窗口，避免脏窗口污染（O-4）。

    常态下没有遗留窗口，所以这里用 max_search_seconds=0 做即时探测，
    不能用默认的 2s —— 否则 3+5 个 spec 累计要等 16s（核心性能黑洞）。
    复用 desktop 适配器；任何异常都吞掉，清理失败不应阻断主流程。
    """
    if sys.platform == "win32":
        try:
            closed = _cleanup_stale_windows_by_win32()
        except Exception:
            closed = 0
        if closed:
            mark(f"STALE_WINDOWS_CLEANED: 已清理 {closed} 个遗留窗口")
        return

    desktop = get_desktop_adapter()
    closed = 0
    add_friends_specs = [
        WindowSpec(**{**vars(s), "max_search_seconds": 0}) for s in ADD_FRIENDS_WINDOW_SPECS
    ]
    verify_specs = [
        WindowSpec(**{**vars(s), "max_search_seconds": 0}) for s in VERIFY_WINDOW_SPECS
    ]
    for specs in (verify_specs, add_friends_specs):
        try:
            stale = desktop.find_window(specs)
        except Exception:
            stale = None
        if stale is not None:
            try:
                desktop.close_window(stale)
                closed += 1
            except Exception:
                # 适配器未实现 close_window 时退而求其次：取消置顶
                try:
                    desktop.set_topmost(stale, False)
                except Exception:
                    pass
    if closed:
        mark(f"STALE_WINDOWS_CLEANED: 已清理 {closed} 个遗留窗口")


def execute_single_add_request(
    phone: str,
    greeting: str,
    update: Callable[[str], None],
    job_id: str | None = None,
    cancel_token: threading.Event | None = None,
) -> list[str]:
    """执行单次加微请求。

    在所有平台上共享同一业务逻辑，通过 ``get_desktop_adapter()``
    和 ``get_ocr_adapter()`` 适配不同操作系统。
    """
    set_cancel_token(cancel_token)
    steps: list[str] = []
    snaps_saved: list[str] = []

    def mark(step: str) -> None:
        steps.append(step)
        update(step)

    def _snap(tag: str) -> str | None:
        """生成留痕截图路径（O-3）。无 job_id 时返回 None。"""
        if not job_id:
            return None
        path = f"backend/data/decision_{job_id}_{tag}.png"
        snaps_saved.append(path)
        return path

    # ---- E-3 入口校验：手机号/标识非空 ----
    if not phone or not str(phone).strip():
        raise AppError("INVALID_TARGET", "加微目标标识为空，已拒绝执行")

    wx_window: Optional[WindowHandle] = None
    target_window: Optional[WindowHandle] = None
    verify_window: Optional[WindowHandle] = None

    # 自愈：清理可能因历史版本误写入的 verify_message_input / friend_verify_input 损坏缓存（例如标题栏截图）
    try:
        vision.clean_cache_by_name("verify_message_input")
        vision.clean_cache_by_name("friend_verify_input")
    except Exception:
        pass

    vision.clear_pending_cache()
    success = False

    try:  # pragma: no cover - requires local WeChat client
        mark("REAL_RPA_STARTED: 开始单次真实微信加友流程")

        # ---- E-2 锁屏/无渲染预检 ----
        try:
            if get_ocr_adapter().is_locked():
                raise AppError(
                    "VISION_LOCKED_SCREEN",
                    "屏幕已锁定或 RDP 会话已断开 / 最小化，无 GUI 渲染可用",
                )
        except AppError:
            raise
        except Exception:
            pass

        wx_window = _find_wechat_window()
        if wx_window is None:
            raise AppError(
                "WECHAT_NOT_FOUND",
                "未发现已登录的微信客户端；请确认微信窗口可见，且不是企业微信",
            )
        mark(
            f"WECHAT_WINDOW_FOUND: 已定位微信主窗口 "
            f"Name={wx_window.name!r} ClassName={wx_window.class_name!r}"
        )

        desktop = get_desktop_adapter()

        # 先还原窗口，让用户看到窗口立刻弹出来（set_active 前的任何
        # 操作都不应阻塞窗口还原，尤其是 _cleanup_stale_windows）。
        desktop.set_active(wx_window)
        desktop.set_topmost(wx_window, True)
        _sleep(0.3)

        # ---- O-4 清理上次任务遗留的脏窗口 ----
        _cleanup_stale_windows(mark)

        already_open = _find_add_friends_window_fast()
        if already_open is not None:
            mark("ADD_FRIENDS_WINDOW_ALREADY_OPEN: 检测到“添加朋友”窗口已处于打开状态，直接复用")
        else:
            _open_add_friends_entry(None, wx_window, mark)

        desktop.set_topmost(wx_window, False)
        target_window = _current_add_friend_target(wx_window=wx_window)
        if target_window is not wx_window:
            desktop.set_active(target_window)
            desktop.set_topmost(target_window, True)
            _sleep(0.3)
            mark(
                f"ADD_FRIENDS_WINDOW_FOUND: 已定位并置顶添加朋友窗口 "
                f"Name={target_window.name!r} ClassName={target_window.class_name!r}"
            )
        else:
            mark("ADD_FRIENDS_WINDOW_IN_MAIN: 添加朋友界面位于微信主窗口内")

        search_box, input_method = _focus_search_box(None, target_window, mark)
        _clear_and_type_target(None, search_box, input_method, phone)
        mark(f"PHONE_TYPED: 已通过 {input_method} 输入客户标识")

        _press_enter(None, search_box, input_method)
        _sleep(2.0)

        target_window = _current_add_friend_target(wx_window=wx_window)

        # ---- S-1/S-2/A-3 搜索结果读屏判定（核心防御） ----
        state = _detect_screen_state(
            target_window,
            ["RISK_CONTROL", "TARGET_NOT_FOUND", "ALREADY_FRIEND"],
            save_path=_snap("after_search"),
            mark=mark,
        )
        if state:
            mark(f"SEARCH_RESULT_STATE: 读屏判定命中 {state}")
        _raise_if_business_outcome(state)

        clicked = _click_add_friend(None, target_window, mark)
        if not clicked:
            # 没有"添加到通讯录"按钮：先读屏二次判定具体业务状态
            state = _detect_screen_state(
                target_window,
                ["RISK_CONTROL", "TARGET_NOT_FOUND", "ALREADY_FRIEND", "ADD_REJECTED"],
                save_path=_snap("no_add_button"),
                mark=mark,
            )
            if state:
                mark(f"NO_ADD_BUTTON_STATE: 读屏判定命中 {state}")
            _raise_if_business_outcome(state)
            # 读屏未命中已知关键词，但"搜索框可用却无添加按钮"本身就是强业务信号，
            # 兜底判定为"未搜索到目标"，而不是误导性的 VISION_TARGET_NOT_FOUND 系统错误。
            raise RpaBusinessOutcome(
                "BIZ_TARGET_NOT_FOUND",
                "未找到可添加的目标（无“添加到通讯录”按钮），通常是该账号不存在或无法通过此标识添加",
            )
        _sleep(1.2)

        verify_window, verify_found = _wait_and_front_verify_window(None, target_window, mark)

        # ---- A-1/A-2/A-3 验证窗缺失时二次读屏判定，杜绝盲操作 ----
        if not verify_found:
            state = _detect_screen_state(
                target_window,
                ["RISK_CONTROL", "ADD_REJECTED", "ALREADY_FRIEND", "SEND_SUCCESS"],
                save_path=_snap("no_verify_window"),
                mark=mark,
            )
            if state == "SEND_SUCCESS":
                mark("ADD_DIRECTLY_SENT: 未出现验证窗但已检测到申请已发送")
                mark("REAL_RPA_COMPLETED: 真实微信 RPA 流程完成")
                success = True
                return steps
            if state:
                mark(f"NO_VERIFY_WINDOW_STATE: 读屏判定命中 {state}")
            _raise_if_business_outcome(state)
            # 仍无法判定：抛系统级终态，不再往不存在的输入框盲粘文字
            raise AppError(
                "VERIFY_WINDOW_MISSING",
                "点击添加后既未出现验证窗口，也未识别到任何已知状态，已中止以避免误操作",
            )

        if _confirm_friend_profile_window(verify_window, mark):
            _sleep(1.0)
            mark("ADD_DIRECTLY_CONFIRMED: 已处理“通过朋友验证”确认页")
            mark("REAL_RPA_COMPLETED: 真实微信 RPA 流程完成")
            return steps

        _fill_verify_message(None, verify_window, greeting, mark)

        post_paste_delay = random.uniform(1.2, 2.5)
        mark(f"POST_PASTE_WAIT: 模拟人工核对，等待 {post_paste_delay:.2f} 秒")
        _sleep(post_paste_delay)
        _click_send_verify(None, verify_window, mark)
        _sleep(0.4)  # 将原来的 1.0s 缩短至 0.4s，抢占 Toast 提示的峰值可见期

        # ---- C-1 发送后结果确认 ----
        send_state = _detect_screen_state(
            wx_window,  # Toast 通常显示在微信主窗口的中央，而不是"添加朋友"小窗口内，因此扩大读屏范围
            ["RISK_CONTROL", "ADD_REJECTED", "SEND_SUCCESS"],
            save_path=_snap("after_send"),
            mark=mark,
        )
        if send_state == "SEND_SUCCESS":
            mark("SEND_CONFIRMED: 已读屏确认好友申请发送成功")
        elif send_state in ("RISK_CONTROL", "ADD_REJECTED"):
            mark(f"SEND_RESULT_STATE: 读屏判定命中 {send_state}")
            _raise_if_business_outcome(send_state)
        else:
            # 验证窗已消失通常意味着发送成功；否则标记为未确认（区别于成功）
            still_open = _find_verify_window() is not None
            if still_open:
                mark("SEND_UNCONFIRMED: 已点击发送但未读到成功提示且验证窗仍在，结果待人工核对")
            else:
                mark("SEND_LIKELY_OK: 验证窗已关闭，推断申请已发送（未捕获到明确成功文案）")

        mark("REAL_RPA_COMPLETED: 真实微信 RPA 流程完成")
        
        # 执行成功，主动清理本次任务的留痕截图，节省磁盘空间
        import os
        for path in snaps_saved:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
                
        success = True
        return steps
    finally:
        if success:
            vision.commit_cache()
        else:
            vision.clear_pending_cache()

        desktop = get_desktop_adapter()
        
        import ctypes
        def _window_exists(h: Optional[WindowHandle]) -> bool:
            if h is None:
                return False
            # 单元测试中的 MagicMock 兼容处理
            if hasattr(h, "native_id"):
                nid = h.native_id
                if not isinstance(nid, int):
                    return True
                if not nid:
                    return False
            else:
                return False

            if sys.platform == "win32":
                try:
                    return bool(ctypes.windll.user32.IsWindow(h.native_id))
                except Exception:
                    return False
            return True

        # 无论成功、业务终态还是系统错误，最后都应当关闭辅助窗口，让状态机归零到微信主窗口锚点。
        # 不依赖下一次任务开头的 _cleanup_stale_windows 兜底，避免任务间隔期屏幕脏。
        if verify_window is not None and verify_window is not target_window:
            if _window_exists(verify_window):
                try:
                    desktop.close_window(verify_window)
                    mark("CLEANUP_VERIFY_WINDOW_CLOSED: 已关闭遗留的验证申请窗口")
                except Exception:
                    pass
        if target_window is not None and target_window is not wx_window:
            if _window_exists(target_window):
                try:
                    desktop.close_window(target_window)
                    mark("CLEANUP_ADD_FRIENDS_WINDOW_CLOSED: 已关闭遗留的添加朋友窗口")
                except Exception:
                    pass

        # close_window 成功后 set_topmost 会是 no-op；保留作为关窗失败时的兜底。
        if verify_window is not None and verify_window is not target_window:
            try:
                desktop.set_topmost(verify_window, False)
            except Exception:
                pass
        if target_window is not None and target_window is not wx_window:
            try:
                desktop.set_topmost(target_window, False)
            except Exception:
                pass
        if wx_window is not None:
            try:
                desktop.set_topmost(wx_window, False)
            except Exception:
                pass
