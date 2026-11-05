"""7차 QA: 실제 직장형 이메일 프롬프트·초안 파싱·기존 임시저장 호환성."""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "aivle" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BusinessEmailPromptTests(unittest.TestCase):
    def setUp(self):
        self.pro = load_module("pro_email_test", "pro_email.py")
        self.drafts = load_module("email_drafts_v7_test", "email_drafts.py")

    def test_reason_recipient_deadline_and_signature_are_in_prompt(self):
        details = {
            "email_intent": "업무 요청", "email_audience": "상사·관리자",
            "email_tone": "격식 있는", "email_to": "manager@example.com",
            "email_cc": "", "email_subject": "기획안 검토 요청",
            "email_brief": "검토 요청, 수정 의견도 함께 수렴",
            "email_deadline": "2026년 11월 12일", "email_body": "",
            "email_sender_name": "김대리", "email_signature": "서명 포함",
            "email_subject_mode": "입력 제목 유지",
        }
        messages = self.pro.build_professional_email_messages(details)
        self.assertIn("받는 사람", messages[1]["content"])
        for item in ("상사·관리자", "2026년 11월 12일", "기획안 검토 요청",
                     "김대리", "검토 요청, 수정 의견도 함께 수렴"):
            self.assertIn(item, messages[1]["content"])
        for instruction in ("첨부파일", "추측", "review_items", "사내", "제목"):
            self.assertIn(instruction, messages[0]["content"])

    def test_original_subject_preserved_when_requested(self):
        output = json.dumps({"subject": "AI가 지은 제목", "body": "안녕하세요.\n요청드립니다.\n김대리 드림",
                             "review_items": ["기한 확인"]}, ensure_ascii=False)
        subject, body, review = self.pro.parse_professional_email_result(
            output, "기존 제목", preserve_subject=True)
        self.assertEqual(subject, "기존 제목")
        self.assertEqual(review, ["기한 확인"])
        self.assertIn("요청드립니다", body)

    def test_missing_or_corrupt_response_keeps_draft_untouched(self):
        for raw in ("", "이메일을 작성했습니다.", "[]", '{"subject":"제목","body":""}'):
            with self.assertRaises(ValueError):
                self.pro.parse_professional_email_result(raw)

    def test_legacy_v6_draft_loads_with_new_defaults(self):
        old = json.dumps({"email_to": "person@example.com", "email_cc": "",
                          "email_subject": "기존 저장 제목", "email_body": "기존 본문"}, ensure_ascii=False)
        new = self.drafts.parse_draft(old)
        self.assertEqual(new["email_subject"], "기존 저장 제목")
        self.assertEqual(new["email_body"], "기존 본문")
        self.assertEqual(new["email_intent"], "업무 요청")
        self.assertEqual(new["email_sender_name"], "김대리")

    def test_cancelled_generation_does_not_auto_send(self):
        text = (ROOT / "aivle/email.py").read_text(encoding="utf-8")
        start = text.index("def _write_professional_email")
        end = text.index("def send_gmail")
        self.assertNotIn("send_gmail(", text[start:end])


if __name__ == "__main__":
    unittest.main()
