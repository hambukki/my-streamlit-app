"""AI 채팅, 대화 라이브러리, 파일·음성, 일정 제안."""
from datetime import datetime

import streamlit as st
from aivle.core import (search_conversations, switch_conversation,
                        start_new_conversation, save_setting, add_task, load_tasks,
                        get_active_chat_id)
from aivle.widgets import (conversation_rename_dialog, conversation_delete_dialog, task_editor,
                           render_task_actions, URGENCY_LABELS)
from aivle.ai import (send_text_chat, send_voice_chat,
                      improve_prompt, restore_prompt)


def render():
    st.title("AI 채팅")
    st.caption("질문하고, 음성으로 대화하고, 일정을 등록하세요.")

    menu_left, menu_right = st.columns([2, 1])
    with menu_left:
        with st.popover("대화 라이브러리 · 저장된 대화 검색", icon=":material/history:",
                        use_container_width=True):
            search_word = st.text_input("제목 또는 대화 키워드 검색", key="conversation_search")
            results = search_conversations(search_word)
            st.caption(f"검색 결과 {len(results)}개 · 대화 선택/이름 변경/삭제")
            with st.container(height=360, border=False):
                if not results:
                    st.info("일치하는 대화가 없습니다.")
                for conversation_id, title in results:
                    row, edit, delete = st.columns([5, 1, 1], gap="small")
                    with row:
                        if st.button(
                            title,
                            key=f"chat_library_{conversation_id}",
                            type="primary" if conversation_id == get_active_chat_id() else "secondary",
                            use_container_width=True
                        ):
                            switch_conversation(conversation_id)
                    with edit:
                        if st.button("✎", key=f"chat_title_edit_{conversation_id}",
                                     help="대화 제목 편집"):
                            conversation_rename_dialog(conversation_id, title)
                    with delete:
                        if st.button("🗑", key=f"chat_title_delete_{conversation_id}",
                                     help="저장된 대화 삭제"):
                            conversation_delete_dialog(conversation_id, title)
    with menu_right:
        if st.button("새로운 대화", key="chat_new_single", icon=":material/add_comment:",
                     type="primary", use_container_width=True):
            start_new_conversation()


    if not st.session_state.messages:
        st.markdown('<div class="chat-empty-state">✦ <strong>새로운 대화를 시작해보세요.</strong>'
                    '<span>에이블이 업무와 일정을 도와드릴게요.</span></div>',
                    unsafe_allow_html=True)

    for index, message in enumerate(st.session_state.messages):
        role = message["role"] if message["role"] in ("user", "assistant") else "assistant"
        avatar = ":material/badge:" if role == "user" else ":material/assistant:"
        with st.container(key=f"chat_line_{role}_{index}"):
            with st.chat_message(role, avatar=avatar):
                st.markdown(message["content"])

    # 음성 답변은 채팅 메시지 바로 아래에만 표시합니다.
    if st.session_state.reply_audio:
        st.caption("에이블의 음성 답변")
        st.audio(
            bytes(st.session_state.reply_audio),
            format="audio/mpeg",
            autoplay=st.session_state.autoplay_reply
        )
        st.download_button("음성 답변 MP3 다운로드", data=st.session_state.reply_audio,
                           file_name="aivle_reply.mp3", mime="audio/mpeg",
                           key="download_chat_tts")
        st.session_state.autoplay_reply = False

    st.divider()

    with st.expander("파일 첨부 (CSV · TXT · Word · PowerPoint · PDF · Excel)"):
        st.file_uploader(
            "업무에 참고할 문서 첨부",
            type=["csv", "txt", "md", "doc", "docx", "ppt", "pptx", "pdf", "xlsx"],
            accept_multiple_files=True,
            key=f"chat_files_{st.session_state.chat_upload_seq}",
            help="파일당 8MB, 추출 텍스트 25,000자까지. 구형 DOC/PPT는 첨부 후 변환 안내를 표시합니다."
        )

    st.text_area(
        "메시지 작성",
        key="chat_draft",
        height=125,
        placeholder="에이블에게 요청할 업무를 입력하세요."
    )

    a, b, microphone, c, d = st.columns([1, 1, 1, 1.5, 1.5])

    with a:
        st.button(
            "✨",
            help="프롬프트 개선",
            on_click=improve_prompt,
            use_container_width=True
        )

    with b:
        st.button(
            "➤",
            help="질문 보내기",
            on_click=send_text_chat,
            type="primary",
            use_container_width=True
        )

    with microphone:
        with st.popover("🎙️", use_container_width=True):
            st.caption("마이크 녹음을 마치면 인식된 질문이 자동 전송됩니다.")
            st.audio_input(
                "음성으로 질문하기", key="chat_voice",
                sample_rate=16000, on_change=send_voice_chat
            )
            if st.session_state.voice_transcript:
                st.caption("최근 인식된 질문: " + st.session_state.voice_transcript)

    with c:
        st.checkbox(
            "음성 답변",
            key="voice_reply"
        )

    with d:
        st.checkbox(
            "웹검색",
            key="web_enabled",
            help="켜면 최신 정보 요청에서 실제 웹검색을 수행하고 출처를 표시합니다. 검색 API 비용이 추가됩니다. 끄면 실시간 사실을 확인할 수 없습니다."
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

    if st.session_state.chat_error:
        st.warning(st.session_state.chat_error)

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
                    "날짜 (YYYY-MM-DD, 공란이면 기한 미정)",
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
                urgency = st.selectbox(
                    "업무 강조 색상", list(URGENCY_LABELS),
                    format_func=lambda item: URGENCY_LABELS[item]
                )

                confirm = st.form_submit_button(
                    "일정에 추가",
                    type="primary"
                )

            if confirm:
                try:
                    if date:
                        datetime.strptime(date, "%Y-%m-%d")

                    if time_value:
                        datetime.strptime(time_value, "%H:%M")

                    add_task(
                        title,
                        date,
                        time_value,
                        detail,
                        urgency
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

    with st.expander("내 업무 목록 · 빠른 추가 / 편집 / 삭제", expanded=False):
        if st.button("+ 업무 추가", key="chat_task_add"):
            task_editor()
        for item in load_tasks()[:30]:
            st.caption(f"{'✓ ' if item['is_done'] else ''}{item['task']} · {item['deadline'] or '기한 미정'}")
            render_task_actions(item, "chat_task")
