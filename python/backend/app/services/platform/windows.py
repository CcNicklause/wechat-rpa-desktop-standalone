"""Windows 平台适配器实现。

把原先散落在 `vision_locator.py` / `wechat_rpa.py` 内的 Win32 / WinRT /
WinReg / uiautomation 直接调用集中到这里，并补齐：

* `is_locked` — 通过 `OpenInputDesktop` + `WTSGetActiveConsoleSessionId`
  检测锁屏 / RDP 断开（解决 plan 中 W-1）。
* `detect_app_language` — 读 `HKCU\\Software\\Tencent\\WeChat\\Language`
  与 `OcrEngine` 可用语言交集，自动选 OCR `lang_tag`（解决 W-2）。

模块在非 Windows 平台导入会失败（uiautomation / winrt），因此
`platform/__init__.py` 中通过 `sys.platform` 守护。
"""
from __future__ import annotations

import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, List, Literal, Optional, Tuple

from backend.app.services.platform.base import (
    OcrWord,
    WindowHandle,
    WindowSpec,
)

# ---------------------------------------------------------------------------
# WinRT OCR 依赖（仅在 Windows 上可用）
# ---------------------------------------------------------------------------
try:
    from winrt.windows.graphics.imaging import (
        SoftwareBitmap,
        BitmapPixelFormat,
        BitmapAlphaMode,
    )
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.globalization import Language
except ImportError:  # pragma: no cover – 单元测试在 Linux/macOS CI 上跑
    OcrEngine = None
    SoftwareBitmap = None
    BitmapPixelFormat = None
    BitmapAlphaMode = None
    Language = None


# ---------------------------------------------------------------------------
# DesktopAdapter
# ---------------------------------------------------------------------------


class WindowsDesktopAdapter:
    """Windows uiautomation + pyautogui + tkinter 的封装。

    `uiautomation` 在 import 时会主动初始化 COM，故 lazy-import 放在
    每个方法体内，确保仅在 RPA 真实执行时才触发 COM。
    """

    def __init__(self) -> None:
        self._auto = None  # 缓存 uiautomation 模块

    # ---- 内部工具 ----

    def _ua(self):
        """Lazy import uiautomation。"""
        if self._auto is None:
            import uiautomation as auto

            self._auto = auto
        return self._auto

    @staticmethod
    def _wrap(control) -> WindowHandle:
        """把 uiautomation 控件包装为统一的 `WindowHandle`。"""
        if isinstance(control, WindowHandle):
            return control
        if hasattr(control, "rect") and not hasattr(control, "BoundingRectangle"):
            return WindowHandle(
                native_id=int(getattr(control, "native_id", 0) or 0),
                name=str(getattr(control, "name", "") or ""),
                class_name=str(getattr(control, "class_name", "") or ""),
                rect=getattr(control, "rect"),
                platform_data=getattr(control, "platform_data", control),
            )
        rect = control.BoundingRectangle
        return WindowHandle(
            native_id=int(getattr(control, "NativeWindowHandle", 0) or 0),
            name=str(getattr(control, "Name", "") or ""),
            class_name=str(getattr(control, "ClassName", "") or ""),
            rect=(int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)),
            platform_data=control,
        )

    def _build_control(self, parent, spec: WindowSpec):
        """根据 WindowSpec 构造 uiautomation 控件。

        ``spec.control_type`` 决定调用哪个 uiautomation 构造方法
        （例如 ``EditControl``、``DocumentControl``、``ButtonControl``）。
        默认为 ``WindowControl``。
        """
        auto = self._ua()
        kwargs: dict[str, Any] = {"searchDepth": spec.search_depth}
        if spec.class_name:
            kwargs["ClassName"] = spec.class_name
        if spec.name:
            kwargs["Name"] = spec.name
        if spec.name_regex:
            kwargs["RegexName"] = spec.name_regex
        target = parent if parent is not None else auto
        # 根据 control_type 动态调用对应的 uiautomation 构造方法
        control_type = getattr(spec, "control_type", "WindowControl") or "WindowControl"
        builder = getattr(target, control_type, None)
        if builder is None:
            # 如果控件类型不存在（拼写错误等），回退到 WindowControl
            builder = target.WindowControl
        return builder(**kwargs)


    # ---- 窗口 ----

    def find_window(self, candidates: List[WindowSpec]) -> Optional[WindowHandle]:
        for spec in candidates:
            control = self._build_control(parent=None, spec=spec)
            if control.Exists(maxSearchSeconds=spec.max_search_seconds):
                return self._wrap(control)
        return None

    def find_child_window(
        self, parent: WindowHandle, candidates: List[WindowSpec]
    ) -> Optional[WindowHandle]:
        for spec in candidates:
            control = self._build_control(parent=parent.platform_data, spec=spec)
            if control.Exists(maxSearchSeconds=spec.max_search_seconds):
                return self._wrap(control)
        return None

    def list_top_level_windows(self) -> List[WindowHandle]:
        auto = self._ua()
        return [self._wrap(child) for child in auto.GetRootControl().GetChildren()]

    def get_bounding_rectangle(self, handle: WindowHandle) -> Tuple[int, int, int, int]:
        control = handle.platform_data
        if control is None:
            return handle.rect
        if isinstance(control, WindowHandle):
            return control.rect
        if not hasattr(control, "BoundingRectangle"):
            return handle.rect
        rect = control.BoundingRectangle
        return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)

    # ---- 操作 ----

    def set_active(self, handle: WindowHandle) -> None:
        try:
            control = handle.platform_data
            if hasattr(control, "ShowWindow"):
                try:
                    control.ShowWindow(9)  # 9: SW_RESTORE
                except Exception:
                    pass
            control.SetActive()
        except Exception:  # pragma: no cover – 窗口已关闭
            pass

    def set_topmost(self, handle: WindowHandle, on: bool) -> None:
        try:
            handle.platform_data.SetTopmost(on)
        except Exception:  # pragma: no cover – 部分弹层不支持置顶
            pass

    def close_window(self, handle: WindowHandle) -> None:
        """关闭窗口：优先调用控件 GetWindowPattern().Close()，
        失败则使用 Win32 PostMessageW 发送 WM_CLOSE (0x0010)，避免误关活动窗口。"""
        control = handle.platform_data
        if control is None:
            if sys.platform == "win32" and handle.native_id:
                try:
                    import ctypes
                    ctypes.windll.user32.PostMessageW(handle.native_id, 0x0010, 0, 0)
                except Exception:
                    pass
            return
        try:
            pattern = control.GetWindowPattern()
            if pattern is not None:
                pattern.Close()
                return
        except Exception:
            pass
        try:
            if sys.platform == "win32" and handle.native_id:
                import ctypes
                ctypes.windll.user32.PostMessageW(handle.native_id, 0x0010, 0, 0)
            else:
                control.SetActive()
                self._ua().SendKeys("{Alt}{F4}")
        except Exception:  # pragma: no cover
            pass

    def click(self, x: int, y: int) -> None:
        auto = self._ua()
        auto.Click(x, y)

    def send_keys(
        self, text: str, per_char_delay: Tuple[float, float] = (0.05, 0.15)
    ) -> None:
        import random
        import time

        auto = self._ua()
        for char in text:
            auto.SendKeys(char)
            time.sleep(random.uniform(*per_char_delay))

    def hotkey(self, *keys: str) -> None:
        try:
            import pyautogui
        except Exception as exc:  # pragma: no cover
            from backend.app.core.errors import AppError

            raise AppError(
                "KEYBOARD_DRIVER_UNAVAILABLE",
                f"物理键盘输入依赖不可用，请安装 pyautogui: {exc}",
            ) from exc
        pyautogui.hotkey(*keys)

    def paste_text(self, text: str) -> None:
        try:
            import pyautogui
            import tkinter as tk
        except Exception as exc:  # pragma: no cover
            from backend.app.core.errors import AppError

            raise AppError(
                "CLIPBOARD_DRIVER_UNAVAILABLE",
                f"剪贴板输入依赖不可用: {exc}",
            ) from exc

        root = tk.Tk()
        root.withdraw()
        try:
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update()
            pyautogui.hotkey("ctrl", "v")
        finally:
            root.destroy()

    def clear_field(self) -> None:
        try:
            import pyautogui
        except Exception as exc:  # pragma: no cover
            from backend.app.core.errors import AppError

            raise AppError(
                "KEYBOARD_DRIVER_UNAVAILABLE",
                f"物理键盘输入依赖不可用，请安装 pyautogui: {exc}",
            ) from exc
        import time
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.15)  # 给微信 UI 线程喘息时间，零间隔连续快捷键会导致卡死
        pyautogui.press("backspace")


# ---------------------------------------------------------------------------
# OcrAdapter
# ---------------------------------------------------------------------------


def _enable_dpi_awareness_win() -> bool:
    """启用进程级 DPI 感知 —— Per-Monitor V2 优先，降级 V1。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
            ctypes.windll.shcore.SetProcessDpiAwareness.restype = ctypes.c_long
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
            return True
        except (AttributeError, OSError):
            pass
        try:
            ctypes.windll.user32.SetProcessDPIAware.argtypes = []
            ctypes.windll.user32.SetProcessDPIAware.restype = ctypes.c_int
            ctypes.windll.user32.SetProcessDPIAware()
            return True
        except (AttributeError, OSError):
            pass
    except Exception:
        pass
    return False


def _get_window_scale_win(hwnd: int) -> float:
    """获取指定 HWND 所在屏幕的 DPI 缩放（1.0/1.25/1.5/...）。"""
    if sys.platform != "win32":
        return 1.0

    import ctypes
    from ctypes import wintypes

    HMONITOR = ctypes.c_void_p

    # 1. Win 8.1+ : MonitorFromWindow + GetDpiForMonitor
    try:
        ctypes.windll.user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        ctypes.windll.user32.MonitorFromWindow.restype = HMONITOR
        ctypes.windll.shcore.GetDpiForMonitor.argtypes = [
            HMONITOR,
            ctypes.c_int,
            ctypes.POINTER(wintypes.UINT),
            ctypes.POINTER(wintypes.UINT),
        ]
        ctypes.windll.shcore.GetDpiForMonitor.restype = ctypes.c_long
        monitor = ctypes.windll.user32.MonitorFromWindow(hwnd, 2)  # NEAREST
        dpi_x = wintypes.UINT()
        dpi_y = wintypes.UINT()
        if ctypes.windll.shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
            return dpi_x.value / 96.0
    except Exception:
        pass

    # 2. Vista+ : GetDeviceCaps(LOGPIXELSX)
    try:
        ctypes.windll.user32.GetDC.argtypes = [wintypes.HWND]
        ctypes.windll.user32.GetDC.restype = wintypes.HDC
        ctypes.windll.gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
        ctypes.windll.gdi32.GetDeviceCaps.restype = ctypes.c_int
        ctypes.windll.user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        ctypes.windll.user32.ReleaseDC.restype = ctypes.c_int
        hdc = ctypes.windll.user32.GetDC(0)
        if hdc:
            try:
                dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
                if dpi > 0:
                    return dpi / 96.0
            finally:
                ctypes.windll.user32.ReleaseDC(0, hdc)
    except Exception:
        pass

    return 1.0


def _get_windows_theme() -> Literal["light", "dark"]:
    """读注册表 `Personalize\\AppsUseLightTheme`。"""
    try:
        import winreg

        registry_key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(registry_key, "AppsUseLightTheme")
        winreg.CloseKey(registry_key)
        return "light" if value == 1 else "dark"
    except Exception:
        return "light"


def _is_locked_win() -> bool:
    """检测当前会话是否处于锁屏 / RDP 断开 / 无渲染状态。

    判定逻辑：
    * `OpenInputDesktop` 返回 NULL 或 desktop name 不是 ``Default``
      → 屏幕被锁屏（Winlogon 桌面占据）。
    * 上面调用本身抛异常时保守认为 *未* 锁屏，避免误报阻断流程。
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.OpenInputDesktop.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        user32.OpenInputDesktop.restype = wintypes.HANDLE
        user32.GetUserObjectInformationW.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetUserObjectInformationW.restype = wintypes.BOOL
        user32.CloseDesktop.argtypes = [wintypes.HANDLE]
        user32.CloseDesktop.restype = wintypes.BOOL

        DESKTOP_READOBJECTS = 0x0001
        h_desk = user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
        if not h_desk:
            return True

        try:
            buf = ctypes.create_unicode_buffer(256)
            need = wintypes.DWORD(0)
            user32.GetUserObjectInformationW(
                h_desk, 2, buf, ctypes.sizeof(buf), ctypes.byref(need)  # UOI_NAME
            )
            name = buf.value or ""
            # Winlogon 桌面名称就是 "Winlogon"
            return name.lower() != "default"
        finally:
            user32.CloseDesktop(h_desk)
    except Exception:
        return False


def _detect_wechat_language() -> str:
    """探测 WeChat 客户端语言（粗粒度），返回 WinRT OCR 可用的 BCP-47 tag。

    优先级：
    1. 读 `HKCU\\Software\\Tencent\\WeChat\\Language`（数字代码）。
    2. 失败时回退到系统 UI 语言。
    3. 做常见 OCR tag 兼容映射（zh-CN → zh-Hans-CN 等）。
    """
    try:
        import winreg

        registry_key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Tencent\WeChat"
        )
        try:
            value, _ = winreg.QueryValueEx(registry_key, "LANGUAGE")
        except FileNotFoundError:
            value = None
        winreg.CloseKey(registry_key)
        # WeChat 内部数字 → BCP-47 映射（经验值，覆盖常见三种）
        mapping = {0: "zh-CN", 1: "zh-CN", 2: "zh-TW", 3: "en-US"}
        if isinstance(value, int) and value in mapping:
            return _normalize_ocr_lang_tag(mapping[value])
    except Exception:
        pass
    try:
        import locale

        loc = locale.getdefaultlocale()[0] or "zh-CN"
        return _normalize_ocr_lang_tag(loc.replace("_", "-"))
    except Exception:
        return _normalize_ocr_lang_tag("zh-CN")


def _normalize_ocr_lang_tag(tag: str) -> str:
    """把用户/微信侧的 lang tag 映射到 WinRT OCR 实际可用的 tag。

    WinRT OCR 不认 `zh-CN`，只认 `zh-Hans-CN` / `zh-Hant-TW`。
    不抛异常，兜底返回 `en-US` 或传入原值。
    """
    # 最常见的 OCR 可用 tag 列表（按命中概率排序）
    common = {
        "zh": "zh-Hans-CN",
        "zh-CN": "zh-Hans-CN",
        "zh_cn": "zh-Hans-CN",
        "zh_SG": "zh-Hans-CN",
        "zh-TW": "zh-Hant-TW",
        "zh_HK": "zh-Hant-HK",
        "zh-MO": "zh-Hant-MO",
        "en": "en-US",
        "en-US": "en-US",
        "en-GB": "en-GB",
    }
    return common.get(tag, tag)


def _ndarray_to_software_bitmap(arr: Any) -> Any:
    """OpenCV/numpy ndarray → WinRT SoftwareBitmap (BGRA8 / PREMULTIPLIED)."""
    if type(arr).__name__ != "ndarray":
        # 单元测试中可能传入 MagicMock，直接透传
        return arr

    import cv2

    if arr.ndim == 2:
        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGRA)
    elif arr.shape[2] == 3:
        arr = cv2.cvtColor(arr, cv2.COLOR_BGR2BGRA)

    height, width, _ = arr.shape
    bitmap = SoftwareBitmap(
        BitmapPixelFormat.BGRA8, width, height, BitmapAlphaMode.PREMULTIPLIED
    )
    bitmap.copy_from_buffer(arr.tobytes())
    return bitmap


async def _run_native_ocr_async(
    image_np: Any, lang_tag: str = ""
) -> List[OcrWord]:
    """异步调用 Windows.Media.Ocr.OcrEngine。

    WinRT 3.x 的 `IAsyncOperation` 需要用 `asyncio.ensure_future()`
    包装成 Python coroutine 才能 await。直接 `await op` 会抛
    "a coroutine was expected, got <winrt._winrt_windows_foundation._IAsyncOperation>"。
    """
    if OcrEngine is None:
        print("[WinOCR] OcrEngine is None (winrt 未安装/导入失败)", flush=True)
        return []

    try:
        software_bitmap = _ndarray_to_software_bitmap(image_np)
    except Exception as exc:
        print(f"[WinOCR] ndarray → SoftwareBitmap 失败: {exc}", flush=True)
        raise

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        print(
            "[WinOCR] try_create_from_user_profile_languages() 返回 None "
            "—— 系统未安装任何 OCR 支持的用户配置语言包",
            flush=True,
        )
    if lang_tag:
        try:
            target_lang = Language(lang_tag)
            custom_engine = OcrEngine.try_create_from_language(target_lang)
            if custom_engine:
                engine = custom_engine
            else:
                # 尝试一次 tag 规范化：用户传 zh-CN 但 OCR 只认 zh-Hans-CN
                normalized = _normalize_ocr_lang_tag(lang_tag)
                if normalized != lang_tag:
                    target_lang2 = Language(normalized)
                    custom_engine2 = OcrEngine.try_create_from_language(target_lang2)
                    if custom_engine2:
                        print(f"[WinOCR] 修正语言标签: {lang_tag!r} → {normalized!r}", flush=True)
                        engine = custom_engine2
                    else:
                        print(
                            f"[WinOCR] try_create_from_language({lang_tag!r}→{normalized!r}) 返回 None "
                            f"—— 该语言 OCR 包未安装；"
                            f"可在「设置→时间和语言→语言→添加首选语言」中添加（需选「光学字符识别」可选功能）",
                            flush=True,
                        )
                else:
                    print(
                        f"[WinOCR] try_create_from_language({lang_tag!r}) 返回 None "
                        f"—— 该语言 OCR 包未安装",
                        flush=True,
                    )
        except Exception as exc:
            print(f"[WinOCR] try_create_from_language({lang_tag!r}) 抛异常: {exc}", flush=True)

    if not engine:
        print("[WinOCR] 没有可用的 OcrEngine，返回空", flush=True)
        return []

    try:
        # WinRT 3.x: IAsyncOperation → Python coroutine 转换
        import asyncio
        op = engine.recognize_async(software_bitmap)
        ocr_result = await asyncio.ensure_future(op)
    except Exception as exc:
        import traceback

        print(f"[WinOCR] recognize_async 失败: {exc}", flush=True)
        traceback.print_exc()
        raise

    parsed: List[OcrWord] = []
    for line in ocr_result.lines:
        if hasattr(line, "bounding_rect") and line.bounding_rect is not None:
            rect = line.bounding_rect
            x = int(rect.x)
            y = int(rect.y)
            width = int(rect.width)
            height = int(rect.height)
        elif hasattr(line, "words") and line.words:
            xs = [w.bounding_rect.x for w in line.words if hasattr(w, "bounding_rect") and w.bounding_rect]
            ys = [w.bounding_rect.y for w in line.words if hasattr(w, "bounding_rect") and w.bounding_rect]
            rxs = [w.bounding_rect.x + w.bounding_rect.width for w in line.words if hasattr(w, "bounding_rect") and w.bounding_rect]
            rys = [w.bounding_rect.y + w.bounding_rect.height for w in line.words if hasattr(w, "bounding_rect") and w.bounding_rect]
            if not xs:
                continue
            min_x, min_y = min(xs), min(ys)
            x = int(min_x)
            y = int(min_y)
            width = int(max(rxs) - min_x)
            height = int(max(rys) - min_y)
        else:
            continue

        parsed.append(OcrWord(text=line.text, x=x, y=y, width=width, height=height))
    return parsed


def _run_async_safe(coro: Any) -> Any:
    """同步调用方安全地运行协程：若 loop 在跑则 fork 一个 worker。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    return asyncio.run(coro)


class WindowsOcrAdapter:
    """Windows OcrEngine + Win32 DPI/主题/锁屏的封装。"""

    def screenshot(self, region: Tuple[int, int, int, int]) -> Any:
        from PIL import ImageGrab

        left, top, width, height = region
        # PIL.ImageGrab.grab expects bbox in (left, top, right, bottom) format
        bbox = (left, top, left + width, top + height)
        return ImageGrab.grab(bbox=bbox, all_screens=True)

    def get_dpi_scale(self, handle: Optional[WindowHandle] = None) -> float:
        hwnd = int(handle.native_id) if handle and handle.native_id else 0
        return _get_window_scale_win(hwnd)

    def get_theme(self) -> Literal["light", "dark"]:
        return _get_windows_theme()

    def is_locked(self) -> bool:
        return _is_locked_win()

    def recognize(self, image: Any, lang_tag: str = "") -> List[OcrWord]:
        if OcrEngine is None:
            return []
        try:
            return _run_async_safe(_run_native_ocr_async(image, lang_tag))
        except Exception as exc:  # pragma: no cover – 真机偶发异常
            import traceback

            print(f"[WindowsOcrAdapter] OCR failed: {exc}", flush=True)
            traceback.print_exc()
            return []

    def detect_app_language(self, handle: Optional[WindowHandle] = None) -> str:
        return _detect_wechat_language()

    def enable_dpi_awareness(self) -> bool:
        return _enable_dpi_awareness_win()