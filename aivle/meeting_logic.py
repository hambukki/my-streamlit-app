"""회의록 날짜 근거 검증. 근거가 없는 날짜는 등록하지 않습니다."""

import re
from datetime import date, timedelta


DATE_PATTERN = re.compile(r"(?<!\d)(20\d{2})\s*(?:[-./년]\s*)\s*(\d{1,2})\s*(?:[-./월]\s*)\s*(\d{1,2})\s*일?(?!\d)")
MONTH_DAY_PATTERN = re.compile(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일?(?!\d)")
SHORT_DATE_PATTERN = re.compile(r"(?<![\d./-])(\d{1,2})\s*[./-]\s*(\d{1,2})(?![\d./-])")
RELATIVE_PATTERN = re.compile(r"(다음\s*주|이번\s*주|다음\s*달|이번\s*달|내일|모레|금주|차주|월말|주말|조속히|가능한\s*한\s*빨리)")


def suggested_deadline_from_phrase(phrase, today):
    """원문에 직접 적힌 날짜만 선택창 초기값으로 제안하며, 등록 확정은 하지 않습니다.

    연도가 없는 11월 6일/11.6/11-6은 회의일 주변의 연도로만 표시합니다.
    여러 날짜가 섞인 표현은 하나를 임의 선택하지 않습니다.
    """
    phrase = str(phrase or "")
    explicit = set()
    for match in DATE_PATTERN.finditer(phrase):
        try:
            explicit.add(date(*map(int, match.groups())))
        except ValueError:
            continue
    if len(explicit) == 1:
        return next(iter(explicit))
    if len(explicit) > 1:
        return None

    # 연도를 포함한 표기(2026.11.6)를 11.6으로 잘못 다시 읽지 않습니다.
    without_full_dates = DATE_PATTERN.sub(" ", phrase)
    month_days = set()
    for pattern in (MONTH_DAY_PATTERN, SHORT_DATE_PATTERN):
        for match in pattern.finditer(without_full_dates):
            month, day = map(int, match.groups())
            month_days.add((month, day))
    if len(month_days) != 1:
        return None

    month, day = next(iter(month_days))
    try:
        suggested = date(today.year, month, day)
        # 연말에 언급된 내년 1월 등만 다음 연도로 제안합니다.
        if suggested < today - timedelta(days=60):
            suggested = date(today.year + 1, month, day)
        return suggested
    except ValueError:
        # 2월 29일처럼 연도가 필요한 표현은 추측하지 않습니다.
        return None


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
