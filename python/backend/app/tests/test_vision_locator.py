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


if __name__ == '__main__':
    unittest.main()
