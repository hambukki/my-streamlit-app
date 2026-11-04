"""회의록 날짜 근거 검증. 근거가 없는 날짜는 등록하지 않습니다."""

import re
from datetime import date


DATE_PATTERN = re.compile(r"(?<!\d)(20\d{2})\s*(?:[-./년]\s*)\s*(\d{1,2})\s*(?:[-./월]\s*)\s*(\d{1,2})\s*일?(?!\d)")
RELATIVE_PATTERN = re.compile(r"(다음\s*주|이번\s*주|다음\s*달|이번\s*달|내일|모레|금주|차주|월말|주말|조속히|가능한\s*한\s*빨리)")


def combine_meeting_sources(sources, selected=None):
    """선택된 모든 자료를 원문 누락 없이 구분 표시하여 하나의 입력으로 합칩니다."""
    names = list(sources) if selected is None else selected
    return "\n\n".join(
        f"[{name}]\n{sources[name]}" for name in names if sources.get(name, "").strip()
    )


def verified_deadline(task, source):
    """(확정 날짜, 상태, 원문 표현) 반환. 상대/미확인은 항상 날짜를 비워 둡니다."""
    phrase = str(task.get("deadline_phrase", "") or "").strip()
    suggestion = str(task.get("deadline", "") or "").strip()
    source = source or ""

    # LLM이 생성한 '증거'가 원문에 실제로 있는지 확인합니다.
    if not phrase or phrase not in source:
        return "", "unverified" if (phrase or suggestion) else "none", phrase

    if RELATIVE_PATTERN.search(phrase):
        return "", "relative", phrase

    dates = []
    for found in DATE_PATTERN.finditer(phrase):
        try:
            dates.append(date(*map(int, found.groups())).isoformat())
        except ValueError:
            continue

    # 명확한 연·월·일을 포함하고, AI가 지정한 날짜와 정확히 같을 때만 확정합니다.
    if suggestion and suggestion in dates:
        return suggestion, "absolute", phrase
    if dates and not suggestion:
        return dates[0], "absolute", phrase
    return "", "unverified", phrase


def verify_meeting_tasks(result, source):
    """분석 결과에 출처 검증 상태를 추가하며 원본 업무는 유지합니다."""
    for task in result.get("kim_tasks", []):
        deadline, kind, phrase = verified_deadline(task, source)
        task["deadline"] = deadline
        task["deadline_kind"] = kind
        task["deadline_phrase"] = phrase
    return result
