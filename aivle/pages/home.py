"""홈 대시보드와 오늘의 업무 브리핑."""
from datetime import date

import streamlit as st
from aivle.core import (now_kst, load_tasks, save_setting, load_task_presets,
                        create_task_from_preset, delete_task_preset)
from aivle.widgets import (task_editor, task_preset_editor, render_task_actions, live_korea_clock,
                           CITIES, get_weather, weather_description, render_mini_calendar)


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

            value = st.checkbox(
                label,
                key=key
            )

            save_setting(
                key,
                "1" if value else "0"
            )

    if st.session_state.widget_briefing:

        st.subheader("오늘의 업무 브리핑")
        if st.button("업무 추가", icon=":material/add:", key="home_task_add"):
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

        if not pending_tasks:
            st.success(
                "등록된 미완료 업무가 없습니다."
            )

        else:

            a, b, c = st.columns(3)

            a.metric(
                "오늘 처리할 업무",
                len(today_tasks)
            )

            b.metric(
                "다가오는 업무",
                len(upcoming_tasks)
            )

            c.metric(
                "전체 미완료 업무",
                len(pending_tasks)
            )

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

                    st.markdown(
                        f"""
                        <div class="briefing-item urgency-{urgency}{emphasized}">
                            <strong>{title}{countdown}</strong>
                            <span>
                                {deadline}
                                {(" · " + detail) if detail else ""}
                            </span>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                    with st.expander("업무 관리", expanded=False):
                        render_task_actions(task, "home")

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
