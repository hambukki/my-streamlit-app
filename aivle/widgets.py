"""공유 업무 편집 창과 캘린더·날씨 위젯."""
import calendar
import html
from datetime import datetime

import requests
import streamlit as st

from .core import (get_task, add_task, update_task, delete_task,
                   rename_conversation, load_tasks, set_task_done, now_kst,
                   add_task_preset)


URGENCY_LABELS = {"urgent": "🔴 긴급 · 파스텔 레드", "high": "🟠 높음 · 파스텔 피치",
                  "normal": "🟢 보통 · 파스텔 민트", "low": "🔵 낮음 · 파스텔 블루"}


CITIES = {
    "서울": (37.5665, 126.9780),
    "화성": (37.1995, 127.0732),
    "부산": (35.1796, 129.0756)
}


@st.dialog("업무 추가 · 편집")
def task_editor(task_id=None, suggested_date=""):
    item = get_task(task_id) if task_id else None
    title = "업무 편집" if item else "새 업무 추가"
    st.caption(f"{title} — 저장하면 홈·내 일정·AI 채팅에 함께 반영됩니다.")
    default_date = item["deadline"] if item else suggested_date
    default_time = item["time"] if item else ""
    # st.form 안의 체크박스는 저장을 누를 때까지 rerun되지 않아
    # date_input/time_input의 disabled가 업데이트되지 않습니다.
    editor_key = f"task_editor_{task_id or 'new'}"
    name = st.text_input("업무명 *", value=item["task"] if item else "",
                         key=f"{editor_key}_name")
    detail = st.text_area("업무 내용", value=item["detail"] if item else "",
                          key=f"{editor_key}_detail")
    use_date = st.checkbox("날짜 지정", value=bool(default_date),
                           key=f"{editor_key}_use_date")
    due_date = st.date_input(
        "업무 날짜", value=(datetime.strptime(default_date, "%Y-%m-%d").date()
                         if default_date else now_kst().date()),
        disabled=not use_date, key=f"{editor_key}_date"
    )
    use_time = st.checkbox("시간 지정", value=bool(default_time),
                           key=f"{editor_key}_use_time")
    due_time = st.time_input(
        "시간", value=(datetime.strptime(default_time, "%H:%M").time()
                     if default_time else now_kst().replace(hour=9, minute=0, second=0, microsecond=0).time()),
        disabled=not use_time, step=900, key=f"{editor_key}_time"
    )
    urgency_options = list(URGENCY_LABELS)
    urgency = st.selectbox(
        "업무 중요도·표시 색상", urgency_options,
        index=urgency_options.index(item.get("urgency", "normal") if item else "normal"),
        format_func=lambda value: URGENCY_LABELS[value], key=f"{editor_key}_urgency"
    )
    submitted = st.button("저장", type="primary", use_container_width=True,
                          key=f"{editor_key}_save")
    if submitted:
        try:
            deadline = due_date.isoformat() if use_date else ""
            time_text = due_time.strftime("%H:%M") if use_time else ""
            if item:
                update_task(task_id, name, deadline, time_text, detail, urgency)
            else:
                add_task(name, deadline, time_text, detail, urgency)
            st.rerun()
        except ValueError as exc:
            st.error(f"입력 확인: {exc}")


@st.dialog("상시 업무 프리셋 등록")
def task_preset_editor():
    st.caption("자주 하는 업무를 저장해 두고 홈에서 필요할 때 오늘의 업무로 추가합니다.")
    with st.form("task_preset_create"):
        title = st.text_input("프리셋 이름 *")
        detail = st.text_area("업무 설명")
        urgency = st.selectbox("표시 색상", list(URGENCY_LABELS),
                               format_func=lambda value: URGENCY_LABELS[value])
        submitted = st.form_submit_button("프리셋 저장", type="primary")
    if submitted:
        try:
            add_task_preset(title, detail, urgency)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("업무 삭제 확인")
def task_delete_dialog(task_id):
    item = get_task(task_id)
    if not item:
        st.info("이미 삭제된 업무입니다.")
        return
    st.warning(f"'{item['task']}' 업무를 삭제할까요? 삭제 후 복구할 수 없습니다.")
    if st.button("휴지통 · 삭제 확인", type="primary", icon=":material/delete:"):
        delete_task(task_id)
        st.rerun()


@st.dialog("업무 상세 보기")
def task_detail_dialog(task_id):
    task = get_task(task_id)
    if not task:
        st.info("삭제되었거나 접근할 수 없는 업무입니다.")
        return
    st.subheader(task["task"])
    st.write("날짜:", task["deadline"] or "기한 미정")
    if task["time"]:
        st.write("시간:", task["time"])
    st.write("상태:", "완료" if task["is_done"] else "미완료")
    st.write("중요도:", URGENCY_LABELS.get(task.get("urgency", "normal"), "보통"))
    st.divider()
    st.write(task["detail"] or "추가 설명이 없습니다.")


@st.dialog("대화 제목 수정")
def conversation_rename_dialog(conversation_id, current_title):
    with st.form("rename_conversation_form"):
        title = st.text_input("저장할 대화 제목", value=current_title, max_chars=70)
        submitted = st.form_submit_button("제목 저장", type="primary")
    if submitted:
        try:
            rename_conversation(conversation_id, title)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("저장된 대화 삭제")
def conversation_delete_dialog(conversation_id, title):
    from .core import delete_conversation, get_active_chat_id
    st.warning(f"'{title}' 대화를 삭제하면 해당 메시지와 첨부 자료를 복구할 수 없습니다.")
    if st.button("이 대화 삭제 확인", icon=":material/delete_forever:",
                 type="primary", key=f"confirm_delete_chat_{conversation_id}"):
        if not delete_conversation(conversation_id):
            st.error("대화를 찾을 수 없습니다.")
            return
        if conversation_id == get_active_chat_id():
            # 다른 기존 대화를 자동 선택하는 대신 새 채팅 창을 엽니다.
            from .core import start_new_conversation
            start_new_conversation()
        else:
            st.rerun()


def render_task_actions(task, prefix, show_done=True):
    """모든 화면에서 동일한 편집·삭제·완료 조작을 제공합니다."""
    cols = st.columns(3 if show_done else 2, gap="small")
    with cols[0]:
        if st.button("편집", key=f"{prefix}_edit_{task['id']}",
                     icon=":material/edit:", use_container_width=True):
            task_editor(task["id"])
    with cols[1]:
        if st.button("삭제", key=f"{prefix}_del_{task['id']}",
                     icon=":material/delete:", use_container_width=True):
            task_delete_dialog(task["id"])
    if show_done:
        with cols[2]:
            label = "취소" if task["is_done"] else "완료"
            if st.button(label, key=f"{prefix}_done_{task['id']}",
                         icon=":material/check_circle:", use_container_width=True):
                set_task_done(task["id"], not task["is_done"])
                st.rerun()


@st.cache_data(ttl=900)
def get_weather(city):
    lat, lon = CITIES[city]

    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": (
                "temperature_2m,"
                "apparent_temperature,"
                "relative_humidity_2m,"
                "weather_code"
            ),
            "timezone": "Asia/Seoul"
        },
        timeout=8
    )
    response.raise_for_status()
    return response.json()["current"]


def weather_description(code):
    if code == 0:
        return "맑음"
    if code in [1, 2, 3]:
        return "구름"
    if code in [45, 48]:
        return "안개"
    if code in [51, 53, 55, 61, 63, 65, 80, 81, 82]:
        return "비"
    if code in [71, 73, 75, 77, 85, 86]:
        return "눈"
    if code in [95, 96, 99]:
        return "뇌우"
    return "날씨 확인 중"


def render_mini_calendar(year, month, tasks):
    """홈 위젯에 한 달의 일정 개수와 주요 업무를 컴팩트하게 표시합니다."""
    groups = {}
    for item in tasks:
        if item["deadline"]:
            groups.setdefault(item["deadline"], []).append(item)
    today = now_kst().date().isoformat()
    pieces = [
        '<div class="mini-calendar"><table><thead><tr>',
        '<th class="sunday">일</th><th>월</th><th>화</th><th>수</th>'
        '<th>목</th><th>금</th><th>토</th></tr></thead><tbody>'
    ]
    for week in calendar.Calendar(firstweekday=6).monthdatescalendar(year, month):
        pieces.append("<tr>")
        for idx, day in enumerate(week):
            day_key = day.isoformat()
            items = groups.get(day_key, [])
            title = html.escape("\n".join(f"{t['task']} · {t['detail']}" for t in items), quote=True)
            classes = "mini-today " if day_key == today else ""
            classes += "mini-outside " if day.month != month else ""
            classes += "sunday" if idx == 0 else ""
            dot = f'<small>{len(items)}건</small>' if items else ""
            pieces.append(f'<td class="{classes}" title="{title}">{day.day}{dot}</td>')
        pieces.append("</tr>")
    pieces.append("</tbody></table></div>")
    st.markdown("".join(pieces), unsafe_allow_html=True)


@st.fragment(run_every="5s")
def live_korea_clock():
    """브라우저 iframe 없이 서버에서 5초마다 시간을 갱신합니다."""
    current = now_kst()
    with st.container(border=True):
        st.caption("KOREA STANDARD TIME")
        weekdays = "월화수목금토일"
        st.markdown(
            f"### {current.year}년 {current.month}월 {current.day}일 "
            f"({weekdays[current.weekday()]})"
        )
        st.markdown(f"**{current:%H:%M:%S}**")
