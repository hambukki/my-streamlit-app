"""회의록 입력·요약·메일 공유·후속 질문."""
import hashlib
import json

import streamlit as st
from aivle.core import get_setting, save_setting
from aivle.ai import SYS_ROLE, MEETING_SCHEMA, ask_llm, transcribe_audio
from aivle.documents import decode_text_file
from aivle.meeting_logic import verify_meeting_tasks, combine_meeting_sources
from aivle.meeting_sections import render_summary, render_tasks

AUTO_TRANSCRIBE_PLACEHOLDER = "(요약 실행 시 자동 전사)"


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
    """선택적으로 전체 전사 텍스트를 미리 검토하게 합니다."""
    if uploaded is None:
        st.info("회의 음성을 첨부하거나 녹음해주세요.")
        return
    data = uploaded.getvalue()
    mime = _audio_mime(uploaded.name)
    st.audio(data, format=mime)
    st.caption("미리 전사하여 수정할 수도 있습니다. 전사하지 않아도 '회의록 정리 실행' 한 번으로 분석됩니다 (25MB 이하).")
    if st.button("음성 전체 텍스트 변환", key=button_key, icon=":material/transcribe:"):
        try:
            with st.spinner("전체 음성을 문자로 변환하고 있습니다..."):
                st.session_state[state_key] = transcribe_audio(uploaded)
                st.session_state[f"{state_key}_revision"] = (
                    st.session_state.get(f"{state_key}_revision", 0) + 1
                )
            st.success("음성 인식이 완료됐습니다. 아래 전사 결과를 검토하고 수정할 수 있습니다.")
        except Exception as exc:
            st.error(f"음성 인식 실패: {exc}")
    st.download_button("원본 음성 다운로드", data=data, mime=mime,
                       file_name=uploaded.name, key=f"{button_key}_download")


def reset_meeting_workspace():
    """이전 회의 자료·검토 내용·결과를 모두 비우고 새 업로더를 엽니다."""
    st.session_state["meeting_input_generation"] = (
        st.session_state.get("meeting_input_generation", 0) + 1
    )
    for key in ("meeting_txt_review", "meeting_txt_hash", "meeting_audio_review",
                "meeting_audio_hash", "meeting_recording_review", "meeting_recording_hash"):
        st.session_state[key] = ""
    for key in ("meeting_audio_review_revision", "meeting_recording_review_revision"):
        st.session_state[key] = 0
    st.session_state.meeting_result = None
    st.session_state.meeting_version += 1
    st.session_state.meeting_audio = None
    st.session_state.meeting_autoplay = False
    st.session_state.meeting_followup = []
    save_setting("meeting_result", "null")


def collect_meeting_sources(notes, txt_text, audio_text, recording_text,
                            audio_present=False, recording_present=False):
    """아직 전사하지 않은 음성도 요약 실행 대상에 표시합니다."""
    entries = [
        ("회의메모", notes), ("회의록 TXT", txt_text),
        ("회의 음성 파일", audio_text if audio_text and audio_text.strip()
         else AUTO_TRANSCRIBE_PLACEHOLDER if audio_present else ""),
        ("회의 내용 녹음", recording_text if recording_text and recording_text.strip()
         else AUTO_TRANSCRIBE_PLACEHOLDER if recording_present else ""),
    ]
    return {name: value.strip() for name, value in entries if value and value.strip()}


def prepare_selected_meeting_text(sources, selected, audio_file=None, recording=None,
                                  transcription_fn=None):
    """선택된 음성의 미전사분을 자동 인식하고, 완전한 원문과 전사 변경사항을 반환합니다."""
    transcription_fn = transcription_fn or transcribe_audio
    resolved = dict(sources)
    transcripts = {}
    for label, uploaded, review_key in (
        ("회의 음성 파일", audio_file, "meeting_audio_review"),
        ("회의 내용 녹음", recording, "meeting_recording_review"),
    ):
        if label not in selected or uploaded is None:
            continue
        if resolved.get(label) != AUTO_TRANSCRIBE_PLACEHOLDER:
            continue
        transcript = transcription_fn(uploaded)
        if not transcript or not transcript.strip():
            raise ValueError(f"{label}에서 인식된 텍스트가 없습니다. 음성 파일을 확인해주세요.")
        transcripts[review_key] = transcript.strip()
        resolved[label] = transcript.strip()
    return combine_meeting_sources(resolved, selected), transcripts


def _audio_review_editor(label, review_key, generation):
    """전사/업로드 변경 시에도 텍스트 편집 위젯 상태와 충돌하지 않습니다."""
    fingerprint = st.session_state.get(review_key.replace("_review", "_hash"), "")[:10]
    revision = st.session_state.get(f"{review_key}_revision", 0)
    updated = st.text_area(label, value=st.session_state.get(review_key, ""),
                           key=f"{review_key}_editor_{generation}_{fingerprint}_{revision}",
                           height=200)
    st.session_state[review_key] = updated


def render():
    st.title("회의록 정리")
    st.caption("회의 내용 확인 → 요약과 음성 듣기 → 김대리 담당 업무 검토")
    if st.button("새로운 회의 정리", icon=":material/note_add:",
                 key="meeting_start_fresh", help="이전 입력과 분석 결과를 비우고 새 회의를 시작합니다."):
        reset_meeting_workspace()
        st.rerun()
    generation = st.session_state.get("meeting_input_generation", 0)

    with st.container(border=True):
        st.subheader("① 회의 자료 입력")
        st.caption("메모·TXT·음성 파일·마이크 녹음을 동시에 사용할 수 있습니다. 입력한 자료를 한데 모아 분석합니다.")
        tab_memo, tab_txt, tab_audio, tab_record = st.tabs(
            ["✍️ 회의메모", "📄 회의록 TXT", "🎧 회의 음성 파일", "🎙️ 회의 내용 녹음"]
        )

        with tab_memo:
            notes = st.text_area("회의메모", height=180, key=f"meeting_manual_notes_{generation}",
                                 placeholder="회의 중 직접 적은 메모나 회의 내용을 입력하세요.")
        with tab_txt:
            txt_file = st.file_uploader("회의록 TXT 첨부", type=["txt", "md"],
                                        key=f"meeting_text_upload_{generation}")
            _prepare_uploaded_text(txt_file, "meeting_txt_review", "meeting_txt_hash", decode=True)
            if txt_file is not None:
                st.text_area("TXT 전체 내용 검토 · 편집", key="meeting_txt_review", height=200)
        with tab_audio:
            audio_file = st.file_uploader("회의 음성 파일 첨부", type=["mp3", "wav", "m4a", "mp4", "webm"],
                                          key=f"meeting_audio_upload_{generation}")
            _prepare_uploaded_text(audio_file, "meeting_audio_review", "meeting_audio_hash")
            _transcribe_file(audio_file, "meeting_audio_review", "meeting_audio_transcribe")
            if audio_file is not None:
                _audio_review_editor("음성 파일 전체 전사 검토 · 편집", "meeting_audio_review", generation)
        with tab_record:
            recording = st.audio_input("회의 내용 녹음", key=f"meeting_recording_{generation}")
            _prepare_uploaded_text(recording, "meeting_recording_review", "meeting_recording_hash")
            _transcribe_file(recording, "meeting_recording_review", "meeting_recording_transcribe")
            if recording is not None:
                _audio_review_editor("녹음 전체 전사 검토 · 편집", "meeting_recording_review", generation)

    sources = collect_meeting_sources(
        notes, st.session_state.get("meeting_txt_review", ""),
        st.session_state.get("meeting_audio_review", ""),
        st.session_state.get("meeting_recording_review", ""),
        audio_present=audio_file is not None,
        recording_present=recording is not None,
    )
    if sources:
        st.subheader("② 분석할 자료 확인")
        source_key = f"{generation}_" + hashlib.sha256(
            "|".join(sources).encode("utf-8")).hexdigest()[:12]
        selected = st.multiselect("요약에 포함할 자료 (기본값: 모두 포함)",
                                  options=list(sources), default=list(sources),
                                  key=f"meeting_sources_{source_key}")
        st.caption(f"분석 대상 {len(selected)}개 · 선택한 자료의 모든 문장을 통합하여 요약합니다. "
                   "서로 중복되는 내용은 하나의 회의 사실로 취급합니다.")
    else:
        selected = []
        st.info("회의메모나 TXT를 입력하거나 음성 파일을 첨부해주세요. 음성은 요약 실행 시 자동으로 전사됩니다.")

    selected_text = combine_meeting_sources(sources, selected)
    if st.button("회의록 정리 실행", type="primary", disabled=not bool(selected_text)):
        try:
            # 오디오만 첨부한 경우에도 한 번의 실행으로 전사→요약합니다.
            with st.spinner("선택한 음성을 전사하고 회의 자료를 준비하는 중입니다..."):
                source, new_transcripts = prepare_selected_meeting_text(
                    sources, selected, audio_file, recording
                )
            for review_key, transcript in new_transcripts.items():
                st.session_state[review_key] = transcript
                st.session_state[f"{review_key}_revision"] = (
                    st.session_state.get(f"{review_key}_revision", 0) + 1
                )

            if not source.strip():
                st.warning("회의 내용을 입력해주세요.")
            else:
                with st.spinner("회의 자료를 종합해 요약하고 있습니다..."):
                    response = ask_llm(
                        [
                        {
                            "role": "system",
                            "content": (
                                SYS_ROLE
                                + "\n다음 회의를 요약하세요. "
                                + "이 작업의 목표는 짧은 개요가 아니라 후속 업무에 그대로 활용할 수 있는 상세 회의록입니다. "
                                + "제공된 모든 회의 자료에서 확인되는 핵심 정보와 세부 논의를 빠짐없이 통합하세요. "
                                + "summary에는 Markdown 소제목을 사용하여 '회의 목적과 배경', "
                                + "'안건별 논의 내용', '의견·검토한 대안·쟁점', "
                                + "'결정사항과 결정 근거', '후속 조치와 남은 확인사항'을 나누어 자세히 작성하세요. "
                                + "각 안건마다 누가 어떤 의견을 제시했는지, 그 이유와 반론, "
                                + "결론까지의 논의 흐름을 원문에서 확인되는 범위 안에서 문장으로 풀어 쓰세요. "
                                + "원문에 등장하는 중요한 날짜·시간·숫자·수량·예산·담당자·실행 순서·조건·위험 요소를 생략하지 마세요. "
                                + "단순 한두 문장으로 압축하지 말고, 원문이 풍부할수록 요약도 충분한 길이로 작성하세요. "
                                + "다만 원문이 짧은 경우에는 분량을 채우기 위해 사실을 만들어내지 마세요. "
                                + "decisions에는 확정된 결정만, questions에는 미정·충돌·추가 확인사항만 기재하세요. "
                                + "같은 사실이 여러 자료에 등장하면 중복으로 부풀리지 마세요. "
                                + "자료 간 내용이 모순되면 단정하지 말고 질문 항목에 명시하세요. "
                                + "김대리가 회의에 참석하지 않았더라도 명시적으로 배정된 업무는 추출하세요. "
                                + "다른 사람에게 배정된 업무를 김대리의 업무로 바꾸지 마세요. "
                                + "불확실한 업무는 추측하지 마세요. "
                                + "원문에 정확한 연·월·일이 명시된 경우에만 YYYY-MM-DD로 작성하세요. "
                                + "deadline_phrase에는 원문에 실제 등장하는 마감일 표현을 그대로 복사하세요. "
                                + "예: '다음 주까지', '11월 6일', '2026년 11월 6일까지'. 기한이 없으면 빈 문자열. "
                                + "원문이 '11월 6일'처럼 연도를 생략했다면 deadline을 비워 두고 deadline_phrase에 '11월 6일'을 넣으세요. "
                                + "상대적인 날짜를 임의의 연월일로 변환하지 마세요. "
                                + "모르는 기한은 deadline도 빈 문자열로 작성하세요."
                            )
                        },
                        {
                            "role": "user",
                            "content": source
                        }
                        ],
                        schema=MEETING_SCHEMA,
                        max_output_tokens=8500
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
        summary_tab, tasks_tab = st.tabs([
            "📝 회의 요약", f"✅ 담당 업무 · {len(result['kim_tasks'])}건"
        ])
        with summary_tab:
            summary = render_summary(result, version)
        with tasks_tab:
            render_tasks(result, version, summary)

