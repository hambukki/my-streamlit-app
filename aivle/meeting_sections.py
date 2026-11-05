"""회의록 결과 영역: 요약·후속 대화 / 담당 업무 탭별 UI."""
import json
from datetime import datetime

import streamlit as st

from .ai import SYS_ROLE, ask_llm, make_full_speech
from .core import add_task_if_missing, load_tasks, now_kst
from .email import send_gmail
from .widgets import URGENCY_LABELS, render_task_actions


def render_summary(result, version):
    """회의 요약 바로 아래에 후속 질의, 이어서 음성 생성 기능을 출력합니다."""
    with st.container(border=True):
        st.subheader("회의 요약")
        summary = st.text_area("요약 내용 확인", value=result["summary"], height=210,
                               key=f"meeting_summary_{version}")
        if result["decisions"]:
            st.markdown("**주요 결정사항**")
            for decision in result["decisions"]:
                st.write("• " + decision)
        for question in result["questions"]:
            st.warning(question)

    with st.container(border=True):
        st.subheader("회의록에 관해 추가 질문하기")
        st.caption("위 회의 요약을 바탕으로 후속 질문을 할 수 있습니다. 확인되지 않은 사실은 추측하지 않습니다.")
        for item in st.session_state.meeting_followup:
            with st.chat_message(item["role"]):
                st.write(item["content"])
        with st.form("meeting_followup_form", clear_on_submit=True):
            question = st.text_input("회의록 질문", placeholder="예: 누가 강사 섭외를 맡았나요?")
            ask = st.form_submit_button("질문하기")
        if ask and question.strip():
            try:
                with st.spinner("회의록 내용을 확인하고 답변을 준비하고 있습니다..."):
                    answer = ask_llm([
                        {"role": "system", "content": (
                            SYS_ROLE + "\n아래 회의록 JSON만을 근거로 답하세요. "
                            "기록에 없는 정보는 확인되지 않았다고 답하세요.\n"
                            + json.dumps(result, ensure_ascii=False))},
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

    with st.container(border=True):
        st.markdown("**요약 음성 듣기**")
        if st.button("요약 음성 생성", key="meeting_make_tts", icon=":material/volume_up:"):
            try:
                with st.spinner("회의 요약의 모든 문장을 음성으로 변환하는 중입니다..."):
                    st.session_state.meeting_audio = make_full_speech(summary)
                st.session_state.meeting_autoplay = True
            except Exception as exc:
                st.session_state.meeting_audio = None
                st.error(f"음성 생성 API 처리 실패: {exc}")
        if st.session_state.meeting_audio:
            st.audio(bytes(st.session_state.meeting_audio), format="audio/wav",
                     autoplay=st.session_state.meeting_autoplay)
            st.session_state.meeting_autoplay = False
            st.download_button("요약 전체 음성 WAV 다운로드",
                               data=st.session_state.meeting_audio,
                               file_name="meeting_summary.wav", mime="audio/wav",
                               key="meeting_tts_download")
        else:
            st.caption("긴 요약도 문장을 자르지 않고 분할 생성한 뒤 WAV 파일 하나로 연결합니다.")
    return summary


def render_tasks(result, version, summary):
    """담당 업무를 접이식 카드로 검토하고 선택 등록·이메일 전송합니다."""
    st.subheader(f"김대리 담당 업무 · {len(result['kim_tasks'])}건")
    st.caption("업무별 카드를 펼쳐 기한과 색상을 검토한 뒤 등록할 수 있습니다.")
    selected_tasks = []

    if not result["kim_tasks"]:
        st.info("김대리에게 명시적으로 배정된 업무는 없습니다.")

    for i, task in enumerate(result["kim_tasks"]):
        with st.expander(f"업무 {i+1} · {task['task']}", expanded=(i == 0)):
            selected = st.checkbox("이 업무를 일정에 추가", value=True,
                                   key=f"meeting_select_{version}_{i}")
            name = st.text_input("업무명", value=task["task"],
                                 key=f"meeting_name_{version}_{i}")

            kind = task.get("deadline_kind", "unverified" if task.get("deadline") else "none")
            phrase = task.get("deadline_phrase", "")
            if kind in ("relative", "unverified"):
                st.warning(f"원문 기한: {phrase or '확인 불가'} · 정확한 날짜를 직접 선택해주세요.")
                confirmed = st.checkbox("정확한 마감일을 직접 선택했습니다", value=False,
                                        key=f"meeting_date_confirm_{version}_{i}")
                chosen = st.date_input("마감일 직접 선택", value=now_kst().date(),
                                       disabled=not confirmed,
                                       key=f"meeting_pick_date_{version}_{i}")
                deadline = chosen.isoformat() if confirmed else ""
            else:
                confirmed = True
                deadline = st.text_input("기한 (YYYY-MM-DD, 공란은 기한 미정)",
                                         value=task["deadline"],
                                         key=f"meeting_date_{version}_{i}")

            detail = st.text_area("업무 설명", value=task["detail"],
                                  key=f"meeting_detail_{version}_{i}")
            urgency = st.selectbox("업무 중요도·표시 색상", list(URGENCY_LABELS),
                                   format_func=lambda value: URGENCY_LABELS[value],
                                   key=f"meeting_urgency_{version}_{i}")
            selected_tasks.append((selected, name, deadline, detail, kind, confirmed, urgency))

    with st.container(border=True):
        st.markdown("**일정에 추가하시겠습니까?**")
        reviewed = st.checkbox("회의 내용과 업무를 검토했습니다.")
        if st.button("선택한 업무를 내 일정에 추가", type="primary"):
            if not reviewed:
                st.warning("검토 여부를 확인해주세요.")
            else:
                added = 0
                missing_date = []
                for selected, name, deadline, detail, kind, confirmed, urgency in selected_tasks:
                    if not selected or not name.strip():
                        continue
                    if kind == "relative" and not confirmed:
                        missing_date.append(name)
                        continue
                    try:
                        if deadline:
                            datetime.strptime(deadline, "%Y-%m-%d")
                        if add_task_if_missing(name, deadline, "", detail, urgency):
                            added += 1
                    except ValueError:
                        st.error(f"'{name}'의 날짜 형식을 확인해주세요.")
                if missing_date:
                    st.warning("정확한 마감일이 필요한 업무: " + ", ".join(missing_date))
                st.success(f"{added}개 업무를 추가했습니다.")

        if reviewed:
            with st.expander("검토 완료 · 회의록 이메일 전송", expanded=False):
                with st.form("meeting_send_form"):
                    recipient = st.text_input("받는 사람 이메일 *", key="meeting_share_to")
                    cc = st.text_input("참조 (선택)", key="meeting_share_cc")
                    subject = st.text_input("메일 제목", value="[회의록] 주요 내용 및 후속 업무")
                    body = st.text_area(
                        "전송할 회의록 본문",
                        value=(summary + "\n\n[결정사항]\n" +
                               "\n".join(f"- {x}" for x in result["decisions"]) +
                               "\n\n[김대리 담당 업무]\n" +
                               "\n".join(f"- {t['task']} ({t['deadline'] or '기한 미정'})"
                                         for t in result["kim_tasks"])),
                        height=200
                    )
                    send = st.form_submit_button("검토한 회의록 이메일 전송", type="primary")
                if send:
                    try:
                        with st.spinner("회의록 이메일을 전송하고 있습니다..."):
                            send_gmail(recipient.strip(), cc.strip(), subject.strip(), body)
                        st.success("회의록 이메일을 전송했습니다.")
                    except Exception as exc:
                        st.error(f"이메일 전송 실패: {exc}")

    with st.expander("등록된 업무 확인 · 편집 / 삭제", expanded=False):
        for item in load_tasks()[:30]:
            st.caption(f"{item['task']} · {item['deadline'] or '기한 미정'}")
            render_task_actions(item, "meeting_task")
