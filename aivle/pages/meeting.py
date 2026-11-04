"""회의록 입력·요약·메일 공유·후속 질문."""
import json
from datetime import datetime

import streamlit as st
from aivle.core import (get_setting, save_setting, add_task_if_missing, load_tasks)
from aivle.ai import SYS_ROLE, MEETING_SCHEMA, ask_llm, transcribe_audio, make_speech
from aivle.documents import decode_text_file
from aivle.email import send_gmail
from aivle.widgets import render_task_actions


def render():
    st.title("회의록 요약")
    st.caption("회의 내용을 분석하고 담당 업무를 확인하세요.")

    notes = st.text_area(
        "회의 내용",
        height=180,
        placeholder="회의 내용을 입력하거나 음성 파일을 첨부하세요."
    )

    notes_file = st.file_uploader(
        "회의록 TXT 파일 첨부 (선택)",
        type=["txt", "md"],
        key="meeting_text_upload",
        help="TXT 파일은 UTF-8 또는 CP949로 저장하세요. 업로드 오류 시 위 입력창에 내용을 붙여 넣을 수 있습니다."
    )

    txt_notes = ""

    if notes_file is not None:
        try:
            if notes_file.size > 2 * 1024 * 1024:
                raise ValueError("회의록 TXT는 2MB 이하로 첨부해주세요.")
            txt_notes = decode_text_file(notes_file.getvalue())
        except (ValueError, OSError) as exc:
            st.error(f"TXT 파일 읽기 오류: {exc}")

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
                st.session_state.meeting_followup = []

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

                        if add_task_if_missing(name, date, "", detail):
                            added += 1
                    except ValueError:
                        st.error(
                            f"'{name}'의 날짜 형식을 확인해주세요."
                        )

                st.success(f"{added}개 업무를 추가했습니다.")

        # 회의 내용을 검토한 뒤 앱 내에서 바로 이메일을 보낼 수 있습니다.
        if reviewed:
            with st.expander("검토 완료 · 회의록 이메일 전송", expanded=False):
                st.caption("검토한 요약과 김대리 담당 업무를 이메일로 공유합니다.")
                with st.form("meeting_send_form"):
                    recipient = st.text_input("받는 사람 이메일 *", key="meeting_share_to")
                    cc = st.text_input("참조 (선택)", key="meeting_share_cc")
                    subject = st.text_input("메일 제목", value="[회의록] 주요 내용 및 후속 업무")
                    email_body = st.text_area(
                        "전송할 회의록 본문",
                        value=(summary + "\n\n[결정사항]\n" +
                               "\n".join(f"- {x}" for x in result["decisions"]) +
                               "\n\n[김대리 담당 업무]\n" +
                               "\n".join(f"- {t['task']} ({t['deadline'] or '기한 미정'})"
                                         for t in result["kim_tasks"])),
                        height=200
                    )
                    send_mail = st.form_submit_button("검토한 회의록 이메일 전송", type="primary")
                if send_mail:
                    try:
                        send_gmail(recipient.strip(), cc.strip(), subject.strip(), email_body)
                        st.success("회의록 이메일을 전송했습니다.")
                    except Exception as exc:
                        st.error(f"이메일 전송 실패: {exc}")

        st.subheader("회의록에 관해 추가 질문하기")
        st.caption("현재 요약된 회의의 사실관계만 바탕으로 후속 질문에 답합니다.")
        for item in st.session_state.meeting_followup:
            with st.chat_message(item["role"]):
                st.write(item["content"])
        with st.form("meeting_followup_form", clear_on_submit=True):
            question = st.text_input("회의록 질문", placeholder="예: 누가 강사 섭외를 맡았나요?")
            ask = st.form_submit_button("질문하기")
        if ask and question.strip():
            try:
                answer = ask_llm([
                    {"role": "system", "content": (
                        SYS_ROLE + "\n아래 회의록 JSON만을 근거로 답하세요. "
                        "기록에 없는 정보는 확인되지 않았다고 답하세요.\n" +
                        json.dumps(result, ensure_ascii=False))},
                    *st.session_state.meeting_followup[-8:],
                    {"role": "user", "content": question}
                ])
                st.session_state.meeting_followup.extend([
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer}
                ])
                st.rerun()
            except Exception as exc:
                st.error(f"후속 질문 오류: {exc}")

        with st.expander("내 일정에 등록된 업무 확인 · 편집 / 삭제", expanded=False):
            for item in load_tasks()[:30]:
                st.caption(f"{item['task']} · {item['deadline'] or '기한 미정'}")
                render_task_actions(item, "meeting_task")

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
