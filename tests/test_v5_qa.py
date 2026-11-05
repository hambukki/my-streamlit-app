"""5차 QA: 새 대화, 대화 삭제, 완료일 조회, 회의 입력 초기화를 검증합니다."""
import importlib.util
import sqlite3
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SID = "session_test_user_identifier_001"


def load_source(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class V5PersistenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.st = types.ModuleType("streamlit")
        self.st.query_params = {"sid": SID}
        self.st.session_state = {}
        with patch.dict(sys.modules, {"streamlit": self.st}):
            self.core = load_source("aivle.core_v5_test", "aivle/core.py")
        self.core.st = self.st
        self.core.DB_PATH = Path(temp.name) / "v5.db"
        self.core.init_db()
        self.core.migrate_task_status()

    def test_fresh_browser_session_does_not_restore_previous_conversation(self):
        original = self.core.choose_conversation()
        self.st.session_state["_active_chat_id"] = original
        self.core.save_message("user", "이전에 진행한 대화")
        self.st.session_state.clear()  # 새로고침으로 새 Streamlit Session State
        refreshed = self.core.choose_conversation()
        self.assertNotEqual(refreshed, original)
        self.assertIn(original, [row[0] for row in self.core.load_conversations()])
        self.assertEqual(self.core.choose_conversation(), refreshed)  # 일반 rerun

    def test_delete_conversation_removes_attachments_and_only_owned_data(self):
        own_id = self.core.choose_conversation()
        self.st.session_state["_active_chat_id"] = own_id
        self.core.save_message("user", "삭제할 메시지")
        self.core.save_chat_attachment("회의.txt", "회의 원문")
        self.st.query_params["sid"] = "session_other_user_identifier_002"
        other_id = self.core.create_conversation()
        self.st.session_state["_active_chat_id"] = other_id
        self.core.save_message("user", "다른 사용자 대화")
        self.assertFalse(self.core.delete_conversation(own_id))
        self.st.query_params["sid"] = SID
        self.assertTrue(self.core.delete_conversation(own_id))
        self.assertFalse(self.core.delete_conversation(own_id))
        with sqlite3.connect(self.core.DB_PATH) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM messages WHERE conversation_id=?",
                                          (own_id,)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM chat_attachments WHERE conversation_id=?",
                                          (own_id,)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM conversations WHERE id=?",
                                          (other_id,)).fetchone()[0], 1)

    def test_completion_date_is_written_and_cleared_on_undo(self):
        task_id = self.core.add_task("QA 완료 업무", "2026-11-12")
        self.core.set_task_done(task_id, True)
        task = self.core.get_task(task_id)
        self.assertTrue(task["is_done"])
        self.assertTrue(task["completed_at"].startswith("20"))
        self.core.set_task_done(task_id, False)
        self.assertFalse(self.core.get_task(task_id)["is_done"])
        self.assertEqual(self.core.get_task(task_id)["completed_at"], "")


class V5ViewHelpersTests(unittest.TestCase):
    def test_completed_filter_week_month_and_keyword(self):
        st = types.ModuleType("streamlit")
        widgets = types.ModuleType("aivle.widgets")
        core = types.ModuleType("aivle.core")
        for method in ("now_kst", "load_tasks", "save_setting", "load_task_presets",
                       "create_task_from_preset", "delete_task_preset", "set_task_done"):
            setattr(core, method, lambda *a, **k: None)
        for method in ("task_editor", "task_delete_dialog", "task_preset_editor",
                       "live_korea_clock", "get_weather", "weather_description", "render_mini_calendar"):
            setattr(widgets, method, lambda *a, **k: None)
        widgets.CITIES = {}
        with patch.dict(sys.modules, {"streamlit": st, "aivle.core": core,
                                      "aivle.widgets": widgets}):
            home = load_source("aivle.home_v5_test", "aivle/pages/home.py")
        tasks = [
            {"task": "기획서", "detail": "작성", "is_done": True,
             "completed_at": "2026-11-04T10:00:00+09:00", "deadline": "2026-11-12"},
            {"task": "보고서", "detail": "검토", "is_done": True,
             "completed_at": "2026-10-22T10:00:00+09:00", "deadline": ""},
            {"task": "미완료", "detail": "기획", "is_done": False,
             "completed_at": "", "deadline": "2026-11-05"},
        ]
        self.assertEqual(len(home.filter_completed_tasks(tasks, "이번 주", date(2026, 11, 5))), 1)
        self.assertEqual(len(home.filter_completed_tasks(tasks, "이번 달", date(2026, 11, 5))), 1)
        self.assertEqual(len(home.filter_completed_tasks(tasks, "이번 주", date(2026, 11, 5), "없는 글자")), 0)
        self.assertEqual(len(home.filter_completed_tasks(tasks, "이번 달", date(2026, 10, 30))), 1)

    def test_audio_only_is_available_for_one_click_analysis_and_reset_clears_result(self):
        class SessionState(dict):
            __getattr__ = dict.get
            __setattr__ = dict.__setitem__

        st = types.ModuleType("streamlit")
        st.session_state = SessionState(meeting_input_generation=0,
                                        meeting_result={"summary": "과거 회의"},
                                        meeting_version=1,
                                        meeting_audio=b"123",
                                        meeting_autoplay=True,
                                        meeting_followup=[{"role": "user", "content": "질문"}])
        core = types.ModuleType("aivle.core")
        saved = []
        core.get_setting = lambda *a: ""
        core.save_setting = lambda name, value: saved.append((name, value))
        ai = types.ModuleType("aivle.ai")
        for name in ("SYS_ROLE", "MEETING_SCHEMA", "ask_llm", "transcribe_audio"):
            setattr(ai, name, lambda *a: "")
        docs = types.ModuleType("aivle.documents")
        docs.decode_text_file = lambda b: ""
        logic = types.ModuleType("aivle.meeting_logic")
        logic.verify_meeting_tasks = lambda result, source: result
        logic.combine_meeting_sources = lambda sources, names: "\n".join(
            sources[name] for name in names if sources.get(name)
        )
        sections = types.ModuleType("aivle.meeting_sections")
        sections.render_summary = sections.render_tasks = lambda *a: None
        with patch.dict(sys.modules, {"streamlit": st, "aivle.core": core,
                                      "aivle.ai": ai, "aivle.documents": docs,
                                      "aivle.meeting_logic": logic,
                                      "aivle.meeting_sections": sections}):
            meeting = load_source("aivle.meeting_v5_test", "aivle/pages/meeting.py")
        self.assertIn("회의 음성 파일", meeting.collect_meeting_sources("", "", "", "", audio_present=True))
        self.assertIn("회의 내용 녹음", meeting.collect_meeting_sources("", "", "", "", recording_present=True))
        audio = object()
        captured = []
        sources = meeting.collect_meeting_sources("", "", "", "", audio_present=True)
        full_text, changes = meeting.prepare_selected_meeting_text(
            sources, ["회의 음성 파일"], audio_file=audio,
            transcription_fn=lambda uploaded: captured.append(uploaded) or "김대리 11월 12일 제출"
        )
        self.assertEqual(captured, [audio])
        self.assertIn("11월 12일", full_text)
        self.assertEqual(changes["meeting_audio_review"], "김대리 11월 12일 제출")
        meeting.reset_meeting_workspace()
        self.assertIsNone(st.session_state.meeting_result)
        self.assertEqual(st.session_state.meeting_input_generation, 1)
        self.assertEqual(st.session_state.meeting_followup, [])
        self.assertIn(("meeting_result", "null"), saved)


if __name__ == "__main__":
    unittest.main()
