"""실제 API 호출 없이 업무 조회 도구와 검색 출처 처리 흐름을 검증합니다."""
import importlib.util
import io
import json
import sys
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import patch


def load_ai_with_stubs():
    st = types.ModuleType("streamlit")
    st.cache_resource = lambda fn: fn
    openai = types.ModuleType("openai")
    openai.OpenAI = object
    core = types.ModuleType("aivle.core")
    core.now_kst = lambda: "2026-11-04T12:00:00+09:00"
    core.get_active_chat_id = lambda: "chat-test"
    core.load_tasks = lambda: [{"id": "1", "task": "회의", "deadline": "2026-11-06", "is_done": False}]
    for fn in ("load_messages", "save_message", "set_conversation_title",
               "save_chat_attachment", "recent_chat_attachments", "save_setting"):
        setattr(core, fn, lambda *args, **kwargs: None)
    documents = types.ModuleType("aivle.documents")
    documents.extract_document = lambda _: ""
    with patch.dict(sys.modules, {"streamlit": st, "openai": openai,
                                  "aivle.core": core, "aivle.documents": documents}):
        filename = Path(__file__).resolve().parents[1] / "aivle" / "ai.py"
        spec = importlib.util.spec_from_file_location("aivle.ai_grounding_test", filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


class ToolGroundingTests(unittest.TestCase):
    def test_streaming_wav_unknown_frame_count_does_not_overflow(self):
        """스트리밍 WAV의 0xFFFFFFFF 크기 필드를 출력 WAV에 복사하지 않습니다."""
        ai = load_ai_with_stubs()
        data = io.BytesIO()
        with wave.open(data, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b"\x02\x00" * 1600)
        streaming_wav = bytearray(data.getvalue())
        streaming_wav[40:44] = b"\xff" * 4
        ai.get_openai_client = lambda: types.SimpleNamespace(
            audio=types.SimpleNamespace(speech=types.SimpleNamespace(
                create=lambda **kwargs: types.SimpleNamespace(content=bytes(streaming_wav))
            ))
        )
        combined = ai.make_full_speech("회의 내용입니다.")
        with wave.open(io.BytesIO(combined), "rb") as audio:
            self.assertEqual(audio.getnframes(), 1600)

    def test_long_speech_keeps_complete_input_and_combines_wav(self):
        ai = load_ai_with_stubs()
        long_text = "회의 합의사항 " * 850
        sent = []

        def fake_create(**kwargs):
            sent.append(kwargs["input"])
            data = io.BytesIO()
            with wave.open(data, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(b"\x01\x00" * 1600)
            return types.SimpleNamespace(content=data.getvalue())

        ai.get_openai_client = lambda: types.SimpleNamespace(
            audio=types.SimpleNamespace(speech=types.SimpleNamespace(create=fake_create))
        )
        output = ai.make_full_speech(long_text)
        self.assertGreater(len(sent), 1)
        self.assertTrue(all(len(part) <= 3500 for part in sent))
        self.assertEqual("".join("".join(sent).split()), "".join(long_text.split()))
        with wave.open(io.BytesIO(output), "rb") as audio:
            self.assertEqual(audio.getnframes(), len(sent) * 1600)

    def test_local_task_query_is_function_call(self):
        ai = load_ai_with_stubs()
        call = types.SimpleNamespace(type="function_call", name="list_registered_tasks",
                                     call_id="call_1", arguments="{}")
        first = types.SimpleNamespace(output=[call], output_text="")
        final = types.SimpleNamespace(output=[], output_text="조회 완료")

        class Responses:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return [first, final][len(self.calls) - 1]

        client = types.SimpleNamespace(responses=Responses())
        ai.get_openai_client = lambda: client
        answer = ai.ask_llm([{"role": "user", "content": "내 일정 보여줘"}],
                            local_tools=True, force_task_lookup=True)
        self.assertEqual(answer, "조회 완료")
        self.assertEqual(client.responses.calls[0]["tool_choice"]["name"], "list_registered_tasks")
        returned = client.responses.calls[1]["input"][-1]
        self.assertEqual(returned["type"], "function_call_output")
        self.assertEqual(json.loads(returned["output"])[0]["task"], "회의")

    def test_web_sources_are_from_response_annotation(self):
        ai = load_ai_with_stubs()
        annotation = types.SimpleNamespace(type="url_citation", url="https://example.com/fact", title="검증 문서")
        content = types.SimpleNamespace(annotations=[annotation])
        message = types.SimpleNamespace(type="message", content=[content])
        response = types.SimpleNamespace(output=[message], output_text="검색에 따른 답변")
        ai.get_openai_client = lambda: types.SimpleNamespace(
            responses=types.SimpleNamespace(create=lambda **kwargs: response)
        )
        answer = ai.ask_llm([{"role": "user", "content": "오늘 뉴스"}],
                            web_search=True, force_search=True)
        self.assertIn("https://example.com/fact", answer)
        self.assertIn("검색 출처", answer)


if __name__ == "__main__":
    unittest.main()
