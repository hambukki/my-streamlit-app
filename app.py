
import os
import re
import json
import uuid
import base64
import html
import ssl
import sqlite3
import calendar
import smtplib
import threading
import time
import secrets
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from email.message import EmailMessage
from email.utils import getaddresses

import requests
import streamlit as st
import streamlit.components.v1 as components
from openai import OpenAI


# ==================================================
# 1. 기본 설정
# ==================================================

st.set_page_config(
    page_title="AIVLE | Personal Assistant",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="expanded"
)

for key in ["OPENAI_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"]:
    if not os.getenv(key):
        try:
            value = st.secrets.get(key)
            if value:
                os.environ[key] = str(value)
        except Exception:
            pass

if not os.getenv("OPENAI_API_KEY"):
    st.error("OPENAI_API_KEY가 없습니다. 인증 정보 설정을 확인해주세요.")
    st.stop()

client = OpenAI()

MODEL = "gpt-4o-mini"
STT_MODEL = "whisper-1"
TTS_MODEL = "tts-1"


def now_kst():
    return datetime.now(ZoneInfo("Asia/Seoul"))


# ==================================================
# 2. 사용자별 임시 작업 공간
# ==================================================

# 브라우저 새로고침 후에도 같은 작업 공간을 찾도록
# 임의 식별자를 URL에 기록합니다.
# 이것은 로그인 인증을 대신하지 않습니다.

SID = st.query_params.get("sid", "")

if not re.fullmatch(r"[A-Za-z0-9_-]{20,80}", SID):
    SID = secrets.token_urlsafe(24)
    st.query_params["sid"] = SID

PAGES = {
    "home": "홈",
    "chat": "AI 채팅",
    "meeting": "회의록 요약",
    "email": "이메일",
    "calendar": "내 일정",
    "translation": "한영 번역"
}

page = st.query_params.get("view", "home")

if page not in PAGES:
    page = "home"


# ==================================================
# 3. 데이터 저장
# ==================================================

# Colab: 기존 project03 구글 드라이브에 저장
# Streamlit Cloud: 앱 서버의 임시 로컬 저장소 사용
# (Cloud 서버가 재시작되면 로컬 데이터가 사라질 수 있습니다.)

drive_dir = Path("/content/drive/MyDrive/project03")

if drive_dir.is_dir():
    DB_PATH = drive_dir / "aivle_assistant.db"
else:
    DB_PATH = Path("aivle_assistant.db")


def connect_db():
    return sqlite3.connect(str(DB_PATH), timeout=10)


def init_db():
    with connect_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sid TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            sid TEXT NOT NULL,
            title TEXT NOT NULL,
            due_date TEXT,
            due_time TEXT,
            detail TEXT
        );

        CREATE TABLE IF NOT EXISTS contacts (
            sid TEXT NOT NULL,
            email TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY (sid, email)
        );

        CREATE TABLE IF NOT EXISTS settings (
            sid TEXT NOT NULL,
            name TEXT NOT NULL,
            value TEXT,
            PRIMARY KEY (sid, name)
        );
        """)

        fields = {
            row[1]
            for row in conn.execute("PRAGMA table_info(messages)")
        }

        if "conversation_id" not in fields:
            conn.execute(
                "ALTER TABLE messages "
                "ADD COLUMN conversation_id TEXT NOT NULL DEFAULT ''"
            )

        conn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            sid TEXT NOT NULL,
            title TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)

        # 기존 대화 기록을 보존합니다.
        for (old_sid,) in conn.execute(
            "SELECT DISTINCT sid FROM messages "
            "WHERE conversation_id=''"
        ).fetchall():

            legacy_id = "legacy-" + old_sid

            conn.execute(
                "INSERT OR IGNORE INTO conversations "
                "(id, sid, title, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    legacy_id,
                    old_sid,
                    "기존 대화",
                    now_kst().isoformat()
                )
            )

            conn.execute(
                "UPDATE messages SET conversation_id=? "
                "WHERE sid=? AND conversation_id=''",
                (legacy_id, old_sid)
            )


init_db()


def init_scheduled_email_table():
    with connect_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_emails (
                id TEXT PRIMARY KEY,
                sid TEXT NOT NULL,
                recipient TEXT NOT NULL,
                cc TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                send_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT NOT NULL DEFAULT ''
            )
        """)


init_scheduled_email_table()


def get_setting(name, default=""):
    with connect_db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE sid=? AND name=?",
            (SID, name)
        ).fetchone()
    return row[0] if row else default


def save_setting(name, value):
    with connect_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO settings
               (sid, name, value) VALUES (?, ?, ?)""",
            (SID, name, str(value))
        )



def load_conversations():
    with connect_db() as conn:
        return conn.execute(
            "SELECT id, title FROM conversations WHERE sid=? "
            "ORDER BY updated_at DESC LIMIT 10",
            (SID,)
        ).fetchall()


def create_conversation():
    conversation_id = str(uuid.uuid4())

    with connect_db() as conn:
        conn.execute(
            "INSERT INTO conversations "
            "(id, sid, title, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (
                conversation_id,
                SID,
                "새 채팅",
                now_kst().isoformat()
            )
        )

    save_setting("active_conversation_id", conversation_id)

    return conversation_id


def choose_conversation():
    candidate = (
        st.query_params.get("chat", "")
        or get_setting("active_conversation_id", "")
    )

    if candidate:
        with connect_db() as conn:
            found = conn.execute(
                "SELECT 1 FROM conversations "
                "WHERE id=? AND sid=?",
                (candidate, SID)
            ).fetchone()

        if found:
            return candidate

    existing = load_conversations()

    if existing:
        candidate = existing[0][0]
    else:
        candidate = create_conversation()

    save_setting("active_conversation_id", candidate)
    st.query_params["chat"] = candidate

    return candidate


ACTIVE_CHAT_ID = choose_conversation()


def switch_conversation(conversation_id):
    with connect_db() as conn:
        owned = conn.execute(
            "SELECT 1 FROM conversations "
            "WHERE id=? AND sid=?",
            (conversation_id, SID)
        ).fetchone()

    if not owned:
        return

    save_setting("active_conversation_id", conversation_id)

    st.query_params["chat"] = conversation_id
    st.query_params["view"] = "chat"

    st.session_state.reply_audio = None
    st.session_state.autoplay_reply = False
    st.session_state.chat_draft = ""
    st.session_state.pending_event = None

    save_setting("pending_event", "null")

    st.rerun()


def start_new_conversation():
    conversation_id = create_conversation()

    st.query_params["chat"] = conversation_id
    st.query_params["view"] = "chat"

    st.session_state.chat_draft = ""
    st.session_state.reply_audio = None
    st.session_state.autoplay_reply = False
    st.session_state.pending_event = None

    save_setting("pending_event", "null")

    st.rerun()


def set_conversation_title(first_message):
    with connect_db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM messages "
            "WHERE sid=? AND conversation_id=?",
            (SID, ACTIVE_CHAT_ID)
        ).fetchone()[0]

        if count == 0:
            title = (
                " ".join(first_message.split())[:35]
                or "새 채팅"
            )

            conn.execute(
                "UPDATE conversations "
                "SET title=?, updated_at=? "
                "WHERE id=? AND sid=?",
                (
                    title,
                    now_kst().isoformat(),
                    ACTIVE_CHAT_ID,
                    SID
                )
            )


def load_messages():
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages "
            "WHERE sid=? AND conversation_id=? "
            "ORDER BY id DESC LIMIT 20",
            (SID, ACTIVE_CHAT_ID)
        ).fetchall()

    return [
        {"role": role, "content": content}
        for role, content in reversed(rows)
    ]


def save_message(role, content):
    with connect_db() as conn:
        conn.execute(
            "INSERT INTO messages "
            "(sid, conversation_id, role, content) "
            "VALUES (?, ?, ?, ?)",
            (SID, ACTIVE_CHAT_ID, role, content)
        )

        # 각 대화에서 최근 메시지 20개 유지
        conn.execute(
            "DELETE FROM messages "
            "WHERE sid=? AND conversation_id=? "
            "AND id NOT IN ("
            "SELECT id FROM messages "
            "WHERE sid=? AND conversation_id=? "
            "ORDER BY id DESC LIMIT 20"
            ")",
            (
                SID,
                ACTIVE_CHAT_ID,
                SID,
                ACTIVE_CHAT_ID
            )
        )

        conn.execute(
            "UPDATE conversations SET updated_at=? "
            "WHERE id=? AND sid=?",
            (
                now_kst().isoformat(),
                ACTIVE_CHAT_ID,
                SID
            )
        )


def clear_messages():
    with connect_db() as conn:
        conn.execute(
            "DELETE FROM messages "
            "WHERE sid=? AND conversation_id=?",
            (SID, ACTIVE_CHAT_ID)
        )





def load_tasks():
    """등록된 업무와 완료 여부를 함께 불러옵니다."""

    with connect_db() as conn:

        rows = conn.execute(
            """
            SELECT
                id,
                title,
                due_date,
                due_time,
                detail,
                COALESCE(is_done, 0)
            FROM tasks
            WHERE sid=?
            ORDER BY
                CASE
                    WHEN due_date IS NULL OR due_date=''
                    THEN 1
                    ELSE 0
                END,
                due_date,
                due_time
            """,
            (SID,)
        ).fetchall()

    return [
        {
            "id": row[0],
            "task": row[1],
            "deadline": row[2] or "",
            "time": row[3] or "",
            "detail": row[4] or "",
            "is_done": bool(row[5])
        }
        for row in rows
    ]

def add_task(title, due_date="", due_time="", detail=""):
    task_id = str(uuid.uuid4())

    with connect_db() as conn:
        conn.execute(
            """INSERT INTO tasks
               (id, sid, title, due_date, due_time, detail)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (task_id, SID, title, due_date, due_time, detail)
        )

    return task_id


def load_contacts():
    with connect_db() as conn:
        return conn.execute(
            """SELECT name, email FROM contacts
               WHERE sid=? ORDER BY name""",
            (SID,)
        ).fetchall()


def save_contact(name, email):
    with connect_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO contacts
               (sid, name, email) VALUES (?, ?, ?)""",
            (SID, name, email)
        )


def delete_contact(email):
    with connect_db() as conn:
        conn.execute(
            "DELETE FROM contacts WHERE sid=? AND email=?",
            (SID, email)
        )


# ==================================================

def migrate_task_status():
    """기존 업무 데이터에 완료 여부 필드를 추가합니다."""

    with connect_db() as conn:

        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(tasks)"
            ).fetchall()
        }

        if "is_done" not in columns:
            conn.execute(
                "ALTER TABLE tasks "
                "ADD COLUMN is_done INTEGER NOT NULL DEFAULT 0"
            )


migrate_task_status()


def set_task_done(task_id, done):
    """선택한 업무의 완료 여부를 변경합니다."""

    with connect_db() as conn:
        conn.execute(
            "UPDATE tasks SET is_done=? "
            "WHERE id=? AND sid=?",
            (1 if done else 0, task_id, SID)
        )


# 4. Streamlit 상태 초기화
# ==================================================

defaults = {
    "messages": load_messages(),
    "chat_draft": "",
    "chat_error": "",
    "prompt_original": "",
    "voice_reply": True,
    "reply_audio": None,
    "autoplay_reply": False,
    "voice_transcript": "",
    "meeting_result": None,
    "meeting_version": 0,
    "meeting_audio": None,
    "meeting_autoplay": False,
    "email_to": "",
    "email_cc": "",
    "email_subject": "",
    "email_body": "",
    "email_error": "",
    "email_last_sent": "",
    "translation_result": "",
    "calendar_year": now_kst().year,
    "calendar_month": now_kst().month,
    "widget_clock": get_setting("widget_clock", "1") == "1",
    "widget_weather": get_setting("widget_weather", "1") == "1",
    "widget_briefing": get_setting("widget_briefing", "1") == "1",
    "weather_city": get_setting("weather_city", "서울")
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

if st.session_state.get("_active_chat_id") != ACTIVE_CHAT_ID:
    st.session_state["_active_chat_id"] = ACTIVE_CHAT_ID
    st.session_state.messages = load_messages()
    st.session_state.reply_audio = None
    st.session_state.autoplay_reply = False
    st.session_state.prompt_original = ""



try:
    pending_event = json.loads(get_setting("pending_event", "null"))
except json.JSONDecodeError:
    pending_event = None

if "pending_event" not in st.session_state:
    st.session_state.pending_event = pending_event


# ==================================================
# 5. AI 공통 함수
# ==================================================

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

현재 연결된 데이터에는 실시간 장소 검색 기능이 없습니다.
지역 맛집이나 특정 업체의 정보를 검증할 수 없다면
실시간 확인이 불가능하다고 명확하게 설명합니다.

모르는 정보는 추측해서 채우지 않습니다.
확실한 정보와 불확실한 정보를 구분하여 답변합니다.
"""


def ask_llm(messages, schema=None):
    options = {
        "model": MODEL,
        "input": messages
    }

    if schema is not None:
        options["text"] = {"format": schema}

    result = client.responses.create(**options)

    return result.output_text


def transcribe_audio(audio):
    data = audio.getvalue()

    if len(data) > 25 * 1024 * 1024:
        raise ValueError("25MB 이하의 음성 파일을 첨부해주세요.")

    name = getattr(audio, "name", "recording.wav")
    mime = getattr(audio, "type", None) or "audio/wav"

    result = client.audio.transcriptions.create(
        model=STT_MODEL,
        file=(name, data, mime)
    )

    return result.text


def make_speech(text):
    result = client.audio.speech.create(
        model=TTS_MODEL,
        voice="alloy",
        input=text[:4000]
    )
    return result.content


# ==================================================
# 6. 일정 감지용 JSON 스키마
# ==================================================

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


def detect_schedule(question):
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

                사용자의 메시지가 새 일정이나 업무를
                등록하려는 요청인지 판단하세요.

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


# ==================================================
# 7. 채팅 전송
# ==================================================


def process_chat(question):
    question = question.strip()

    if not question:
        return

    st.session_state.chat_error = ""

    try:
        tasks = load_tasks()

        task_context = json.dumps(
            tasks[:30],
            ensure_ascii=False
        )

        history = load_messages()

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
        elif (
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

        else:
            answer = ask_llm([
                {
                    "role": "system",
                    "content": (
                        SYS_ROLE
                        + "\n현재 등록된 일정:\n"
                        + task_context
                    )
                },
                *history,
                {
                    "role": "user",
                    "content": question
                }
            ])

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
    process_chat(st.session_state.chat_draft)


# ==================================================
# 8. 음성 녹음 완료 후 즉시 전송
# ==================================================

def send_voice_chat():
    audio = st.session_state.get("chat_voice")

    if audio is None:
        return

    try:
        transcript = transcribe_audio(audio)
        st.session_state.voice_transcript = transcript

        # 별도의 질문 보내기 버튼 없이 전송
        process_chat(transcript)

    except Exception as e:
        st.session_state.chat_error = f"음성 질문 처리 오류: {e}"


# ==================================================
# 9. 스마트 프롬프트 개선
# ==================================================

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


# ==================================================
# 10. 이메일
# ==================================================

def valid_email(address):
    return bool(
        re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address)
    )


def make_email_draft():
    subject = st.session_state.email_subject.strip()

    if not subject:
        st.session_state.email_error = (
            "먼저 이메일 제목이나 목적을 입력해주세요."
        )
        return

    try:
        answer = ask_llm([
            {
                "role": "system",
                "content": (
                    "당신은 김대리의 업무 비서입니다. "
                    "정중하고 간결한 업무 이메일 본문을 작성하세요. "
                    "확인되지 않은 사실은 만들어내지 마세요. "
                    "이메일 본문만 출력하세요."
                )
            },
            {
                "role": "user",
                "content": (
                    f"제목: {subject}\n"
                    f"받는 사람: {st.session_state.email_to}\n"
                    f"참고 내용: {st.session_state.email_body}"
                )
            }
        ])

        st.session_state.email_body = answer
        st.session_state.email_error = ""

    except Exception as e:
        st.session_state.email_error = str(e)


def send_gmail(to, cc, subject, body):
    sender = os.getenv("GMAIL_ADDRESS")
    password = os.getenv("GMAIL_APP_PASSWORD")

    if not sender or not password:
        raise ValueError("Gmail 인증 정보가 없습니다.")

    recipients = [to]
    if cc:
        recipients.extend(
            address.strip()
            for address in cc.split(",")
            if address.strip()
        )

    if not all(valid_email(address) for address in recipients):
        raise ValueError("이메일 주소 형식을 확인해주세요.")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject

    if cc:
        message["Cc"] = cc

    message.set_content(body)

    with smtplib.SMTP(
        "smtp.gmail.com", 587, timeout=20
    ) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(sender, password)
        server.send_message(message)




def schedule_gmail(to, cc, subject, body, send_at):
    recipients = [to] + [
        item.strip()
        for item in cc.split(",")
        if item.strip()
    ]

    if not all(valid_email(email) for email in recipients):
        raise ValueError(
            "받는 사람 또는 참조 이메일 주소가 올바르지 않습니다."
        )

    if not to.strip() or not subject.strip() or not body.strip():
        raise ValueError(
            "받는 사람, 제목, 본문을 모두 입력해주세요."
        )

    if send_at <= now_kst():
        raise ValueError(
            "예약 시각은 현재 시각 이후로 설정해주세요."
        )

    send_at_text = send_at.isoformat(timespec="seconds")

    with connect_db() as conn:
        previous = conn.execute(
            "SELECT id FROM scheduled_emails "
            "WHERE sid=? AND recipient=? AND cc=? "
            "AND subject=? AND body=? AND send_at=? "
            "AND status='pending'",
            (SID, to, cc, subject, body, send_at_text)
        ).fetchone()

        if previous:
            return False

        conn.execute(
            "INSERT INTO scheduled_emails "
            "(id, sid, recipient, cc, subject, body, send_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')",
            (
                str(uuid.uuid4()),
                SID,
                to,
                cc,
                subject,
                body,
                send_at_text
            )
        )

    return True


def load_scheduled_emails():
    with connect_db() as conn:
        return conn.execute(
            "SELECT id, recipient, subject, send_at, status, error "
            "FROM scheduled_emails "
            "WHERE sid=? "
            "ORDER BY send_at DESC LIMIT 15",
            (SID,)
        ).fetchall()


def _scheduled_mail_worker():
    while True:
        job = None

        try:
            current = now_kst()

            with connect_db() as conn:
                conn.execute("BEGIN IMMEDIATE")

                row = conn.execute(
                    "SELECT id, recipient, cc, subject, body, send_at "
                    "FROM scheduled_emails "
                    "WHERE status='pending' AND send_at<=? "
                    "ORDER BY send_at LIMIT 1",
                    (current.isoformat(timespec="seconds"),)
                ).fetchone()

                if row is not None:
                    due = datetime.fromisoformat(row[5])

                    # 서버가 장시간 멈췄다면 늦게 발송하지 않습니다.
                    if current - due > timedelta(minutes=10):
                        conn.execute(
                            "UPDATE scheduled_emails "
                            "SET status='missed', "
                            "error='서버 중단 등으로 발송 시각을 놓쳤습니다.' "
                            "WHERE id=?",
                            (row[0],)
                        )
                    else:
                        conn.execute(
                            "UPDATE scheduled_emails "
                            "SET status='sending' "
                            "WHERE id=? AND status='pending'",
                            (row[0],)
                        )
                        job = row

            if job is not None:
                message_id, to, cc, subject, body, _ = job

                try:
                    send_gmail(to, cc, subject, body)

                    with connect_db() as conn:
                        conn.execute(
                            "UPDATE scheduled_emails "
                            "SET status='sent', error='' "
                            "WHERE id=? AND status='sending'",
                            (message_id,)
                        )

                except Exception as exc:
                    with connect_db() as conn:
                        conn.execute(
                            "UPDATE scheduled_emails "
                            "SET status='failed', error=? "
                            "WHERE id=? AND status='sending'",
                            (str(exc)[:300], message_id)
                        )

        except Exception as exc:
            print(
                "예약전송 점검 오류:",
                type(exc).__name__,
                str(exc)
            )

        time.sleep(5)


@st.cache_resource
def start_scheduled_email_worker():
    worker = threading.Thread(
        target=_scheduled_mail_worker,
        name="aivle-scheduled-gmail",
        daemon=True
    )

    worker.start()
    return worker


start_scheduled_email_worker()


# ==================================================
# 11. 회의록 요약 스키마
# ==================================================

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
                        "detail": {"type": "string"}
                    },
                    "required": [
                        "task", "deadline", "detail"
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


# ==================================================
# 12. 날씨 위젯
# ==================================================

CITIES = {
    "서울": (37.5665, 126.9780),
    "화성": (37.1995, 127.0732),
    "부산": (35.1796, 129.0756)
}


@st.cache_data(ttl=900)
def get_weather(city):
    lat, lon = CITIES[city]

    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": (
                "temperature_2m,"
                "apparent_temperature,"
                "relative_humidity_2m,"
                "weather_code"
            ),
            "timezone": "Asia/Seoul"
        },
        timeout=8
    )
    response.raise_for_status()
    return response.json()["current"]


def weather_description(code):
    if code == 0:
        return "맑음"
    if code in [1, 2, 3]:
        return "구름"
    if code in [45, 48]:
        return "안개"
    if code in [51, 53, 55, 61, 63, 65, 80, 81, 82]:
        return "비"
    if code in [71, 73, 75, 77, 85, 86]:
        return "눈"
    if code in [95, 96, 99]:
        return "뇌우"
    return "날씨 확인 중"


# ==================================================
# 13. 화면 디자인
# ==================================================

st.markdown('\n<style>\n\n@import url(\'https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css\');\n\n:root {\n    --background: #F6F9F7;\n    --sidebar: #EAF3EF;\n    --surface: #FFFFFF;\n    --text: #19332C;\n    --muted: #526E63;\n    --border: #D4E3DA;\n    --primary: #087568;\n}\n\n/* 전체 화면 */\n\nhtml, body, .stApp,\nbutton, input, textarea, select {\n    font-family:\n        \'Pretendard Variable\',\n        Pretendard,\n        -apple-system,\n        BlinkMacSystemFont,\n        sans-serif !important;\n}\n\n.stApp,\n[data-testid="stAppViewContainer"] {\n    background: #F6F9F7 !important;\n    color: #19332C !important;\n}\n\n[data-testid="stHeader"] {\n    background: rgba(246,249,247,.96) !important;\n}\n\n.block-container {\n    max-width: 1280px;\n    padding-top: 2rem;\n    padding-bottom: 4rem;\n}\n\n/* 텍스트 */\n\nh1, h2, h3, h4,\n.stMarkdown h1,\n.stMarkdown h2,\n.stMarkdown h3 {\n    color: #19332C !important;\n}\n\n.stMarkdown p,\n.stMarkdown li,\n.stMarkdown strong {\n    color: #19332C;\n}\n\n[data-testid="stWidgetLabel"] p,\n.stApp label {\n    color: #25453B !important;\n}\n\n[data-testid="stCaptionContainer"],\n[data-testid="stCaptionContainer"] p {\n    color: #526E63 !important;\n}\n\n/* 왼쪽 메뉴 */\n\nsection[data-testid="stSidebar"] {\n    background: #EAF3EF !important;\n    border-right: 1px solid #CDDFD5;\n}\n\nsection[data-testid="stSidebar"] h1 {\n    color: #075C50 !important;\n}\n\nsection[data-testid="stSidebar"] p,\nsection[data-testid="stSidebar"] label {\n    color: #2B5145 !important;\n}\n\nsection[data-testid="stSidebar"] .stButton button {\n    width: 100%;\n    min-height: 47px;\n    justify-content: flex-start;\n    text-align: left;\n\n    background: transparent !important;\n    border: 1px solid transparent !important;\n    color: #24453A !important;\n\n    border-radius: 10px;\n    font-weight: 650;\n}\n\nsection[data-testid="stSidebar"] .stButton button:hover {\n    background: #D6E8DE !important;\n    border-color: #A5CABB !important;\n}\n\nsection[data-testid="stSidebar"]\n.stButton button[kind="primary"],\nsection[data-testid="stSidebar"]\n[data-testid="baseButton-primary"] {\n    background: #087568 !important;\n    border-color: #087568 !important;\n    color: #FFFFFF !important;\n}\n\nsection[data-testid="stSidebar"]\n.stButton button[kind="primary"] *,\nsection[data-testid="stSidebar"]\n[data-testid="baseButton-primary"] * {\n    color: #FFFFFF !important;\n}\n\n/* 일반 버튼 */\n\ndiv.stButton button[kind="secondary"],\ndiv.stFormSubmitButton button[kind="secondary"],\n[data-testid="baseButton-secondary"] {\n    background: #FFFFFF !important;\n    border: 1px solid #AFCBBF !important;\n    color: #193B31 !important;\n    border-radius: 10px;\n    font-weight: 650;\n}\n\ndiv.stButton button[kind="secondary"] *,\ndiv.stFormSubmitButton button[kind="secondary"] *,\n[data-testid="baseButton-secondary"] * {\n    color: #193B31 !important;\n}\n\n/* 주요 버튼 */\n\ndiv.stButton button[kind="primary"],\ndiv.stFormSubmitButton button[kind="primary"],\n[data-testid="baseButton-primary"] {\n    background: #087568 !important;\n    border: 1px solid #087568 !important;\n    color: #FFFFFF !important;\n    border-radius: 10px;\n    font-weight: 750;\n}\n\ndiv.stButton button[kind="primary"] *,\ndiv.stFormSubmitButton button[kind="primary"] *,\n[data-testid="baseButton-primary"] * {\n    color: #FFFFFF !important;\n}\n\nbutton:disabled {\n    opacity: .55 !important;\n}\n\n/* 입력창 */\n\n.stTextInput input,\n.stTextArea textarea,\n.stDateInput input,\n.stTimeInput input {\n    background: #FFFFFF !important;\n    border: 1px solid #B8D0C4 !important;\n    color: #17372D !important;\n    -webkit-text-fill-color: #17372D !important;\n    border-radius: 10px !important;\n}\n\n.stTextInput input::placeholder,\n.stTextArea textarea::placeholder {\n    color: #718B7F !important;\n    -webkit-text-fill-color: #718B7F !important;\n}\n\ndiv[data-baseweb="select"] > div,\ndiv[data-baseweb="input"] > div,\ndiv[data-baseweb="textarea"] > div {\n    background: #FFFFFF !important;\n    color: #19332C !important;\n    border-color: #B8D0C4 !important;\n}\n\n/* 카드 */\n\n[data-testid="stVerticalBlockBorderWrapper"] > div {\n    background: #FFFFFF;\n    border-color: #D2E1D8 !important;\n    border-radius: 15px !important;\n}\n\n[data-testid="stExpander"] {\n    background: #FFFFFF !important;\n    border: 1px solid #D2E1D8 !important;\n}\n\n[data-testid="stExpander"] summary,\n[data-testid="stExpander"] summary p {\n    color: #19332C !important;\n}\n\n[data-testid="stMetric"] {\n    background: #FFFFFF !important;\n    border: 1px solid #D2E1D8 !important;\n    border-radius: 15px;\n    padding: 18px;\n}\n\n[data-testid="stMetricValue"] * {\n    color: #193B31 !important;\n}\n\n/* 채팅 */\n\n[data-testid="stChatMessage"] {\n    background: #FFFFFF !important;\n    border: 1px solid #D2E1D8 !important;\n    border-radius: 15px;\n}\n\n[data-testid="stChatMessage"] p,\n[data-testid="stChatMessage"] li,\n[data-testid="stChatMessage"] strong {\n    color: #19332C !important;\n}\n\n/* 홈 */\n\n.aivle-hero {\n    position: relative;\n    overflow: hidden;\n    min-height: 210px;\n    padding: 42px;\n    border-radius: 21px;\n\n    background:\n        linear-gradient(\n            115deg,\n            #E8F7EF,\n            #C6EADA\n        ) !important;\n\n    border: 1px solid #B5DCCC !important;\n    margin-bottom: 24px;\n}\n\n.aivle-hero h2 {\n    color: #124C3E !important;\n    font-size: 30px;\n    font-weight: 800;\n    position: relative;\n    z-index: 2;\n    max-width: 70%;\n}\n\n.aivle-hero p {\n    color: #315F50 !important;\n    position: relative;\n    z-index: 2;\n    max-width: 65%;\n}\n\n/* 업무 브리핑 */\n\n.briefing-item {\n    background: #FFFFFF;\n    border: 1px solid #D5E4DB;\n    border-radius: 10px;\n    padding: 12px 16px;\n    margin: 7px 0;\n}\n\n.briefing-item strong {\n    display: block;\n    color: #19332C;\n    font-size: 14px;\n}\n\n.briefing-item span {\n    color: #547165;\n    font-size: 12px;\n}\n\n/* 캘린더 */\n\n.calendar-table {\n    width: 100%;\n    border-collapse: separate;\n    border-spacing: 5px;\n    table-layout: fixed;\n}\n\n.calendar-table th {\n    text-align: center;\n    padding: 10px;\n    color: #526E63;\n}\n\n.calendar-table td {\n    width: 14.28%;\n    height: 116px;\n    vertical-align: top;\n\n    background: #FFFFFF;\n    border: 1px solid #D4E3DA;\n    border-radius: 10px;\n\n    padding: 9px;\n    color: #19332C;\n}\n\n.calendar-table td.calendar-today {\n    border: 2px solid #087568;\n    background: #F3FBF6;\n}\n\n.calendar-table .sunday {\n    color: #C52D47 !important;\n    font-weight: 700;\n}\n\n.calendar-table .other-month {\n    color: #9AAD9F;\n    background: #EFF4F1;\n}\n\n.calendar-day {\n    display: block;\n    margin-bottom: 7px;\n    font-size: 14px;\n    font-weight: 700;\n}\n\n.calendar-event {\n    display: block;\n    margin: 4px 0;\n    padding: 5px 6px;\n\n    background: #DFF1E7;\n    color: #175647;\n\n    border-left: 3px solid #087568;\n    border-radius: 4px;\n\n    font-size: 11px;\n    line-height: 1.35;\n\n    white-space: nowrap;\n    overflow: hidden;\n    text-overflow: ellipsis;\n}\n\n.calendar-event.done {\n    background: #EFF2F0;\n    border-left-color: #A4B1AA;\n    color: #87978F;\n    text-decoration: line-through;\n}\n\n.calendar-more {\n    display: block;\n    padding: 3px;\n    font-size: 11px;\n    color: #577569;\n}\n\n.calendar-table td.other-month .calendar-event {\n    opacity: .55;\n}\n\n/* 기타 */\n\n[data-testid="stFileUploadDropzone"] {\n    background: #FFFFFF !important;\n    border-color: #B8D0C4 !important;\n}\n\n[data-testid="stAlert"] {\n    border-radius: 12px;\n}\n\nhr {\n    border-color: #D4E3DA !important;\n}\n\n@media (max-width: 800px) {\n\n    .aivle-hero {\n        padding: 26px;\n    }\n\n    .aivle-hero h2 {\n        font-size: 23px;\n        max-width: 100%;\n    }\n\n    .aivle-hero p {\n        max-width: 100%;\n    }\n\n    .calendar-table td {\n        height: 90px;\n        padding: 4px;\n    }\n\n    .calendar-event {\n        font-size: 10px;\n        padding: 3px;\n    }\n}\n\n</style>\n', unsafe_allow_html=True)

# ==================================================

# 14. 왼쪽 버튼형 메뉴
# ==================================================

NAV = [
    ("home", "홈", "home"),
    ("chat", "AI 채팅", "forum"),
    ("meeting", "회의록 요약", "description"),
    ("email", "이메일", "mail"),
    ("calendar", "내 일정", "calendar_month"),
    ("translation", "한영 번역", "translate")
]

with st.sidebar:
    st.markdown(
        '<h1 style="color:#FFFFFF;font-size:29px;'
        'font-weight:800;margin-bottom:0;">✦ AIVLE</h1>',
        unsafe_allow_html=True
    )
    st.markdown(
        '<p style="color:#67EED7;font-size:11px;'
        'letter-spacing:2px;">PERSONAL AI ASSISTANT</p>',
        unsafe_allow_html=True
    )

    st.divider()

    for nav_id, nav_label, nav_icon in NAV:
        active = (page == nav_id)

        if st.button(
            nav_label,
            key=f"nav_{nav_id}",
            icon=f":material/{nav_icon}:",
            type="primary" if active else "secondary",
            use_container_width=True
        ):
            st.query_params["view"] = nav_id
            st.rerun()

    st.divider()

    st.caption("김대리 전담 비서")
    st.caption(f"MODEL · {MODEL}")


# ==================================================
# 15. 홈 화면
# ==================================================




if page == "home":

    import html as html_escape_module

    tasks = load_tasks()
    today = now_kst().date()
    today_text = today.isoformat()

    # 완료되지 않은 업무만 브리핑에 표시
    pending_tasks = [
        task for task in tasks
        if not task.get("is_done", False)
    ]

    overdue_tasks = []
    today_tasks = []
    upcoming_tasks = []
    undated_tasks = []

    for task in pending_tasks:

        deadline = task["deadline"]

        if not deadline:
            undated_tasks.append(task)

        elif deadline < today_text:
            overdue_tasks.append(task)

        elif deadline == today_text:
            today_tasks.append(task)

        else:
            upcoming_tasks.append(task)

    st.markdown(
        """
        <div class="aivle-hero">
            <h2>좋은 하루예요, 김대리님.</h2>
            <p>
                오늘 처리할 업무부터 다가오는 일정까지,
                에이블이 함께 확인해 드릴게요.
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )

    with st.popover(
        "홈 위젯 설정",
        icon=":material/tune:"
    ):

        for key, label in [
            ("widget_clock", "날짜와 시간"),
            ("widget_weather", "날씨"),
            ("widget_briefing", "업무 브리핑")
        ]:

            value = st.checkbox(
                label,
                key=key
            )

            save_setting(
                key,
                "1" if value else "0"
            )

    if st.session_state.widget_briefing:

        st.subheader("오늘의 업무 브리핑")

        st.caption(
            "완료하지 않은 업무를 기한별로 정리했습니다."
        )

        if not pending_tasks:
            st.success(
                "등록된 미완료 업무가 없습니다."
            )

        else:

            a, b, c = st.columns(3)

            a.metric(
                "오늘 처리할 업무",
                len(today_tasks)
            )

            b.metric(
                "다가오는 업무",
                len(upcoming_tasks)
            )

            c.metric(
                "전체 미완료 업무",
                len(pending_tasks)
            )

            groups = [
                ("기한이 지난 업무", overdue_tasks),
                ("오늘의 업무", today_tasks),
                ("다가오는 일정", upcoming_tasks),
                ("기한 미정 업무", undated_tasks)
            ]

            for group_name, group_tasks in groups:

                if not group_tasks:
                    continue

                st.markdown(
                    f"#### {group_name} · {len(group_tasks)}건"
                )

                for task in group_tasks:

                    title = html_escape_module.escape(
                        task["task"]
                    )

                    deadline = (
                        task["deadline"]
                        if task["deadline"]
                        else "기한 미정"
                    )

                    if task["time"]:
                        deadline += (
                            " · " + task["time"]
                        )

                    detail = (
                        html_escape_module.escape(
                            task["detail"]
                        )
                        if task["detail"]
                        else ""
                    )

                    st.markdown(
                        f"""
                        <div class="briefing-item">
                            <strong>{title}</strong>
                            <span>
                                {deadline}
                                {(" · " + detail) if detail else ""}
                            </span>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

    left, right = st.columns(2)

    with left:

        if st.session_state.widget_clock:

            st.subheader("날짜와 시간")

            components.html(
                """
                <div style="
                    padding:24px;
                    border-radius:14px;
                    background:#FFFFFF;
                    border:1px solid #D4E3DA;
                    font-family:Arial,sans-serif;
                    color:#19332C;
                ">
                    <div style="
                        font-size:12px;
                        color:#526E63;
                    ">
                        KOREA STANDARD TIME
                    </div>

                    <div id="clock" style="
                        font-size:25px;
                        font-weight:700;
                        margin-top:12px;
                    "></div>
                </div>

                <script>
                function updateClock() {
                    const options = {
                        timeZone: "Asia/Seoul",
                        year: "numeric",
                        month: "long",
                        day: "numeric",
                        weekday: "long",
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit"
                    };

                    document.getElementById(
                        "clock"
                    ).textContent =
                        new Intl.DateTimeFormat(
                            "ko-KR",
                            options
                        ).format(new Date());
                }

                updateClock();
                setInterval(updateClock, 1000);
                </script>
                """,
                height=145
            )

    with right:

        if st.session_state.widget_weather:

            st.subheader("오늘의 날씨")

            city = st.selectbox(
                "지역",
                list(CITIES.keys()),
                key="weather_city"
            )

            save_setting(
                "weather_city",
                city
            )

            try:

                weather = get_weather(city)

                st.metric(
                    f"{city} · "
                    f"{weather_description(weather['weather_code'])}",
                    f"{weather['temperature_2m']}°C"
                )

                st.caption(
                    f"체감 {weather['apparent_temperature']}°C"
                    f" · 습도 {weather['relative_humidity_2m']}%"
                    " · Open-Meteo 제공"
                )

            except Exception:
                st.info(
                    "현재 날씨 정보를 불러올 수 없습니다."
                )

elif page == "chat":
    st.title("AI 채팅")
    st.caption("질문하고, 음성으로 대화하고, 일정을 등록하세요.")

    with st.expander(
        "대화 라이브러리 · 최근 10개",
        expanded=False
    ):
        if st.button(
            "새 채팅",
            key="chat_new_inside",
            icon=":material/add_comment:",
            use_container_width=True
        ):
            start_new_conversation()

        for conversation_id, title in load_conversations():
            if st.button(
                title,
                key=f"chat_library_{conversation_id}",
                type=(
                    "primary"
                    if conversation_id == ACTIVE_CHAT_ID
                    else "secondary"
                ),
                use_container_width=True
            ):
                switch_conversation(conversation_id)


    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    st.divider()

    st.text_area(
        "메시지 작성",
        key="chat_draft",
        height=125,
        placeholder="에이블에게 요청할 업무를 입력하세요."
    )

    a, b, c = st.columns([1.2, 1.2, 1])

    with a:
        st.button(
            "프롬프트 개선",
            icon=":material/auto_fix_high:",
            on_click=improve_prompt,
            use_container_width=True
        )

    with b:
        st.button(
            "질문 보내기",
            icon=":material/send:",
            on_click=send_text_chat,
            type="primary",
            use_container_width=True
        )

    with c:
        st.checkbox(
            "음성 답변",
            key="voice_reply"
        )

    if st.session_state.prompt_original:
        with st.expander("프롬프트 개선 전후 확인"):
            st.caption("개선 전")
            st.text(st.session_state.prompt_original)

            st.caption("개선 후")
            st.text(st.session_state.chat_draft)

            st.button(
                "원래 프롬프트로 되돌리기",
                on_click=restore_prompt
            )

    with st.expander("음성으로 질문하기"):
        st.caption(
            "마이크로 녹음한 뒤 종료하면 "
            "질문이 자동으로 전송됩니다."
        )

        st.audio_input(
            "음성 질문",
            key="chat_voice",
            on_change=send_voice_chat
        )

        if st.session_state.voice_transcript:
            st.caption(
                "인식된 질문: "
                + st.session_state.voice_transcript
            )

    if st.session_state.chat_error:
        st.warning(st.session_state.chat_error)

    if st.session_state.reply_audio:
        st.markdown("**에이블의 음성 답변**")

        st.audio(
            st.session_state.reply_audio,
            format="audio/mp3",
            autoplay=st.session_state.autoplay_reply
        )

        # 탭 이동이나 새로고침 시 다시 재생하지 않음
        st.session_state.autoplay_reply = False

    # 채팅으로 추출한 일정
    proposal = st.session_state.pending_event

    if proposal:
        st.divider()

        with st.container(border=True):
            st.subheader("일정에 추가하시겠습니까?")
            st.caption(
                "에이블이 일정 요청을 감지했습니다. "
                "내용을 확인한 후 등록하세요."
            )

            with st.form("schedule_confirm"):
                title = st.text_input(
                    "일정명",
                    value=proposal["title"]
                )
                date = st.text_input(
                    "날짜 (YYYY-MM-DD)",
                    value=proposal["date"]
                )
                time_value = st.text_input(
                    "시간 (HH:MM, 선택)",
                    value=proposal["time"]
                )
                detail = st.text_area(
                    "설명",
                    value=proposal["detail"]
                )

                confirm = st.form_submit_button(
                    "일정에 추가",
                    type="primary"
                )

            if confirm:
                try:
                    datetime.strptime(date, "%Y-%m-%d")

                    if time_value:
                        datetime.strptime(time_value, "%H:%M")

                    add_task(
                        title,
                        date,
                        time_value,
                        detail
                    )

                    st.session_state.pending_event = None
                    save_setting("pending_event", "null")

                    st.success("내 일정에 등록했습니다.")

                except ValueError:
                    st.error(
                        "날짜 또는 시간 형식을 확인해주세요."
                    )

            if st.button("이번 일정 제안 취소"):
                st.session_state.pending_event = None
                save_setting("pending_event", "null")
                st.rerun()

    if st.button(
        "새 대화 시작",
        icon=":material/add_comment:"
    ):
        start_new_conversation()


# ==================================================
# 17. 회의록 요약
# ==================================================

elif page == "meeting":
    st.title("회의록 요약")
    st.caption("회의 내용을 분석하고 담당 업무를 확인하세요.")

    notes = st.text_area(
        "회의 내용",
        height=180,
        placeholder="회의 내용을 입력하거나 음성 파일을 첨부하세요."
    )

    notes_file = st.file_uploader(
        "회의록 TXT 파일 첨부 (선택)",
        type=["txt"],
        key="meeting_text_upload"
    )

    txt_notes = ""

    if notes_file is not None:
        raw = notes_file.getvalue()

        try:
            txt_notes = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                txt_notes = raw.decode("cp949")
            except UnicodeDecodeError:
                st.error(
                    "TXT 파일을 UTF-8 또는 CP949 형식으로 저장해주세요."
                )

        if txt_notes:
            st.text_area(
                "첨부 파일 내용 미리보기",
                value=txt_notes,
                height=120
            )

    left, right = st.columns(2)

    with left:
        file = st.file_uploader(
            "회의 음성 파일 첨부",
            type=["mp3", "wav", "m4a", "mp4", "webm"]
        )
        if file:
            st.audio(file)

    with right:
        recording = st.audio_input("회의 내용 녹음")
        if recording:
            st.audio(recording)

    if st.button("회의록 요약하기", type="primary"):
        try:
            source = "\n".join(
                part
                for part in [notes.strip(), txt_notes.strip()]
                if part
            )

            audio = file or recording

            if audio:
                source += "\n" + transcribe_audio(audio)

            if not source.strip():
                st.warning("회의 내용을 입력해주세요.")
            else:
                response = ask_llm(
                    [
                        {
                            "role": "system",
                            "content": (
                                SYS_ROLE
                                + "\n다음 회의를 요약하세요. "
                                + "결정사항과 김대리 담당 업무를 구분하세요. "
                                + "김대리가 회의에 참석하지 않았더라도 명시적으로 배정된 업무는 추출하세요. "
                                + "다른 사람에게 배정된 업무를 김대리의 업무로 바꾸지 마세요. "
                                + "불확실한 업무는 추측하지 마세요. "
                                + "명확한 날짜만 YYYY-MM-DD로 작성하세요. "
                                + "모르는 기한은 빈 문자열로 작성하세요."
                            )
                        },
                        {
                            "role": "user",
                            "content": source
                        }
                    ],
                    schema=MEETING_SCHEMA
                )

                result = json.loads(response)
                st.session_state.meeting_result = result
                st.session_state.meeting_version += 1
                st.session_state.meeting_audio = None

                save_setting(
                    "meeting_result",
                    json.dumps(result, ensure_ascii=False)
                )

                st.success("회의록을 요약했습니다.")

        except Exception as e:
            st.error(f"회의록 요약 오류: {e}")

    result = st.session_state.meeting_result

    if result is None:
        try:
            result = json.loads(
                get_setting("meeting_result", "null")
            )
        except json.JSONDecodeError:
            result = None

    if result:
        version = st.session_state.meeting_version

        st.subheader("회의 요약")

        summary = st.text_area(
            "요약 내용 확인",
            value=result["summary"],
            height=160,
            key=f"meeting_summary_{version}"
        )

        st.subheader("주요 결정사항")

        for decision in result["decisions"]:
            st.write("• " + decision)

        st.subheader("김대리 담당 업무")

        selected_tasks = []

        if not result["kim_tasks"]:
            st.info("김대리에게 명시적으로 배정된 업무는 없습니다.")

        for i, task in enumerate(result["kim_tasks"]):
            with st.container(border=True):
                selected = st.checkbox(
                    f"업무 {i+1}을 일정에 추가",
                    value=True,
                    key=f"meeting_select_{version}_{i}"
                )

                name = st.text_input(
                    "업무명",
                    value=task["task"],
                    key=f"meeting_name_{version}_{i}"
                )

                date = st.text_input(
                    "기한 (YYYY-MM-DD)",
                    value=task["deadline"],
                    key=f"meeting_date_{version}_{i}"
                )

                detail = st.text_area(
                    "업무 설명",
                    value=task["detail"],
                    key=f"meeting_detail_{version}_{i}"
                )

                selected_tasks.append(
                    (selected, name, date, detail)
                )

        for question in result["questions"]:
            st.warning(question)

        st.subheader("일정에 추가하시겠습니까?")
        st.caption(
            "김대리의 담당 업무만 선택하여 내 일정에 등록합니다."
        )

        reviewed = st.checkbox(
            "회의 내용과 업무를 검토했습니다."
        )

        if st.button("선택한 업무를 내 일정에 추가", type="primary"):
            if not reviewed:
                st.warning("검토 여부를 확인해주세요.")
            else:
                added = 0
                for selected, name, date, detail in selected_tasks:
                    if not selected or not name.strip():
                        continue

                    try:
                        if date:
                            datetime.strptime(date, "%Y-%m-%d")

                        existing = load_tasks()

                        if not any(
                            item["task"] == name
                            and item["deadline"] == date
                            for item in existing
                        ):
                            add_task(name, date, "", detail)
                            added += 1
                    except ValueError:
                        st.error(
                            f"'{name}'의 날짜 형식을 확인해주세요."
                        )

                st.success(f"{added}개 업무를 추가했습니다.")

        if st.button("요약 음성으로 듣기"):
            try:
                st.session_state.meeting_audio = make_speech(summary)
                st.session_state.meeting_autoplay = True
            except Exception as e:
                st.error(str(e))

        if st.session_state.meeting_audio:
            st.audio(
                st.session_state.meeting_audio,
                format="audio/mp3",
                autoplay=st.session_state.meeting_autoplay
            )
            st.session_state.meeting_autoplay = False


# ==================================================
# 18. 이메일 및 주소록
# ==================================================

elif page == "email":
    st.title("이메일 비서")
    st.caption("AI 초안 작성, 참조 지정, 주소록 선택 및 발송")

    contacts = load_contacts()

    contact_options = ["직접 입력"] + [
        f"{name} <{email}>"
        for name, email in contacts
    ]

    selected_contact = st.selectbox(
        "주소록에서 수신자 선택",
        contact_options
    )

    if selected_contact != "직접 입력":
        contact_email = selected_contact.rsplit("<", 1)[-1].rstrip(">")
        if st.button("선택한 연락처를 수신자로 지정"):
            st.session_state.email_to = contact_email
            st.rerun()

    st.text_input("받는 사람", key="email_to")
    st.text_input(
        "참조 (CC)",
        key="email_cc",
        placeholder="여러 명이면 쉼표로 구분"
    )
    st.text_input("제목", key="email_subject")
    st.text_area("본문", key="email_body", height=210)

    st.button(
        "AI 이메일 초안 작성",
        icon=":material/auto_awesome:",
        on_click=make_email_draft
    )

    if st.session_state.email_error:
        st.warning(st.session_state.email_error)

    approved = st.checkbox(
        "수신자, 참조, 제목, 본문을 확인했고 발송에 동의합니다."
    )

    if st.button(
        "이메일 전송",
        type="primary",
        icon=":material/send:",
        disabled=not approved
    ):
        try:
            to = st.session_state.email_to.strip()
            cc = st.session_state.email_cc.strip()
            subject = st.session_state.email_subject.strip()
            body = st.session_state.email_body.strip()

            if not to or not subject or not body:
                st.warning("필수 항목을 모두 입력해주세요.")
            else:
                signature = json.dumps(
                    [to, cc, subject, body],
                    ensure_ascii=False
                )

                if signature == st.session_state.email_last_sent:
                    st.warning("동일한 내용의 이메일을 이미 전송했습니다.")
                else:
                    send_gmail(to, cc, subject, body)
                    st.session_state.email_last_sent = signature
                    st.success("이메일을 전송했습니다.")

        except Exception as e:
            st.error(f"이메일 전송 실패: {e}")


    st.subheader("이메일 예약전송")

    st.caption(
        "현재 시연 버전은 앱 서버가 실행 중일 때만 예약을 처리합니다. "
        "서버가 중단되거나 휴면 상태가 되면 예약 시각에 "
        "발송되지 않을 수 있습니다."
    )

    with st.form("gmail_schedule_form"):
        send_date = st.date_input(
            "예약 날짜",
            value=now_kst().date(),
            min_value=now_kst().date()
        )

        send_time = st.time_input(
            "예약 시간 (한국 시간)",
            value=(
                now_kst() + timedelta(minutes=5)
            ).time().replace(
                second=0,
                microsecond=0
            )
        )

        scheduled_approved = st.checkbox(
            "작성한 이메일을 지정 시각에 자동 전송하도록 승인합니다."
        )

        schedule_submitted = st.form_submit_button(
            "예약전송 등록",
            type="primary"
        )

    if schedule_submitted:
        if not scheduled_approved:
            st.warning(
                "예약전송 승인 항목을 확인해주세요."
            )
        else:
            try:
                send_at = datetime.combine(
                    send_date,
                    send_time,
                    tzinfo=ZoneInfo("Asia/Seoul")
                )

                created = schedule_gmail(
                    st.session_state.email_to.strip(),
                    st.session_state.email_cc.strip(),
                    st.session_state.email_subject.strip(),
                    st.session_state.email_body.strip(),
                    send_at
                )

                if created:
                    st.success(
                        "예약을 등록했습니다. "
                        "발송 시각까지 서버를 실행 상태로 유지해주세요."
                    )
                else:
                    st.info(
                        "동일한 예약이 이미 등록되어 있습니다."
                    )

            except Exception as exc:
                st.error(f"예약 등록 실패: {exc}")

    with st.expander("예약전송 내역"):
        labels = {
            "pending": "발송 대기",
            "sending": "발송 중",
            "sent": "발송 완료",
            "failed": "발송 실패",
            "missed": "예약 시각 경과",
            "cancelled": "취소됨"
        }

        scheduled_rows = load_scheduled_emails()

        if not scheduled_rows:
            st.caption("예약된 이메일이 없습니다.")

        for (
            record_id,
            recipient,
            subject,
            send_at_text,
            status,
            error
        ) in scheduled_rows:

            with st.container(border=True):
                st.write(f"**{subject}** · {recipient}")

                display_time = send_at_text[:16].replace("T", " ")

                st.caption(
                    f"{display_time} KST · "
                    f"{labels.get(status, status)}"
                )

                if error:
                    st.caption(f"상태 안내: {error}")

                if status == "pending" and st.button(
                    "예약 취소",
                    key=f"cancel_mail_{record_id}"
                ):
                    with connect_db() as conn:
                        conn.execute(
                            "UPDATE scheduled_emails "
                            "SET status='cancelled' "
                            "WHERE id=? AND sid=? AND status='pending'",
                            (record_id, SID)
                        )

                    st.rerun()

    st.divider()

    with st.expander("주소록 관리"):
        with st.form("contact_add"):
            name = st.text_input("이름")
            email = st.text_input("이메일 주소")
            submitted = st.form_submit_button("연락처 저장")

        if submitted:
            if name.strip() and valid_email(email.strip()):
                save_contact(name.strip(), email.strip())
                st.success("연락처를 저장했습니다.")
                st.rerun()
            else:
                st.warning("이름과 이메일 주소를 확인해주세요.")

        contacts = load_contacts()

        for name, email in contacts:
            c1, c2 = st.columns([5, 1])
            c1.write(f"**{name}** · {email}")

            if c2.button(
                "삭제",
                key=f"delete_contact_{email}"
            ):
                delete_contact(email)
                st.rerun()


# ==================================================
# 19. 캘린더
# ==================================================




elif page == "calendar":

    import html as html_escape_module

    st.title("내 일정")

    st.caption(
        "날짜별로 등록된 업무를 확인하고 "
        "완료 여부를 관리할 수 있습니다."
    )

    year = st.session_state.calendar_year
    month = st.session_state.calendar_month

    def move_month(amount):

        total = (
            st.session_state.calendar_year * 12
            + st.session_state.calendar_month
            - 1
            + amount
        )

        st.session_state.calendar_year = total // 12
        st.session_state.calendar_month = total % 12 + 1

    c1, c2, center, c3, c4 = st.columns(
        [1, 1, 4, 1, 1]
    )

    with c1:

        if st.button(
            "«",
            help="이전 연도"
        ):
            move_month(-12)
            st.rerun()

    with c2:

        if st.button(
            "‹",
            help="이전 달"
        ):
            move_month(-1)
            st.rerun()

    with center:

        st.markdown(
            f"<h3 style='text-align:center'>"
            f"{year}년 {month}월</h3>",
            unsafe_allow_html=True
        )

    with c3:

        if st.button(
            "›",
            help="다음 달"
        ):
            move_month(1)
            st.rerun()

    with c4:

        if st.button(
            "»",
            help="다음 연도"
        ):
            move_month(12)
            st.rerun()

    tasks = load_tasks()

    # 날짜별 업무 묶기
    tasks_by_date = {}

    for task in tasks:

        deadline = task["deadline"]

        if deadline:

            tasks_by_date.setdefault(
                deadline,
                []
            ).append(task)

    cal = calendar.Calendar(
        firstweekday=6
    )

    today_text = now_kst().date().isoformat()

    rows = [
        "<table class='calendar-table'>",
        "<tr>",
        "<th class='sunday'>SUN</th>",
        "<th>MON</th>",
        "<th>TUE</th>",
        "<th>WED</th>",
        "<th>THU</th>",
        "<th>FRI</th>",
        "<th>SAT</th>",
        "</tr>"
    ]

    for week in cal.monthdatescalendar(
        year,
        month
    ):

        rows.append("<tr>")

        for index, day in enumerate(week):

            date_text = day.isoformat()

            classes = []

            if index == 0:
                classes.append("sunday")

            if day.month != month:
                classes.append("other-month")

            if date_text == today_text:
                classes.append("calendar-today")

            day_tasks = tasks_by_date.get(
                date_text,
                []
            )

            event_html = []

            # 달력 한 칸에 일정명 최대 3개 표시
            for task in day_tasks[:3]:

                name = " ".join(
                    task["task"].split()
                )

                short_name = (
                    name[:17] + "…"
                    if len(name) > 17
                    else name
                )

                escaped_name = (
                    html_escape_module.escape(
                        name,
                        quote=True
                    )
                )

                escaped_short = (
                    html_escape_module.escape(
                        short_name
                    )
                )

                done_class = (
                    " done"
                    if task.get("is_done", False)
                    else ""
                )

                event_html.append(
                    f'<span class="calendar-event{done_class}" '
                    f'title="{escaped_name}">'
                    f'{escaped_short}'
                    f'</span>'
                )

            extra_count = len(day_tasks) - 3

            if extra_count > 0:

                event_html.append(
                    f'<span class="calendar-more">'
                    f'+{extra_count}개 더 있음'
                    f'</span>'
                )

            rows.append(
                f'<td class="{" ".join(classes)}">'
                f'<span class="calendar-day">{day.day}</span>'
                + "".join(event_html)
                + "</td>"
            )

        rows.append("</tr>")

    rows.append("</table>")

    st.markdown(
        "".join(rows),
        unsafe_allow_html=True
    )

    st.caption(
        "초록색은 미완료 업무, "
        "회색 취소선은 완료된 업무를 뜻합니다."
    )

    st.divider()

    # 현재 보고 있는 달에 맞춰 날짜 선택
    default_day = min(
        now_kst().day,
        calendar.monthrange(year, month)[1]
    )

    selected_default = datetime(
        year,
        month,
        default_day
    ).date()

    chosen = st.date_input(
        "업무를 확인할 날짜",
        value=selected_default,
        key=f"calendar_day_{year}_{month}"
    )

    matching = [
        task for task in tasks
        if task["deadline"] == chosen.isoformat()
    ]

    st.subheader(
        f"{chosen:%Y년 %m월 %d일} 업무"
    )

    if not matching:

        st.info(
            "선택한 날짜에 등록된 업무가 없습니다."
        )

    for task in matching:

        with st.container(border=True):

            left, right = st.columns(
                [4, 1.5]
            )

            with left:

                if task.get("is_done", False):

                    st.markdown(
                        f"~~{task['task']}~~"
                    )

                    st.caption("완료된 업무")

                else:

                    st.markdown(
                        f"**{task['task']}**"
                    )

                    st.caption("진행 또는 예정 업무")

                if task["time"]:
                    st.caption(
                        "시간: " + task["time"]
                    )

                if task["detail"]:
                    st.write(task["detail"])

            with right:

                is_done = task.get(
                    "is_done",
                    False
                )

                label = (
                    "미완료로 되돌리기"
                    if is_done
                    else "완료 처리"
                )

                if st.button(
                    label,
                    key="task_status_" + task["id"],
                    use_container_width=True
                ):

                    set_task_done(
                        task["id"],
                        not is_done
                    )

                    st.rerun()

    # 기한을 지정하지 않은 업무도 확인 가능
    undated_tasks = [
        task for task in tasks
        if not task["deadline"]
    ]

    if undated_tasks:

        st.divider()

        with st.expander(
            f"기한 미정 업무 · {len(undated_tasks)}건",
            expanded=True
        ):

            for task in undated_tasks:

                with st.container(border=True):

                    left, right = st.columns(
                        [4, 1.5]
                    )

                    with left:

                        if task.get("is_done", False):
                            st.markdown(
                                f"~~{task['task']}~~"
                            )
                        else:
                            st.markdown(
                                f"**{task['task']}**"
                            )

                        if task["detail"]:
                            st.caption(
                                task["detail"]
                            )

                    with right:

                        is_done = task.get(
                            "is_done",
                            False
                        )

                        label = (
                            "미완료로 되돌리기"
                            if is_done
                            else "완료 처리"
                        )

                        if st.button(
                            label,
                            key="undated_" + task["id"],
                            use_container_width=True
                        ):

                            set_task_done(
                                task["id"],
                                not is_done
                            )

                            st.rerun()

    # 전체 업무 목록
    with st.expander("전체 등록 업무 보기"):

        if not tasks:
            st.caption(
                "등록된 업무가 없습니다."
            )

        for task in tasks:

            status = (
                "완료"
                if task.get("is_done", False)
                else "미완료"
            )

            st.write(
                f"• [{status}] "
                f"{task['task']} · "
                f"{task['deadline'] or '기한 미정'}"
            )

elif page == "translation":
    st.title("한영 번역")
    st.caption(
        "업무 문장 및 음성 파일을 한국어·영어로 번역합니다."
    )

    direction = st.radio(
        "번역 방향",
        ["한국어 → 영어", "영어 → 한국어"],
        horizontal=True
    )

    source = st.text_area(
        "번역할 문장",
        height=180
    )

    file = st.file_uploader(
        "번역할 음성 파일 첨부 (선택)",
        type=["mp3", "wav", "m4a", "mp4", "webm"],
        key="translation_audio_file"
    )

    if file:
        st.audio(file)

    if st.button(
        "번역하기",
        type="primary",
        icon=":material/translate:"
    ):
        try:
            transcript = (
                transcribe_audio(file)
                if file
                else ""
            )

            combined = "\n".join(
                piece
                for piece in [source.strip(), transcript.strip()]
                if piece
            )

            if not combined:
                st.warning(
                    "번역할 문장이나 음성 파일을 입력해주세요."
                )
            else:
                st.session_state.translation_transcript = transcript

                target = (
                    "영어"
                    if direction == "한국어 → 영어"
                    else "한국어"
                )

                answer = ask_llm([
                    {
                        "role": "system",
                        "content": (
                            f"입력 문장을 자연스러운 {target}로 번역하세요. "
                            "업무상 의미를 정확히 유지하고 "
                            "번역문만 출력하세요."
                        )
                    },
                    {
                        "role": "user",
                        "content": combined
                    }
                ])

                st.session_state.translation_result = answer

        except Exception as e:
            st.error(f"번역 오류: {e}")

    if st.session_state.get("translation_transcript"):
        with st.expander("음성 인식 결과"):
            st.text(
                st.session_state.translation_transcript
            )

    if st.session_state.translation_result:
        st.subheader("번역 결과")
        st.write(st.session_state.translation_result)
