import gc
import tempfile
from pathlib import Path
from backend.app.storage.sqlite_store import SQLiteStore


def test_save_and_get_config():
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        db_path = Path(tmp_dir.name) / "test.db"
        store = SQLiteStore(db_path)
        test_cfg = {"upstream_mode": "mock", "client_id": "test_c"}
        store.save_upstream_config(test_cfg)
        loaded = store.get_upstream_config()
        assert loaded["upstream_mode"] == "mock"
        assert loaded["client_id"] == "test_c"
    finally:
        # 释放 SQLite 文件锁后再清理临时目录
        store = None
        gc.collect()
        tmp_dir.cleanup()
