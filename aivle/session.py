"""Streamlit 세션 상태를 각 브라우저에서 초기화."""
import json

import streamlit as st

from .core import load_messages, get_setting, save_setting, now_kst
from .email_drafts import parse_draft, SETTING as EMAIL_DRAFT_SETTING

def initialize_session(active_chat_id):
    previous_chat_id = st.session_state.get("_active_chat_id")
    st.session_state["_active_chat_id"] = active_chat_id
    # v5 첫 실행 때 이전 버전의 잘못 기록된 위젯 체크 상태를 한 번만 복구합니다.
    # 이후에는 사용자가 체크를 해제한 선택을 영구 보존합니다.
    widget_names = ("widget_clock", "widget_weather", "widget_briefing", "widget_calendar")
    if get_setting("widget_defaults_v5", "") != "ready":
        for widget_name in widget_names:
            save_setting(widget_name, "1")
            st.session_state[widget_name] = True
        save_setting("widget_defaults_v5", "ready")
    saved_email = parse_draft(get_setting(EMAIL_DRAFT_SETTING, "{}"))
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
        "meeting_input_generation": 0,
        "meeting_audio": None,
        "meeting_autoplay": False,
        "meeting_txt_hash": "",
        "meeting_txt_review": "",
        "meeting_audio_hash": "",
        "meeting_audio_review": "",
        "meeting_recording_hash": "",
        "meeting_recording_review": "",
        **saved_email,
        "email_error": "",
        "email_review_items": [],
        "email_last_sent": "",
        "translation_result": "",
        "calendar_year": now_kst().year,
        "calendar_month": now_kst().month,
        "widget_clock": get_setting("widget_clock", "1") == "1",
        "widget_weather": get_setting("widget_weather", "1") == "1",
        "widget_briefing": get_setting("widget_briefing", "1") == "1",
        "weather_city": get_setting("weather_city", "서울"),
        "widget_calendar": get_setting("widget_calendar", "1") == "1",
        "web_enabled": False,
        "chat_upload_seq": 0,
        "last_voice_hash": "",
        "meeting_followup": []
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if previous_chat_id != active_chat_id:
        st.session_state["_active_chat_id"] = active_chat_id
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
