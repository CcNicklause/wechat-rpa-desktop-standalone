import abc
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
        self._fetched = False

    def login(self) -> bool:
        self.token = "mock-bearer-token-123456"
        return True

    def send_heartbeat(self, status: str, wechat_online: bool, net_info: dict) -> bool:
        print(f"[Mock Upstream] 心跳成功: status={status}, wechat_online={wechat_online}")
        return True

    def fetch_leads(self) -> List[Dict[str, Any]]:
        # 仅下发一次，防止重复无休止添加
        if self._fetched:
            return []
        self._fetched = True
        return [
            {
                "lead_id": "mock_lead_1",
                "phone": "13800000001",
                "customer_name": "莫克测试1",
                "greeting": "测试上游线索，请求通过。",
            }
        ]

    def report_lead_status(
        self, lead_id: str, status: str, remark: Optional[str], error_details: Optional[str]
    ) -> bool:
        print(f"[Mock Upstream] 结果上报: {lead_id} -> {status}, remark={remark}")
        return True

    def report_friend_check(self, lead_id: str, is_friend: bool) -> bool:
        print(f"[Mock Upstream] 好友对账反馈: {lead_id} -> is_friend={is_friend}")
        return True


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
