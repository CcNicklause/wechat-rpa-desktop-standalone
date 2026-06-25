"""
OCR 调试脚本：直接读取 error_screenshot.png，打印 WinRT OCR 完整输出
用法：python backend/debug_ocr.py
"""
import sys
import cv2
import numpy as np
from PIL import Image

try:
    from winrt.windows.graphics.imaging import (
        SoftwareBitmap,
        BitmapPixelFormat,
        BitmapAlphaMode,
    )
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.globalization import Language
except ImportError as e:
    print(f"WinRT OCR 导入失败: {e}")
    print("pip install winrt-Windows.Media.Ocr winrt-Windows.Graphics winrt-Windows.Globalization")
    sys.exit(1)

from backend.app.services.platform.windows import _ndarray_to_software_bitmap, _run_async_safe

# 1. 读取你截图里那张图
img_path = "backend/data/error_screenshot.png"
pil_img = Image.open(img_path)
print(f"图像: {img_path}, 尺寸: {pil_img.size}")

# 2. 走 OCR 前的转换链
rgb = np.array(pil_img)
print(f"PIL → ndarray 后 shape: {rgb.shape}, dtype: {rgb.dtype}")

bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
print(f"COLOR_RGB2BGR 后 shape: {bgr.shape}")

# 3. 直接调 WinRT OCR
print("\n" + "=" * 60)
print("直接走 WinRT OCR...")

try:
    bitmap = _ndarray_to_software_bitmap(bgr)
    print(f"SoftwareBitmap 转换成功")
except Exception as e:
    print(f"SoftwareBitmap 转换失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n尝试创建 OCR engine...")
engine = OcrEngine.try_create_from_user_profile_languages()
print(f"用户语言 engine: {engine}")

print(f"\n尝试创建中文 engine...")
try:
    zh = Language("zh-CN")
    engine_zh = OcrEngine.try_create_from_language(zh)
    print(f"中文 engine: {engine_zh}")
except Exception as e:
    print(f"创建中文 Language 失败: {e}")
    engine_zh = None

if engine is None and engine_zh is None:
    print("\n!!! 两个 engine 全是 None —— 系统没有安装任何 OCR 语言包")
    print("到 「设置 → 时间和语言 → 语言 → 添加首选语言」")
    print("搜索「中文（简体）」，安装后勾选「光学字符识别」")
    sys.exit(1)

active_engine = engine_zh or engine
print(f"\n开始识别（使用 engine: {active_engine}）...")

ocr_result = _run_async_safe(active_engine.recognize_async(bitmap))
print(f"OcrResult 对象: {ocr_result}")

print(f"\n" + "=" * 60)
print(f"识别到 {len(ocr_result.lines)} 行文字：")
for i, line in enumerate(ocr_result.lines):
    print(f"  行 {i:>2}: {repr(line.text)}")
    rect = line.bounding_rect
    print(f"      rect: x={rect.x}, y={rect.y}, w={rect.width}, h={rect.height}")
    if line.words:
        print(f"      words: {[w.text for w in line.words]}")

if not ocr_result.lines:
    print("\n!!! OCR 确实返回 0 行 —— 这是 Windows OCR 引擎的结论")
    print("检查 ① 系统是否装了中文 OCR 包 ② 图像是否翻转/过暗 ③ 字号是否太小")
