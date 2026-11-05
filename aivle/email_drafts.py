"""수신자·참조·제목·본문을 탭 전환/재접속 후에도 유지하는 이메일 초안 저장소.

위젯 상태를 DB와 동기화해 Streamlit이 숨겨진 위젯 키를 삭제해도 복구합니다.
"""
import json

EMAIL_DEFAULTS = {
    "email_to": "",
    "email_cc": "",
    "email_subject": "",
    "email_body": "",
    "email_brief": "",
    "email_intent": "업무 요청",
    "email_audience": "사내 동료·담당자",
    "email_tone": "표준 비즈니스",
    "email_deadline": "",
    "email_sender_name": "김대리",
    "email_signature": "서명 포함",
    "email_subject_mode": "입력 제목 유지",
}
FIELDS = tuple(EMAIL_DEFAULTS)
SETTING = "email_composer_draft_v6"


def parse_draft(raw):
    try:
        parsed = json.loads(raw or "{}")
    except (ValueError, TypeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return {field: str(parsed.get(field) or default)
            for field, default in EMAIL_DEFAULTS.items()}


def serialize_draft(state):
    return json.dumps({key: str(state.get(key, EMAIL_DEFAULTS[key]) or EMAIL_DEFAULTS[key])
                       for key in FIELDS},
                      ensure_ascii=False)


def persist_draft(state, save_setting):
    """입력 위젯 변경, AI 생성, 수신자 선택 직후 DB에 자동 저장합니다."""
    save_setting(SETTING, serialize_draft(state))


def clear_draft(state, save_setting):
    """명시적 '새 이메일 작성' 또는 발송 성공 후에만 현재 초안을 비웁니다."""
    for key in FIELDS:
        state[key] = EMAIL_DEFAULTS[key]
    state["email_error"] = ""
    persist_draft(state, save_setting)
