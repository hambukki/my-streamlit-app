"""회의록 입력·요약·메일 공유·후속 질문."""
import hashlib
import json
from datetime import datetime

import streamlit as st
from aivle.core import (get_setting, save_setting, add_task_if_missing, load_tasks, now_kst)
from aivle.ai import SYS_ROLE, MEETING_SCHEMA, ask_llm, transcribe_audio, make_full_speech
from aivle.documents import decode_text_file
from aivle.email import send_gmail
from aivle.meeting_logic import verify_meeting_tasks, combine_meeting_sources
from aivle.widgets import render_task_actions, URGENCY_LABELS


def _audio_mime(name):
    suffix = name.rsplit(".", 1)[-1].lower()
    return {"mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4",
            "mp4": "audio/mp4", "webm": "audio/webm"}.get(suffix, "audio/mpeg")


def _prepare_uploaded_text(uploaded, state_key, hash_key, decode=False):
    """파일이 교체됐을 때만 검토할 텍스트를 초기화합니다."""
    if uploaded is None:
        st.session_state[state_key] = ""
        st.session_state[hash_key] = ""
        return
    data = uploaded.getvalue()
    fingerprint = hashlib.sha256(data).hexdigest()
    if st.session_state.get(hash_key) == fingerprint:
        return
    st.session_state[hash_key] = fingerprint
    st.session_state[state_key] = ""
    if decode:
        try:
            if len(data) > 2 * 1024 * 1024:
                raise ValueError("TXT 파일은 2MB 이하로 첨부해주세요.")
            st.session_state[state_key] = decode_text_file(data)
        except (UnicodeError, ValueError, OSError) as exc:
            st.error(f"파일 읽기 오류: {exc}")


def _transcribe_file(uploaded, state_key, button_key):
    """업로드된 오디오를 재생하고 전체 전사 텍스트를 검토할 수 있게 합니다."""
    if uploaded is None:
        st.info("회의 음성을 첨부하거나 녹음해주세요.")
        return
    data = uploaded.getvalue()
    mime = _audio_mime(uploaded.name)
    st.audio(data, format=mime)
    st.caption("음성 파일 전체를 문자로 변환합니다. 25MB를 초과하면 안내를 표시합니다.")
    if st.button("음성 전체 텍스트 변환", key=button_key, icon=":material/transcribe:"):
        try:
            with st.spinner("전체 음성을 문자로 변환하고 있습니다..."):
                st.session_state[state_key] = transcribe_audio(uploaded)
            st.success("음성 인식이 완료됐습니다. 아래 전사 결과를 검토하고 수정할 수 있습니다.")
        except Exception as exc:
            st.error(f"음성 인식 실패: {exc}")
    st.download_button("원본 음성 다운로드", data=data, mime=mime,
                       file_name=uploaded.name, key=f"{button_key}_download")


def render():
    st.title("회의록 정리")
    st.caption("회의 내용 확인 → 요약과 음성 듣기 → 김대리 담당 업무 검토")

    with st.container(border=True):
        st.subheader("① 회의 자료 입력")
        st.caption("메모·TXT·음성 파일·마이크 녹음을 동시에 사용할 수 있습니다. 입력한 자료를 한데 모아 분석합니다.")
        tab_memo, tab_txt, tab_audio, tab_record = st.tabs(
            ["✍️ 회의메모", "📄 회의록 TXT", "🎧 회의 음성 파일", "🎙️ 회의 내용 녹음"]
        )

        with tab_memo:
            notes = st.text_area("회의메모", height=180, key="meeting_manual_notes",
                                 placeholder="회의 중 직접 적은 메모나 회의 내용을 입력하세요.")
        with tab_txt:
            txt_file = st.file_uploader("회의록 TXT 첨부", type=["txt", "md"],
                                        key="meeting_text_upload")
            _prepare_uploaded_text(txt_file, "meeting_txt_review", "meeting_txt_hash", decode=True)
            if txt_file is not None:
                st.text_area("TXT 전체 내용 검토 · 편집", key="meeting_txt_review", height=200)
        with tab_audio:
            audio_file = st.file_uploader("회의 음성 파일 첨부", type=["mp3", "wav", "m4a", "mp4", "webm"],
                                          key="meeting_audio_upload")
            _prepare_uploaded_text(audio_file, "meeting_audio_review", "meeting_audio_hash")
            _transcribe_file(audio_file, "meeting_audio_review", "meeting_audio_transcribe")
            if audio_file is not None:
                st.text_area("음성 파일 전체 전사 검토 · 편집", key="meeting_audio_review", height=200)
        with tab_record:
            recording = st.audio_input("회의 내용 녹음", key="meeting_recording")
            _prepare_uploaded_text(recording, "meeting_recording_review", "meeting_recording_hash")
            _transcribe_file(recording, "meeting_recording_review", "meeting_recording_transcribe")
            if recording is not None:
                st.text_area("녹음 전체 전사 검토 · 편집", key="meeting_recording_review", height=200)

    sources = {
        name: value.strip()
        for name, value in [
            ("회의메모", notes),
            ("회의록 TXT", st.session_state.get("meeting_txt_review", "")),
            ("회의 음성 파일", st.session_state.get("meeting_audio_review", "")),
            ("회의 내용 녹음", st.session_state.get("meeting_recording_review", "")),
        ] if value and value.strip()
    }
    if sources:
        st.subheader("② 분석할 자료 확인")
        source_key = hashlib.sha256("|".join(sources).encode("utf-8")).hexdigest()[:12]
        selected = st.multiselect("요약에 포함할 자료 (기본값: 모두 포함)",
                                  options=list(sources), default=list(sources),
                                  key=f"meeting_sources_{source_key}")
        st.caption(f"분석 대상 {len(selected)}개 · 선택한 자료의 모든 문장을 통합하여 요약합니다. "
                   "서로 중복되는 내용은 하나의 회의 사실로 취급합니다.")
    else:
        selected = []
        st.info("회의메모를 입력하거나 회의록 TXT를 첨부하거나 음성을 변환해주세요.")

    selected_text = combine_meeting_sources(sources, selected)
    if st.button("회의록 정리 실행", type="primary", disabled=not bool(selected_text)):
        try:
            source = selected_text

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
                                + "제공된 모든 회의 자료를 빠짐없이 통합해 상세히 요약하세요. "
                                + "배경·논의 경과·결정사항·확인 과제·김대리 담당 업무를 충분한 분량으로 구분하세요. "
                                + "같은 사실이 여러 자료에 등장하면 중복으로 부풀리지 마세요. "
                                + "자료 간 내용이 모순되면 단정하지 말고 질문 항목에 명시하세요. "
                                + "김대리가 회의에 참석하지 않았더라도 명시적으로 배정된 업무는 추출하세요. "
                                + "다른 사람에게 배정된 업무를 김대리의 업무로 바꾸지 마세요. "
                                + "불확실한 업무는 추측하지 마세요. "
                                + "원문에 정확한 연·월·일이 명시된 경우에만 YYYY-MM-DD로 작성하세요. "
                                + "deadline_phrase에는 원문에 실제 등장하는 마감일 표현을 그대로 복사하세요. "
                                + "예: '다음 주까지', '2026년 11월 6일까지'. 기한이 없으면 빈 문자열. "
                                + "상대적인 날짜를 임의의 연월일로 변환하지 마세요. "
                                + "모르는 기한은 deadline도 빈 문자열로 작성하세요."
                            )
                        },
                        {
                            "role": "user",
                            "content": source
                        }
                    ],
                    schema=MEETING_SCHEMA
                )

                result = verify_meeting_tasks(json.loads(response), source)
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

        with st.container(border=True):
            st.subheader("③ 회의 요약")
            summary = st.text_area(
                "요약 내용 확인",
                value=result["summary"], height=150,
                key=f"meeting_summary_{version}"
            )
            st.markdown("**주요 결정사항**")
            for decision in result["decisions"]:
                st.write("• " + decision)

        # 회의 요약 바로 아래에 음성 답변을 배치합니다.
        with st.container(border=True):
            st.markdown("**요약 음성 듣기**")
            if st.button("요약 음성 생성", key="meeting_make_tts"):
                try:
                    st.session_state.meeting_audio = make_full_speech(summary)
                    st.session_state.meeting_autoplay = True
                except Exception as exc:
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
                st.caption("긴 요약도 누락되지 않도록 여러 음성 구간을 생성하여 하나의 WAV로 연결합니다.")

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

                kind = task.get("deadline_kind", "unverified" if task.get("deadline") else "none")
                phrase = task.get("deadline_phrase", "")
                if kind in ("relative", "unverified"):
                    st.warning(
                        f"원문 기한: {phrase or '확인 불가'} · 정확한 날짜를 확인해주세요. "
                        "원문에서 날짜가 검증되지 않아 자동 지정하지 않았습니다."
                    )
                    pick_deadline = st.checkbox(
                        "정확한 마감일을 직접 선택했습니다",
                        value=False, key=f"meeting_date_confirm_{version}_{i}"
                    )
                    picked = st.date_input(
                        "마감일 직접 선택", value=now_kst().date(),
                        disabled=not pick_deadline, key=f"meeting_pick_date_{version}_{i}"
                    )
                    date = picked.isoformat() if pick_deadline else ""
                else:
                    pick_deadline = True
                    date = st.text_input(
                        "기한 (YYYY-MM-DD, 공란은 기한 미정)",
                        value=task["deadline"],
                        key=f"meeting_date_{version}_{i}"
                    )

                detail = st.text_area(
                    "업무 설명",
                    value=task["detail"],
                    key=f"meeting_detail_{version}_{i}"
                )

                urgency = st.selectbox(
                    "업무 중요도·표시 색상", list(URGENCY_LABELS),
                    format_func=lambda value: URGENCY_LABELS[value],
                    key=f"meeting_urgency_{version}_{i}"
                )

                selected_tasks.append(
                    (selected, name, date, detail, kind, pick_deadline, urgency)
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
                missing_date = []
                for selected, name, date, detail, kind, confirmed_date, urgency in selected_tasks:
                    if not selected or not name.strip():
                        continue

                    if kind == "relative" and not confirmed_date:
                        missing_date.append(name)
                        continue

                    try:
                        if date:
                            datetime.strptime(date, "%Y-%m-%d")

                        if add_task_if_missing(name, date, "", detail, urgency):
                            added += 1
                    except ValueError:
                        st.error(
                            f"'{name}'의 날짜 형식을 확인해주세요."
                        )

                if missing_date:
                    st.warning("다음 업무는 정확한 마감일을 선택해야 등록할 수 있습니다: "
                               + ", ".join(missing_date))
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

