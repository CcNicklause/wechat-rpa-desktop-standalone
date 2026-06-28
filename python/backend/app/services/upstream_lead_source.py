import threading
from collections.abc import Callable
from typing import Any

from backend.app.services.upstream_client import UpstreamClientInterface


class PollingLeadSource:
    def __init__(
        self,
        client: UpstreamClientInterface,
        enqueue_lead: Callable[[dict[str, Any]], bool],
        interval_seconds: float,
        log: Callable[[str], None],
        is_frozen: Callable[[], bool] | None = None,
    ):
        self.client = client
        self.enqueue_lead = enqueue_lead
        self.interval_seconds = float(interval_seconds)
        self.log = log
        # 用回调注入而不是 scheduler 引用，避免循环依赖；为旧调用方留 None 默认值。
        self.is_frozen = is_frozen or (lambda: False)

    def fetch_once(self) -> int:
        self.log("正在尝试拉取待添加线索...")
        leads = self.client.fetch_leads()
        if not leads:
            self.log("暂无待加微线索")
            return 0

        self.log(f"📥 成功拉取到 {len(leads)} 个线索")
        enqueued_count = 0
        for item in leads:
            if self.enqueue_lead(item):
                enqueued_count += 1
        return enqueued_count

    def run(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            # RISK_FROZEN 期间跳过 fetch（设计 §1）：本地队列已 enqueue 的任务会
            # 在 worker_loop 里被回插队尾，新一波远端线索不应该再叠加进来。
            if self.is_frozen():
                self.log("⏸ 调度器 RISK_FROZEN 中，本轮跳过远端拉取")
            else:
                try:
                    self.fetch_once()
                except Exception as e:
                    self.log(f"拉取循环异常: {e}")
            stop_event.wait(self.interval_seconds)
