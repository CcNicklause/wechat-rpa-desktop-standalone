import sys
from unittest.mock import patch, MagicMock

# 提前 mock 图像识别的第三方依赖，使单元测试能在无 GUI/无依赖的环境下运行
mock_cv2 = MagicMock()
mock_cv2.COLOR_RGB2BGR = 4
mock_cv2.COLOR_BGR2GRAY = 6
mock_cv2.TM_CCOEFF_NORMED = 5
mock_cv2.INTER_AREA = 3
sys.modules['cv2'] = mock_cv2

mock_numpy = MagicMock()
sys.modules['numpy'] = mock_numpy

mock_pyautogui = MagicMock()
sys.modules['pyautogui'] = mock_pyautogui

mock_pil = MagicMock()
sys.modules['PIL'] = mock_pil
sys.modules['PIL.Image'] = mock_pil

import unittest

# 尝试导入这两个尚未实现的 API，用于 Step 2 验证无法导入的异常
from backend.app.services.vision_locator import get_window_scale, enable_dpi_awareness

class TestVisionLocatorDPI(unittest.TestCase):
    
    @patch('sys.platform', 'win32')
    def test_get_window_scale_success(self):
        # 模拟成功情况：GetDpiForMonitor 成功执行并返回 144 DPI (1.5倍缩放)
        mock_windll = MagicMock()
        mock_windll.user32.MonitorFromWindow.return_value = 9999
        
        # 模拟 GetDpiForMonitor 修改指针值
        def fake_get_dpi(monitor, dpi_type, dpi_x_ref, dpi_y_ref):
            dpi_x_ref._obj.value = 144
            dpi_y_ref._obj.value = 144
            return 0  # S_OK
            
        mock_windll.shcore.GetDpiForMonitor.side_effect = fake_get_dpi
        
        with patch('ctypes.windll', mock_windll, create=True):
            scale = get_window_scale(12345)
            self.assertEqual(scale, 1.5)
            mock_windll.user32.MonitorFromWindow.assert_called_once_with(12345, 2)
            mock_windll.shcore.GetDpiForMonitor.assert_called_once()

    @patch('sys.platform', 'win32')
    def test_get_window_scale_fallback_screen_dpi(self):
        # 模拟降级情况：GetDpiForMonitor 失败，降级使用 GetDeviceCaps 返回 120 DPI (1.25倍缩放)
        mock_windll = MagicMock()
        # 让 GetDpiForMonitor 抛出 AttributeError 或者 OSError
        mock_windll.shcore.GetDpiForMonitor.side_effect = AttributeError("not supported")
        
        # 模拟 GetDC 和 GetDeviceCaps
        mock_windll.user32.GetDC.return_value = 8888
        mock_windll.gdi32.GetDeviceCaps.return_value = 120
        mock_windll.user32.ReleaseDC.return_value = 1
        
        with patch('ctypes.windll', mock_windll, create=True):
            scale = get_window_scale(12345)
            self.assertEqual(scale, 1.25)
            mock_windll.user32.GetDC.assert_called_once_with(0)
            mock_windll.gdi32.GetDeviceCaps.assert_called_once_with(8888, 88)
            mock_windll.user32.ReleaseDC.assert_called_once_with(0, 8888)

    @patch('sys.platform', 'win32')
    def test_get_window_scale_all_exceptions(self):
        # 模拟所有 API 异常的情况
        mock_windll = MagicMock()
        mock_windll.user32.MonitorFromWindow.side_effect = Exception("windows error")
        mock_windll.user32.GetDC.side_effect = Exception("gdi error")
        
        with patch('ctypes.windll', mock_windll, create=True):
            scale = get_window_scale(12345)
            self.assertEqual(scale, 1.0)

    @patch('sys.platform', 'darwin')
    def test_get_window_scale_non_windows(self):
        # 模拟非 Windows 平台，直接返回 1.0
        scale = get_window_scale(12345)
        self.assertEqual(scale, 1.0)

    @patch('sys.platform', 'win32')
    def test_enable_dpi_awareness_shcore_success(self):
        mock_windll = MagicMock()
        mock_windll.shcore.SetProcessDpiAwareness.return_value = 0
        
        with patch('ctypes.windll', mock_windll, create=True):
            res = enable_dpi_awareness()
            self.assertTrue(res)
            mock_windll.shcore.SetProcessDpiAwareness.assert_called_once_with(2)
            mock_windll.user32.SetProcessDPIAware.assert_not_called()

    @patch('sys.platform', 'win32')
    def test_enable_dpi_awareness_user32_success(self):
        mock_windll = MagicMock()
        mock_windll.shcore.SetProcessDpiAwareness.side_effect = AttributeError("not supported")
        mock_windll.user32.SetProcessDPIAware.return_value = 1
        
        with patch('ctypes.windll', mock_windll, create=True):
            res = enable_dpi_awareness()
            self.assertTrue(res)
            mock_windll.shcore.SetProcessDpiAwareness.assert_called_once_with(2)
            mock_windll.user32.SetProcessDPIAware.assert_called_once()

    @patch('sys.platform', 'win32')
    def test_enable_dpi_awareness_all_exceptions(self):
        mock_windll = MagicMock()
        mock_windll.shcore.SetProcessDpiAwareness.side_effect = Exception("shcore error")
        mock_windll.user32.SetProcessDPIAware.side_effect = Exception("user32 error")
        
        with patch('ctypes.windll', mock_windll, create=True):
            res = enable_dpi_awareness()
            self.assertFalse(res)

    @patch('sys.platform', 'darwin')
    def test_enable_dpi_awareness_non_windows(self):
        res = enable_dpi_awareness()
        self.assertFalse(res)

    @patch('backend.app.services.vision_locator.enable_dpi_awareness')
    @patch('backend.app.services.vision_locator.get_window_scale')
    @patch('backend.app.services.vision_locator.get_ocr_adapter')
    def test_match_template_dynamic_dpi(
        self,
        mock_get_ocr,
        mock_get_window_scale,
        mock_enable_dpi_awareness
    ):
        from backend.app.services.vision_locator import VisionLocator
        from pathlib import Path

        # 1. 重置所有的全局 mock 对象
        mock_cv2.reset_mock()
        mock_numpy.reset_mock()
        mock_pyautogui.reset_mock()

        # 2. 准备 mock 数据
        mock_window = MagicMock()
        mock_window.BoundingRectangle.left = 100
        mock_window.BoundingRectangle.top = 200
        mock_window.BoundingRectangle.right = 900
        mock_window.BoundingRectangle.bottom = 800
        mock_window.NativeWindowHandle = 12345

        # Mock OCR adapter screenshot
        mock_ocr = MagicMock()
        mock_screenshot = MagicMock()
        mock_ocr.screenshot.return_value = mock_screenshot
        mock_get_ocr.return_value = mock_ocr

        # mock_numpy.array(screenshot) 返回 mock_source
        mock_source = MagicMock()
        mock_numpy.array.return_value = mock_source

        # mock_cv2.cvtColor 被调用两次：
        # 1. cv2.cvtColor(source, cv2.COLOR_RGB2BGR) -> source_bgr
        # 2. cv2.cvtColor(source_bgr, cv2.COLOR_BGR2GRAY) -> gray_source
        mock_source_bgr = MagicMock()
        mock_gray_source = MagicMock()
        mock_gray_source.shape = (600, 800)
        mock_cv2.cvtColor.side_effect = [mock_source_bgr, mock_gray_source]

        # mock_cv2.imread 返回 mock_template
        mock_template = MagicMock()
        mock_cv2.imread.return_value = mock_template

        # mock_cv2.resize 返回 mock_resized
        mock_resized = MagicMock()
        mock_resized.shape = (50, 50)
        mock_cv2.resize.return_value = mock_resized

        # mock_cv2.matchTemplate 返回 mock_result
        mock_result = MagicMock()
        mock_cv2.matchTemplate.return_value = mock_result

        # mock_cv2.minMaxLoc 被调用 3 次（对应 base_scale*0.95, base_scale*1.0, base_scale*1.05）
        mock_cv2.minMaxLoc.side_effect = [
            (0.0, 0.70, (0, 0), (5, 5)),
            (0.0, 0.85, (0, 0), (10, 20)),
            (0.0, 0.80, (0, 0), (8, 8)),
        ]

        mock_enable_dpi_awareness.return_value = True
        mock_get_window_scale.return_value = 1.5

        locator = VisionLocator(template_dir='backend/assets/wechat_templates')

        res = locator._match_template(
            auto=MagicMock(),
            window=mock_window,
            template_path=Path('dummy_template.png'),
            threshold=0.78
        )


        # 4. 验证是否调用了 DPI 相关 API
        mock_enable_dpi_awareness.assert_called_once()
        mock_get_window_scale.assert_called_once_with(12345)

        # 5. 验证是否使用了正确的 region 进行截图
        mock_ocr.screenshot.assert_called_once_with((100, 200, 800, 600))

        # 6. 验证是否使用了 narrow target scale: [1.5 * 0.95, 1.5 * 1.0, 1.5 * 1.05] -> [1.425, 1.5, 1.575]
        self.assertEqual(mock_cv2.resize.call_count, 3)
        
        calls = mock_cv2.resize.call_args_list
        scales = []
        for call in calls:
            args, kwargs = call
            if 'fx' in kwargs:
                scales.append(kwargs['fx'])
            elif len(args) > 2:
                scales.append(args[2])
            else:
                scales.append(None)
        
        self.assertAlmostEqual(scales[0], 1.425)
        self.assertAlmostEqual(scales[1], 1.5)
        self.assertAlmostEqual(scales[2], 1.575)

        # 7. 验证返回值是否正确
        self.assertIsNotNone(res)
        self.assertEqual(res['center_x'], 135)
        self.assertEqual(res['center_y'], 245)
        self.assertEqual(res['score'], 0.85)

    @patch('backend.app.services.wechat_rpa._find_wechat_window')
    @patch('backend.app.services.wechat_rpa._cleanup_stale_windows')
    @patch('backend.app.services.wechat_rpa._find_add_friends_window')
    @patch('backend.app.services.wechat_rpa._open_add_friends_entry')
    @patch('backend.app.services.wechat_rpa._focus_search_box')
    @patch('backend.app.services.wechat_rpa._clear_and_type_target')
    @patch('backend.app.services.wechat_rpa._press_enter')
    @patch('backend.app.services.wechat_rpa._detect_screen_state')
    @patch('backend.app.services.wechat_rpa._click_add_friend')
    @patch('backend.app.services.wechat_rpa._wait_and_front_verify_window')
    @patch('backend.app.services.wechat_rpa._fill_verify_message')
    @patch('backend.app.services.wechat_rpa._click_send_verify')
    @patch('backend.app.services.wechat_rpa.get_ocr_adapter')
    @patch('backend.app.services.wechat_rpa.get_desktop_adapter')
    @patch('time.sleep')
    @patch('random.uniform')
    def test_wechat_rpa_uses_random_delay_before_send(
        self,
        mock_random_uniform,
        mock_sleep,
        mock_get_desktop_adapter,
        mock_get_ocr_adapter,
        mock_click_send_verify,
        mock_fill_verify_message,
        mock_wait_and_front_verify_window,
        mock_click_add_friend,
        mock_detect_screen_state,
        mock_press_enter,
        mock_clear_and_type_target,
        mock_focus_search_box,
        mock_open_add_friends_entry,
        mock_find_add_friends_window,
        mock_cleanup_stale_windows,
        mock_find_wechat_window
    ):
        from backend.app.services.wechat_rpa import execute_single_add_request
        import sys

        # 提前 mock uiautomation，避免 Windows 依赖导入异常
        mock_auto = MagicMock()
        sys.modules['uiautomation'] = mock_auto

        # OCR/desktop 适配器 mock
        mock_ocr = MagicMock()
        mock_ocr.is_locked.return_value = False
        mock_get_ocr_adapter.return_value = mock_ocr
        mock_get_desktop_adapter.return_value = MagicMock()

        # 读屏判定恒返回 None（不命中任何业务终态），让流程走到发送
        mock_detect_screen_state.return_value = None
        # 复用主窗口作为添加朋友窗口，避免独立窗口分支
        mock_find_add_friends_window.return_value = None

        # 模拟微信窗口和搜索框
        mock_wx_window = MagicMock()
        mock_wx_window.name = "WeChat"
        mock_wx_window.class_name = "WeChatMainWndForPC"
        mock_find_wechat_window.return_value = mock_wx_window

        mock_search_box = MagicMock()
        mock_focus_search_box.return_value = (mock_search_box, 'uia')

        # 验证窗找到（返回 2-tuple：window, found=True）
        mock_verify_window = MagicMock()
        mock_wait_and_front_verify_window.return_value = (mock_verify_window, True)

        # 模拟随机等待时间
        mock_random_uniform.return_value = 1.88

        # 执行流程并收集步骤
        steps = []
        def update_cb(step):
            steps.append(step)

        execute_single_add_request(
            phone="13800138000",
            greeting="你好，我是销售经理",
            update=update_cb
        )

        # 验证是否在 1.2 至 2.5 秒范围内随机选择
        mock_random_uniform.assert_called_with(1.2, 2.5)

        # 验证是否在发送前 sleep 了随机选择的秒数
        sleep_args = [call[0][0] for call in mock_sleep.call_args_list]
        self.assertIn(1.88, sleep_args)

        # 验证 mark 步骤中包含 POST_PASTE_WAIT 记录
        post_paste_wait_steps = [s for s in steps if "POST_PASTE_WAIT" in s]
        self.assertEqual(len(post_paste_wait_steps), 1)
        self.assertIn("1.88", post_paste_wait_steps[0])

    @patch('backend.app.services.vision_locator.get_window_scale')
    @patch('backend.app.services.vision_locator.get_windows_theme')
    @patch('backend.app.services.vision_locator.get_ocr_adapter')
    def test_find_first_ocr_track(self, mock_get_ocr, mock_get_theme, mock_get_scale):
        from backend.app.services.vision_locator import VisionLocator
        from pathlib import Path
        from backend.app.services.platform.base import OcrWord
        
        # Setup mocks
        mock_get_scale.return_value = 1.0
        mock_get_theme.return_value = "light"
        
        # Mock OCR Adapter
        mock_ocr = MagicMock()
        mock_ocr.is_locked.return_value = False
        mock_ocr.get_dpi_scale.return_value = 1.0
        mock_ocr.screenshot.return_value = MagicMock()
        mock_ocr.recognize.return_value = [
            OcrWord(text="添加朋友", x=20, y=30, width=100, height=40)
        ]
        mock_get_ocr.return_value = mock_ocr

        
        # Mock window properties
        mock_window = MagicMock()
        mock_window.BoundingRectangle.left = 100
        mock_window.BoundingRectangle.top = 200
        mock_window.BoundingRectangle.right = 900
        mock_window.BoundingRectangle.bottom = 800
        mock_window.NativeWindowHandle = 12345
        
        mock_source = MagicMock()
        mock_numpy.array.return_value = mock_source
        
        mock_source_bgr = MagicMock()
        mock_gray_source = MagicMock()
        mock_gray_source.shape = (600, 800)
        mock_gray_source.std.return_value = 15.0
        
        mock_cv2.cvtColor.side_effect = [mock_source_bgr, mock_gray_source]
        
        # Mock Path.exists to return False for cache files to ensure OCR path is taken
        with patch.object(Path, 'exists', return_value=False):
            locator = VisionLocator(template_dir='backend/assets/wechat_templates')
            res = locator.find_first(
                auto=MagicMock(),
                window=mock_window,
                template_names=['menu_add_friends'],
                threshold=0.78
            )
            
            # Assert OCR was called and coordinates returned
            self.assertEqual(res.template_name, "ocr_menu_add_friends.png")
            self.assertEqual(res.center_x, 170)
            self.assertEqual(res.center_y, 250)
            self.assertEqual(res.score, 1.0)


    @patch('backend.app.services.wechat_rpa.get_ocr_adapter')
    @patch('backend.app.services.wechat_rpa.get_desktop_adapter')
    @patch('backend.app.services.wechat_rpa.vision')
    @patch('backend.app.services.wechat_rpa._paste_text_via_clipboard')
    @patch('time.sleep')
    def test_fill_verify_message_ocr_offset(self, mock_sleep, mock_paste, mock_vision, mock_get_desktop, mock_get_ocr):

        from backend.app.services.wechat_rpa import _fill_verify_message
        
        # Mock OCR adapter
        mock_ocr = MagicMock()
        mock_ocr.get_dpi_scale.return_value = 1.5
        mock_get_ocr.return_value = mock_ocr
        
        # Mock desktop adapter
        mock_desktop = MagicMock()
        mock_get_desktop.return_value = mock_desktop
        
        # 1. 模拟 UIA 控件不存在，触发 vision 降级
        mock_window = MagicMock()
        mock_desktop.find_child_window.return_value = None
        mock_window.NativeWindowHandle = 12345
        
        # 2. 模拟 vision 返回 OCR 命中的模板
        from backend.app.services.vision_locator import MatchResult
        mock_vision.find_first.return_value = MatchResult(
            template_name="ocr_verify_message_input.png",
            center_x=200,
            center_y=100,
            score=1.0
        )
        
        mock_auto = MagicMock()
        steps = []
        def update_cb(step):
            steps.append(step)
            
        with patch('backend.app.services.vision_locator.get_window_scale', return_value=1.5):
            _fill_verify_message(
                auto=mock_auto,
                target_window=mock_window,
                greeting="测试验证语",
                mark=update_cb
            )
            
        # 3. 验证是否增加了偏移量 Y: 100 + int(75 * 1.5) = 100 + 112 = 212
        mock_desktop.click.assert_called_once_with(200, 212)
        mock_paste.assert_called_once_with("测试验证语")
        self.assertIn("GREETING_FILLED_BY_VISION", steps[-1])

    @patch('backend.app.services.wechat_rpa.get_ocr_adapter')
    @patch('backend.app.services.wechat_rpa.get_desktop_adapter')
    @patch('backend.app.services.wechat_rpa.vision')
    @patch('backend.app.services.wechat_rpa._paste_text_via_clipboard')
    @patch('time.sleep')
    def test_fill_verify_message_cache_offset(self, mock_sleep, mock_paste, mock_vision, mock_get_desktop, mock_get_ocr):
        from backend.app.services.wechat_rpa import _fill_verify_message
        
        # Mock OCR adapter
        mock_ocr = MagicMock()
        mock_ocr.get_dpi_scale.return_value = 1.5
        mock_get_ocr.return_value = mock_ocr
        
        # Mock desktop adapter
        mock_desktop = MagicMock()
        mock_get_desktop.return_value = mock_desktop
        
        mock_window = MagicMock()
        mock_window.NativeWindowHandle = 12345
        
        # 模拟自学习缓存命中的名字 "cache_verify_message_input.png"
        from backend.app.services.vision_locator import MatchResult
        mock_vision.find_first.return_value = MatchResult(
            template_name="cache_verify_message_input.png",
            center_x=200,
            center_y=100,
            score=1.0
        )
        
        mock_auto = MagicMock()
        steps = []
        def update_cb(step):
            steps.append(step)
            
        with patch('backend.app.services.vision_locator.get_window_scale', return_value=1.5):
            _fill_verify_message(
                auto=mock_auto,
                target_window=mock_window,
                greeting="测试验证语",
                mark=update_cb
            )
            
        # 验证是否增加了偏移量 Y: 100 + int(75 * 1.5) = 212
        mock_desktop.click.assert_called_once_with(200, 212)



class TestWindowsDesktopAdapter(unittest.TestCase):
    def test_windows_desktop_adapter_robustness(self):
        from backend.app.services.platform.windows import WindowsDesktopAdapter
        from backend.app.services.platform.base import WindowHandle
        
        adapter = WindowsDesktopAdapter()
        
        # Test 1: _wrap with already wrapped WindowHandle should return it directly
        h = WindowHandle(native_id=123, rect=(10, 20, 30, 40))
        wrapped = adapter._wrap(h)
        self.assertEqual(wrapped, h)
        
        # Test 2: _wrap with structurally similar object (has rect, no BoundingRectangle)
        class StructSimilar:
            def __init__(self):
                self.native_id = 456
                self.name = "Test"
                self.class_name = "Class"
                self.rect = (50, 60, 70, 80)
        
        obj = StructSimilar()
        wrapped2 = adapter._wrap(obj)
        self.assertEqual(wrapped2.native_id, 456)
        self.assertEqual(wrapped2.rect, (50, 60, 70, 80))
        
        # Test 3: get_bounding_rectangle with handle whose platform_data is a WindowHandle
        h2 = WindowHandle(native_id=123, rect=(10, 20, 30, 40), platform_data=h)
        rect = adapter.get_bounding_rectangle(h2)
        self.assertEqual(rect, (10, 20, 30, 40))
        
        # Test 4: get_bounding_rectangle with handle whose platform_data does not have BoundingRectangle
        class NoBoundRect:
            pass
        h3 = WindowHandle(native_id=789, rect=(1, 2, 3, 4), platform_data=NoBoundRect())
        rect = adapter.get_bounding_rectangle(h3)
        self.assertEqual(rect, (1, 2, 3, 4))


class TestScreenStateDetection(unittest.TestCase):
    """读屏状态判定 _detect_screen_state（S-1/S-2/A-3 核心防御）"""

    def _make_words(self, *texts):
        from backend.app.services.platform.base import OcrWord
        return [OcrWord(text=t, x=0, y=0, width=10, height=10) for t in texts]

    @patch('backend.app.services.wechat_rpa.vision')
    def test_detect_target_not_found(self, mock_vision):
        from backend.app.services.wechat_rpa import _detect_screen_state
        mock_vision.read_window_text.return_value = self._make_words("该用户不存在，请检查你填写的账号")
        state = _detect_screen_state(MagicMock(), ["TARGET_NOT_FOUND", "ALREADY_FRIEND"])
        self.assertEqual(state, "TARGET_NOT_FOUND")

    @patch('backend.app.services.wechat_rpa.vision')
    def test_detect_already_friend(self, mock_vision):
        from backend.app.services.wechat_rpa import _detect_screen_state
        mock_vision.read_window_text.return_value = self._make_words("发消息", "音视频通话")
        state = _detect_screen_state(MagicMock(), ["TARGET_NOT_FOUND", "ALREADY_FRIEND"])
        self.assertEqual(state, "ALREADY_FRIEND")

    @patch('backend.app.services.wechat_rpa.vision')
    def test_detect_already_friend_profile_before_search_false_positive(self, mock_vision):
        from backend.app.services.wechat_rpa import _detect_screen_state
        mock_vision.read_window_text.return_value = self._make_words(
            "添 加 朋 友",
            "pixel punk",
            "搜 索",
            "朋 友 资 料",
            "发 消 息",
            "微 信 号 ： pixel punk",
            "语 音 聊 天",
            "见 频 聊 天",
        )

        state = _detect_screen_state(MagicMock(), ["RISK_CONTROL", "TARGET_NOT_FOUND", "ALREADY_FRIEND"])

        self.assertEqual(state, "ALREADY_FRIEND")

    @patch('backend.app.services.wechat_rpa.vision')
    def test_detect_risk_control_priority(self, mock_vision):
        from backend.app.services.wechat_rpa import _detect_screen_state
        # 风控关键词排在前面 → 优先命中
        mock_vision.read_window_text.return_value = self._make_words("操作过于频繁，请稍后再试")
        state = _detect_screen_state(MagicMock(), ["RISK_CONTROL", "TARGET_NOT_FOUND"])
        self.assertEqual(state, "RISK_CONTROL")

    @patch('backend.app.services.wechat_rpa.vision')
    def test_detect_none_when_no_keyword(self, mock_vision):
        from backend.app.services.wechat_rpa import _detect_screen_state
        mock_vision.read_window_text.return_value = self._make_words("正常的聊天界面内容")
        state = _detect_screen_state(MagicMock(), ["TARGET_NOT_FOUND", "ALREADY_FRIEND"])
        self.assertIsNone(state)

    @patch('backend.app.services.wechat_rpa.vision')
    def test_detect_none_when_ocr_empty(self, mock_vision):
        from backend.app.services.wechat_rpa import _detect_screen_state
        mock_vision.read_window_text.return_value = []
        state = _detect_screen_state(MagicMock(), ["TARGET_NOT_FOUND"])
        self.assertIsNone(state)

    def test_raise_if_business_outcome(self):
        from backend.app.services.wechat_rpa import (
            _raise_if_business_outcome,
            RpaBusinessOutcome,
        )
        # 命中业务终态 → 抛 RpaBusinessOutcome
        with self.assertRaises(RpaBusinessOutcome) as ctx:
            _raise_if_business_outcome("TARGET_NOT_FOUND")
        self.assertEqual(ctx.exception.code, "BIZ_TARGET_NOT_FOUND")
        self.assertFalse(ctx.exception.circuit_break)

        # 风控终态 → circuit_break=True
        with self.assertRaises(RpaBusinessOutcome) as ctx2:
            _raise_if_business_outcome("RISK_CONTROL")
        self.assertEqual(ctx2.exception.code, "BIZ_RISK_CONTROL")
        self.assertTrue(ctx2.exception.circuit_break)

        # None / 非业务状态 → 不抛
        _raise_if_business_outcome(None)
        _raise_if_business_outcome("SEND_SUCCESS")  # 成功类不在 _BUSINESS_OUTCOME_MAP

    @patch('backend.app.services.wechat_rpa.vision')
    def test_click_add_friend_missing_returns_false(self, mock_vision):
        """找不到添加按钮时返回 False，而非冒泡 VISION_TARGET_NOT_FOUND（S-1 兜底）。"""
        from backend.app.services.wechat_rpa import _click_add_friend
        from backend.app.core.errors import AppError

        # vision.click_first 抛 VISION_TARGET_NOT_FOUND
        mock_vision.click_first.side_effect = AppError(
            "VISION_TARGET_NOT_FOUND", "未匹配: add_to_contacts_button.png"
        )
        steps = []
        clicked = _click_add_friend(MagicMock(), MagicMock(), steps.append)
        self.assertFalse(clicked)
        self.assertTrue(any("ADD_BUTTON_NOT_FOUND" in s for s in steps))

    @patch('backend.app.services.wechat_rpa.vision')
    def test_click_add_friend_other_error_propagates(self, mock_vision):
        """非 VISION_TARGET_NOT_FOUND 的系统错误仍应冒泡。"""
        from backend.app.services.wechat_rpa import _click_add_friend
        from backend.app.core.errors import AppError

        mock_vision.click_first.side_effect = AppError(
            "VISION_SCREENSHOT_FAILED", "截屏失败"
        )
        with self.assertRaises(AppError):
            _click_add_friend(MagicMock(), MagicMock(), lambda s: None)


class TestOrchestratorOutcome(unittest.TestCase):
    """编排层业务终态分流（O-2）与超时（O-1）"""

    def _make_orchestrator(self):
        from backend.app.services.rpa_orchestrator import RpaOrchestrator
        store = MagicMock()
        audit = MagicMock()
        settings = MagicMock()
        settings.rpa_daily_limit = 3
        settings.rpa_task_timeout_seconds = 90
        return RpaOrchestrator(store, audit, settings), store, audit

    def test_finalize_business_outcome_not_failed(self):
        from backend.app.services.wechat_rpa import RpaBusinessOutcome
        from backend.app.schemas.lead import LeadStatus
        orch, store, audit = self._make_orchestrator()
        lead = {'lead_id': 'lead_1', 'sales_id': 'sales_1', 'phone': '13800138000'}
        outcome = RpaBusinessOutcome("BIZ_TARGET_NOT_FOUND", "搜不到")

        orch._finalize_business_outcome('job_1', lead, ['step'], outcome)

        # job 应标记为 REAL_BIZ_TARGET_NOT_FOUND + outcome_type=business
        job_call = store.update_job.call_args
        self.assertEqual(job_call.kwargs['status'], 'REAL_BIZ_TARGET_NOT_FOUND')
        self.assertEqual(job_call.kwargs['outcome_type'], 'business')
        self.assertEqual(job_call.kwargs['error_code'], 'BIZ_TARGET_NOT_FOUND')
        # lead 状态映射到业务终态而非 RPA_FAILED
        lead_call = store.update_lead.call_args
        self.assertEqual(lead_call.kwargs['status'], LeadStatus.WECHAT_TARGET_NOT_FOUND.value)

    def test_risk_control_triggers_circuit_break(self):
        from backend.app.services.wechat_rpa import RpaBusinessOutcome
        orch, store, audit = self._make_orchestrator()
        lead = {'lead_id': 'lead_1', 'sales_id': 'sales_1', 'phone': '13800138000'}
        outcome = RpaBusinessOutcome("BIZ_RISK_CONTROL", "风控", circuit_break=True)

        with patch('backend.app.services.rpa_orchestrator.increment_daily_count') as mock_inc:
            orch._finalize_business_outcome('job_1', lead, [], outcome)
            # 熔断：把今日计数顶到上限（调用 rpa_daily_limit 次）
            self.assertEqual(mock_inc.call_count, 3)

    def test_fail_job_marks_system_outcome(self):
        orch, store, audit = self._make_orchestrator()
        lead = {'lead_id': 'lead_1', 'sales_id': 'sales_1', 'phone': '13800138000'}
        orch._fail_job('job_1', lead, [], 'SYS_RPA_TIMEOUT', '超时')
        job_call = store.update_job.call_args
        self.assertEqual(job_call.kwargs['status'], 'FAILED')
        self.assertEqual(job_call.kwargs['outcome_type'], 'system')


class TestVisionLocatorPendingCache(unittest.TestCase):
    """测试缓存队列延迟提交机制"""

    def test_pending_cache_commit_and_clear(self):
        import numpy as np
        from backend.app.services.vision_locator import VisionLocator
        
        locator = VisionLocator()
        locator.clear_pending_cache()
        self.assertEqual(len(locator.pending_cache), 0)
        
        # Add a mock cache item
        from pathlib import Path
        mock_file = Path("backend/data/templates_cache/test_item.png")
        mock_img = np.zeros((10, 10), dtype=np.uint8)
        
        locator.pending_cache.append((mock_file, mock_img))
        self.assertEqual(len(locator.pending_cache), 1)
        
        # Test clear
        locator.clear_pending_cache()
        self.assertEqual(len(locator.pending_cache), 0)
        
        # Add again
        locator.pending_cache.append((mock_file, mock_img))
        
        # Test commit with patched cv2.imwrite and Path.mkdir
        with patch('cv2.imwrite') as mock_imwrite, patch.object(Path, 'mkdir') as mock_mkdir:
            locator.commit_cache()
            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
            mock_imwrite.assert_called_once_with(str(mock_file), mock_img)
            
        self.assertEqual(len(locator.pending_cache), 0)

    def test_record_match_for_cache_appends_and_commits(self):
        """search_anchor 命中补写：record_match_for_cache 把命中截图加入 pending_cache，
        commit_cache 落盘到 {res}_{dpi}_{theme}/ 目录。闭合自学习链路。"""
        from pathlib import Path
        from backend.app.services.vision_locator import VisionLocator

        class FakeGray:
            """轻量灰度图替身（测试环境 numpy 已被全局 mock，无法用真数组切片）。"""
            def __init__(self, h, w):
                self.shape = (h, w)
            def __getitem__(self, sl):
                # 返回一个带 size 的 fake cropped
                rows = sl[0]
                cols = sl[1]
                fh = (rows.stop if rows.stop is not None else self.shape[0]) - (rows.start if rows.start is not None else 0)
                fw = (cols.stop if cols.stop is not None else self.shape[1]) - (cols.start if cols.start is not None else 0)
                cropped = MagicMock()
                cropped.size = max(0, fh) * max(0, fw)
                cropped.shape = (max(0, fh), max(0, fw))
                return cropped

        locator = VisionLocator()
        locator.clear_pending_cache()
        gray = FakeGray(200, 200)

        locator.record_match_for_cache(
            gray_source=gray,
            x=100, y=50, w=30, h=30,
            clean_name="wechat_add_button",
            dpi_scale=1.0,
            theme="light",
            resolution=(1920, 1080),
        )
        self.assertEqual(len(locator.pending_cache), 1)
        cache_file, img = locator.pending_cache[0]
        # 文件名 + 目录命名规则（分辨率_DPI_主题）
        self.assertEqual(cache_file.name, "wechat_add_button.png")
        self.assertIn("1920x1080_1.0_light", str(cache_file))
        # 截图带 ±5px padding → (30+10) x (30+10)
        self.assertEqual(img.shape, (40, 40))

        # commit 落盘
        with patch('cv2.imwrite') as mock_imwrite, patch.object(Path, 'mkdir'):
            locator.commit_cache()
        mock_imwrite.assert_called_once()
        self.assertEqual(str(mock_imwrite.call_args[0][0]), str(cache_file))
        self.assertEqual(len(locator.pending_cache), 0)

    def test_record_match_for_cache_invalid_rect_skips(self):
        """越界/空截图不写 pending_cache（防脏数据）。"""
        from pathlib import Path
        from unittest.mock import MagicMock
        from backend.app.services.vision_locator import VisionLocator

        class FakeGray:
            def __init__(self, h, w):
                self.shape = (h, w)
            def __getitem__(self, sl):
                rows = sl[0]; cols = sl[1]
                fh = (rows.stop if rows.stop is not None else self.shape[0]) - (rows.start if rows.start is not None else 0)
                fw = (cols.stop if cols.stop is not None else self.shape[1]) - (cols.start if cols.start is not None else 0)
                cropped = MagicMock()
                cropped.size = max(0, fh) * max(0, fw)
                return cropped

        locator = VisionLocator()
        locator.clear_pending_cache()
        gray = FakeGray(10, 10)
        # 坐标完全越界 → cropped.size == 0
        locator.record_match_for_cache(
            gray_source=gray,
            x=100, y=100, w=30, h=30,
            clean_name="wechat_add_button",
            dpi_scale=1.0, theme="light", resolution=(1920, 1080),
        )
        self.assertEqual(len(locator.pending_cache), 0)

    def test_ocr_track_does_not_pollute_pending_cache(self):
        """修复1：OCR 轨命中（含短关键词误命中）不写 pending_cache，避免错误位置污染缓存。

        模拟 1.0 DPI 下"添加"误命中聊天区中部场景：OCR 轨返回 ocr_ 命中，
        但 pending_cache 必须保持空（自学习只接受模板轨样本）。
        """
        import numpy as np
        from pathlib import Path
        from unittest.mock import MagicMock
        from backend.app.services.vision_locator import VisionLocator, OCR_INTENT_MAP
        from backend.app.services.platform import OcrWord, WindowHandle, SystemContext

        locator = VisionLocator()
        locator.clear_pending_cache()

        # mock ocr：返回一个含"添加"的误命中词块（模拟聊天区中部）
        mock_ocr = MagicMock()
        mock_ocr.recognize.return_value = [OcrWord(text="添加", x=400, y=300, width=40, height=20)]

        gray = np.zeros((646, 892), dtype=np.uint8)
        ctx = SystemContext(resolution=(1920, 1080), dpi_scale=1.0, is_dark_mode=False, language="zh-CN")

        result = locator._try_ocr_track(
            cv2=MagicMock(),
            ocr=mock_ocr,
            handle=WindowHandle(native_id=0),
            source_bgr=gray,
            gray_source=gray,
            cache_sub_dir=Path("backend/data/templates_cache/1920x1080_1.0_light"),
            template_names=["wechat_add_button"],
            left=29, top=124, width=892, height=646,
            context=ctx,
        )
        # OCR 轨命中了"添加"
        self.assertIsNotNone(result)
        self.assertTrue(result.template_name.startswith("ocr_"))
        # 关键断言：pending_cache 不被污染
        self.assertEqual(len(locator.pending_cache), 0,
                         "OCR 命中不得写入 pending_cache，否则误命中位置会被落盘成正式缓存")


class TestFuzzyTextHit(unittest.TestCase):
    """fuzzy_text_hit 的单元测试，重点覆盖 partial_ratio 短文本假阳性。"""

    def setUp(self):
        from backend.app.services.vision_locator import fuzzy_text_hit
        self.fuzzy_text_hit = fuzzy_text_hit

    # ---- 子串精确匹配（不依赖 rapidfuzz） ----

    def test_exact_substring_hit(self):
        """关键词是 OCR 文本的子串时应命中。"""
        result = self.fuzzy_text_hit("该用户不存在，请检查", ["该用户不存在"])
        self.assertEqual(result, "该用户不存在")

    def test_exact_substring_miss(self):
        """OCR 文本完全不含关键词时应返回 None。"""
        result = self.fuzzy_text_hit("添加到通讯录", ["该用户不存在", "搜索结果为空"])
        self.assertIsNone(result)

    # ---- partial_ratio 短文本假阳性回归测试 ----

    def test_short_ocr_word_should_not_match_long_keyword(self):
        """回归: OCR 词"搜索"不应匹配"搜索结果为空"或"你搜索的账号不存在"。

        这是 job_b5810110bdcb 的真实 bug：搜索按钮文字被 partial_ratio
        反向匹配到 TARGET_NOT_FOUND 关键词，导致已搜到的用户被判为未找到。
        """
        keywords = [
            "搜索结果为空",
            "你搜索的账号不存在",
            "该用户不存在",
            "未找到相关结果",
        ]
        result = self.fuzzy_text_hit("搜索", keywords)
        self.assertIsNone(result, "短 OCR 词'搜索'不应匹配到任何 TARGET_NOT_FOUND 关键词")

    def test_short_ocr_word_add_friends_no_false_positive(self):
        """OCR 词"朋友"不应匹配"添加朋友"等长关键词（通过 partial_ratio）。"""
        # "朋友" 长度 2，"添加朋友" 长度 4，比例 0.5 刚好在边界
        # 但真正有意义的匹配应该是子串命中，不是 partial_ratio
        keywords = ["添加朋友验证申请", "发送朋友验证"]
        result = self.fuzzy_text_hit("朋友", keywords)
        self.assertIsNone(result)

    # ---- partial_ratio 正常模糊匹配（OCR 拼错容错） ----

    def test_fuzzy_match_ocr_typo(self):
        """OCR 小幅拼错时 partial_ratio 应正常命中。"""
        # "添加到涌讯录" 是 OCR 把"通"识别为"涌"的真实案例
        result = self.fuzzy_text_hit("添加到涌讯录", ["添加到通讯录"])
        # 5/5 字，只差一个字，partial_ratio 应 >= 80
        self.assertEqual(result, "添加到通讯录")

    def test_fuzzy_match_with_similar_length(self):
        """长度相近时 partial_ratio 应正常工作。"""
        result = self.fuzzy_text_hit("搜索结果为空", ["搜索结果为空"])
        self.assertEqual(result, "搜索结果为空")

    def test_fuzzy_match_exact_keyword_in_longer_text(self):
        """关键词完整出现在较长 OCR 文本中时应命中。"""
        result = self.fuzzy_text_hit(
            "该用户不存在请检查你填写的账号是否正确",
            ["该用户不存在"],
        )
        self.assertEqual(result, "该用户不存在")

    # ---- 空格不敏感 ----

    def test_spaces_ignored(self):
        """OCR 文本中的空格应被忽略。"""
        result = self.fuzzy_text_hit("该 用 户 不 存 在", ["该用户不存在"])
        self.assertEqual(result, "该用户不存在")

    # ---- allow_fuzzy 参数行为 ----

    def test_allow_fuzzy_false_disables_partial_ratio(self):
        """allow_fuzzy=False 时仅做 substring，不做 partial_ratio。"""
        # OCR 拼错 "Add Frlends" vs 关键词 "Add Friends"
        result = self.fuzzy_text_hit("Add Frlends", ["Add Friends"], allow_fuzzy=False)
        self.assertIsNone(result, "allow_fuzzy=False 时拼错不应命中")

    def test_allow_fuzzy_true_keeps_ocr_typo_tolerance(self):
        """allow_fuzzy=True 时保持 OCR 拼错容错（回归）。"""
        result = self.fuzzy_text_hit("Add Frlends", ["Add Friends"], allow_fuzzy=True)
        self.assertEqual(result, "Add Friends")

    # ---- min_ratio 自适应（仅默认值时生效）----

    def test_min_ratio_adaptive_by_keyword_length(self):
        """短关键词要求更高 min_ratio（自适应）。"""
        # 关键词长度 2 → 自适应 min_ratio=90
        # "搜素" vs "搜索" → partial_ratio 约 67
        # 默认 min_ratio=None 时自适应为 90，67 < 90 不应命中
        result = self.fuzzy_text_hit("搜素", ["搜索"])
        self.assertIsNone(result, "短关键词应有更高相似度要求")

    def test_explicit_min_ratio_overrides_adaptive(self):
        """显式传 min_ratio 覆盖自适应。"""
        # 显式传 min_ratio=60，即使短关键词也使用该值（"搜素"vs"搜索"实际≈67）
        result = self.fuzzy_text_hit("搜素", ["搜索"], min_ratio=60)
        self.assertEqual(result, "搜索", "显式传值应覆盖自适应")

    # ---- full_text 假阳性回归 ----

    def test_full_text_fuzzy_disabled_direct(self):
        """直接测试 fuzzy_text_hit 在 allow_fuzzy=False 时的行为。"""
        # 构造场景：full_text = "添加朋友"，关键词 = "添加到通讯录"
        # 这两个有部分重叠，partial_ratio 可能给高分，但不是子串
        result = self.fuzzy_text_hit(
            "添加朋友",
            ["添加到通讯录"],
            min_ratio=80,
            allow_fuzzy=False
        )
        self.assertIsNone(result, "allow_fuzzy=False 时仅子串匹配，不应命中")

        # 同样场景 allow_fuzzy=True 可能命中（取决于相似度）
        result_fuzzy = self.fuzzy_text_hit(
            "添加朋友",
            ["添加到通讯录"],
            min_ratio=80,
            allow_fuzzy=True
        )
        # 这里我们不断言 fuzzy 一定命中，只确认它不抛异常即可


class TestCachedAddButtonGeometry(unittest.TestCase):
    """cached_vision 加号几何判定：0.18 下限适配"加号偏左"布局。

    根因：加号在微信主窗口的相对 x 随内部布局浮动。job 实证同尺寸(1118x809)
    同 DPI(1.25)下，加号 center 可在 606(偏左, ratio=0.315) 到 876(偏右, ratio=0.556)
    之间浮动。原 0.35 下限会把 ratio=0.315 的偏左加号误拒，导致主路径 Miss、
    降级到 search_anchor 慢路径。改为 0.18 后覆盖所有现实布局。
    """

    def _make_match(self, center_x, center_y, template_name="cache_wechat_add_button.png"):
        from backend.app.services.vision_locator import MatchResult
        return MatchResult(
            template_name=template_name,
            center_x=center_x,
            center_y=center_y,
            score=1.0,
        )

    def _run_cached_vision(self, window_rect, match_center):
        """跑 _click_wechat_add_button_by_cached_vision，返回 (result, clicked_coords)。

        window_rect: (left, top, right, bottom)
        match_center: (cx, cy) find_first 返回的命中中心
        """
        from backend.app.services import wechat_rpa
        from backend.app.services.vision_locator import MatchResult

        left, top, right, bottom = window_rect
        match = self._make_match(*match_center)
        clicked = []

        mock_desktop = MagicMock()
        mock_desktop.get_bounding_rectangle.return_value = window_rect
        mock_desktop.click.side_effect = lambda x, y: clicked.append((x, y))

        with patch('backend.app.services.wechat_rpa.vision') as mock_vision, \
             patch('backend.app.services.wechat_rpa.get_desktop_adapter', return_value=mock_desktop):
            mock_vision.find_first.return_value = match
            result = wechat_rpa._click_wechat_add_button_by_cached_vision(None, MagicMock())
        return result, clicked

    def test_left_layout_add_button_not_rejected(self):
        """偏左布局（job 实证 center=606, ratio=0.315）不应被几何拒。

        回归保护：0.35 下限会拒掉这个 case，改 0.18 后必须放行并点击。
        """
        # job 真实数据：window left=254 w=1118，加号 center=(606,184)
        result, clicked = self._run_cached_vision((254, 113, 1372, 922), (606, 184))
        self.assertIsNotNone(result, "偏左布局加号不应被几何阈值误拒")
        self.assertEqual(clicked, [(606, 184)])

    def test_right_layout_add_button_passes(self):
        """偏右布局（实测 center=876, ratio=0.556）放行。"""
        result, clicked = self._run_cached_vision((254, 113, 1372, 922), (876, 184))
        self.assertIsNotNone(result)
        self.assertEqual(clicked, [(876, 184)])

    def test_too_left_still_rejected(self):
        """极左（ratio<0.18）仍应拒，避免误点左侧边缘元素。"""
        # width=1118, 0.18*1118=201，local_x=150 → ratio=0.134 < 0.18
        result, clicked = self._run_cached_vision((254, 113, 1372, 922), (254 + 150, 184))
        self.assertIsNone(result, "ratio<0.18 的极左命中仍应被拒")
        self.assertEqual(clicked, [])

    def test_too_right_still_rejected(self):
        """极右（ratio>0.75）仍应拒。"""
        # width=1118, 0.75*1118=838，local_x=900 → ratio=0.805 > 0.75
        result, clicked = self._run_cached_vision((254, 113, 1372, 922), (254 + 900, 184))
        self.assertIsNone(result, "ratio>0.75 的极右命中仍应被拒")
        self.assertEqual(clicked, [])

    def test_too_low_still_rejected(self):
        """y 超过顶部 22% 仍应拒（防误点聊天列表区）。"""
        # height=809, top_limit=max(120, 0.22*809)=177，local_y=300
        result, clicked = self._run_cached_vision((254, 113, 1372, 922), (606, 113 + 300))
        self.assertIsNone(result, "y 超过顶部 22% 的命中仍应被拒")
        self.assertEqual(clicked, [])

    def test_ocr_hit_rejected(self):
        """OCR 命中（template_name 以 ocr_ 开头）应拒绝，避免全窗口误点。"""
        from backend.app.services import wechat_rpa
        from backend.app.services.vision_locator import MatchResult

        match = MatchResult(
            template_name="ocr_wechat_add_button.png",
            center_x=606, center_y=184, score=1.0,
        )
        mock_desktop = MagicMock()
        mock_desktop.get_bounding_rectangle.return_value = (254, 113, 1372, 922)
        with patch('backend.app.services.wechat_rpa.vision') as mock_vision, \
             patch('backend.app.services.wechat_rpa.get_desktop_adapter', return_value=mock_desktop):
            mock_vision.find_first.return_value = match
            result = wechat_rpa._click_wechat_add_button_by_cached_vision(None, MagicMock())
        self.assertIsNone(result, "OCR 命中应被拒绝")


class TestAddFriendsMenuOffset(unittest.TestCase):
    """菜单"添加朋友"偏移兜底：+86 → 86*dpi_scale（多 DPI 适配）+ 点完校验。

    实测：1.0 DPI 下"添加朋友"距加号 86px，1.25 DPI 下 105px ≈ 86×1.25。
    原硬编码 +86 只在 1.0 准确，高 DPI 下偏小会点到上方菜单项。
    """

    def _run_offset(self, dpi_scale, verify_found, add_plus_center=(606, 184)):
        """模拟模板匹配菜单项失败 → 走偏移兜底。返回 (clicked_coords, raised, marks)。"""
        from backend.app.services import wechat_rpa
        from backend.app.services.vision_locator import MatchResult
        from backend.app.core.errors import AppError

        add_plus_match = MatchResult(
            template_name="cache_wechat_add_button.png",
            center_x=add_plus_center[0], center_y=add_plus_center[1], score=1.0,
        )
        clicked = []
        marks = []

        mock_desktop = MagicMock()
        # wx_window rect: left=254 top=113 w=1118 h=809 (job 真实)
        mock_desktop.get_bounding_rectangle.return_value = (254, 113, 1372, 922)
        mock_desktop.click.side_effect = lambda x, y: clicked.append((x, y))

        mock_ocr = MagicMock()
        mock_ocr.get_dpi_scale.return_value = dpi_scale

        raised = None
        with patch('backend.app.services.wechat_rpa.vision') as mock_vision, \
             patch('backend.app.services.wechat_rpa.get_desktop_adapter', return_value=mock_desktop), \
             patch('backend.app.services.wechat_rpa.get_ocr_adapter', return_value=mock_ocr), \
             patch('backend.app.services.wechat_rpa._find_add_friends_window_fast', return_value=verify_found), \
             patch('backend.app.services.wechat_rpa._click_wechat_add_button_by_cached_vision', return_value=add_plus_match), \
             patch('backend.app.services.wechat_rpa._click_wechat_add_button_by_search_anchor'), \
             patch('backend.app.services.wechat_rpa._sleep'):
            # click_first 抛 AppError → 触发偏移兜底
            mock_vision.click_first.side_effect = AppError("VISION_TARGET_NOT_FOUND", "菜单项未匹配")
            try:
                wechat_rpa._open_add_friends_entry(None, MagicMock(), marks.append)
            except AppError as e:
                raised = e
        return clicked, raised, marks

    def test_offset_scales_with_dpi_1_0(self):
        """1.0 DPI 下偏移 = 86。"""
        clicked, raised, marks = self._run_offset(1.0, verify_found=MagicMock())
        self.assertIsNone(raised)
        # 加号 center_y=184 + 86 = 270
        self.assertEqual(clicked[-1], (606, 270))
        self.assertTrue(any("ADD_FRIENDS_MENU_OFFSET_VERIFIED" in m for m in marks))

    def test_offset_scales_with_dpi_1_25(self):
        """1.25 DPI 下偏移 = round(86*1.25)=108（实测真值 105，误差取整可接受）。"""
        clicked, raised, _ = self._run_offset(1.25, verify_found=MagicMock())
        self.assertIsNone(raised)
        # 184 + 108 = 292（实测真菜单项 289，差 3px 在菜单项高度内）
        self.assertEqual(clicked[-1], (606, 292))

    def test_offset_scales_with_dpi_1_5(self):
        """1.5 DPI 下偏移 = round(86*1.5)=129。原 +86 会偏小 43px，改后正确。"""
        clicked, raised, _ = self._run_offset(1.5, verify_found=MagicMock())
        self.assertIsNone(raised)
        self.assertEqual(clicked[-1], (606, 184 + 129))

    def test_offset_clamped_to_bottom(self):
        """偏移不超出窗口底部（bottom-20）。"""
        # 加号 center_y 故意设很大，逼近底部
        clicked, raised, _ = self._run_offset(1.5, verify_found=MagicMock(), add_plus_center=(606, 800))
        self.assertIsNone(raised)
        # bottom=922, bottom-20=902，902 < 800+129=929 → clamp 到 902
        self.assertEqual(clicked[-1][1], 902)

    def test_verify_failure_raises(self):
        """偏移点击后未检测到"添加朋友"窗口 → 抛 ADD_FRIENDS_MENU_OFFSET_MISS，不静默继续。"""
        clicked, raised, marks = self._run_offset(1.0, verify_found=None)
        self.assertIsNotNone(raised, "校验失败应抛错而非静默继续")
        self.assertEqual(raised.detail.get("code"), "ADD_FRIENDS_MENU_OFFSET_MISS")
        self.assertTrue(any("ADD_FRIENDS_PAGE_OPENED_BY_MENU_OFFSET" in m for m in marks))
        self.assertFalse(any("ADD_FRIENDS_MENU_OFFSET_VERIFIED" in m for m in marks))

    def test_offset_floor_when_dpi_unknown(self):
        """DPI 读取异常时回退 1.0，偏移仍 ≥20（防 0 偏移点到加号自身）。"""
        # dpi_scale=0.0 模拟异常回退（实际代码 try/except 回退 1.0，这里测 max(20,...) 兜底）
        clicked, raised, _ = self._run_offset(0.0, verify_found=MagicMock())
        self.assertIsNone(raised)
        # max(20, round(86*0))=max(20,0)=20 → 184+20=204
        self.assertEqual(clicked[-1], (606, 204))


class TestConfirmFriendProfileOffset(unittest.TestCase):
    """_confirm_friend_profile_window 偏移兜底：底部按钮 y 偏移按 DPI 缩放。

    原 min(40, max(28, height*0.05)) 混用绝对像素 28/40 与比例，高 DPI 下不缩放。
    改为 round(34*dpi_scale)，与菜单 +86 偏移同思路。
    """

    def _run_confirm_offset(self, dpi_scale, window_rect=(100, 100, 700, 700)):
        """模拟"通过朋友验证"页 + 模板失败 → 走偏移兜底。返回 (clicked, raised)。"""
        from backend.app.services import wechat_rpa
        from backend.app.core.errors import AppError
        from backend.app.services.platform import WindowHandle

        left, top, right, bottom = window_rect
        width = right - left
        height = bottom - top
        clicked = []

        mock_desktop = MagicMock()
        mock_desktop.get_bounding_rectangle.return_value = window_rect
        mock_desktop.click.side_effect = lambda x, y: clicked.append((x, y))

        mock_ocr = MagicMock()
        mock_ocr.get_dpi_scale.return_value = dpi_scale

        target = WindowHandle(native_id=12345, rect=window_rect)

        raised = None
        with patch('backend.app.services.wechat_rpa._window_name', return_value='通过朋友验证'), \
             patch('backend.app.services.wechat_rpa.vision') as mock_vision, \
             patch('backend.app.services.wechat_rpa.get_desktop_adapter', return_value=mock_desktop), \
             patch('backend.app.services.wechat_rpa.get_ocr_adapter', return_value=mock_ocr), \
             patch('backend.app.services.wechat_rpa._find_verify_window', return_value=None), \
             patch('backend.app.services.wechat_rpa._sleep'):
            # 模板匹配失败 → 触发偏移兜底
            mock_vision.click_first.side_effect = AppError("VISION_TARGET_NOT_FOUND", "确认按钮未匹配")
            try:
                ret = wechat_rpa._confirm_friend_profile_window(target, lambda s: None)
            except AppError as e:
                raised = e
        return clicked, raised, (ret if not raised else None)

    def test_offset_scales_with_dpi_1_0(self):
        """1.0 DPI 下底部偏移 = 34。"""
        # window bottom=700, 700-34=666
        clicked, raised, ret = self._run_confirm_offset(1.0)
        self.assertIsNone(raised)
        self.assertTrue(ret)
        self.assertEqual(clicked[-1][0], 100 + int(600 * 0.28))  # click_x 纯比例
        self.assertEqual(clicked[-1][1], 700 - 34)

    def test_offset_scales_with_dpi_1_25(self):
        """1.25 DPI 下底部偏移 = round(34*1.25)=42（Python round 银行家舍入）。
        原 28/40 clamp 在 1.25 下仍卡 40，偏小。"""
        clicked, raised, ret = self._run_confirm_offset(1.25)
        self.assertIsNone(raised)
        self.assertTrue(ret)
        self.assertEqual(clicked[-1][1], 700 - 42)

    def test_offset_scales_with_dpi_1_5(self):
        """1.5 DPI 下底部偏移 = round(34*1.5)=51。"""
        clicked, raised, ret = self._run_confirm_offset(1.5)
        self.assertIsNone(raised)
        self.assertEqual(clicked[-1][1], 700 - 51)

    def test_offset_floor_when_dpi_low(self):
        """DPI 异常低时偏移 ≥15（防 0 偏移点到窗口最底边外）。"""
        clicked, raised, ret = self._run_confirm_offset(0.1)
        self.assertIsNone(raised)
        # max(15, round(34*0.1))=max(15,3)=15
        self.assertEqual(clicked[-1][1], 700 - 15)

    def test_x_is_pure_ratio(self):
        """click_x 是纯比例 0.28，不随 DPI 变（多 DPI 下 x 行为一致）。"""
        c1, _, _ = self._run_confirm_offset(1.0)
        c2, _, _ = self._run_confirm_offset(1.5)
        self.assertEqual(c1[-1][0], c2[-1][0], "click_x 应为纯比例，与 DPI 无关")


if __name__ == '__main__':
    unittest.main()

