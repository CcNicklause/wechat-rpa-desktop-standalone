import gc
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

# friend_acceptance 复用 wechat_rpa 模块；单测只测服务状态流转，不加载真实 GUI 依赖。
sys.modules.setdefault('cv2', MagicMock())
sys.modules.setdefault('numpy', MagicMock())
sys.modules.setdefault('pyautogui', MagicMock())
sys.modules.setdefault('PIL', MagicMock())
sys.modules.setdefault('PIL.Image', MagicMock())

from backend.app.core.errors import AppError
from backend.app.schemas.lead import LeadStatus
from backend.app.services import friend_acceptance
from backend.app.services.friend_acceptance import (
    FriendAcceptanceCheckResult,
    FriendAcceptanceService,
)
from backend.app.storage.sqlite_store import SQLiteStore


class TestFriendAcceptanceService(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(Path(self.temp_dir.name) / 'demo.db')
        self.audit = MagicMock()

    def tearDown(self) -> None:
        self.store = None
        gc.collect()
        self.temp_dir.cleanup()

    def test_check_lead_marks_accepted_when_ocr_matches_friend_state(self):
        self._create_lead('lead_accept', LeadStatus.WECHAT_ADD_REQUESTED)

        def checker(phone: str, **kwargs):
            return FriendAcceptanceCheckResult(
                phone=phone,
                accepted=True,
                state='ALREADY_FRIEND',
                matched_text='发消息',
                screenshot_path='backend/data/friend_acceptance_lead_accept_after_search.png',
                steps=['OCR_RAW_TEXT: 发消息'],
            )

        service = FriendAcceptanceService(self.store, self.audit, checker=checker)

        result = service.check_lead('lead_accept')

        self.assertTrue(result['accepted'])
        self.assertEqual(result['state'], 'ALREADY_FRIEND')
        self.assertEqual(
            self.store.get_lead('lead_accept')['status'],
            LeadStatus.WECHAT_ACCEPTED.value,
        )
        self.audit.record.assert_called_once()
        self.assertEqual(self.audit.record.call_args.args[0], 'wechat.friend.accepted')

    def test_check_lead_keeps_pending_when_friend_state_not_detected(self):
        self._create_lead('lead_pending', LeadStatus.WECHAT_ADD_REQUESTED)

        def checker(phone: str, **kwargs):
            return FriendAcceptanceCheckResult(
                phone=phone,
                accepted=False,
                state='PENDING',
                matched_text='添加到通讯录',
                steps=['OCR_RAW_TEXT: 添加到通讯录'],
            )

        service = FriendAcceptanceService(self.store, self.audit, checker=checker)

        result = service.check_lead('lead_pending')

        self.assertFalse(result['accepted'])
        self.assertEqual(
            self.store.get_lead('lead_pending')['status'],
            LeadStatus.WECHAT_ADD_REQUESTED.value,
        )
        self.audit.record.assert_called_once()
        self.assertEqual(
            self.audit.record.call_args.args[0],
            'wechat.friend.acceptance_checked',
        )

    def test_check_pending_only_scans_waiting_add_requests(self):
        self._create_lead('lead_pending', LeadStatus.WECHAT_ADD_REQUESTED)
        self._create_lead('lead_new', LeadStatus.NEW_LEAD)
        checked_phones = []

        def checker(phone: str, **kwargs):
            checked_phones.append(phone)
            return FriendAcceptanceCheckResult(phone=phone, accepted=False, state='PENDING')

        service = FriendAcceptanceService(self.store, self.audit, checker=checker)

        result = service.check_pending(limit=10)

        self.assertEqual(result['checked'], 1)
        self.assertEqual(result['accepted'], 0)
        self.assertEqual(checked_phones, ['18325661362'])

    def test_check_by_phone_preserves_wechat_not_found_when_cleanup_fails(self):
        with patch.object(
            friend_acceptance.wechat_rpa,
            '_find_wechat_window',
            return_value=None,
        ), patch.object(
            friend_acceptance.wechat_rpa,
            'get_desktop_adapter',
            side_effect=RuntimeError('desktop unavailable'),
        ):
            with self.assertRaises(AppError) as context:
                friend_acceptance.check_friend_acceptance_by_phone('18325661362')

        self.assertEqual(context.exception.detail['code'], 'WECHAT_NOT_FOUND')

    def _create_lead(self, lead_id: str, status: LeadStatus) -> None:
        self.store.create_lead(
            {
                'lead_id': lead_id,
                'customer_name': '测试客户',
                'company': '测试公司',
                'phone': '18325661362',
                'sales_id': 'sales_demo_001',
                'status': status.value,
                'created_at': '2026-06-24T00:00:00+00:00',
                'updated_at': '2026-06-24T00:00:00+00:00',
            }
        )


if __name__ == '__main__':
    unittest.main()
