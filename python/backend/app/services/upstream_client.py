import abc
import threading
import httpx
from typing import List, Dict, Any, Optional


class UpstreamClientInterface(abc.ABC):
    @abc.abstractmethod
    def login(self) -> bool: pass

    @abc.abstractmethod
    def send_heartbeat(self, status: str, wechat_online: bool, net_info: dict) -> bool: pass

    @abc.abstractmethod
    def fetch_leads(self) -> List[Dict[str, Any]]: pass

    @abc.abstractmethod
    def report_lead_status(
        self, lead_id: str, status: str, remark: Optional[str], error_details: Optional[str]
    ) -> bool: pass

    @abc.abstractmethod
    def report_friend_check(self, lead_id: str, is_friend: bool) -> bool: pass


class MockUpstreamClient(UpstreamClientInterface):
    def __init__(self):
        self.token = None
        self._pending_leads: List[Dict[str, Any]] = []
        self._friend_check_reports: List[Dict[str, Any]] = []
        self._pending_lock = threading.Lock()
        self._reports_lock = threading.Lock()

    def login(self) -> bool:
        self.token = "mock-bearer-token-123456"
        return True

    def send_heartbeat(self, status: str, wechat_online: bool, net_info: dict) -> bool:
        print(f"[Mock Upstream] 心跳成功: status={status}, wechat_online={wechat_online}")
        return True

    def seed_leads(self, leads: List[Dict[str, Any]]) -> int:
        """注入一批 mock 线索到待发池；返回入池数量。同一 lead_id 在池中只保留一条。"""
        added = 0
        with self._pending_lock:
            existing_ids = {item.get("lead_id") for item in self._pending_leads}
            for lead in leads:
                lead_id = lead.get("lead_id")
                if not lead_id or lead_id in existing_ids:
                    continue
                self._pending_leads.append(lead)
                existing_ids.add(lead_id)
                added += 1
        return added

    def fetch_leads(self) -> List[Dict[str, Any]]:
        with self._pending_lock:
            out = list(self._pending_leads)
            self._pending_leads.clear()
            return out

    def report_lead_status(
        self, lead_id: str, status: str, remark: Optional[str], error_details: Optional[str]
    ) -> bool:
        print(f"[Mock Upstream] 结果上报: {lead_id} -> {status}, remark={remark}")
        return True

    def report_friend_check(self, lead_id: str, is_friend: bool) -> bool:
        with self._reports_lock:
            self._friend_check_reports.append({
                "lead_id": lead_id,
                "is_friend": bool(is_friend),
            })
        print(f"[Mock Upstream] 好友对账反馈: {lead_id} -> is_friend={is_friend}")
        return True

    def friend_check_reports(self) -> List[Dict[str, Any]]:
        with self._reports_lock:
            return list(self._friend_check_reports)


class RealUpstreamClient(UpstreamClientInterface):
    def __init__(self, api_url: str, client_id: str, client_secret: str):
        self.api_url = api_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.token: Optional[str] = None

    def login(self) -> bool:
        try:
            r = httpx.post(
                f"{self.api_url}/login",
                json={"client_id": self.client_id, "client_secret": self.client_secret},
                timeout=10.0,
            )
            if r.status_code == 200:
                self.token = r.json().get("access_token")
                return True
        except Exception as e:
            print(f"[Real Upstream] Login error: {e}")
        return False

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def send_heartbeat(self, status: str, wechat_online: bool, net_info: dict) -> bool:
        try:
            payload = {
                "client_id": self.client_id,
                "status": status,
                "wechat_online": wechat_online,
                **net_info,
            }
            r = httpx.post(
                f"{self.api_url}/heartbeat",
                json=payload,
                headers=self._headers(),
                timeout=10.0,
            )
            return r.status_code == 200
        except Exception:
            return False

    def fetch_leads(self) -> List[Dict[str, Any]]:
        try:
            r = httpx.get(
                f"{self.api_url}/leads/pending",
                headers=self._headers(),
                timeout=10.0,
            )
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return []

    def report_lead_status(
        self, lead_id: str, status: str, remark: Optional[str], error_details: Optional[str]
    ) -> bool:
        try:
            payload = {
                "lead_id": lead_id,
                "status": status,
                "remark": remark,
                "error_details": error_details,
            }
            r = httpx.post(
                f"{self.api_url}/leads/report",
                json=payload,
                headers=self._headers(),
                timeout=10.0,
            )
            return r.status_code == 200
        except Exception:
            return False

    def report_friend_check(self, lead_id: str, is_friend: bool) -> bool:
        try:
            payload = {"lead_id": lead_id, "is_friend": is_friend}
            r = httpx.post(
                f"{self.api_url}/leads/friend-check",
                json=payload,
                headers=self._headers(),
                timeout=10.0,
            )
            return r.status_code == 200
        except Exception:
            return False
