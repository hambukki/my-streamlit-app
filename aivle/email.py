"""Gmail 발송, 예약전송, 이메일 초안."""
import json
import os
import re
import smtplib
import ssl
import threading
import time
import uuid
from datetime import datetime, timedelta
from email.message import EmailMessage

import streamlit as st

from .core import connect_db, get_sid, now_kst
from .ai import ask_llm


def valid_email(address):
    return bool(
        re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address)
    )


def make_email_draft():
    subject = st.session_state.email_subject.strip()

    if not subject:
        st.session_state.email_error = (
            "먼저 이메일 제목이나 목적을 입력해주세요."
        )
        return

    try:
        with st.spinner("이메일 초안을 작성하고 있습니다..."):
            answer = ask_llm([
            {
                "role": "system",
                "content": (
                    "당신은 김대리의 업무 비서입니다. "
                    "정중하고 간결한 업무 이메일 본문을 작성하세요. "
                    "확인되지 않은 사실은 만들어내지 마세요. "
                    "이메일 본문만 출력하세요."
                )
            },
            {
                "role": "user",
                "content": (
                    f"제목: {subject}\n"
                    f"받는 사람: {st.session_state.email_to}\n"
                    f"참고 내용: {st.session_state.email_body}"
                )
            }
            ])

        st.session_state.email_body = answer
        st.session_state.email_error = ""

    except Exception as e:
        st.session_state.email_error = str(e)


def send_gmail(to, cc, subject, body):
    sender = os.getenv("GMAIL_ADDRESS")
    password = os.getenv("GMAIL_APP_PASSWORD")

    if not sender or not password:
        raise ValueError("Gmail 인증 정보가 없습니다.")

    recipients = [to]
    if cc:
        recipients.extend(
            address.strip()
            for address in cc.split(",")
            if address.strip()
        )

    if not all(valid_email(address) for address in recipients):
        raise ValueError("이메일 주소 형식을 확인해주세요.")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject

    if cc:
        message["Cc"] = cc

    message.set_content(body)

    with smtplib.SMTP(
        "smtp.gmail.com", 587, timeout=20
    ) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(sender, password)
        server.send_message(message)


def schedule_gmail(to, cc, subject, body, send_at):
    recipients = [to] + [
        item.strip()
        for item in cc.split(",")
        if item.strip()
    ]

    if not all(valid_email(email) for email in recipients):
        raise ValueError(
            "받는 사람 또는 참조 이메일 주소가 올바르지 않습니다."
        )

    if not to.strip() or not subject.strip() or not body.strip():
        raise ValueError(
            "받는 사람, 제목, 본문을 모두 입력해주세요."
        )

    if send_at <= now_kst():
        raise ValueError(
            "예약 시각은 현재 시각 이후로 설정해주세요."
        )

    send_at_text = send_at.isoformat(timespec="seconds")

    with connect_db() as conn:
        previous = conn.execute(
            "SELECT id FROM scheduled_emails "
            "WHERE sid=? AND recipient=? AND cc=? "
            "AND subject=? AND body=? AND send_at=? "
            "AND status='pending'",
            (get_sid(), to, cc, subject, body, send_at_text)
        ).fetchone()

        if previous:
            return False

        conn.execute(
            "INSERT INTO scheduled_emails "
            "(id, sid, recipient, cc, subject, body, send_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')",
            (
                str(uuid.uuid4()),
                get_sid(),
                to,
                cc,
                subject,
                body,
                send_at_text
            )
        )

    return True


def load_scheduled_emails():
    with connect_db() as conn:
        return conn.execute(
            "SELECT id, recipient, subject, send_at, status, error "
            "FROM scheduled_emails "
            "WHERE sid=? "
            "ORDER BY send_at DESC LIMIT 15",
            (get_sid(),)
        ).fetchall()


def _scheduled_mail_worker():
    while True:
        job = None

        try:
            current = now_kst()

            with connect_db() as conn:
                conn.execute("BEGIN IMMEDIATE")

                row = conn.execute(
                    "SELECT id, recipient, cc, subject, body, send_at "
                    "FROM scheduled_emails "
                    "WHERE status='pending' AND send_at<=? "
                    "ORDER BY send_at LIMIT 1",
                    (current.isoformat(timespec="seconds"),)
                ).fetchone()

                if row is not None:
                    due = datetime.fromisoformat(row[5])

                    # 서버가 장시간 멈췄다면 늦게 발송하지 않습니다.
                    if current - due > timedelta(minutes=10):
                        conn.execute(
                            "UPDATE scheduled_emails "
                            "SET status='missed', "
                            "error='서버 중단 등으로 발송 시각을 놓쳤습니다.' "
                            "WHERE id=?",
                            (row[0],)
                        )
                    else:
                        conn.execute(
                            "UPDATE scheduled_emails "
                            "SET status='sending' "
                            "WHERE id=? AND status='pending'",
                            (row[0],)
                        )
                        job = row

            if job is not None:
                message_id, to, cc, subject, body, _ = job

                try:
                    send_gmail(to, cc, subject, body)

                    with connect_db() as conn:
                        conn.execute(
                            "UPDATE scheduled_emails "
                            "SET status='sent', error='' "
                            "WHERE id=? AND status='sending'",
                            (message_id,)
                        )

                except Exception as exc:
                    with connect_db() as conn:
                        conn.execute(
                            "UPDATE scheduled_emails "
                            "SET status='failed', error=? "
                            "WHERE id=? AND status='sending'",
                            (str(exc)[:300], message_id)
                        )

        except Exception as exc:
            print(
                "예약전송 점검 오류:",
                type(exc).__name__,
                str(exc)
            )

        time.sleep(5)


@st.cache_resource
def start_scheduled_email_worker():
    worker = threading.Thread(
        target=_scheduled_mail_worker,
        name="aivle-scheduled-gmail",
        daemon=True
    )

    worker.start()
    return worker
