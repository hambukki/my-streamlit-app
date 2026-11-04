"""김대리 개인비서 공통 상태, 사용자별 업무·대화·주소록 DB."""
import json
import re
import secrets
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

DB_PATH = (Path("/content/drive/MyDrive/project03") / "aivle_assistant.db"
           if Path("/content/drive/MyDrive/project03").is_dir()
           else Path("aivle_assistant.db"))

def get_sid():
    """세션별 URL 식별자를 반환하며 모듈 전역에 캐시하지 않습니다."""
    sid = st.query_params.get("sid", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,80}", sid):
        sid = secrets.token_urlsafe(24)
        st.query_params["sid"] = sid
    return sid

def get_active_chat_id():
    return st.session_state.get("_active_chat_id", "")


def now_kst():
    return datetime.now(ZoneInfo("Asia/Seoul"))


def connect_db():
    # 동시 접속자가 있는 Streamlit Cloud에서 일시적인 DB 잠금에 대비합니다.
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


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

        CREATE TABLE IF NOT EXISTS chat_attachments (
            id TEXT PRIMARY KEY,
            sid TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            extracted_text TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS task_presets (
            id TEXT PRIMARY KEY,
            sid TEXT NOT NULL,
            title TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            urgency TEXT NOT NULL DEFAULT 'normal'
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


def get_setting(name, default=""):
    with connect_db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE sid=? AND name=?",
            (get_sid(), name)
        ).fetchone()
    return row[0] if row else default


def save_setting(name, value):
    with connect_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO settings
               (sid, name, value) VALUES (?, ?, ?)""",
            (get_sid(), name, str(value))
        )


def load_conversations():
    with connect_db() as conn:
        return conn.execute(
            "SELECT id, title FROM conversations WHERE sid=? "
            "ORDER BY updated_at DESC LIMIT 100",
            (get_sid(),)
        ).fetchall()


def search_conversations(keyword=""):
    keyword = (keyword or "").strip()
    if not keyword:
        return load_conversations()
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    with connect_db() as conn:
        return conn.execute(
            """SELECT c.id, c.title FROM conversations c
               WHERE c.sid=? AND (
                  c.title LIKE ? ESCAPE '\\' OR EXISTS (
                    SELECT 1 FROM messages m
                    WHERE m.conversation_id=c.id AND m.sid=c.sid
                      AND m.content LIKE ? ESCAPE '\\'
                  )
               ) ORDER BY c.updated_at DESC LIMIT 100""",
            (get_sid(), pattern, pattern)
        ).fetchall()


def rename_conversation(conversation_id, title):
    title = title.strip()[:70]
    if not title:
        raise ValueError("대화 제목을 입력해주세요.")
    with connect_db() as conn:
        conn.execute(
            "UPDATE conversations SET title=? WHERE sid=? AND id=?",
            (title, get_sid(), conversation_id)
        )


def create_conversation():
    conversation_id = str(uuid.uuid4())

    with connect_db() as conn:
        conn.execute(
            "INSERT INTO conversations "
            "(id, sid, title, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (
                conversation_id,
                get_sid(),
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
                (candidate, get_sid())
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


def switch_conversation(conversation_id):
    with connect_db() as conn:
        owned = conn.execute(
            "SELECT 1 FROM conversations "
            "WHERE id=? AND sid=?",
            (conversation_id, get_sid())
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
            (get_sid(), get_active_chat_id())
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
                    get_active_chat_id(),
                    get_sid()
                )
            )


def load_messages():
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages "
            "WHERE sid=? AND conversation_id=? "
            "ORDER BY id DESC LIMIT 20",
            (get_sid(), get_active_chat_id())
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
            (get_sid(), get_active_chat_id(), role, content)
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
                get_sid(),
                get_active_chat_id(),
                get_sid(),
                get_active_chat_id()
            )
        )

        conn.execute(
            "UPDATE conversations SET updated_at=? "
            "WHERE id=? AND sid=?",
            (
                now_kst().isoformat(),
                get_active_chat_id(),
                get_sid()
            )
        )


def clear_messages():
    with connect_db() as conn:
        conn.execute(
            "DELETE FROM messages "
            "WHERE sid=? AND conversation_id=?",
            (get_sid(), get_active_chat_id())
        )


def save_chat_attachment(filename, extracted_text):
    with connect_db() as conn:
        conn.execute(
            """INSERT INTO chat_attachments
            (id, sid, conversation_id, filename, extracted_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), get_sid(), get_active_chat_id(), filename,
             extracted_text[:25000], now_kst().isoformat())
        )


def recent_chat_attachments():
    with connect_db() as conn:
        rows = conn.execute(
            """SELECT filename, extracted_text FROM chat_attachments
               WHERE sid=? AND conversation_id=?
               ORDER BY created_at DESC LIMIT 3""",
            (get_sid(), get_active_chat_id())
        ).fetchall()
    return "\n\n".join(f"[첨부: {name}]\n{content[:18000]}"
                        for name, content in rows)


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
                COALESCE(is_done, 0),
                urgency
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
            (get_sid(),)
        ).fetchall()

    return [
        {
            "id": row[0],
            "task": row[1],
            "deadline": row[2] or "",
            "time": row[3] or "",
            "detail": row[4] or "",
            "is_done": bool(row[5]),
            "urgency": row[6] or "normal"
        }
        for row in rows
    ]


VALID_URGENCY = {"urgent", "high", "normal", "low"}


def validate_urgency(urgency):
    if urgency not in VALID_URGENCY:
        raise ValueError("업무 강조 색상을 다시 선택해주세요.")


def add_task(title, due_date="", due_time="", detail="", urgency="normal"):
    validate_task_fields(title, due_date, due_time)
    validate_urgency(urgency)
    task_id = str(uuid.uuid4())

    with connect_db() as conn:
        conn.execute(
            """INSERT INTO tasks
               (id, sid, title, due_date, due_time, detail, urgency)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (task_id, get_sid(), title, due_date, due_time, detail, urgency)
        )

    return task_id


def validate_task_fields(title, due_date="", due_time=""):
    if not str(title).strip():
        raise ValueError("업무명을 입력해주세요.")
    if due_date:
        datetime.strptime(str(due_date), "%Y-%m-%d")
    if due_time:
        datetime.strptime(str(due_time), "%H:%M")


def update_task(task_id, title, due_date="", due_time="", detail="", urgency="normal"):
    validate_task_fields(title, due_date, due_time)
    validate_urgency(urgency)
    with connect_db() as conn:
        cursor = conn.execute(
            """UPDATE tasks SET title=?, due_date=?, due_time=?, detail=?, urgency=?
               WHERE id=? AND sid=?""",
            (title.strip(), due_date, due_time, detail, urgency, task_id, get_sid())
        )
        return cursor.rowcount == 1


def delete_task(task_id):
    with connect_db() as conn:
        cursor = conn.execute(
            "DELETE FROM tasks WHERE id=? AND sid=?", (task_id, get_sid())
        )
        return cursor.rowcount == 1


def get_task(task_id):
    return next((item for item in load_tasks() if item["id"] == task_id), None)


def add_task_if_missing(title, due_date="", due_time="", detail="", urgency="normal"):
    """회의록이나 채팅을 반복 실행해도 동일 업무가 복제되지 않도록 합니다."""
    if any(t["task"] == title.strip() and t["deadline"] == due_date
           for t in load_tasks()):
        return False
    add_task(title, due_date, due_time, detail, urgency)
    return True


def load_contacts():
    with connect_db() as conn:
        return conn.execute(
            """SELECT name, email FROM contacts
               WHERE sid=? ORDER BY name""",
            (get_sid(),)
        ).fetchall()


def save_contact(name, email):
    with connect_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO contacts
               (sid, name, email) VALUES (?, ?, ?)""",
            (get_sid(), name, email)
        )


def delete_contact(email):
    with connect_db() as conn:
        conn.execute(
            "DELETE FROM contacts WHERE sid=? AND email=?",
            (get_sid(), email)
        )


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
        if "urgency" not in columns:
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN urgency TEXT NOT NULL DEFAULT 'normal'"
            )


def load_task_presets():
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT id, title, detail, urgency FROM task_presets "
            "WHERE sid=? ORDER BY title", (get_sid(),)
        ).fetchall()
    return [{"id": row[0], "title": row[1], "detail": row[2],
             "urgency": row[3]} for row in rows]


def add_task_preset(title, detail="", urgency="normal"):
    validate_task_fields(title)
    validate_urgency(urgency)
    with connect_db() as conn:
        conn.execute(
            "INSERT INTO task_presets (id, sid, title, detail, urgency) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), get_sid(), title.strip(), detail.strip(), urgency)
        )


def delete_task_preset(preset_id):
    with connect_db() as conn:
        conn.execute("DELETE FROM task_presets WHERE id=? AND sid=?", (preset_id, get_sid()))


def create_task_from_preset(preset_id, due_date):
    preset = next((row for row in load_task_presets() if row["id"] == preset_id), None)
    if not preset:
        raise ValueError("선택한 프리셋을 찾지 못했습니다.")
    if any(row["task"] == preset["title"] and row["deadline"] == due_date
           for row in load_tasks()):
        return False
    add_task(preset["title"], due_date, "", preset["detail"], preset["urgency"])
    return True


def set_task_done(task_id, done):
    """선택한 업무의 완료 여부를 변경합니다."""

    with connect_db() as conn:
        conn.execute(
            "UPDATE tasks SET is_done=? "
            "WHERE id=? AND sid=?",
            (1 if done else 0, task_id, get_sid())
        )
