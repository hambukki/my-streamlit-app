"""AI 이메일, 주소록, Gmail 예약전송."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st
from aivle.core import (get_sid, connect_db, now_kst, load_contacts,
                        save_contact, delete_contact)
from aivle.email import (make_email_draft, send_gmail, schedule_gmail,
                         load_scheduled_emails, valid_email)


def render():
    st.title("이메일 비서")
    st.caption("AI 초안 작성, 참조 지정, 주소록 선택 및 발송")

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
            st.rerun()

    st.text_input("받는 사람", key="email_to")
    st.text_input(
        "참조 (CC)",
        key="email_cc",
        placeholder="여러 명이면 쉼표로 구분"
    )
    st.text_input("제목", key="email_subject")
    st.text_area("본문", key="email_body", height=210)

    st.button(
        "AI 이메일 초안 작성",
        icon=":material/auto_awesome:",
        on_click=make_email_draft
    )

    if st.session_state.email_error:
        st.warning(st.session_state.email_error)

    approved = st.checkbox(
        "수신자, 참조, 제목, 본문을 확인했고 발송에 동의합니다."
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
                    send_gmail(to, cc, subject, body)
                    st.session_state.email_last_sent = signature
                    st.success("이메일을 전송했습니다.")

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
