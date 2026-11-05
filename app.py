"""AIVLE 김대리 개인비서 진입점: 설정, 초기화, 좌측 메뉴와 페이지 라우팅."""
import os
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="AIVLE | Personal Assistant", page_icon="✦",
                   layout="wide", initial_sidebar_state="expanded")

# 공개 Streamlit 앱에도 GitHub 소스나 브라우저 화면에 비밀키를 포함하지 않습니다.
for secret_name in ("OPENAI_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"):
    if not os.getenv(secret_name):
        try:
            value = st.secrets.get(secret_name)
            if value:
                os.environ[secret_name] = str(value)
        except Exception:
            pass

if not os.getenv("OPENAI_API_KEY"):
    st.error("OPENAI_API_KEY가 없습니다. 인증 정보 설정을 확인해주세요.")
    st.stop()

from aivle.core import (get_sid, init_db, init_scheduled_email_table,
                        migrate_task_status, choose_conversation)
from aivle.session import initialize_session
from aivle.email import start_scheduled_email_worker
from aivle.sidebar import render_sidebar_upcoming
from aivle.pages import home, chat, meeting, email, calendar, translation

get_sid()
init_db()
init_scheduled_email_table()
migrate_task_status()
initialize_session(choose_conversation())
start_scheduled_email_worker()

style_path = Path(__file__).resolve().parent / "assets" / "style.css"
st.markdown("<style>" + style_path.read_text(encoding="utf-8") + "</style>",
            unsafe_allow_html=True)

PAGES = {
    "home": ("홈", "home", home.render),
    "chat": ("AI 채팅", "forum", chat.render),
    "meeting": ("회의록 요약", "description", meeting.render),
    "email": ("이메일", "mail", email.render),
    "calendar": ("내 일정", "calendar_month", calendar.render),
    "translation": ("한영 번역", "translate", translation.render),
}
page = st.query_params.get("view", "home")
if page not in PAGES:
    page = "home"

with st.sidebar:
    st.markdown('<h1 style="color:#075C50;font-size:29px;font-weight:800;'
                'margin-bottom:0;">✦ AIVLE</h1>', unsafe_allow_html=True)
    st.markdown('<p style="color:#087568;font-size:11px;letter-spacing:2px;">'
                'PERSONAL AI ASSISTANT</p>', unsafe_allow_html=True)
    st.divider()
    for page_id, (label, icon, renderer) in PAGES.items():
        if st.button(label, key=f"nav_{page_id}", icon=f":material/{icon}:",
                     type="primary" if page == page_id else "secondary",
                     use_container_width=True):
            st.query_params["view"] = page_id
            st.rerun()
    st.divider()
    render_sidebar_upcoming()

PAGES[page][2]()
