"""홈 대시보드와 오늘의 업무 브리핑."""
from datetime import date, timedelta

import streamlit as st
from aivle.core import (now_kst, load_tasks, save_setting, load_task_presets,
                        create_task_from_preset, delete_task_preset, set_task_done)
from aivle.widgets import (task_editor, task_delete_dialog, task_preset_editor, live_korea_clock,
                           CITIES, get_weather, weather_description, render_mini_calendar)


def filter_completed_tasks(tasks, period="이번 주", reference=None, keyword=""):
    """실제 완료일 기준 필터. v4에서 완료된 업무는 기존 기한을 대체 기준으로 사용합니다."""
    today = reference or now_kst().date()
    keyword = (keyword or "").strip().casefold()
    beginning = (today - timedelta(days=today.weekday())
                 if period in ("이번 주", "주별") else today.replace(day=1))
    next_month = (today.replace(year=today.year + 1, month=1, day=1)
                  if today.month == 12 else today.replace(month=today.month + 1, day=1))
    end = (beginning + timedelta(days=7) if period in ("이번 주", "주별") else next_month)
    filtered = []
    for task in tasks:
        if not task.get("is_done"):
            continue
        if keyword and keyword not in (task.get("task", "") + " " + task.get("detail", "")).casefold():
            continue
        completed_day = (task.get("completed_at") or "")[:10] or task.get("deadline", "")
        if not completed_day:
            continue
        try:
            if beginning <= date.fromisoformat(completed_day) < end:
                filtered.append({**task, "display_completed_on": completed_day})
        except ValueError:
            continue
    return sorted(filtered, key=lambda task: (task["display_completed_on"], task["task"]), reverse=True)


def render_completed_tasks(tasks, today):
    """완료 업무를 주/월 및 키워드로 확인하고 다시 미완료로 되돌립니다."""
    with st.expander("완료한 업무 · 주별/월별 확인 및 검색", expanded=False):
        st.caption("완료 처리한 날짜를 기준으로 조회합니다. 이전 버전의 기록은 업무 기한을 사용합니다.")
        period_col, date_col = st.columns([1, 2])
        with period_col:
            period = st.selectbox("조회 단위", ["주별", "월별"], key="home_completed_period")
        with date_col:
            anchor = st.date_input("조회할 날짜", value=today, key="home_completed_anchor")
        keyword = st.text_input("완료 업무 검색", placeholder="업무명 또는 설명을 입력하세요",
                                key="home_completed_search")
        completed = filter_completed_tasks(tasks, period, anchor, keyword)
        st.caption(f"검색 결과 · {len(completed)}건")
        if not completed:
            st.info("해당 기간에 완료된 업무가 없습니다.")
        last_day = None
        for task in completed:
            day = task["display_completed_on"]
            if last_day != day:
                st.markdown(f"**{day}**")
                last_day = day
            info, revert = st.columns([5, 1], vertical_alignment="center")
            with info:
                st.markdown("✓ " + task["task"])
                if task.get("detail"):
                    st.caption(task["detail"])
            with revert:
                if st.button("되돌리기", key=f"home_undo_{task['id']}",
                             help="미완료 업무로 다시 표시"):
                    set_task_done(task["id"], False)
                    st.rerun()


def render():
    import html as html_escape_module

    tasks = load_tasks()
    today = now_kst().date()
    today_text = today.isoformat()

    # 완료되지 않은 업무만 브리핑에 표시
    pending_tasks = [
        task for task in tasks
        if not task.get("is_done", False)
    ]

    overdue_tasks = []
    today_tasks = []
    upcoming_tasks = []
    undated_tasks = []

    for task in pending_tasks:

        deadline = task["deadline"]

        if not deadline:
            undated_tasks.append(task)

        elif deadline < today_text:
            overdue_tasks.append(task)

        elif deadline == today_text:
            today_tasks.append(task)

        else:
            upcoming_tasks.append(task)

    def ordered(items):
        weight = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
        return sorted(items, key=lambda item: (item["deadline"] or "9999-12-31",
                                               weight.get(item.get("urgency"), 2),
                                               item["time"] or ""))

    st.markdown(
        """
        <div class="aivle-hero">
            <h2>좋은 하루예요, 김대리님.</h2>
            <p>
                오늘 처리할 업무부터 다가오는 일정까지,
                에이블이 함께 확인해 드릴게요.
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )

    with st.popover(
        "홈 위젯 설정",
        icon=":material/tune:"
    ):

        for key, label in [
            ("widget_clock", "날짜와 시간"),
            ("widget_weather", "날씨"),
            ("widget_briefing", "업무 브리핑"),
            ("widget_calendar", "미니 캘린더")
        ]:

            st.checkbox(
                label, key=key,
                on_change=lambda setting=key: save_setting(
                    setting, "1" if st.session_state[setting] else "0"
                )
            )

    if st.session_state.widget_briefing:

        brief_title, brief_add = st.columns([5, 1.3], vertical_alignment="center")
        with brief_title:
            st.subheader("오늘의 업무 브리핑")
        with brief_add:
            if st.button("업무 추가", icon=":material/add:", key="home_task_add",
                         type="primary", use_container_width=True):
                task_editor()

        with st.expander("상시 업무 프리셋 · 자주 하는 업무 바로 등록", expanded=False):
            st.caption("반복적으로 수행하는 업무를 저장해두고 필요할 때 오늘 일정으로 추가합니다.")
            if st.button("+ 상시 업무 프리셋 만들기", key="home_preset_new"):
                task_preset_editor()
            presets = load_task_presets()
            if not presets:
                st.caption("등록된 프리셋이 없습니다.")
            for preset in presets:
                row_title, row_add, row_delete = st.columns([4, 2, 1])
                with row_title:
                    st.markdown(f"**{html_escape_module.escape(preset['title'])}**")
                    if preset["detail"]:
                        st.caption(preset["detail"])
                with row_add:
                    if st.button("오늘 업무로 추가", key=f"add_preset_{preset['id']}"):
                        if create_task_from_preset(preset["id"], today_text):
                            st.rerun()
                        else:
                            st.info("오늘 동일한 이름의 업무가 이미 등록돼 있습니다.")
                with row_delete:
                    with st.popover("🗑", help="프리셋 삭제"):
                        if st.button("프리셋 삭제 확인", key=f"delete_preset_{preset['id']}"):
                            delete_task_preset(preset["id"])
                            st.rerun()

        st.caption(
            "완료하지 않은 업무를 기한별로 정리했습니다."
        )

        a, b, c = st.columns(3)
        a.metric("오늘 처리할 업무", len(today_tasks))
        b.metric("다가오는 업무", len(upcoming_tasks))
        c.metric("전체 미완료 업무", len(pending_tasks))

        render_completed_tasks(tasks, today)

        if not pending_tasks:
            st.success("등록된 미완료 업무가 없습니다.")
        else:

            groups = [
                ("오늘의 업무", ordered(today_tasks)),
                ("다가오는 일정", ordered(upcoming_tasks)),
                ("기한이 지난 업무", ordered(overdue_tasks)),
                ("기한 미정 업무", ordered(undated_tasks))
            ]

            for group_name, group_tasks in groups:

                if not group_tasks:
                    continue

                st.markdown(
                    f"#### {group_name} · {len(group_tasks)}건"
                )

                for task in group_tasks:

                    title = html_escape_module.escape(
                        task["task"]
                    )

                    deadline = (
                        task["deadline"]
                        if task["deadline"]
                        else "기한 미정"
                    )

                    if task["time"]:
                        deadline += (
                            " · " + task["time"]
                        )

                    detail = (
                        html_escape_module.escape(
                            task["detail"]
                        )
                        if task["detail"]
                        else ""
                    )

                    urgency = task.get("urgency", "normal")
                    urgency = urgency if urgency in ("urgent", "high", "normal", "low") else "normal"
                    countdown = ""
                    if task["deadline"]:
                        days_left = (date.fromisoformat(task["deadline"]) - today).days
                        if 0 <= days_left <= 2:
                            countdown = " · ⏳ " + ("오늘 마감" if days_left == 0 else f"D-{days_left}")
                    emphasized = " deadline-soon" if countdown else ""

                    card_key = f"briefing_{urgency}_{task['id'].replace('-', '_')}"
                    if emphasized:
                        card_key += "_soon"
                    with st.container(border=True, key=card_key):
                        description, edit_col, delete_col, done_col = st.columns(
                            [7, 0.8, 0.8, 0.8], vertical_alignment="center", gap="small"
                        )
                        with description:
                            st.markdown(
                                f'<div class="briefing-card-content">'
                                f'<strong>{title}{countdown}</strong>'
                                f'<span>{deadline}{(" · " + detail) if detail else ""}</span>'
                                f'</div>', unsafe_allow_html=True
                            )
                        with edit_col:
                            if st.button("✏️", key=f"home_edit_{task['id']}",
                                         help="업무 편집", use_container_width=True):
                                task_editor(task["id"])
                        with delete_col:
                            if st.button("🗑️", key=f"home_del_{task['id']}",
                                         help="업무 삭제", use_container_width=True):
                                task_delete_dialog(task["id"])
                        with done_col:
                            if st.button("✓", key=f"home_done_{task['id']}",
                                         help="업무 완료", use_container_width=True):
                                set_task_done(task["id"], True)
                                st.rerun()

    left, right = st.columns(2)

    with left:

        if st.session_state.widget_clock:

            st.subheader("날짜와 시간")

            live_korea_clock()

    with right:

        if st.session_state.widget_weather:

            st.subheader("오늘의 날씨")

            city = st.selectbox(
                "지역",
                list(CITIES.keys()),
                key="weather_city"
            )

            save_setting(
                "weather_city",
                city
            )

            try:

                weather = get_weather(city)

                st.metric(
                    f"{city} · "
                    f"{weather_description(weather['weather_code'])}",
                    f"{weather['temperature_2m']}°C"
                )

                st.caption(
                    f"체감 {weather['apparent_temperature']}°C"
                    f" · 습도 {weather['relative_humidity_2m']}%"
                    " · Open-Meteo 제공"
                )

            except Exception:
                st.info(
                    "현재 날씨 정보를 불러올 수 없습니다."
                )

    if st.session_state.widget_calendar:
        st.divider()
        top_left, top_right = st.columns([4, 1])
        with top_left:
            st.subheader(f"미니 캘린더 · {today.year}년 {today.month}월")
        with top_right:
            if st.button("내 일정", icon=":material/calendar_month:", key="home_go_calendar"):
                st.query_params["view"] = "calendar"
                st.rerun()
        render_mini_calendar(today.year, today.month, tasks)
