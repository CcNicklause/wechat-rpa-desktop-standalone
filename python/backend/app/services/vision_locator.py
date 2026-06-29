"""微信 RPA 视觉定位器（跨平台 v2）。

本模块负责把"视觉缓存 → 边缘骨架 → 自适应二值化 → 本地 OCR
→ 多尺度模板"五轨自愈定位策略串成一个 `find_first` 入口。

与 v1 相比的主要变化：

* 所有 Win32 / WinRT / Vision.framework 调用都通过
  ``backend.app.services.platform`` 适配器间接发起，不再硬编码 ``ctypes`` /
  ``winrt``，从而支持 macOS。
* 引入 :class:`SystemContext` 一次性快照运行环境（替代散落的 DPI / 主题 /
  锁屏 / 语言判断）。
* 新增 :func:`match_template_binary` —— Canny 失败时再降一级到自适应
  二值化骨架匹配（解决 plan W-3）。
* OCR 文本匹配在 substring 命中之外，新增 ``rapidfuzz.partial_ratio``
  容错（解决 plan W-4），且对系统 / 应用语言探测的 ``lang_tag``
  传给原生 OCR 引擎（解决 W-2）。
* 锁屏 / RDP 断开时直接抛 ``VISION_LOCKED_SCREEN``，不再耗时跑完三轨
  （解决 W-1）。

向后兼容保留的模块级符号（被现有测试与 ``wechat_rpa.py`` import）：

* :func:`enable_dpi_awareness` / :func:`get_window_scale` /
  :func:`get_windows_theme` —— 仍是模块级函数，内部委托给当前平台 OCR
  适配器；Windows 上行为与 v1 完全一致。
* :data:`OcrEngine` —— Windows-only 全局符号；用于现有单测仅检测
  "OCR 是否可用"。在 Windows 上等价于 ``winrt.windows.media.ocr.OcrEngine``，
  其它平台为 ``None``。
* :data:`OCR_INTENT_MAP` —— 模板名 → 多语言关键词清单。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from backend.app.core.errors import AppError
from backend.app.services.platform import (
    OcrWord,
    SystemContext,
    WindowHandle,
    get_desktop_adapter,
    get_ocr_adapter,
)

# 维持 v1 公开符号：单测 / 直接 import 该名字的代码继续可用。
try:  # pragma: no cover - import-time branch only
    from winrt.windows.media.ocr import OcrEngine  # type: ignore
except ImportError:  # pragma: no cover
    OcrEngine = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 向后兼容的模块级薄包装
# ---------------------------------------------------------------------------


def enable_dpi_awareness() -> bool:
    """启用 DPI 感知（委托给当前平台 OCR 适配器）。"""
    return get_ocr_adapter().enable_dpi_awareness()


def get_window_scale(hwnd: int) -> float:
    """获取窗口缩放（接受裸 HWND/PID 以兼容 v1 测试与调用方）。"""
    handle = WindowHandle(native_id=int(hwnd) if hwnd else 0)
    try:
        return get_ocr_adapter().get_dpi_scale(handle)
    except Exception:
        return 1.0


def get_windows_theme() -> str:
    """获取当前主题（"light" / "dark"，委托给适配器）。"""
    return get_ocr_adapter().get_theme()


# ---------------------------------------------------------------------------
# 图像处理工具 —— 平台无关
# ---------------------------------------------------------------------------


def compute_ssim(img1: Any, img2: Any) -> float:
    """手写 Gaussian SSIM，避免引入 scikit-image。"""
    import cv2
    import numpy as np

    if img1.shape != img2.shape:
        img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))

    img1 = img1.astype(np.float64)
    img2 = img2.astype(np.float64)

    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2
    kernel = (11, 11)
    sigma = 1.5

    mu1 = cv2.GaussianBlur(img1, kernel, sigma)
    mu2 = cv2.GaussianBlur(img2, kernel, sigma)
    mu1_sq = mu1 ** 2
    mu2_sq = mu2 ** 2
    mu1_mu2 = mu1 * mu2

    sigma1_sq = cv2.GaussianBlur(img1 ** 2, kernel, sigma) - mu1_sq
    sigma2_sq = cv2.GaussianBlur(img2 ** 2, kernel, sigma) - mu2_sq
    sigma12 = cv2.GaussianBlur(img1 * img2, kernel, sigma) - mu1_mu2

    ssim_map = ((2 * mu1_mu2 + C1) * (2 * sigma12 + C2)) / (
        (mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2)
    )
    return float(ssim_map.mean())


def match_template_edge(
    gray_source: Any, gray_template: Any, threshold: float = 0.6
) -> Optional[Tuple[float, Tuple[int, int], Tuple[int, int]]]:
    """Canny 边缘骨架匹配 —— 去 ClearType 彩色伪影。"""
    import cv2

    try:
        edge_source = cv2.Canny(gray_source, 50, 150)
        edge_template = cv2.Canny(gray_template, 50, 150)
        res = cv2.matchTemplate(edge_source, edge_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val >= threshold:
            th, tw = gray_template.shape[:2]
            return float(max_val), max_loc, (tw, th)
    except Exception:
        pass
    return None


def match_template_binary(
    gray_source: Any, gray_template: Any, threshold: float = 0.55
) -> Optional[Tuple[float, Tuple[int, int], Tuple[int, int]]]:
    """自适应二值化匹配 —— Canny 断裂时的 Plan B（解决 plan W-3）。

    对小文字 / 低对比场景，自适应阈值能比 Canny 保留更完整的笔画。
    """
    import cv2

    try:
        bin_source = cv2.adaptiveThreshold(
            gray_source,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            5,
        )
        bin_template = cv2.adaptiveThreshold(
            gray_template,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            5,
        )
        res = cv2.matchTemplate(bin_source, bin_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val >= threshold:
            th, tw = gray_template.shape[:2]
            return float(max_val), max_loc, (tw, th)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 模糊文本匹配 —— rapidfuzz + substring（解决 plan W-4）
# ---------------------------------------------------------------------------


def _strip_spaces(s: str) -> str:
    return "".join(s.split())


def fuzzy_text_hit(
    item_text: str, keywords: Sequence[str], min_ratio: int = 80
) -> Optional[str]:
    """先做空格不敏感的子串匹配；命中则原样返回 keyword。

    若子串失败，再用 rapidfuzz.partial_ratio 做容错匹配
    （应对 OCR 拼错，如 ``Add Frlends`` → ``Add Friends``）。
    """
    clean_text = _strip_spaces(item_text).lower()
    for kw in keywords:
        clean_kw = _strip_spaces(kw).lower()
        if clean_kw and clean_kw in clean_text:
            return kw

    try:
        from rapidfuzz import fuzz

        best_score = 0
        best_kw: Optional[str] = None
        for kw in keywords:
            clean_kw = _strip_spaces(kw).lower()
            if not clean_kw:
                continue
            # 长度守卫：partial_ratio 会将较短串滑过较长串做最优对齐。
            # 当 OCR 文本远短于关键词时（如"搜索"2字 vs "搜索结果为空"6字），
            # 它回答的是"OCR文本是否出现在关键词里"——方向反了，极易假阳性。
            # 要求 OCR 文本至少达到关键词长度的 50%，才允许模糊匹配。
            if len(clean_text) < len(clean_kw) * 0.5:
                continue
            score = fuzz.partial_ratio(clean_kw, clean_text)
            if score > best_score:
                best_score = score
                best_kw = kw
        if best_kw is not None and best_score >= min_ratio:
            return best_kw
    except ImportError:
        # rapidfuzz 未安装时仅做 substring 匹配
        pass
    return None


# ---------------------------------------------------------------------------
# 意图映射
# ---------------------------------------------------------------------------


OCR_INTENT_MAP: dict[str, List[str]] = {
    "wechat_add_button": ["添加", "＋", "+"],
    "wechat_plus_button": ["添加", "＋", "+"],
    "wechat_toolbar_add": ["添加", "＋", "+"],
    "menu_add_friends": ["添加朋友", "添加好友", "加好友", "Add Friends", "新增好友", "添加"],
    "add_friends_menu_item": ["添加朋友", "添加好友", "加好友", "Add Friends", "新增好友", "添加"],
    "add_friends_search_box": ["搜索", "微信号/手机号", "微信号", "手机号", "Search"],
    "wechat_search_box": ["搜索", "微信号/手机号", "微信号", "手机号", "Search"],
    "search_input": ["搜索", "微信号/手机号", "微信号", "手机号", "Search"],
    "add_to_contacts_button": ["添加到通讯录", "添加好友", "Add to Contacts", "添加到通訊錄"],
    "add_friend_button": ["添加到通讯录", "添加好友", "Add to Contacts", "添加到通訊錄"],
    "add_contact_button": ["添加到通讯录", "添加好友", "Add to Contacts", "添加到通訊錄"],
    "verify_message_input": ["发送朋友验证申请", "发送添加朋友申请", "申请添加朋友", "发送朋友验证", "申请添加", "验证申请", "朋友申请", "验证消息"],
    "friend_verify_input": ["发送朋友验证申请", "发送添加朋友申请", "申请添加朋友", "发送朋友验证", "申请添加", "验证申请", "朋友申请", "验证消息"],
    "send_button": ["确定", "发送", "確定", "傳送", "Send", "OK"],
    "confirm_button": ["确定", "发送", "確定", "傳送", "Send", "OK"],
    "verify_confirm_button": ["确定", "发送", "確定", "傳送", "Send", "OK"],
}


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MatchResult:
    template_name: str
    center_x: int
    center_y: int
    score: float


# ---------------------------------------------------------------------------
# VisionLocator
# ---------------------------------------------------------------------------


class VisionLocator:
    """五轨自愈定位器。

    优先级：``缓存(1.0 倍)`` → ``缓存边缘`` → ``缓存自适应二值化``
    → ``本地 OCR + rapidfuzz`` → ``多尺度 + 反色模板``。

    锁屏 / RDP 断开时直接抛 ``VISION_LOCKED_SCREEN``，不耗时跑后续轨。
    """

    def __init__(
        self,
        template_dir: Path | str | None = None,
        cache_dir: Path | str | None = None,
    ) -> None:
        from backend.app.core.paths import get_base_dir, get_data_dir
        
        if template_dir is None:
            self.template_dir = get_base_dir() / "backend" / "assets" / "wechat_templates"
        else:
            self.template_dir = Path(template_dir)
            
        if cache_dir is None:
            self.cache_dir = get_data_dir() / "templates_cache"
        else:
            self.cache_dir = Path(cache_dir)

        self.pending_cache = []

    def commit_cache(self) -> None:
        """将当前挂起的缓存截图写入磁盘文件。"""
        import cv2
        for cache_file, img in self.pending_cache:
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(cache_file), img)
            except Exception:
                pass
        self.pending_cache.clear()

    def clear_pending_cache(self) -> None:
        """清空未提交的挂起缓存。"""
        self.pending_cache.clear()

    def clean_cache_by_name(self, clean_name: str) -> None:
        """删除所有分辨率子目录下的特定缓存文件，实现坏缓存的清理自愈。"""
        import os
        try:
            if self.cache_dir.exists():
                for sub in self.cache_dir.iterdir():
                    if sub.is_dir():
                        cache_file = sub / f"{clean_name}.png"
                        if cache_file.exists():
                            os.remove(str(cache_file))
        except Exception:
            pass

    # ---- 顶层入口 ----

    def click_first(
        self,
        auto,
        window,
        template_names: Iterable[str],
        threshold: float = 0.78,
    ) -> MatchResult:
        match = self.find_first(auto, window, template_names, threshold=threshold)
        desktop = get_desktop_adapter()
        desktop.click(match.center_x, match.center_y)
        time.sleep(0.25)
        return match

    def find_first(
        self,
        auto,
        window,
        template_names: Iterable[str],
        threshold: float = 0.78,
    ) -> MatchResult:
        try:
            import cv2
            import numpy as np
        except Exception as exc:  # pragma: no cover - local desktop dependency
            raise AppError(
                "VISION_DRIVER_UNAVAILABLE",
                f"图像识别依赖不可用，请安装 opencv-python/pillow: {exc}",
            ) from exc

        ocr = get_ocr_adapter()
        ocr.enable_dpi_awareness()

        # ---- 锁屏 / RDP 提前断流 (W-1) ----
        if ocr.is_locked():
            raise AppError(
                "VISION_LOCKED_SCREEN",
                "屏幕已锁定或 RDP 会话已断开 / 最小化，无 GUI 渲染可用",
            )

        # ---- 取窗口外框 ----
        # 兼容两种入参：v1 的 uiautomation 控件（.BoundingRectangle / .NativeWindowHandle）
        # 与 v2 的 WindowHandle dataclass（.rect / .native_id / .platform_data）
        left, top, right, bottom = _window_rect(window)
        width = max(right - left, 1)
        height = max(bottom - top, 1)

        try:
            window_handle_id = _window_native_id(window)
        except Exception:
            window_handle_id = 0
        handle = WindowHandle(native_id=window_handle_id)
        try:
            base_scale = ocr.get_dpi_scale(handle)
        except Exception:
            base_scale = 1.0

        template_names = list(template_names)
        missing: list[str] = []
        unmatched: list[str] = []
        ocr_dump: list[str] = []  # Track 2 看到但没匹配上的 OCR 原文，用于失败诊断
        screenshot = None

        for attempt in range(3):
            # ---- 截屏 ----
            try:
                screenshot = ocr.screenshot((left, top, width, height))
                source = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
                gray_source = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
            except Exception as exc:
                if attempt == 2:
                    raise AppError("VISION_SCREENSHOT_FAILED", f"截屏失败: {exc}")
                time.sleep(0.35)
                continue

            # ---- 构造 SystemContext 快照 (W-5) ----
            try:
                import pyautogui
                screen_res = pyautogui.size()
            except Exception:
                screen_res = (1920, 1080)

            context = self._build_context(
                ocr=ocr,
                handle=handle,
                gray_source=gray_source,
                resolution=screen_res,
                dpi_scale=base_scale,
            )

            cache_sub_dir = (
                self.cache_dir
                / f"{context.resolution[0]}x{context.resolution[1]}_{context.dpi_scale}_{self._theme_tag(context)}"
            )

            # ---- Track 1: 视觉缓存（毫秒级快速通道） ----
            if not _is_frozen(gray_source):
                cache_result = self._try_cache_tracks(
                    cv2, gray_source, cache_sub_dir, template_names, left, top
                )
                if cache_result is not None:
                    return cache_result

            # ---- Track 2: 本地 OCR + rapidfuzz 自愈学习 ----
            if not _is_frozen(gray_source):
                ocr_result = self._try_ocr_track(
                    cv2=cv2,
                    ocr=ocr,
                    handle=handle,
                    source_bgr=source,
                    gray_source=gray_source,
                    cache_sub_dir=cache_sub_dir,
                    template_names=template_names,
                    left=left,
                    top=top,
                    width=width,
                    height=height,
                    context=context,
                    ocr_dump=ocr_dump,
                )
                if ocr_result is not None:
                    return ocr_result

            # ---- Track 3: 多尺度模板匹配（含反色 + 自学习写缓存） ----
            unmatched = []
            for template_name in template_names:
                template_path = self._template_path(template_name)
                if not template_path.exists():
                    if template_path.name not in missing:
                        missing.append(template_path.name)
                    continue
                match = self._match_template_on_image(
                    cv2, gray_source, template_path, base_scale, threshold, theme=self._theme_tag(context)
                )
                if match is not None:
                    try:
                        clean_name = (
                            template_name[:-4]
                            if template_name.lower().endswith(".png")
                            else template_name
                        )
                        cache_file = cache_sub_dir / f"{clean_name}.png"
                        cropped = gray_source[
                            match["y"] : match["y"] + match["th"],
                            match["x"] : match["x"] + match["tw"],
                        ]
                        if cropped.size > 0:
                            self.pending_cache.append((cache_file, cropped))
                    except Exception:
                        pass
                    return MatchResult(
                        template_name=template_path.name,
                        center_x=left + match["x"] + match["tw"] // 2,
                        center_y=top + match["y"] + match["th"] // 2,
                        score=match["score"],
                    )
                unmatched.append(f"{template_path.name}(score<{threshold})")

            if attempt < 2:
                time.sleep(0.35)

        # 失败：保存调试截图
        if screenshot is not None:
            try:
                import os

                os.makedirs("backend/data", exist_ok=True)
                screenshot.save("backend/data/error_screenshot.png")
            except Exception:
                pass

        details = []
        if missing:
            details.append("缺失: " + ", ".join(missing))
        if unmatched:
            details.append("未匹配: " + ", ".join(unmatched))
        if ocr_dump:
            # 取最后一次 OCR 看到的内容（截断 > 400 字符避免错误消息过长）
            raw = ocr_dump[-1]
            if len(raw) > 400:
                raw = raw[:397] + "..."
            details.append(f"OCR原文: {raw}")
        raise AppError(
            "VISION_TARGET_NOT_FOUND",
            "未能通过 UIA 或图像识别定位微信元素；" + "；".join(details or ["未提供模板"]),
        )

    def read_window_text(
        self,
        window,
        lang_tag: str = "",
        save_path: str | None = None,
    ) -> list[OcrWord]:
        """对窗口区域截屏并执行 OCR，返回所有识别词块。

        供 ``_detect_screen_state`` 读屏判定使用 —— 与 ``find_first`` 共用
        同一套截图 + OCR 适配器，不做模板匹配。

        Args:
            window: uiautomation 控件或 WindowHandle。
            lang_tag: OCR 语言标签；留空则由适配器自动探测应用语言。
            save_path: 若提供，把截图存到该路径用于留痕。

        Returns:
            识别出的 OcrWord 列表；锁屏 / 依赖缺失时返回空列表（不抛异常，
            交由调用方决定是否当作"无法判定"）。所有异常分支都通过
            ``[OCR READ ERROR]`` 前缀的 stderr 打印暴露真实原因，避免
            "截图明明有字、OCR_RAW_TEXT 却是空"这类静默故障无从下手。
        """
        try:
            import cv2
            import numpy as np
        except Exception as exc:
            print(f"[OCR READ ERROR] cv2/numpy import failed: {exc}", flush=True)
            return []

        ocr = get_ocr_adapter()
        try:
            if ocr.is_locked():
                print("[OCR READ ERROR] is_locked() returned True; OCR skipped", flush=True)
                return []
        except Exception as exc:
            print(f"[OCR READ ERROR] is_locked() raised: {exc}", flush=True)

        try:
            left, top, right, bottom = _window_rect(window)
        except Exception as exc:
            print(f"[OCR READ ERROR] _window_rect failed: {exc}", flush=True)
            return []
        width = max(right - left, 1)
        height = max(bottom - top, 1)

        try:
            screenshot = ocr.screenshot((left, top, width, height))
        except Exception as exc:
            print(f"[OCR READ ERROR] screenshot failed: {exc}", flush=True)
            return []

        if save_path:
            try:
                import os

                os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
                screenshot.save(save_path)
            except Exception as exc:
                print(f"[OCR READ ERROR] screenshot.save failed: {exc}", flush=True)

        try:
            source = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        except Exception as exc:
            print(f"[OCR READ ERROR] PIL→ndarray/cvtColor failed: {exc}", flush=True)
            return []

        if not lang_tag:
            try:
                handle = WindowHandle(native_id=_window_native_id(window))
                lang_tag = ocr.detect_app_language(handle)
            except Exception as exc:
                print(f"[OCR READ ERROR] detect_app_language failed: {exc}", flush=True)
                lang_tag = ""

        try:
            words = ocr.recognize(source, lang_tag)
            if not words:
                print(
                    f"[OCR READ EMPTY] recognize() returned 0 words "
                    f"(lang_tag={lang_tag!r}, region={width}x{height})",
                    flush=True,
                )
            return words
        except Exception as exc:
            import traceback

            print(f"[OCR READ ERROR] recognize() raised: {exc}", flush=True)
            traceback.print_exc()
            return []

    # ---- 内部：上下文 ----

    @staticmethod
    def _theme_tag(ctx: SystemContext) -> str:
        return "dark" if ctx.is_dark_mode else "light"

    @staticmethod
    def _build_context(
        ocr,
        handle: WindowHandle,
        gray_source: Any,
        resolution: Tuple[int, int],
        dpi_scale: float,
    ) -> SystemContext:
        """主题判定：系统设置只作为初值，最终以截图实际亮度为准。

        微信单独跟随的深色模式 + 系统浅色，用 `ocr.get_theme()` 会错判
        为 light。截图自身的灰度分布是最可靠的信号：
        * 整窗口灰度中位数 < 90  → 大部分像素偏暗，判为 dark
        * 整窗口灰度中位数 > 170 → 大部分像素偏亮，判为 light
        * 灰区（90~170）保留系统主题判定结果作为兜底

        中位数比平均值更稳：截图里红色"添加"按钮、彩色头像、ClearType
        子像素都会拉高 mean，但 median 看的是分布中点，反映背景色更准。
        """
        theme = ocr.get_theme()
        is_dark = theme == "dark"

        if hasattr(gray_source, "shape"):
            try:
                import numpy as np

                # numpy 的 median 比 mean 更抗"小面积亮色装饰物"干扰
                median_brightness = float(np.median(gray_source))
                if median_brightness < 90:
                    is_dark = True
                elif median_brightness > 170:
                    is_dark = False
                # 90 ~ 170 之间灰度不确定，保留系统主题判定结果
            except Exception:
                pass

        try:
            language = ocr.detect_app_language(handle)
        except Exception:
            language = "zh-CN"

        return SystemContext(
            resolution=resolution,
            dpi_scale=dpi_scale,
            is_dark_mode=is_dark,
            language=language,
            is_locked=False,
        )

    # ---- 内部：Track 1 缓存 ----

    def _try_cache_tracks(
        self,
        cv2,
        gray_source: Any,
        cache_sub_dir: Path,
        template_names: Sequence[str],
        left: int,
        top: int,
    ) -> Optional[MatchResult]:
        for template_name in template_names:
            clean_name = (
                template_name[:-4] if template_name.lower().endswith(".png") else template_name
            )
            cache_file = cache_sub_dir / f"{clean_name}.png"
            if not cache_file.exists():
                continue
            cache_img = cv2.imread(str(cache_file), cv2.IMREAD_GRAYSCALE)
            if cache_img is None:
                continue

            # 1a: 1.0 倍快速匹配
            best_match = self._search_scales(cv2, gray_source, cache_img, [1.0], 0.95)
            if best_match is not None:
                score, (x, y), (tw, th) = best_match
                return MatchResult(
                    template_name=f"cache_{clean_name}.png",
                    center_x=left + x + tw // 2,
                    center_y=top + y + th // 2,
                    score=score,
                )

            # 1b: Canny 边缘骨架
            edge_match = match_template_edge(gray_source, cache_img, threshold=0.60)
            if edge_match is not None:
                score, (x, y), (tw, th) = edge_match
                return MatchResult(
                    template_name=f"edge_cache_{clean_name}.png",
                    center_x=left + x + tw // 2,
                    center_y=top + y + th // 2,
                    score=score,
                )

            # 1c: 自适应二值化骨架（W-3）
            bin_match = match_template_binary(
                gray_source, cache_img, threshold=0.55
            )
            if bin_match is not None:
                score, (x, y), (tw, th) = bin_match
                return MatchResult(
                    template_name=f"binary_cache_{clean_name}.png",
                    center_x=left + x + tw // 2,
                    center_y=top + y + th // 2,
                    score=score,
                )
        return None

    # ---- 内部：Track 2 OCR ----

    def _try_ocr_track(
        self,
        cv2,
        ocr,
        handle: WindowHandle,
        source_bgr: Any,
        gray_source: Any,
        cache_sub_dir: Path,
        template_names: Sequence[str],
        left: int,
        top: int,
        width: int,
        height: int,
        context: SystemContext,
        ocr_dump: Optional[list[str]] = None,
    ) -> Optional[MatchResult]:
        # 适配器自行决定是否有可用 OCR；返回 [] 视为无结果
        try:
            ocr_results: List[OcrWord] = ocr.recognize(source_bgr, context.language)
        except Exception as exc:
            import traceback

            print(f"[OCR TRACK ERROR]: {exc}", flush=True)
            traceback.print_exc()
            return None

        if not ocr_results:
            return None

        # 留痕 OCR 看到的全部文本；即便后续模板/关键词没匹配上，也能在
        # VISION_TARGET_NOT_FOUND 错误里把"OCR 实际看到了什么"暴露出来。
        if ocr_dump is not None:
            try:
                joined = " | ".join(w.text for w in ocr_results if w.text)
                if joined:
                    ocr_dump.append(joined)
            except Exception:
                pass

        for template_name in template_names:
            clean_name = (
                template_name[:-4] if template_name.lower().endswith(".png") else template_name
            )
            if clean_name not in OCR_INTENT_MAP:
                continue
            keywords = OCR_INTENT_MAP[clean_name]

            for item in ocr_results:
                matched_kw = fuzzy_text_hit(item.text, keywords)
                if matched_kw is None:
                    continue
                # 防范弹窗标题栏：验证消息字样如果极靠顶（Y < 55px），通常是弹窗的标题栏，应予排除以定位真正的输入框提示
                if clean_name in ("verify_message_input", "friend_verify_input") and item.y < 55:
                    continue
                cx = left + item.x + item.width // 2
                cy = top + item.y + item.height // 2

                # 自学习：直接写入缓存（由外层 commit_cache 在成功完成工作流后安全提交）
                cache_file = cache_sub_dir / f"{clean_name}.png"
                pad = 5
                py1 = max(0, item.y - pad)
                py2 = min(height, item.y + item.height + pad)
                px1 = max(0, item.x - pad)
                px2 = min(width, item.x + item.width + pad)
                cropped = gray_source[py1:py2, px1:px2]
                is_valid = True
                if hasattr(cropped, 'size'):
                    try:
                        is_valid = int(cropped.size) > 0
                    except (TypeError, ValueError):
                        pass
                if is_valid:
                    self.pending_cache.append((cache_file, cropped))

                return MatchResult(
                    template_name=f"ocr_{clean_name}.png",
                    center_x=cx,
                    center_y=cy,
                    score=1.0,
                )

        # 第一轮没有匹配到任何意图，尝试二值化图像（针对绿底白字等高对比度彩色按钮）
        # 阀值设为 210 可以将白色文字与绿色按钮背景完美分离
        try:
            _, thresh = cv2.threshold(gray_source, 210, 255, cv2.THRESH_BINARY)
            ocr_results_thresh = ocr.recognize(thresh, context.language)
            if ocr_results_thresh:
                # 把二值化 OCR 到的原文也 dump 记录下来
                if ocr_dump is not None:
                    joined = " | ".join(w.text for w in ocr_results_thresh if w.text)
                    if joined:
                        ocr_dump.append(f"[Thresh210] {joined}")

                for template_name in template_names:
                    clean_name = (
                        template_name[:-4] if template_name.lower().endswith(".png") else template_name
                    )
                    if clean_name not in OCR_INTENT_MAP:
                        continue
                    keywords = OCR_INTENT_MAP[clean_name]

                    for item in ocr_results_thresh:
                        matched_kw = fuzzy_text_hit(item.text, keywords)
                        if matched_kw is None:
                            continue
                        # 防范弹窗标题栏：验证消息字样如果极靠顶（Y < 55px），通常是弹窗的标题栏，应予排除以定位真正的输入框提示
                        if clean_name in ("verify_message_input", "friend_verify_input") and item.y < 55:
                            continue
                        cx = left + item.x + item.width // 2
                        cy = top + item.y + item.height // 2

                        # 自学习：直接写入缓存（由外层 commit_cache 在成功完成工作流后安全提交）
                        cache_file = cache_sub_dir / f"{clean_name}.png"
                        pad = 5
                        py1 = max(0, item.y - pad)
                        py2 = min(height, item.y + item.height + pad)
                        px1 = max(0, item.x - pad)
                        px2 = min(width, item.x + item.width + pad)
                        cropped = gray_source[py1:py2, px1:px2]
                        is_valid = True
                        if hasattr(cropped, 'size'):
                            try:
                                is_valid = int(cropped.size) > 0
                            except (TypeError, ValueError):
                                pass
                        if is_valid:
                            self.pending_cache.append((cache_file, cropped))

                        return MatchResult(
                            template_name=f"ocr_{clean_name}.png",
                            center_x=cx,
                            center_y=cy,
                            score=1.0,
                        )
        except Exception as exc:
            print(f"[OCR THRESH210 TRACK ERROR]: {exc}", flush=True)

        return None

    # ---- 内部：Track 3 多尺度模板 ----

    def _match_template(self, auto, window, template_path: Path, threshold: float) -> dict | None:
        """v1 兼容入口：单模板匹配（被现有单测 `test_match_template_dynamic_dpi` 使用）。"""
        try:
            import cv2
            import numpy as np
        except Exception as exc:  # pragma: no cover - local desktop dependency
            raise AppError(
                "VISION_DRIVER_UNAVAILABLE",
                f"图像识别依赖不可用，请安装 opencv-python/pillow: {exc}",
            ) from exc

        enable_dpi_awareness()

        left, top, right, bottom = _window_rect(window)
        width = max(right - left, 1)
        height = max(bottom - top, 1)

        try:
            screenshot = get_ocr_adapter().screenshot((left, top, width, height))
        except Exception as exc:
            raise AppError("VISION_SCREENSHOT_FAILED", f"截屏失败: {exc}") from exc
        source = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        gray_source = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)

        try:
            base_scale = get_window_scale(_window_native_id(window))
        except Exception:
            base_scale = 1.0

        theme = get_windows_theme()
        if theme == "light":
            try:
                if hasattr(gray_source, "shape"):
                    h_s, _ = gray_source.shape[:2]
                    top_region = gray_source[0 : min(30, h_s), :]
                    if hasattr(top_region, "size") and top_region.size > 0:
                        if float(top_region.mean()) < 80:
                            theme = "dark"
            except Exception:
                pass

        match = self._match_template_on_image(
            cv2, gray_source, template_path, base_scale, threshold, theme=theme
        )
        if match is None:
            try:
                import os

                os.makedirs("backend/data", exist_ok=True)
                screenshot.save("backend/data/error_screenshot.png")
            except Exception:
                pass
            return None
        return {
            "center_x": left + match["x"] + match["tw"] // 2,
            "center_y": top + match["y"] + match["th"] // 2,
            "score": match["score"],
        }

    def _match_template_on_image(
        self,
        cv2,
        gray_source,
        template_path: Path,
        base_scale: float,
        threshold: float,
        theme: str = "light",
    ) -> dict | None:
        """多尺度模板匹配。

        主题冲突（系统浅 + 微信深，或反之）时，单凭 ``theme`` 判定
        `need_invert` 会错过反色模板。这里改用"原模板 + 反色模板都试一遍
        取更高分"的两路并行策略：
        * 快路径：先按 `need_invert` 启发式只跑一种模板，命中即返回
          （命中时分数往往很高，没必要再算反色）
        * 慢路径（fallback）：原图与反色图都在宽范围尺度上跑，取最高分
          作为最终结果。代价是这一轨慢一倍，但只在缓存 miss + OCR miss
          之后才发生，整体可接受。
        """
        template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
        if template is None:
            raise AppError("VISION_TEMPLATE_INVALID", f"模板图片无法读取: {template_path}")

        template_is_light = float(template.mean()) > 127
        window_is_dark = theme == "dark"
        # 启发式：理论上模板与窗口"颜色背景一致"就不必反色，反之需要反色。
        # 但只是优先尝试顺序，并不再决定"完全不试反色"。
        prefer_invert = window_is_dark == template_is_light
        inverted = 255 - template

        # ---- 第一轨：窄范围（快路径，命中即返回） ----
        target_scales = [base_scale * 0.95, base_scale * 1.00, base_scale * 1.05]
        primary = inverted if prefer_invert else template
        secondary = template if prefer_invert else inverted

        best = self._search_scales(cv2, gray_source, primary, target_scales, threshold)
        if best is None:
            best = self._search_scales(cv2, gray_source, secondary, target_scales, threshold)

        # ---- 第二轨：宽范围（慢路径，两种模板都跑取最高分） ----
        if best is None:
            fallback_scales = [
                1.00,
                base_scale * 0.70,
                base_scale * 0.80,
                base_scale * 0.90,
                base_scale * 1.10,
                base_scale * 1.20,
                base_scale * 1.30,
                base_scale * 1.50,
            ]
            fallback_scales = list({round(s, 2) for s in fallback_scales})
            fallback_scales = [
                s for s in fallback_scales if not any(abs(s - ts) < 0.02 for ts in target_scales)
            ]
            best_a = self._search_scales(cv2, gray_source, template, fallback_scales, threshold)
            best_b = self._search_scales(cv2, gray_source, inverted, fallback_scales, threshold)
            # 两路都跑，取分数更高的一边。这是解决"系统浅 + 微信深"
            # （或反之）主题冲突的根本手段——不依赖单向的反色判定。
            if best_a and best_b:
                best = best_a if best_a[0] >= best_b[0] else best_b
            else:
                best = best_a or best_b

        if best is None:
            return None
        score, (x, y), (tw, th) = best
        return {"x": x, "y": y, "tw": tw, "th": th, "score": score}

    @staticmethod
    def _search_scales(
        cv2, gray_source, template, scales: Iterable[float], threshold: float
    ) -> tuple[float, tuple[int, int], tuple[int, int]] | None:
        best: tuple[float, tuple[int, int], tuple[int, int]] | None = None
        for scale in scales:
            resized = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            th, tw = resized.shape[:2]
            if th >= gray_source.shape[0] or tw >= gray_source.shape[1]:
                continue
            result = cv2.matchTemplate(gray_source, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val >= threshold:
                if best is None or max_val > best[0]:
                    best = (float(max_val), max_loc, (tw, th))
        return best

    def _template_path(self, template_name: str) -> Path:
        name = template_name if template_name.lower().endswith(".png") else f"{template_name}.png"
        return self.template_dir / name


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _is_frozen(gray_source: Any) -> bool:
    """渲染冻结启发式：标准差 < 2.0 视为纯色帧。"""
    try:
        if hasattr(gray_source, "std"):
            return float(gray_source.std()) < 2.0
    except Exception:
        pass
    return False


def _window_rect(window: Any) -> Tuple[int, int, int, int]:
    """统一从 uiautomation 控件 (v1) 或 WindowHandle dataclass (v2) 取窗口矩形。

    返回 (left, top, right, bottom)。
    """
    # 优先使用 platform_data 中的实时 uiautomation 控件对象取最新坐标
    inner = getattr(window, "platform_data", None)
    if inner is not None and hasattr(inner, "BoundingRectangle"):
        try:
            rect = inner.BoundingRectangle
            if type(rect.left) in (int, float):
                return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
        except Exception:
            pass
    
    # v1 uiautomation 控件直接传入的情况
    if hasattr(window, "BoundingRectangle"):
        try:
            rect = window.BoundingRectangle
            if type(rect.left) in (int, float):
                return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
        except Exception:
            pass
        
    # 降级：使用 v2 WindowHandle 的缓存 .rect
    if hasattr(window, "rect") and not hasattr(window, "BoundingRectangle"):
        l, t, r, b = window.rect
        return int(l), int(t), int(r), int(b)

    raise AttributeError(f"无法识别的窗口对象类型: {type(window).__name__}")


def _window_native_id(window: Any) -> int:
    """统一取窗口 HWND/PID。"""
    if hasattr(window, "native_id") and not hasattr(window, "NativeWindowHandle"):
        return int(getattr(window, "native_id", 0) or 0)
    if hasattr(window, "NativeWindowHandle"):
        try:
            return int(window.NativeWindowHandle)
        except Exception:
            return 0
    inner = getattr(window, "platform_data", None)
    if inner is not None and hasattr(inner, "NativeWindowHandle"):
        try:
            return int(inner.NativeWindowHandle)
        except Exception:
            return 0
    return 0


def _is_macos() -> bool:
    import sys

    return sys.platform == "darwin"


# ---------------------------------------------------------------------------
# v1 公开符号：保留 ndarray → SoftwareBitmap 与异步 OCR 函数（被旧测试 import）
# ---------------------------------------------------------------------------


async def run_windows_native_ocr(image_np: Any, lang_tag: str = "") -> List[dict]:  # pragma: no cover
    """v1 兼容入口；正式调用请走 ``get_ocr_adapter().recognize()``。"""
    from backend.app.services.platform.windows import _run_native_ocr_async

    words = await _run_native_ocr_async(image_np, lang_tag)
    return [
        {"text": w.text, "x": w.x, "y": w.y, "width": w.width, "height": w.height}
        for w in words
    ]


def run_async_safe(coro: Any) -> Any:  # pragma: no cover
    """v1 兼容入口。"""
    from backend.app.services.platform.windows import _run_async_safe

    return _run_async_safe(coro)


def ndarray_to_software_bitmap(arr: Any) -> Any:  # pragma: no cover
    """v1 兼容入口。"""
    from backend.app.services.platform.windows import _ndarray_to_software_bitmap

    return _ndarray_to_software_bitmap(arr)