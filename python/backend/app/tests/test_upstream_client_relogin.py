"""RealUpstreamClient 401 自动续签测试（Cycle 1 需求 6）。

用 monkeypatch 替换 httpx.post / httpx.get；按 (path, call_count)
返回预设的 fake response，验证：
- 401 触发 _login_locked 一次后用新 token 重试
- /login 持续 500 时 send_heartbeat 返回 False 不死循环
- 并发 401 仅触发一次实际 login
- 非 401 不触发续签
"""
from __future__ import annotations

import threading
from typing import Callable
from unittest.mock import MagicMock

import httpx
import pytest

from backend.app.services.upstream_client import RealUpstreamClient


class _FakeResponse:
    def __init__(self, status_code: int, body: dict | None = None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body


def _patch_httpx(monkeypatch, post_router: Callable[..., _FakeResponse], get_router: Callable[..., _FakeResponse] | None = None):
    monkeypatch.setattr("backend.app.services.upstream_client.httpx.post", post_router)
    if get_router is not None:
        monkeypatch.setattr("backend.app.services.upstream_client.httpx.get", get_router)


def test_send_heartbeat_relogins_and_retries_on_401(monkeypatch):
    """heartbeat 第一次 401 → login 一次 → 用新 token 重试 → 200。"""
    state = {"login_calls": 0, "hb_calls": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        if url.endswith("/login"):
            state["login_calls"] += 1
            return _FakeResponse(200, {"access_token": f"token-v{state['login_calls']}"})
        if url.endswith("/heartbeat"):
            state["hb_calls"] += 1
            if state["hb_calls"] == 1:
                return _FakeResponse(401)
            assert headers["Authorization"] == "Bearer token-v1"
            return _FakeResponse(200)
        raise AssertionError(f"Unexpected URL {url}")

    _patch_httpx(monkeypatch, fake_post)

    client = RealUpstreamClient("http://upstream", "c1", "s1")
    ok = client.send_heartbeat("IDLE", True, {"hostname": "h", "ip": "1.1.1.1", "mac": "00:00"})

    assert ok is True
    assert state["login_calls"] == 1, "首次 401 应该恰好触发一次 login"
    assert state["hb_calls"] == 2, "heartbeat 应该被重试一次"


def test_send_heartbeat_returns_false_when_relogin_fails(monkeypatch):
    """heartbeat 401 但 login 总 500：返回 False，不死循环。"""
    state = {"hb_calls": 0, "login_calls": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        if url.endswith("/login"):
            state["login_calls"] += 1
            return _FakeResponse(500)
        if url.endswith("/heartbeat"):
            state["hb_calls"] += 1
            return _FakeResponse(401)
        raise AssertionError(url)

    _patch_httpx(monkeypatch, fake_post)
    client = RealUpstreamClient("http://upstream", "c1", "s1")

    ok = client.send_heartbeat("IDLE", True, {})
    assert ok is False
    assert state["login_calls"] == 1
    assert state["hb_calls"] == 1, "续签失败不应该再额外重试 heartbeat"


def test_concurrent_401_triggers_single_login(monkeypatch):
    """5 个线程同时撞 401 → 只触发 1 次 login → 全部重试成功。"""
    state = {
        "login_calls": 0,
        "lock": threading.Lock(),
        "first_hb_per_thread": set(),
    }

    barrier = threading.Barrier(5)

    def fake_post(url, json=None, headers=None, timeout=None):
        if url.endswith("/login"):
            with state["lock"]:
                state["login_calls"] += 1
                token = f"token-v{state['login_calls']}"
            return _FakeResponse(200, {"access_token": token})
        if url.endswith("/heartbeat"):
            tid = threading.get_ident()
            with state["lock"]:
                is_first = tid not in state["first_hb_per_thread"]
                if is_first:
                    state["first_hb_per_thread"].add(tid)
            if is_first:
                # 在锁外等：让 5 个线程都拿到 401 第一次响应后再放行 → 模拟并发 401
                try:
                    barrier.wait(timeout=2.0)
                except threading.BrokenBarrierError:
                    pass
                return _FakeResponse(401)
            return _FakeResponse(200)
        raise AssertionError(url)

    _patch_httpx(monkeypatch, fake_post)
    client = RealUpstreamClient("http://upstream", "c1", "s1")

    results = []
    results_lock = threading.Lock()
    def runner():
        ok = client.send_heartbeat("IDLE", True, {})
        with results_lock:
            results.append(ok)

    threads = [threading.Thread(target=runner) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert len(results) == 5, "所有线程都应该完成"
    assert all(results), f"所有线程都应该最终成功，实际 {results}"
    assert state["login_calls"] == 1, f"并发 401 只应触发一次 login，实际 {state['login_calls']}"


def test_non_401_does_not_trigger_relogin(monkeypatch):
    state = {"login_calls": 0, "hb_calls": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        if url.endswith("/login"):
            state["login_calls"] += 1
            return _FakeResponse(200, {"access_token": "t"})
        if url.endswith("/heartbeat"):
            state["hb_calls"] += 1
            return _FakeResponse(500)
        raise AssertionError(url)

    _patch_httpx(monkeypatch, fake_post)
    client = RealUpstreamClient("http://upstream", "c1", "s1")

    ok = client.send_heartbeat("IDLE", True, {})
    assert ok is False
    assert state["login_calls"] == 0, "非 401 不应该触发 login"
    assert state["hb_calls"] == 1


def test_report_lead_status_relogins_on_401(monkeypatch):
    state = {"login_calls": 0, "report_calls": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        if url.endswith("/login"):
            state["login_calls"] += 1
            return _FakeResponse(200, {"access_token": "t1"})
        if url.endswith("/leads/report"):
            state["report_calls"] += 1
            if state["report_calls"] == 1:
                return _FakeResponse(401)
            return _FakeResponse(200)
        raise AssertionError(url)

    _patch_httpx(monkeypatch, fake_post)
    client = RealUpstreamClient("http://upstream", "c1", "s1")
    ok = client.report_lead_status("lead_a", "REAL_SENT", "remark", None)

    assert ok is True
    assert state["login_calls"] == 1
    assert state["report_calls"] == 2


def test_fetch_leads_relogins_on_401(monkeypatch):
    state = {"login_calls": 0, "fetch_calls": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        if url.endswith("/login"):
            state["login_calls"] += 1
            return _FakeResponse(200, {"access_token": "t1"})
        raise AssertionError(url)

    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/leads/pending"):
            state["fetch_calls"] += 1
            if state["fetch_calls"] == 1:
                return _FakeResponse(401)
            return _FakeResponse(200, body=[{"lead_id": "x"}])
        raise AssertionError(url)

    _patch_httpx(monkeypatch, fake_post, fake_get)
    client = RealUpstreamClient("http://upstream", "c1", "s1")
    leads = client.fetch_leads()

    assert leads == [{"lead_id": "x"}]
    assert state["login_calls"] == 1
    assert state["fetch_calls"] == 2
