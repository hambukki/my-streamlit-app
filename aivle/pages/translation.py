"""한영 번역과 음성 파일 전사."""
import streamlit as st
from aivle.ai import ask_llm, transcribe_audio


def render():
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

                with st.spinner("문장을 번역하고 있습니다..."):
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
