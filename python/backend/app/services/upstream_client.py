import abc
import threading
import httpx
from typing import Any, Callable, Dict, List, Optional


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
    """对接真实上游 HTTP。所有鉴权调用走 `_call_with_relogin` 包装：
    收到 401 时单点重新 login，并用新 token 重试一次；并发场景由
    `_login_lock + _token_version` 保证只触发一次实际 login()。"""

    def __init__(self, api_url: str, client_id: str, client_secret: str):
        self.api_url = api_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.token: Optional[str] = None
        self._login_lock = threading.Lock()
        # 每次成功 login() 自增，用来识别"我看到的 token 是否已被别的线程换过"
        self._token_version = 0

    def login(self) -> bool:
        with self._login_lock:
            return self._login_locked()

    def _login_locked(self) -> bool:
        """实际登录逻辑，调用方必须已持有 self._login_lock。成功时刷新 self.token 与 token 版本号。"""
        try:
            r = httpx.post(
                f"{self.api_url}/login",
                json={"client_id": self.client_id, "client_secret": self.client_secret},
                timeout=10.0,
            )
            if r.status_code == 200:
                self.token = r.json().get("access_token")
                self._token_version += 1
                return True
        except Exception as e:
            print(f"[Real Upstream] Login error: {e}")
        return False

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _call_with_relogin(self, do_request: Callable[[], httpx.Response]) -> Optional[httpx.Response]:
        """统一包装：执行 do_request；若 401 则在锁内尝试 login() 一次，然后用新 token
        重试一次。do_request 内部必须每次都重新 self._headers() 取最新 token，
        否则续签后无法生效。"""
        token_version_at_entry = self._token_version
        try:
            resp = do_request()
        except Exception as exc:
            print(f"[Real Upstream] HTTP error: {exc}")
            return None
        if resp.status_code != 401:
            return resp

        # 401 → 尝试续签。若同期已有其他线程续签过（token_version 变了），就跳过实际登录直接重试。
        relogin_ok = True
        with self._login_lock:
            if self._token_version == token_version_at_entry:
                relogin_ok = self._login_locked()
                if not relogin_ok:
                    print("[Real Upstream] ⚠️ 上游 token 续签失败，请检查 client_id/secret")
        if not relogin_ok:
            return resp

        try:
            return do_request()
        except Exception as exc:
            print(f"[Real Upstream] HTTP retry error: {exc}")
            return None

    def send_heartbeat(self, status: str, wechat_online: bool, net_info: dict) -> bool:
        payload = {
            "client_id": self.client_id,
            "status": status,
            "wechat_online": wechat_online,
            **net_info,
        }

        def _do() -> httpx.Response:
            return httpx.post(
                f"{self.api_url}/heartbeat",
                json=payload,
                headers=self._headers(),
                timeout=10.0,
            )

        resp = self._call_with_relogin(_do)
        return resp is not None and resp.status_code == 200

    def fetch_leads(self) -> List[Dict[str, Any]]:
        def _do() -> httpx.Response:
            return httpx.get(
                f"{self.api_url}/leads/pending",
                headers=self._headers(),
                timeout=10.0,
            )

        resp = self._call_with_relogin(_do)
        if resp is not None and resp.status_code == 200:
            try:
                return resp.json()
            except Exception:
                pass
        return []

    def report_lead_status(
        self, lead_id: str, status: str, remark: Optional[str], error_details: Optional[str]
    ) -> bool:
        payload = {
            "lead_id": lead_id,
            "status": status,
            "remark": remark,
            "error_details": error_details,
        }

        def _do() -> httpx.Response:
            return httpx.post(
                f"{self.api_url}/leads/report",
                json=payload,
                headers=self._headers(),
                timeout=10.0,
            )

        resp = self._call_with_relogin(_do)
        return resp is not None and resp.status_code == 200

    def report_friend_check(self, lead_id: str, is_friend: bool) -> bool:
        payload = {"lead_id": lead_id, "is_friend": is_friend}

        def _do() -> httpx.Response:
            return httpx.post(
                f"{self.api_url}/leads/friend-check",
                json=payload,
                headers=self._headers(),
                timeout=10.0,
            )

        resp = self._call_with_relogin(_do)
        return resp is not None and resp.status_code == 200
