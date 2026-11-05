"""원문 근거가 있는 날짜만 확정되는지 검증합니다."""
import unittest
from datetime import date

from aivle.meeting_logic import (verified_deadline, verify_meeting_tasks,
                                 combine_meeting_sources, suggested_deadline_from_phrase)


class MeetingDateTests(unittest.TestCase):
    def test_all_selected_meeting_inputs_are_kept_without_truncation(self):
        sources = {
            "회의메모": "신제품 출시 목표와 배경",
            "회의록 TXT": "제품 출시 회의 내용 " * 1500,
            "회의 음성 파일": "긴 녹음 전사 내용 " * 1300,
            "회의 내용 녹음": "추가 결정사항과 담당자 배정",
        }
        combined = combine_meeting_sources(sources)
        for name, content in sources.items():
            self.assertIn(f"[{name}]\n{content}", combined)
        self.assertEqual(combine_meeting_sources(sources, ["회의메모"]),
                         "[회의메모]\n신제품 출시 목표와 배경")

    def test_absent_date_is_never_invented(self):
        row = {"deadline": "2023-10-20", "deadline_phrase": "2023-10-20"}
        self.assertEqual(verified_deadline(row, "SNS 콘텐츠 초안 작성"),
                         ("", "unverified", "2023-10-20"))

    def test_relative_date_requires_manual_choice(self):
        row = {"deadline": "2023-10-20", "deadline_phrase": "다음 주까지"}
        self.assertEqual(verified_deadline(row, "경쟁사 분석 다음 주까지"),
                         ("", "relative", "다음 주까지"))

    def test_explicit_date_is_preserved(self):
        row = {"deadline": "2026-11-06", "deadline_phrase": "2026년 11월 6일까지"}
        self.assertEqual(verified_deadline(row, "보고서 2026년 11월 6일까지"),
                         ("2026-11-06", "absolute", "2026년 11월 6일까지"))

    def test_deadline_without_year_is_unverified(self):
        row = {"deadline": "2026-11-06", "deadline_phrase": "11월 6일까지"}
        self.assertEqual(verified_deadline(row, "11월 6일까지 마감"),
                         ("", "unverified", "11월 6일까지"))

    def test_original_month_day_preselects_correct_calendar_date(self):
        today = date(2026, 11, 5)
        self.assertEqual(suggested_deadline_from_phrase("11월 6일까지", today),
                         date(2026, 11, 6))
        self.assertEqual(suggested_deadline_from_phrase("11월 12일", today),
                         date(2026, 11, 12))
        self.assertEqual(suggested_deadline_from_phrase("11/12", today),
                         date(2026, 11, 12))

    def test_date_hint_does_not_autoconfirm_missing_year(self):
        source = "김대리: 11월 6일까지 초안 작성, 11월 12일에 최종 제출"
        row = {"deadline": "2026-11-05", "deadline_phrase": "11월 6일까지"}
        self.assertEqual(verified_deadline(row, source),
                         ("", "unverified", "11월 6일까지"))
        self.assertEqual(suggested_deadline_from_phrase(row["deadline_phrase"],
                                                       date(2026, 11, 5)), date(2026, 11, 6))

    def test_ambiguous_and_relative_phrase_has_no_guess(self):
        today = date(2026, 11, 5)
        self.assertIsNone(suggested_deadline_from_phrase("다음 주까지", today))
        self.assertIsNone(suggested_deadline_from_phrase("기한 미정", today))
        self.assertIsNone(suggested_deadline_from_phrase("11월 6일과 11월 12일", today))

    def test_full_year_and_near_past_date(self):
        today = date(2026, 11, 5)
        self.assertEqual(suggested_deadline_from_phrase("2026년 11월 12일", today),
                         date(2026, 11, 12))
        self.assertEqual(suggested_deadline_from_phrase("11월 4일", today),
                         date(2026, 11, 4))

    def test_missing_date_stays_empty(self):
        row = {"deadline": "", "deadline_phrase": ""}
        self.assertEqual(verified_deadline(row, "인플루언서 후보 조사"),
                         ("", "none", ""))

    def test_three_tasks(self):
        result = {"kim_tasks": [
            {"task": "경쟁사 마케팅 분석", "deadline": "2023-10-20", "deadline_phrase": "다음 주까지"},
            {"task": "SNS 콘텐츠 초안 작성", "deadline": "2023-10-20", "deadline_phrase": ""},
            {"task": "인플루언서 후보 조사", "deadline": "2023-10-20", "deadline_phrase": ""},
        ]}
        verified = verify_meeting_tasks(result, "경쟁사 마케팅 분석은 다음 주까지")
        self.assertEqual([t["deadline"] for t in verified["kim_tasks"]], ["", "", ""])
        self.assertEqual([t["deadline_kind"] for t in verified["kim_tasks"]],
                         ["relative", "unverified", "unverified"])


if __name__ == "__main__":
    unittest.main()
