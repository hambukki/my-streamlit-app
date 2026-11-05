"""8차 QA: 한국어 STT 힌트, 비한국어 답변 보정, TTS 한국어 강제·실패 차단."""
import importlib.util
import io
import types
import unittest
from pathlib import Path

from test_ai_grounding import load_ai_with_stubs


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("voice_language_v8_test", ROOT / "aivle/voice_language.py")
voice = importlib.util.module_from_spec(spec)
spec.loader.exec_module(voice)


class KoreanVoiceTests(unittest.TestCase):
    def test_korean_with_english_links_and_acronyms_is_preserved(self):
        self.assertFalse(voice.needs_korean_rewrite(
            "오늘은 API와 GPT-4o를 확인하세요. https://example.com/path"))
        self.assertFalse(voice.needs_korean_rewrite("API GPT SQL"))

    def test_foreign_prose_and_scripts_detected_even_in_mixed_answer(self):
        for sentence in ("Hello, this is a complete English response.",
                         "Bonjour, comment allez-vous?", "こんにちは、元気ですか。",
                         "안녕하세요. This is an English sentence with multiple words."):
            self.assertTrue(voice.needs_korean_rewrite(sentence), sentence)

    def test_korean_translation_rechecks_and_preserves_links(self):
        url = "https://example.com/info"
        source = "Please visit this website now: " + url
        korean = voice.require_korean_reply(
            source, lambda original: "안내 링크를 확인하세요: " + url)
        self.assertIn("안내 링크", korean)
        self.assertIn(url, korean)
        blocked = voice.require_korean_reply(source, lambda original: "안내 내용만 남깁니다.")
        self.assertIn("한국어", blocked)
        self.assertNotIn("Please visit", blocked)

    def test_spoken_text_removes_urls_and_prevents_foreign_playback(self):
        spoken = voice.korean_speech_input("검색 출처: [공식 문서](https://example.com)")
        self.assertIn("공식 문서", spoken)
        self.assertNotIn("https://", spoken)
        with self.assertRaises(ValueError):
            voice.korean_speech_input("This output is not written in Korean.")

    def test_korean_tts_uses_instruction_capable_model(self):
        ai = load_ai_with_stubs()
        calls = []

        def create(**params):
            calls.append(params)
            return types.SimpleNamespace(content=b"fake-mp3")

        ai.get_openai_client = lambda: types.SimpleNamespace(
            audio=types.SimpleNamespace(speech=types.SimpleNamespace(create=create)))
        self.assertEqual(ai.make_speech("김대리님, 오늘 업무를 안내합니다."), b"fake-mp3")
        self.assertEqual(calls[0]["model"], "gpt-4o-mini-tts")
        self.assertIn("한국어", calls[0]["instructions"])
        self.assertNotIn("language", calls[0])  # speech API에는 language 매개변수가 없습니다.
        with self.assertRaises(ValueError):
            ai.make_speech("Hola buenos días")
        self.assertEqual(len(calls), 1)

    def test_voice_chat_transcription_can_force_korean_without_affecting_meetings(self):
        ai = load_ai_with_stubs()
        calls = []

        def transcribe(**kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(text="회의를 요약해 줘")

        ai.get_openai_client = lambda: types.SimpleNamespace(
            audio=types.SimpleNamespace(transcriptions=types.SimpleNamespace(create=transcribe)))
        sound = types.SimpleNamespace(getvalue=lambda: b"1234", name="voice.wav", type="audio/wav")
        ai.transcribe_audio(sound, language="ko")
        ai.transcribe_audio(sound)
        self.assertEqual(calls[0]["language"], "ko")
        self.assertNotIn("language", calls[1])


if __name__ == "__main__":
    unittest.main()
