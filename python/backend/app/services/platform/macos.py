"""macOS 平台适配器实现。

依赖：

* `pyobjc-framework-Cocoa` — `NSWorkspace`, `NSScreen`, `NSPasteboard`,
  `NSUserDefaults`
* `pyobjc-framework-Quartz` — `Quartz.CGEvent*` 用于点击/键盘事件、
  `CGSessionCopyCurrentDictionary` 判定锁屏
* `pyobjc-framework-Vision` — `VNRecognizeTextRequest` 本地 OCR
* `pyobjc-framework-ApplicationServices` — `AXUIElement*` 可访问性 API
* `pyobjc-framework-CoreFoundation` — CFString / CFArray 桥接

实施约束：
* 用户必须授予「辅助功能」(Accessibility) + 「屏幕录制」(Screen Recording)
  权限，否则 AX API 与 CGWindowList/CGImage API 会返回空结果。
* macOS 上微信 bundle ID：`com.tencent.xinWeChat`（个人版） /
  `com.tencent.WeWorkMac`（企业版，需排除）。
* `Vision` 框架的坐标系原点在图像 *左下角*，需翻转 Y 轴。
"""
from __future__ import annotations

import sys
from typing import Any, List, Literal, Optional, Tuple

from backend.app.services.platform.base import (
    OcrWord,
    WindowHandle,
    WindowSpec,
)

# 微信 macOS bundle ID
_WECHAT_BUNDLE_IDS = (
    "com.tencent.xinWeChat",  # 个人版微信
    "com.tencent.WeChatMac",  # 历史包名兜底
)
# 企业微信需要排除
_WEWORK_BUNDLE_IDS = (
    "com.tencent.WeWorkMac",
    "com.tencent.WeWork",
)


# ---------------------------------------------------------------------------
# DesktopAdapter
# ---------------------------------------------------------------------------


class MacDesktopAdapter:
    """基于 pyobjc + Quartz CGEvent 的 macOS 桌面适配器。

    macOS 没有 Windows 那种"置顶"的窗口属性；`set_topmost(on=True)`
    实际上通过 `NSRunningApplication.activateWithOptions_` +
    AX `kAXRaiseAction` 把窗口置前 —— 不会"穿透"用户主动切前台。
    """

    def __init__(self) -> None:
        self._wechat_pid: Optional[int] = None  # 上次定位到的微信进程 PID

    # ---- 内部工具 ----

    @staticmethod
    def _ax():
        """Lazy import ApplicationServices for AX* APIs."""
        import ApplicationServices  # type: ignore

        return ApplicationServices

    @staticmethod
    def _quartz():
        import Quartz  # type: ignore

        return Quartz

    @staticmethod
    def _appkit():
        import AppKit  # type: ignore

        return AppKit

    def _find_wechat_app(self):
        """返回正在运行的微信 `NSRunningApplication`，否则 None。"""
        ws = self._appkit().NSWorkspace.sharedWorkspace()
        for running in ws.runningApplications():
            bundle = running.bundleIdentifier() or ""
            if bundle in _WECHAT_BUNDLE_IDS:
                return running
            if bundle in _WEWORK_BUNDLE_IDS:
                continue
        return None

    def _ax_window_to_handle(self, ax_window, pid: int) -> WindowHandle:
        """将 AXUIElement 包装为 `WindowHandle`。"""
        AX = self._ax()
        title = self._ax_value(ax_window, AX.kAXTitleAttribute, default="") or ""
        role = self._ax_value(ax_window, AX.kAXRoleAttribute, default="") or ""

        # 位置与尺寸需要分别拿 kAXPositionAttribute / kAXSizeAttribute
        pos = self._ax_value(ax_window, AX.kAXPositionAttribute)
        size = self._ax_value(ax_window, AX.kAXSizeAttribute)
        rect = (0, 0, 0, 0)
        if pos is not None and size is not None:
            try:
                # AXValue 需要 AXValueGetValue 提取
                pt = AX.AXValueGetValue(pos, AX.kAXValueCGPointType, None)
                sz = AX.AXValueGetValue(size, AX.kAXValueCGSizeType, None)
                if pt and sz:
                    _, p = pt
                    _, s = sz
                    rect = (
                        int(p.x),
                        int(p.y),
                        int(p.x + s.width),
                        int(p.y + s.height),
                    )
            except Exception:
                pass
        return WindowHandle(
            native_id=pid,
            name=str(title),
            class_name=str(role),
            rect=rect,
            platform_data=ax_window,
        )

    @staticmethod
    def _ax_value(element, attr: str, default: Any = None) -> Any:
        import ApplicationServices  # type: ignore

        err, value = ApplicationServices.AXUIElementCopyAttributeValue(element, attr, None)
        if err != 0:
            return default
        return value

    # ---- 窗口 ----

    def find_window(self, candidates: List[WindowSpec]) -> Optional[WindowHandle]:
        running = self._find_wechat_app()
        if running is None:
            return None
        pid = int(running.processIdentifier())
        self._wechat_pid = pid

        AX = self._ax()
        app_element = AX.AXUIElementCreateApplication(pid)
        err, windows = AX.AXUIElementCopyAttributeValue(
            app_element, AX.kAXWindowsAttribute, None
        )
        if err != 0 or not windows:
            return None

        for spec in candidates:
            for window in windows:
                if self._match_spec(window, spec):
                    return self._ax_window_to_handle(window, pid)
        return None

    def find_child_window(
        self, parent: WindowHandle, candidates: List[WindowSpec]
    ) -> Optional[WindowHandle]:
        AX = self._ax()
        err, children = AX.AXUIElementCopyAttributeValue(
            parent.platform_data, AX.kAXChildrenAttribute, None
        )
        if err != 0 or not children:
            return None

        for spec in candidates:
            for child in children:
                if self._match_spec(child, spec):
                    return self._ax_window_to_handle(child, parent.native_id)
        return None

    def _match_spec(self, ax_element, spec: WindowSpec) -> bool:
        AX = self._ax()
        title = self._ax_value(ax_element, AX.kAXTitleAttribute, default="") or ""
        role = self._ax_value(ax_element, AX.kAXRoleAttribute, default="") or ""

        if spec.class_name and str(role) != spec.class_name:
            return False
        if spec.name and str(title) != spec.name:
            return False
        if spec.name_regex:
            import re

            if not re.search(spec.name_regex, str(title)):
                return False
        return True

    def list_top_level_windows(self) -> List[WindowHandle]:
        running = self._find_wechat_app()
        if running is None:
            return []
        pid = int(running.processIdentifier())
        AX = self._ax()
        app_element = AX.AXUIElementCreateApplication(pid)
        err, windows = AX.AXUIElementCopyAttributeValue(
            app_element, AX.kAXWindowsAttribute, None
        )
        if err != 0 or not windows:
            return []
        return [self._ax_window_to_handle(w, pid) for w in windows]

    def get_bounding_rectangle(self, handle: WindowHandle) -> Tuple[int, int, int, int]:
        if handle.platform_data is None:
            return handle.rect
        refreshed = self._ax_window_to_handle(handle.platform_data, handle.native_id)
        return refreshed.rect

    # ---- 操作 ----

    def set_active(self, handle: WindowHandle) -> None:
        AppKit = self._appkit()
        running = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(
            handle.native_id
        )
        if running is not None:
            running.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)

    def set_topmost(self, handle: WindowHandle, on: bool) -> None:
        # macOS 没有 SetTopmost；on=True 时通过 AX 把窗口抬到前。
        if not on:
            return
        AX = self._ax()
        try:
            AX.AXUIElementPerformAction(handle.platform_data, AX.kAXRaiseAction)
        except Exception:  # pragma: no cover
            pass

    def close_window(self, handle: WindowHandle) -> None:
        """关闭窗口：查找标题栏关闭按钮 (kAXCloseButtonAttribute) 并 Press。"""
        AX = self._ax()
        try:
            close_btn = self._ax_value(handle.platform_data, AX.kAXCloseButtonAttribute)
            if close_btn is not None:
                AX.AXUIElementPerformAction(close_btn, AX.kAXPressAction)
        except Exception:  # pragma: no cover
            pass

    def click(self, x: int, y: int) -> None:
        Q = self._quartz()
        point = Q.CGPointMake(x, y)
        down = Q.CGEventCreateMouseEvent(None, Q.kCGEventLeftMouseDown, point, Q.kCGMouseButtonLeft)
        up = Q.CGEventCreateMouseEvent(None, Q.kCGEventLeftMouseUp, point, Q.kCGMouseButtonLeft)
        Q.CGEventPost(Q.kCGHIDEventTap, down)
        Q.CGEventPost(Q.kCGHIDEventTap, up)

    def send_keys(
        self, text: str, per_char_delay: Tuple[float, float] = (0.05, 0.15)
    ) -> None:
        """中文等多字节字符走剪贴板，避免 keycode 表覆盖不全。"""
        # macOS 的 CGEventKeyboardSetUnicodeString 可以直接发 Unicode
        import random
        import time

        Q = self._quartz()
        for char in text:
            event = Q.CGEventCreateKeyboardEvent(None, 0, True)
            Q.CGEventKeyboardSetUnicodeString(event, 1, char)
            Q.CGEventPost(Q.kCGHIDEventTap, event)

            event_up = Q.CGEventCreateKeyboardEvent(None, 0, False)
            Q.CGEventKeyboardSetUnicodeString(event_up, 1, char)
            Q.CGEventPost(Q.kCGHIDEventTap, event_up)

            time.sleep(random.uniform(*per_char_delay))

    def hotkey(self, *keys: str) -> None:
        """把 Windows 风格组合键翻译为 macOS 等价物（ctrl→cmd）。

        覆盖最常用的 ``ctrl+a`` / ``ctrl+v`` / ``ctrl+c`` / ``ctrl+x``
        以及 ``backspace`` / ``delete`` / ``enter`` 单键。
        """
        Q = self._quartz()
        # 1) 翻译修饰键
        translated = []
        for k in keys:
            kl = k.lower()
            if kl == "ctrl":
                translated.append("cmd")
            else:
                translated.append(kl)

        keycode_map = {
            "a": 0,
            "c": 8,
            "v": 9,
            "x": 7,
            "backspace": 51,
            "delete": 117,
            "enter": 36,
            "return": 36,
            "escape": 53,
        }
        # 字符键
        char_keys = [k for k in translated if k in keycode_map]
        if not char_keys:
            return
        key_char = char_keys[-1]
        keycode = keycode_map[key_char]

        # 修饰键 flag
        flag = 0
        if "cmd" in translated:
            flag |= Q.kCGEventFlagMaskCommand
        if "shift" in translated:
            flag |= Q.kCGEventFlagMaskShift
        if "alt" in translated:
            flag |= Q.kCGEventFlagMaskAlternate

        event = Q.CGEventCreateKeyboardEvent(None, keycode, True)
        Q.CGEventSetFlags(event, flag)
        Q.CGEventPost(Q.kCGHIDEventTap, event)
        event_up = Q.CGEventCreateKeyboardEvent(None, keycode, False)
        Q.CGEventSetFlags(event_up, flag)
        Q.CGEventPost(Q.kCGHIDEventTap, event_up)

    def paste_text(self, text: str) -> None:
        AppKit = self._appkit()
        pb = AppKit.NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(text, AppKit.NSPasteboardTypeString)
        self.hotkey("cmd", "v")

    def clear_field(self) -> None:
        self.hotkey("cmd", "a")
        # 单独按一次 delete
        Q = self._quartz()
        for down in (True, False):
            ev = Q.CGEventCreateKeyboardEvent(None, 51, down)  # backspace
            Q.CGEventPost(Q.kCGHIDEventTap, ev)


# ---------------------------------------------------------------------------
# OcrAdapter
# ---------------------------------------------------------------------------


class MacOcrAdapter:
    """基于 Vision.VNRecognizeTextRequest 的本地 OCR + macOS 环境感知。"""

    def screenshot(self, region: Tuple[int, int, int, int]) -> Any:
        # pyautogui 在 macOS 上有 Quartz 实现；保持跨平台一致。
        import pyautogui

        return pyautogui.screenshot(region=region)

    def get_dpi_scale(self, handle: Optional[WindowHandle] = None) -> float:
        try:
            import AppKit  # type: ignore

            screen = AppKit.NSScreen.mainScreen()
            return float(screen.backingScaleFactor())
        except Exception:
            return 1.0

    def get_theme(self) -> Literal["light", "dark"]:
        try:
            import Foundation  # type: ignore

            defaults = Foundation.NSUserDefaults.standardUserDefaults()
            style = defaults.stringForKey_("AppleInterfaceStyle")
            return "dark" if style == "Dark" else "light"
        except Exception:
            return "light"

    def is_locked(self) -> bool:
        try:
            import Quartz  # type: ignore

            session = Quartz.CGSessionCopyCurrentDictionary()
            if session is None:
                return True
            locked = session.get("CGSSessionScreenIsLocked", False)
            on_console = session.get("kCGSSessionOnConsoleKey", True)
            return bool(locked) or not bool(on_console)
        except Exception:
            return False

    def recognize(self, image: Any, lang_tag: str = "") -> List[OcrWord]:
        try:
            return _vision_recognize(image, lang_tag)
        except Exception as exc:  # pragma: no cover
            import traceback

            print(f"[MacOcrAdapter] OCR failed: {exc}", flush=True)
            traceback.print_exc()
            return []

    def detect_app_language(self, handle: Optional[WindowHandle] = None) -> str:
        # macOS 微信跟随系统语言；读 AppleLanguages 第一项。
        try:
            import Foundation  # type: ignore

            defaults = Foundation.NSUserDefaults.standardUserDefaults()
            langs = defaults.arrayForKey_("AppleLanguages") or []
            if langs:
                first = str(langs[0])
                # 形如 "zh-Hans-CN" → 归一化到 "zh-CN"
                if first.startswith("zh-Hans"):
                    return "zh-CN"
                if first.startswith("zh-Hant"):
                    return "zh-TW"
                if first.startswith("en"):
                    return "en-US"
                return first
        except Exception:
            pass
        return "zh-CN"

    def enable_dpi_awareness(self) -> bool:
        # macOS 自动处理 Retina；适配器只需返回 True 表示"已生效"。
        return sys.platform == "darwin"


def _vision_recognize(image: Any, lang_tag: str = "") -> List[OcrWord]:
    """调用 Vision.framework 同步识别文本块。

    输入 ``image`` 应为 PIL Image 或 numpy.ndarray；输出坐标系
    已转换为图像左上原点（与 pyautogui 截图一致）。
    """
    import Quartz  # type: ignore
    import Vision  # type: ignore
    import numpy as np
    import cv2
    from Foundation import NSData  # type: ignore

    # 1) 统一到 PNG 字节流，喂 NSData → CGImage
    if type(image).__name__ == "Image":
        # PIL Image
        import io

        buf = io.BytesIO()
        image.save(buf, format="PNG")
        data = buf.getvalue()
        img_w, img_h = image.size
    else:
        arr = image
        if arr.ndim == 3 and arr.shape[2] == 3:
            arr = cv2.cvtColor(arr, cv2.COLOR_BGR2RGBA)
        success, png = cv2.imencode(".png", arr)
        if not success:
            return []
        data = png.tobytes()
        img_h, img_w = arr.shape[:2]

    ns_data = NSData.dataWithBytes_length_(data, len(data))
    source = Quartz.CGImageSourceCreateWithData(ns_data, None)
    if source is None:
        return []
    cg_image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    if cg_image is None:
        return []

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
        cg_image, None
    )
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    # 中英繁三语优先
    langs = []
    if lang_tag:
        langs.append(lang_tag.replace("zh-CN", "zh-Hans").replace("zh-TW", "zh-Hant"))
    langs.extend(["zh-Hans", "zh-Hant", "en-US"])
    # 去重保序
    seen = set()
    unique_langs = [l for l in langs if not (l in seen or seen.add(l))]
    request.setRecognitionLanguages_(unique_langs)
    request.setUsesLanguageCorrection_(True)

    success, error = handler.performRequests_error_([request], None)
    if not success:
        return []

    observations = request.results() or []
    results: List[OcrWord] = []
    for obs in observations:
        candidates = obs.topCandidates_(1)
        if not candidates:
            continue
        text = str(candidates[0].string())
        bbox = obs.boundingBox()  # 归一化坐标，原点左下
        nx, ny = bbox.origin.x, bbox.origin.y
        nw, nh = bbox.size.width, bbox.size.height
        # 还原到图像像素坐标（左上原点）
        x = int(nx * img_w)
        width = int(nw * img_w)
        height = int(nh * img_h)
        y = int((1.0 - ny - nh) * img_h)
        results.append(OcrWord(text=text, x=x, y=y, width=width, height=height))
    return results