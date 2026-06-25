import threading
from collections.abc import Callable


def run_background(target: Callable[[], None]) -> None:
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
