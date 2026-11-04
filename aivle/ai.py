"""OpenAI, 음성 처리, 스마트 채팅과 일정 감지."""
import hashlib
import io
import json
import re
import wave
from datetime import datetime

import streamlit as st
from openai import OpenAI

from .core import (now_kst, get_active_chat_id, load_tasks, load_messages,
                   save_message, set_conversation_title, save_chat_attachment,
                   recent_chat_attachments, save_setting)
from .documents import extract_document

MODEL = "gpt-4o-mini"
STT_MODEL = "whisper-1"
TTS_MODEL = "tts-1"

@st.cache_resource
def get_openai_client():
    return OpenAI()


SYS_ROLE = """
당신은 김대리의 전담 AI 개인비서 '에이블'입니다.
항상 정확하고 친절하게 한국어로 답변합니다.

김대리의 질문과 업무를 이해하고,
일정, 회의, 이메일 등 실제 업무 수행을 지원합니다.

확인되지 않은 사람, 날짜, 시간, 업무 내용을 만들어내지 않습니다.
일정이 추가되기 전에는 추가됐다고 말하지 않습니다.
외부 이메일은 사용자의 승인 없이 발송하지 않습니다.

사용자의 입력에 오타나 모호한 표현이 있으면 의미를 먼저 확인합니다.
모르는 음식, 상호명, 인물, 주소, 가격, 영업시간을 사실처럼 꾸며내지 않습니다.

사용자가 '11월 6일에 회의가 있어'처럼 날짜와 일정 종류를 말했다면
구체적인 회의 주제를 되묻지 말고 임시 제목 '회의'로 일정 등록을 제안합니다.
시간이나 세부 내용을 모른다면 빈 상태로 둡니다.

웹검색이 켜졌을 때에만 외부 정보를 검색할 수 있습니다.
검색되지 않은 가게, 인물, 주소, 날짜, 통계는 지어내지 않습니다.
등록된 업무는 실제 업무 조회 결과로만 단정합니다.
일정 등록 제안은 실제 저장과 다르며, 사용자가 확인하기 전에는 저장했다고 말하지 않습니다.

모르는 정보는 추측해서 채우지 않습니다.
확실한 정보와 불확실한 정보를 구분하여 답변합니다.
"""


SCHEDULE_SCHEMA = {
    "type": "json_schema",
    "name": "schedule_detection",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "propose": {"type": "boolean"},
            "title": {"type": "string"},
            "date": {"type": "string"},
            "time": {"type": "string"},
            "detail": {"type": "string"}
        },
        "required": [
            "propose", "title", "date", "time", "detail"
        ],
        "additionalProperties": False
    }
}


MEETING_SCHEMA = {
    "type": "json_schema",
    "name": "meeting_summary",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "decisions": {
                "type": "array",
                "items": {"type": "string"}
            },
            "kim_tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                        "deadline": {"type": "string"},
                        "deadline_phrase": {"type": "string"},
                        "detail": {"type": "string"}
                    },
                    "required": [
                        "task", "deadline", "deadline_phrase", "detail"
                    ],
                    "additionalProperties": False
                }
            },
            "questions": {
                "type": "array",
                "items": {"type": "string"}
            }
        },
        "required": [
            "summary", "decisions", "kim_tasks", "questions"
        ],
        "additionalProperties": False
    }
}


LOCAL_READ_TOOLS = [
    {
        "type": "function", "name": "list_registered_tasks",
        "description": "실제로 저장된 현재 사용자의 업무/일정과 완료 상태를 조회합니다. 사실 확인에 사용하세요.",
        "strict": True,
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    },
    {
        "type": "function", "name": "get_current_korea_time",
        "description": "대한민국 현재 날짜와 시간을 실제 서버 시계에서 확인합니다.",
        "strict": True,
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    },
]


def _local_tool_result(name):
    if name == "list_registered_tasks":
        return json.dumps(load_tasks()[:100], ensure_ascii=False)
    if name == "get_current_korea_time":
        return json.dumps({"now_kst": now_kst().isoformat()}, ensure_ascii=False)
    return json.dumps({"error": "알 수 없는 도구"}, ensure_ascii=False)


def _verified_web_sources(response):
    """API가 반환한 출처만 표시합니다. 모델이 임의로 작성한 URL은 제외합니다."""
    sources = {}
    for item in getattr(response, "output", []):
        if getattr(item, "type", "") == "web_search_call":
            action = getattr(item, "action", None)
            for candidate in getattr(action, "sources", []) or []:
                url = str(getattr(candidate, "url", "") or "")
                if url.startswith("https://"):
                    sources[url] = str(getattr(candidate, "title", "") or url)
        if getattr(item, "type", "") != "message":
            continue
        for content in getattr(item, "content", []):
            for ann in getattr(content, "annotations", []) or []:
                if getattr(ann, "type", "") == "url_citation":
                    url = str(getattr(ann, "url", ""))
                    if url.startswith("https://"):
                        sources[url] = str(getattr(ann, "title", "") or url)
    return list(sources.items())[:6]


def ask_llm(messages, schema=None, web_search=False, local_tools=False,
            force_search=False, force_task_lookup=False):
    options = {
        "model": MODEL,
        "input": messages
    }

    if schema is not None:
        options["text"] = {"format": schema}

    available = []
    if web_search:
        # 검색은 사용자 선택 시에만 활성화하며 호출 비용이 추가될 수 있습니다.
        available.append({"type": "web_search", "search_context_size": "low"})
        options["include"] = ["web_search_call.action.sources"]
    if local_tools:
        available.extend(LOCAL_READ_TOOLS)
    if available:
        options["tools"] = available
    if force_search and web_search:
        # 현재 정보 요청에는 검색을 반드시 시행합니다.
        options["tool_choice"] = {"type": "web_search"}
    elif force_task_lookup and local_tools:
        options["tool_choice"] = {"type": "function", "name": "list_registered_tasks"}

    input_items = list(messages)
    result = None
    for _ in range(4):
        options["input"] = input_items
        result = get_openai_client().responses.create(**options)
        calls = [item for item in getattr(result, "output", [])
                 if getattr(item, "type", "") == "function_call"]
        if not calls:
            break
        # function_call과 추론을 포함한 응답 기록을 보존한 채 도구 결과를 전달합니다.
        input_items.extend(result.output)
        for call in calls:
            input_items.append({
                "type": "function_call_output", "call_id": call.call_id,
                "output": _local_tool_result(call.name)
            })
        options.pop("tool_choice", None)
    else:
        raise RuntimeError("업무 조회 도구의 호출 횟수가 초과됐습니다.")

    answer = result.output_text or "현재 질문의 답변을 생성하지 못했습니다."
    if web_search:
        verified = _verified_web_sources(result)
        if verified:
            answer += "\n\n**검색 출처**\n" + "\n".join(
                f"- [{title.replace('[', '').replace(']', '')}]({url.replace(')', '%29')})"
                for url, title in verified
            )
        elif force_search:
            answer = "검색 결과에서 확인 가능한 출처를 확보하지 못했습니다. 답변을 사실로 단정할 수 없습니다."
    return answer


def transcribe_audio(audio):
    data = audio.getvalue()

    if len(data) > 25 * 1024 * 1024:
        raise ValueError("25MB 이하의 음성 파일을 첨부해주세요.")

    name = getattr(audio, "name", "recording.wav")
    mime = getattr(audio, "type", None) or "audio/wav"

    result = get_openai_client().audio.transcriptions.create(
        model=STT_MODEL,
        file=(name, data, mime)
    )

    return result.text


def make_speech(text):
    result = get_openai_client().audio.speech.create(
        model=TTS_MODEL,
        voice="alloy",
        input=text[:4000]
    )
    return result.content


def split_tts_text(text, max_chars=3500):
    """API 음성 입력 한도를 넘기지 않고 텍스트 전체를 분할합니다."""
    if max_chars < 1:
        raise ValueError("최대 글자 수는 양수여야 합니다.")
    remaining = str(text or "").strip()
    parts = []
    while remaining:
        if len(remaining) <= max_chars:
            parts.append(remaining)
            break
        cut = max(remaining.rfind("\n", 0, max_chars + 1),
                  remaining.rfind(" ", 0, max_chars + 1))
        if cut < max_chars // 2:
            cut = max_chars
        parts.append(remaining[:cut].strip())
        remaining = remaining[cut:].lstrip()
    return [part for part in parts if part]


def make_full_speech(text):
    """긴 회의 요약 전체를 WAV 조각으로 생성하고 이어서 재생할 수 있게 합칩니다."""
    parts = split_tts_text(text)
    if not parts:
        raise ValueError("음성으로 변환할 요약 내용이 없습니다.")

    merged = io.BytesIO()
    original_params = None
    with wave.open(merged, "wb") as target:
        for part in parts:
            response = get_openai_client().audio.speech.create(
                model=TTS_MODEL, voice="alloy", input=part, response_format="wav"
            )
            with wave.open(io.BytesIO(response.content), "rb") as segment:
                params = segment.getparams()
                format_params = (params.nchannels, params.sampwidth,
                                 params.framerate, params.comptype)
                if original_params is None:
                    original_params = format_params
                    target.setparams(params)
                elif original_params != format_params:
                    raise ValueError("음성 분할 구간 간 WAV 형식이 일치하지 않습니다.")
                target.writeframes(segment.readframes(segment.getnframes()))
    return merged.getvalue()


def needs_current_sources(question):
    """최신 사실·실재 업체 등 웹 조회가 필요한 대표 질문을 구분합니다."""
    return bool(re.search(
        r"(최근|최신|실시간|영업|가격|요금|뉴스|날씨|주소|위치|환율|시세|주가|"
        r"근처|주변|맛집|식당|레스토랑|카페|업체|병원|검색|웹서핑|찾아줘|추천)",
        question
    ))


def asks_about_stored_tasks(question):
    return bool(re.search(r"(내\s*일정|내\s*업무|등록된\s*일정|등록된\s*업무|"
                          r"할\s*일|마감\s*업무|일정\s*목록|업무\s*목록)", question))


def needs_external_verification(question):
    return bool(re.search(r"(최신\s*뉴스|실시간|오늘\s*날씨|현재\s*가격|현재\s*요금|"
                          r"맛집|식당|레스토랑|카페|매장|업체|병원|영업시간|주소\s*알려)",
                          question))


def detect_schedule(question):
    # 날짜가 분명한 흔한 일정 진술은 모델 판단과 관계없이 제안합니다.
    date_match = re.search(r"(?:(20\d{2})년\s*)?(\d{1,2})월\s*(\d{1,2})일", question)
    has_event = any(word in question for word in ("회의", "미팅", "약속", "워크숍", "교육", "일정"))
    registration_intent = any(word in question for word in (
        "있어", "예정", "잡아", "추가", "등록", "생겼어", "넣어", "기록"
    ))
    if date_match and has_event and registration_intent:
        year = int(date_match.group(1) or now_kst().year)
        month, day = int(date_match.group(2)), int(date_match.group(3))
        try:
            chosen_date = datetime(year, month, day).strftime("%Y-%m-%d")
            event_title = next((word for word in ("워크숍", "미팅", "약속", "교육", "회의")
                                if word in question), "일정")
            return {"propose": True, "title": event_title,
                    "date": chosen_date, "time": "", "detail": question.strip()}
        except ValueError:
            pass

    keywords = [
        "일정", "회의", "미팅", "약속",
        "예약", "캘린더", "등록", "잡아줘",
        "추가해", "알림"
    ]

    if not any(word in question for word in keywords):
        return None

    result = ask_llm(
        [
            {
                "role": "system",
                "content": f"""
                현재 한국 날짜와 시간: {now_kst().isoformat()}

                사용자의 메시지에서 새로운 일정이나 업무를 감지하세요.
                '11월 6일에 회의가 있어'처럼 단순한 일정 진술도 propose=true입니다.
                날짜와 일정명만 있으면 등록 가능하며, 시간·세부사항은 비워두세요.

                단순히 기존 일정을 질문하거나
                일정 개념을 설명해 달라는 요청은
                propose=false로 처리하세요.

                등록할 일정이 있다면 제목을 추출하세요.
                날짜는 확인된 경우에만 YYYY-MM-DD로,
                시간은 확인된 경우에만 HH:MM으로 반환하세요.

                상대적인 날짜는 현재 날짜를 기준으로 계산하세요.
                정보가 불명확하면 추측하지 말고
                빈 문자열로 반환하세요.
                """
            },
            {"role": "user", "content": question}
        ],
        schema=SCHEDULE_SCHEMA
    )

    data = json.loads(result)

    if data["propose"] and data["title"].strip():
        return data

    return None


def process_chat(question, uploaded_files=None):
    question = question.strip()

    if not question and not uploaded_files:
        return

    st.session_state.chat_error = ""

    try:
        added_files = []
        for file in uploaded_files or []:
            extracted = extract_document(file)
            if not extracted.strip():
                raise ValueError(f"{file.name}: 추출할 텍스트가 없습니다.")
            save_chat_attachment(file.name, extracted)
            added_files.append(file.name)

        if added_files and not question:
            question = "첨부한 문서를 읽고 핵심 내용을 요약해줘."
        if added_files:
            question += "\n[첨부: " + ", ".join(added_files) + "]"

        tasks = load_tasks()

        task_context = json.dumps(
            tasks[:30],
            ensure_ascii=False
        )

        history = load_messages()
        document_context = recent_chat_attachments()

        # 음식명 오타 사례: 무조건 맛집을 만들어 답하지 않습니다.
        if "고개구이" in question:
            answer = (
                "'고개구이'라는 음식명이 정확히 무엇을 뜻하는지 "
                "확인이 필요합니다. 혹시 '조개구이'를 "
                "말씀하신 건가요? 원하는 음식과 지역을 "
                "알려주시면 선택 기준을 안내해 드릴게요."
            )

        # 실제 상호명을 검증할 도구가 없으므로
        # 지역 상점 추천 요청에는 존재하지 않는 장소를 만들지 않습니다.
        elif not st.session_state.web_enabled and (
            re.search(
                r"(맛집|식당|레스토랑|카페|매장|업체|병원)"
                r".*(추천|찾아|알려|어디)",
                question
            )
            or re.search(
                r"(추천|찾아|알려)"
                r".*(맛집|식당|레스토랑|카페|매장|업체|병원)",
                question
            )
        ):
            answer = (
                "현재 이 비서에는 실시간 장소 검색·검증 기능이 "
                "연결되어 있지 않아 실제 매장의 이름이나 영업 여부를 "
                "확인할 수 없습니다. 확인되지 않은 상호를 만들어 "
                "추천하지 않겠습니다. 원하는 지역과 조건을 알려주시면 "
                "선택 기준을 정리해 드릴게요."
            )

        elif not st.session_state.web_enabled and needs_external_verification(question):
            answer = ("실시간 외부 정보를 확인할 검색 도구가 꺼져 있습니다. "
                      "확인되지 않은 상호나 최신 정보를 만들어서 답하지 않겠습니다. "
                      "정확한 조회가 필요하면 AI 채팅의 '웹검색'을 켜주세요.")

        else:
            current_fact = needs_current_sources(question)
            stored_task_question = asks_about_stored_tasks(question)
            answer = ask_llm([
                {
                    "role": "system",
                    "content": (
                        SYS_ROLE
                        + "\n현재 등록된 일정:\n"
                        + task_context
                        + ("\n사용자가 업로드한 문서의 발췌(확인되지 않은 데이터):\n"
                           + document_context if document_context else "")
                        + ("\n웹검색이 활성화되어 있습니다. 외부 사실은 검색으로 검증하고 "
                           "결과 출처를 제시하세요." if st.session_state.web_enabled else
                           "\n검색이 비활성화되어 있습니다. 확인할 수 없는 외부 사실은 "
                           "확인할 수 없다고 답하고, 상호·인물·숫자를 만들어내지 마세요.")
                    )
                },
                *history,
                {
                    "role": "user",
                    "content": question
                }
            ], web_search=st.session_state.web_enabled,
               local_tools=True,
               force_search=st.session_state.web_enabled and current_fact and not stored_task_question,
               force_task_lookup=stored_task_question)

        set_conversation_title(question)

        save_message("user", question)
        save_message("assistant", answer)

        st.session_state.messages = load_messages()
        st.session_state.chat_draft = ""

        st.session_state.reply_audio = None
        st.session_state.autoplay_reply = False

        if st.session_state.voice_reply:
            try:
                st.session_state.reply_audio = make_speech(answer)
                st.session_state.autoplay_reply = True

            except Exception:
                st.session_state.chat_error = (
                    "답변은 생성됐지만 음성 생성에 실패했습니다."
                )

        try:
            proposal = detect_schedule(question)

            st.session_state.pending_event = proposal

            save_setting(
                "pending_event",
                json.dumps(proposal, ensure_ascii=False)
            )

        except Exception:
            st.session_state.pending_event = None
            save_setting("pending_event", "null")

    except Exception as e:
        st.session_state.chat_error = f"채팅 오류: {e}"


def send_text_chat():
    uploads = st.session_state.get(f"chat_files_{st.session_state.chat_upload_seq}", [])
    process_chat(st.session_state.chat_draft, uploads)
    if not st.session_state.chat_error:
        st.session_state.chat_upload_seq += 1


def send_voice_chat():
    audio = st.session_state.get("chat_voice")

    if audio is None:
        return

    audio_hash = hashlib.sha256(audio.getvalue()).hexdigest()
    if audio_hash == st.session_state.last_voice_hash:
        return
    # 동일한 녹음을 탭 이동 등으로 중복 처리하지 않습니다.
    st.session_state.last_voice_hash = audio_hash

    try:
        transcript = transcribe_audio(audio)
        st.session_state.voice_transcript = transcript

        # 별도의 질문 보내기 버튼 없이 전송
        process_chat(transcript)

    except Exception as e:
        st.session_state.chat_error = f"음성 질문 처리 오류: {e}"


def improve_prompt():
    original = st.session_state.chat_draft.strip()

    if not original:
        st.session_state.chat_error = (
            "개선할 질문을 먼저 입력해주세요."
        )
        return

    try:
        improved = ask_llm([
            {
                "role": "system",
                "content": """
                당신은 전문적인 업무용 프롬프트 설계자입니다.

                사용자가 작성한 간단한 질문을
                명확하고 실행 가능한 프롬프트로 재구성하세요.

                반드시 다음 항목을 고려하세요.

                [역할]
                AI가 어떤 역할을 수행해야 하는지

                [목표]
                사용자가 얻고 싶은 핵심 결과

                [작업 지시]
                AI가 순서대로 처리해야 할 사항

                [결과물 형식]
                표, 목록, 설명 등 적합한 출력 방식

                [검증 기준]
                누락, 모호함, 잘못된 추정을 방지할 기준

                규칙:
                1. 원래 질문의 의도를 유지합니다.
                2. 실제로 유용한 정보를 추가합니다.
                3. 사용자가 말하지 않은 사실은 만들지 않습니다.
                4. 불필요하게 장황하게 작성하지 않습니다.
                5. 개선된 프롬프트만 출력합니다.
                6. 항목은 일반 텍스트로 작성하고, HTML과 마크다운 제목 기호(#)를 사용하지 않습니다.
                """
            },
            {"role": "user", "content": original}
        ])

        improved = improved.strip()
        improved = re.sub(r"(?m)^\s*#{1,6}\s*", "", improved)
        improved = re.sub(r"</?[^>]+>", "", improved)

        if improved == original:
            improved = (
                "[목표]\n"
                + original
                + "\n\n[작업 지시]\n"
                + "1. 요청의 핵심을 분석합니다.\n"
                + "2. 필요한 내용을 구체적으로 정리합니다.\n"
                + "3. 불확실한 정보는 구분합니다.\n\n"
                + "[결과물 형식]\n"
                + "핵심 내용을 명확한 목록으로 정리해주세요."
            )

        st.session_state.prompt_original = original
        st.session_state.chat_draft = improved
        st.session_state.chat_error = ""

    except Exception as e:
        st.session_state.chat_error = (
            f"프롬프트 개선 오류: {e}"
        )


def restore_prompt():
    if st.session_state.prompt_original:
        st.session_state.chat_draft = (
            st.session_state.prompt_original
        )
