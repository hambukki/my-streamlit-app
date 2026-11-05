"""AI 이메일, 주소록, Gmail 예약전송."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st
from aivle.core import (get_sid, connect_db, now_kst, load_contacts,
                        save_contact, delete_contact, save_setting)
from aivle.email import (make_email_draft, polish_email_draft, send_gmail, schedule_gmail,
                         load_scheduled_emails, valid_email)
from aivle.email_drafts import persist_draft, clear_draft
from aivle.pro_email import (EMAIL_INTENTS, EMAIL_AUDIENCES, EMAIL_TONES,
                             EMAIL_SUBJECT_MODES, EMAIL_SIGNATURE_MODES)


def _save_composer():
    persist_draft(st.session_state, save_setting)
    # 수정 후에는 이전 발송 확인을 재사용하지 않습니다.
    st.session_state["email_approval_v7"] = False


def _new_composer():
    clear_draft(st.session_state, save_setting)
    st.session_state.email_last_sent = ""
    st.session_state.email_review_items = []
    st.session_state["email_approval_v7"] = False



def render():
    # Streamlit에서는 위젯 렌더 후 동일 키 변경이 금지됩니다.
    # 발송 성공 시 다음 rerun의 맨 처음에 안전하게 초기화합니다.
    if st.session_state.pop("_email_clear_after_send", False):
        clear_draft(st.session_state, save_setting)
        st.session_state["_email_sent_notice"] = True
        st.session_state.email_review_items = []
        st.session_state["email_approval_v7"] = False

    title_col, new_col = st.columns([4, 1.4], vertical_alignment="center")
    with title_col:
        st.title("이메일 비서")
    with new_col:
        if st.button("새 이메일 작성", icon=":material/edit_square:",
                     use_container_width=True, key="email_new_compose"):
            _new_composer()
            st.rerun()
    st.caption("수신 대상·업무 목적을 반영한 실무형 이메일 초안, 참조 지정 및 발송")
    st.caption("작성 중인 내용은 자동 저장되며 다른 메뉴를 다녀와도 복원됩니다.")
    if st.session_state.pop("_email_sent_notice", False):
        st.success("이메일을 전송했습니다. 새 이메일을 작성할 수 있습니다.")

    contacts = load_contacts()

    contact_options = ["직접 입력"] + [
        f"{name} <{email}>"
        for name, email in contacts
    ]

    selected_contact = st.selectbox(
        "주소록에서 수신자 선택",
        contact_options
    )

    if selected_contact != "직접 입력":
        contact_email = selected_contact.rsplit("<", 1)[-1].rstrip(">")
        if st.button("선택한 연락처를 수신자로 지정"):
            st.session_state.email_to = contact_email
            _save_composer()
            st.rerun()

    st.text_input("받는 사람", key="email_to", on_change=_save_composer)
    st.text_input(
        "참조 (CC)",
        key="email_cc",
        placeholder="여러 명이면 쉼표로 구분",
        on_change=_save_composer
    )

    with st.expander("AI 업무 메일 작성 설정", expanded=True):
        purpose_col, recipient_col = st.columns(2)
        with purpose_col:
            st.selectbox("발송 목적", EMAIL_INTENTS, key="email_intent",
                         on_change=_save_composer)
        with recipient_col:
            st.selectbox("수신자 관계", EMAIL_AUDIENCES, key="email_audience",
                         on_change=_save_composer)
        tone_col, subject_mode_col = st.columns(2)
        with tone_col:
            st.selectbox("이메일 문체", EMAIL_TONES, key="email_tone",
                         on_change=_save_composer)
        with subject_mode_col:
            st.selectbox("제목 처리", EMAIL_SUBJECT_MODES, key="email_subject_mode",
                         on_change=_save_composer)
        st.text_input("요청·회신 기한 (선택)", key="email_deadline",
                      placeholder="예: 11월 12일 오후 3시 / 없으면 비워두세요",
                      on_change=_save_composer)
        sender_col, sign_col = st.columns(2)
        with sender_col:
            st.text_input("발신자 표시 이름", key="email_sender_name",
                          on_change=_save_composer)
        with sign_col:
            st.selectbox("메일 하단 서명", EMAIL_SIGNATURE_MODES,
                         key="email_signature", on_change=_save_composer)

    st.text_input("제목", key="email_subject", on_change=_save_composer)
    st.text_area("작성 메모 · 핵심 내용 (AI 참고용)", key="email_brief",
                 height=100, on_change=_save_composer,
                 placeholder="예: 11월 12일까지 기획안 검토 요청, 변경 사항 세 가지를 확인해 달라는 내용")
    st.text_area("발송할 이메일 본문 (자유롭게 수정 가능)", key="email_body",
                 height=250, on_change=_save_composer)
    st.caption("메모와 발송 본문은 별개로 저장됩니다. 기존 본문을 더 자연스럽게 바꾸려면 '본문 다듬기'를 사용하세요.")

    generate_col, polish_col, save_col = st.columns([1.5, 1.2, 1], vertical_alignment="center")
    with generate_col:
        st.button("AI 업무 메일 생성", icon=":material/auto_awesome:",
                  on_click=make_email_draft, use_container_width=True)
    with polish_col:
        st.button("본문 다듬기", icon=":material/edit_note:",
                  on_click=polish_email_draft, use_container_width=True)
    with save_col:
        if st.button("임시저장", icon=":material/save:", use_container_width=True):
            _save_composer()
            st.success("작성 중인 이메일을 임시저장했습니다.")

    if st.session_state.email_error:
        st.warning(st.session_state.email_error)
    if st.session_state.email_review_items:
        with st.expander("발송 전 확인할 사항", expanded=True):
            for item in st.session_state.email_review_items:
                st.markdown("- " + item)
    st.caption("생성된 문장과 실제 업무 사실을 확인한 뒤 전송해 주세요. AI 생성만으로 이메일이 발송되지는 않습니다.")

    approved = st.checkbox(
        "수신자, 참조, 제목, 본문을 확인했고 발송에 동의합니다.",
        key="email_approval_v7"
    )

    if st.button(
        "이메일 전송",
        type="primary",
        icon=":material/send:",
        disabled=not approved
    ):
        try:
            to = st.session_state.email_to.strip()
            cc = st.session_state.email_cc.strip()
            subject = st.session_state.email_subject.strip()
            body = st.session_state.email_body.strip()

            if not to or not subject or not body:
                st.warning("필수 항목을 모두 입력해주세요.")
            else:
                signature = json.dumps(
                    [to, cc, subject, body],
                    ensure_ascii=False
                )

                if signature == st.session_state.email_last_sent:
                    st.warning("동일한 내용의 이메일을 이미 전송했습니다.")
                else:
                    with st.spinner("이메일을 전송하는 중입니다..."):
                        send_gmail(to, cc, subject, body)
                    st.session_state.email_last_sent = signature
                    st.session_state["_email_clear_after_send"] = True
                    st.rerun()

        except Exception as e:
            st.error(f"이메일 전송 실패: {e}")


    st.subheader("이메일 예약전송")

    st.caption(
        "현재 시연 버전은 앱 서버가 실행 중일 때만 예약을 처리합니다. "
        "서버가 중단되거나 휴면 상태가 되면 예약 시각에 "
        "발송되지 않을 수 있습니다."
    )

    with st.form("gmail_schedule_form"):
        send_date = st.date_input(
            "예약 날짜",
            value=now_kst().date(),
            min_value=now_kst().date()
        )

        send_time = st.time_input(
            "예약 시간 (한국 시간)",
            value=(
                now_kst() + timedelta(minutes=5)
            ).time().replace(
                second=0,
                microsecond=0
            )
        )

        scheduled_approved = st.checkbox(
            "작성한 이메일을 지정 시각에 자동 전송하도록 승인합니다."
        )

        schedule_submitted = st.form_submit_button(
            "예약전송 등록",
            type="primary"
        )

    if schedule_submitted:
        if not scheduled_approved:
            st.warning(
                "예약전송 승인 항목을 확인해주세요."
            )
        else:
            try:
                send_at = datetime.combine(
                    send_date,
                    send_time,
                    tzinfo=ZoneInfo("Asia/Seoul")
                )

                created = schedule_gmail(
                    st.session_state.email_to.strip(),
                    st.session_state.email_cc.strip(),
                    st.session_state.email_subject.strip(),
                    st.session_state.email_body.strip(),
                    send_at
                )

                if created:
                    st.success(
                        "예약을 등록했습니다. "
                        "발송 시각까지 서버를 실행 상태로 유지해주세요."
                    )
                else:
                    st.info(
                        "동일한 예약이 이미 등록되어 있습니다."
                    )

            except Exception as exc:
                st.error(f"예약 등록 실패: {exc}")

    with st.expander("예약전송 내역"):
        labels = {
            "pending": "발송 대기",
            "sending": "발송 중",
            "sent": "발송 완료",
            "failed": "발송 실패",
            "missed": "예약 시각 경과",
            "cancelled": "취소됨"
        }

        scheduled_rows = load_scheduled_emails()

        if not scheduled_rows:
            st.caption("예약된 이메일이 없습니다.")

        for (
            record_id,
            recipient,
            subject,
            send_at_text,
            status,
            error
        ) in scheduled_rows:

            with st.container(border=True):
                st.write(f"**{subject}** · {recipient}")

                display_time = send_at_text[:16].replace("T", " ")

                st.caption(
                    f"{display_time} KST · "
                    f"{labels.get(status, status)}"
                )

                if error:
                    st.caption(f"상태 안내: {error}")

                if status == "pending" and st.button(
                    "예약 취소",
                    key=f"cancel_mail_{record_id}"
                ):
                    with connect_db() as conn:
                        conn.execute(
                            "UPDATE scheduled_emails "
                            "SET status='cancelled' "
                            "WHERE id=? AND sid=? AND status='pending'",
                            (record_id, get_sid())
                        )

                    st.rerun()

    st.divider()

    with st.expander("주소록 관리"):
        with st.form("contact_add"):
            name = st.text_input("이름")
            email = st.text_input("이메일 주소")
            submitted = st.form_submit_button("연락처 저장")

        if submitted:
            if name.strip() and valid_email(email.strip()):
                save_contact(name.strip(), email.strip())
                st.success("연락처를 저장했습니다.")
                st.rerun()
            else:
                st.warning("이름과 이메일 주소를 확인해주세요.")

        contacts = load_contacts()

        for name, email in contacts:
            c1, c2 = st.columns([5, 1])
            c1.write(f"**{name}** · {email}")

            if c2.button(
                "삭제",
                key=f"delete_contact_{email}"
            ):
                delete_contact(email)
                st.rerun()
