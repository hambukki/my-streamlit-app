"""수신자·참조·제목·본문을 탭 전환/재접속 후에도 유지하는 이메일 초안 저장소.

위젯 상태를 DB와 동기화해 Streamlit이 숨겨진 위젯 키를 삭제해도 복구합니다.
"""
import json

FIELDS = ("email_to", "email_cc", "email_subject", "email_body")
SETTING = "email_composer_draft_v6"


def parse_draft(raw):
    try:
        parsed = json.loads(raw or "{}")
    except (ValueError, TypeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return {field: str(parsed.get(field, "") or "") for field in FIELDS}


def serialize_draft(state):
    return json.dumps({key: str(state.get(key, "") or "") for key in FIELDS},
                      ensure_ascii=False)


def persist_draft(state, save_setting):
    """입력 위젯 변경, AI 생성, 수신자 선택 직후 DB에 자동 저장합니다."""
    save_setting(SETTING, serialize_draft(state))


def clear_draft(state, save_setting):
    """명시적 '새 이메일 작성' 또는 발송 성공 후에만 현재 초안을 비웁니다."""
    for key in FIELDS:
        state[key] = ""
    state["email_error"] = ""
    persist_draft(state, save_setting)
