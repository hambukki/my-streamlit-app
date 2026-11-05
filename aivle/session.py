"""Streamlit 세션 상태를 각 브라우저에서 초기화."""
import json

import streamlit as st

from .core import load_messages, get_setting, save_setting, now_kst
from .email_drafts import parse_draft, SETTING as EMAIL_DRAFT_SETTING
from .home_preferences import restore_preferences

def initialize_session(active_chat_id):
    previous_chat_id = st.session_state.get("_active_chat_id")
    st.session_state["_active_chat_id"] = active_chat_id
    # 별도 설정에 저장하여 Streamlit 위젯 키가 페이지 이동 중 삭제되어도 복구합니다.
    # 기존 버전의 잘못된 '모두 숨김' 설정은 v9 첫 실행 때 한 번만 복구합니다.
    home_widgets = restore_preferences(st.session_state, get_setting, save_setting)
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
        "widget_clock": home_widgets["widget_clock"],
        "widget_weather": home_widgets["widget_weather"],
        "widget_briefing": home_widgets["widget_briefing"],
        "weather_city": get_setting("weather_city", "서울"),
        "widget_calendar": home_widgets["widget_calendar"],
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
