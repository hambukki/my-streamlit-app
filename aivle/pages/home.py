"""홈 대시보드와 오늘의 업무 브리핑."""
import streamlit as st
from aivle.core import now_kst, load_tasks, save_setting
from aivle.widgets import (task_editor, render_task_actions, live_korea_clock,
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
                ("오늘의 업무", today_tasks),
                ("다가오는 일정", upcoming_tasks),
                ("기한이 지난 업무", overdue_tasks),
                ("기한 미정 업무", undated_tasks)
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

                    st.markdown(
                        f"""
                        <div class="briefing-item">
                            <strong>{title}</strong>
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
