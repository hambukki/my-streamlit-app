"""홈 위젯의 기본 표시 및 브라우저 새로고침 후 상태 복원.

구버전의 잘못 저장된 빈 체크박스 설정을 v9에서 1회 복구하며,
그 이후 사용자가 직접 해제한 선택은 별도 JSON 설정으로 보존합니다.
"""
import json


SETTING = "home_widget_preferences_v9"
WIDGET_KEYS = ("widget_clock", "widget_weather", "widget_briefing", "widget_calendar")


def read_preferences(raw):
    try:
        parsed = json.loads(raw or "")
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict) or not all(type(parsed.get(key)) is bool for key in WIDGET_KEYS):
        return None
    return {key: parsed[key] for key in WIDGET_KEYS}


def restore_preferences(state, get_setting, save_setting):
    """처음에는 모두 표시; 이후에는 사용자 설정값만 복원합니다."""
    saved = read_preferences(get_setting(SETTING, ""))
    if saved is None:
        saved = {key: True for key in WIDGET_KEYS}
        save_setting(SETTING, json.dumps(saved, ensure_ascii=False))
        # 이전 버전에서 잘못 남은 체크 해제값이 세션에 있어도 1회 복구.
        for key, enabled in saved.items():
            state[key] = enabled
    else:
        for key, enabled in saved.items():
            if key not in state:
                state[key] = enabled
    return saved


def save_preferences(state, save_setting):
    values = {key: bool(state.get(key, True)) for key in WIDGET_KEYS}
    save_setting(SETTING, json.dumps(values, ensure_ascii=False))
    return values
