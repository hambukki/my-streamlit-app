"""6차 QA: 이메일 초안 생존·초기화, 좌측 업무 연동, 마스코트 누락 검증."""
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def read_module(module_name, rel_path):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / rel_path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class EmailDraftTests(unittest.TestCase):
    def setUp(self):
        self.drafts = read_module("v6_email_drafts", "aivle/email_drafts.py")
        self.db = {}
        self.save_setting = self.db.__setitem__

    def test_compose_save_and_restore_after_widget_cleanup(self):
        state = dict(email_to="boss@example.com", email_cc="staff@example.com",
                     email_subject="업무 보고", email_body="11월 12일 보고서 제출")
        self.drafts.persist_draft(state, self.save_setting)
        # 다른 페이지에 이동해 입력 위젯이 사라지고 세션이 새로 구성된 상황.
        state.clear()
        state.update(self.drafts.parse_draft(self.db[self.drafts.SETTING]))
        self.assertEqual(state["email_to"], "boss@example.com")
        self.assertEqual(state["email_body"], "11월 12일 보고서 제출")

    def test_new_message_clears_saved_draft_not_other_settings(self):
        state = {key: "old" for key in self.drafts.FIELDS}
        state["email_error"] = "오류"
        self.db["unrelated"] = "keep"
        self.drafts.clear_draft(state, self.save_setting)
        self.assertTrue(all(state[key] == self.drafts.EMAIL_DEFAULTS[key]
                            for key in self.drafts.FIELDS))
        self.assertEqual(json.loads(self.db[self.drafts.SETTING]), self.drafts.EMAIL_DEFAULTS)
        self.assertEqual(self.db["unrelated"], "keep")

    def test_corrupted_saved_json_does_not_break_app(self):
        for content in ("broken", "[]", "null", '{"email_body":123}'):
            result = self.drafts.parse_draft(content)
            self.assertEqual(set(result), set(self.drafts.FIELDS))
        self.assertEqual(self.drafts.parse_draft('{"email_body":123}')["email_body"], "123")


class SidebarTests(unittest.TestCase):
    def setUp(self):
        st = types.ModuleType("streamlit")
        core = types.ModuleType("aivle.core")
        widgets = types.ModuleType("aivle.widgets")
        core.load_tasks = lambda: []
        core.now_kst = lambda: None
        core.set_task_done = lambda *args: None
        widgets.task_editor = lambda *args: None
        with patch.dict(sys.modules, {"streamlit": st, "aivle.core": core,
                                      "aivle.widgets": widgets}):
            self.sidebar = read_module("aivle.sidebar_v6_test", "aivle/sidebar.py")

    def test_only_incomplete_today_and_future_tasks_display(self):
        tasks = [
            {"task": "완료", "deadline": "2026-11-06", "time": "", "is_done": True},
            {"task": "지난 업무", "deadline": "2026-11-04", "time": "", "is_done": False},
            {"task": "기한 없음", "deadline": "", "time": "", "is_done": False},
            {"task": "다음 주", "deadline": "2026-11-12", "time": "", "is_done": False},
            {"task": "오늘", "deadline": "2026-11-05", "time": "09:00", "is_done": False},
        ]
        rows = self.sidebar.sidebar_upcoming_tasks(tasks, date(2026, 11, 5))
        self.assertEqual([row["task"] for row in rows], ["오늘", "다음 주"])

    def test_tooltip_escapes_task_content(self):
        tooltip = self.sidebar._tooltip({"task": "<img src=x>",
                                         "deadline": "2026-11-12",
                                         "detail": '" onmouseover="x'})
        self.assertNotIn("<img", tooltip)
        self.assertIn("&lt;img", tooltip)
        self.assertIn("&quot;", tooltip)


class IntegrationFileTests(unittest.TestCase):
    def test_original_mascot_is_packed_and_rendered(self):
        path = ROOT / "assets" / "aivle_hero.png"
        self.assertTrue(path.exists())
        with path.open("rb") as image:
            self.assertEqual(image.read(8), b"\x89PNG\r\n\x1a\n")
        home = (ROOT / "aivle/pages/home.py").read_text(encoding="utf-8")
        self.assertIn('aivle-hero-mascot', home)

    def test_sidebar_uses_shared_db_and_no_staff_badge(self):
        main = (ROOT / "app.py").read_text(encoding="utf-8")
        side = (ROOT / "aivle/sidebar.py").read_text(encoding="utf-8")
        self.assertIn("render_sidebar_upcoming()", main)
        self.assertNotIn("employee_badge.png", main)
        self.assertIn("load_tasks()", side)
        self.assertIn("set_task_done", side)
        self.assertIn("task_editor", side)


if __name__ == "__main__":
    unittest.main()
