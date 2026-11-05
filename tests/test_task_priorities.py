"""기존 업무 DB 마이그레이션·중요도·프리셋과 사용자 분리를 검증합니다."""
import importlib.util
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class TaskPriorityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "aivle.db"
        streamlit = types.ModuleType("streamlit")
        streamlit.query_params = {"sid": "session_test_user_identifier_001"}
        streamlit.session_state = {}
        with patch.dict(sys.modules, {"streamlit": streamlit}):
            source = Path(__file__).resolve().parents[1] / "aivle" / "core.py"
            spec = importlib.util.spec_from_file_location("aivle.core_task_test", source)
            self.core = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.core)
        self.core.st = streamlit
        self.core.DB_PATH = self.db_path
        self.core.init_db()

    def test_existing_task_migrates_and_priority_edits(self):
        with sqlite3.connect(self.db_path) as db:
            db.execute("INSERT INTO tasks (id,sid,title,due_date,due_time,detail) "
                       "VALUES (?,?,?,?,?,?)", ("old-1", "session_test_user_identifier_001",
                                              "기존 업무", "2026-11-06", "", "기존 내용"))
        self.core.migrate_task_status()
        self.assertEqual(self.core.load_tasks()[0]["urgency"], "normal")
        self.core.update_task("old-1", "기존 업무 수정", "2026-11-05", "", "수정된 내용", "urgent")
        self.assertEqual(self.core.get_task("old-1")["urgency"], "urgent")
        self.assertEqual(self.core.get_task("old-1")["deadline"], "2026-11-05")

    def test_preset_creates_once_and_other_sessions_cannot_see_it(self):
        self.core.migrate_task_status()
        self.core.add_task_preset("일일 보고", "진행 상황 확인", "low")
        preset_id = self.core.load_task_presets()[0]["id"]
        self.assertTrue(self.core.create_task_from_preset(preset_id, "2026-11-04"))
        self.assertFalse(self.core.create_task_from_preset(preset_id, "2026-11-04"))
        self.assertEqual(self.core.load_tasks()[0]["urgency"], "low")
        self.core.st.query_params["sid"] = "session_other_user_identifier_002"
        self.assertEqual(self.core.load_tasks(), [])
        self.assertEqual(self.core.load_task_presets(), [])


if __name__ == "__main__":
    unittest.main()
