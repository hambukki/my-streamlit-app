"""월별 캘린더 및 등록 업무 관리."""
import calendar
from datetime import datetime

import streamlit as st
from aivle.core import now_kst, load_tasks
from aivle.widgets import task_editor, render_task_actions, task_detail_dialog


def render():
    import html as html_escape_module

    st.title("내 일정")

    st.caption(
        "날짜별로 등록된 업무를 확인하고 "
        "완료 여부를 관리할 수 있습니다."
    )

    if st.button("업무 추가", icon=":material/add:", type="primary", key="calendar_task_add"):
        task_editor()

    year = st.session_state.calendar_year
    month = st.session_state.calendar_month

    def move_month(amount):

        total = (
            st.session_state.calendar_year * 12
            + st.session_state.calendar_month
            - 1
            + amount
        )

        st.session_state.calendar_year = total // 12
        st.session_state.calendar_month = total % 12 + 1

    c1, c2, center, c3, c4 = st.columns(
        [1, 1, 4, 1, 1]
    )

    with c1:

        if st.button(
            "«",
            help="이전 연도"
        ):
            move_month(-12)
            st.rerun()

    with c2:

        if st.button(
            "‹",
            help="이전 달"
        ):
            move_month(-1)
            st.rerun()

    with center:
        with st.popover(f"{year}년 {month}월  ▾", icon=":material/calendar_month:",
                        use_container_width=True):
            st.caption("연도와 월을 선택하면 해당 달로 바로 이동합니다.")
            jump_year = st.selectbox("연도", list(range(2020, 2041)),
                                     index=year - 2020 if 2020 <= year <= 2040 else 6,
                                     key=f"cal_year_picker_{year}_{month}")
            jump_month = st.selectbox("월", list(range(1, 13)), index=month - 1,
                                      key=f"cal_month_picker_{year}_{month}")
            if st.button("선택한 달로 이동", type="primary", key=f"calendar_jump_{year}_{month}"):
                st.session_state.calendar_year = jump_year
                st.session_state.calendar_month = jump_month
                st.rerun()

    with c3:

        if st.button(
            "›",
            help="다음 달"
        ):
            move_month(1)
            st.rerun()

    with c4:

        if st.button(
            "»",
            help="다음 연도"
        ):
            move_month(12)
            st.rerun()

    tasks = load_tasks()

    # 날짜별 업무 묶기
    tasks_by_date = {}

    for task in tasks:

        deadline = task["deadline"]

        if deadline:

            tasks_by_date.setdefault(
                deadline,
                []
            ).append(task)

    cal = calendar.Calendar(
        firstweekday=6
    )

    today_text = now_kst().date().isoformat()

    rows = [
        "<table class='calendar-table'>",
        "<tr>",
        "<th class='sunday'>SUN</th>",
        "<th>MON</th>",
        "<th>TUE</th>",
        "<th>WED</th>",
        "<th>THU</th>",
        "<th>FRI</th>",
        "<th>SAT</th>",
        "</tr>"
    ]

    for week in cal.monthdatescalendar(
        year,
        month
    ):

        rows.append("<tr>")

        for index, day in enumerate(week):

            date_text = day.isoformat()

            classes = []

            if index == 0:
                classes.append("sunday")

            if day.month != month:
                classes.append("other-month")

            if date_text == today_text:
                classes.append("calendar-today")

            day_tasks = tasks_by_date.get(
                date_text,
                []
            )

            event_html = []

            # 달력 한 칸에 일정명 최대 3개 표시
            for task in day_tasks[:3]:

                name = " ".join(
                    task["task"].split()
                )

                short_name = (
                    name[:17] + "…"
                    if len(name) > 17
                    else name
                )

                escaped_name = (
                    html_escape_module.escape(
                        name,
                        quote=True
                    )
                )

                full_description = html_escape_module.escape(
                    f"{name}\n날짜: {date_text}"
                    + (f"\n시간: {task['time']}" if task["time"] else "")
                    + (f"\n설명: {task['detail']}" if task["detail"] else "")
                    + ("\n상태: 완료" if task.get("is_done") else "\n상태: 미완료"),
                    quote=True
                )

                escaped_short = (
                    html_escape_module.escape(
                        short_name
                    )
                )

                done_class = (
                    " done"
                    if task.get("is_done", False)
                    else ""
                )
                urgency = task.get("urgency", "normal")
                urgency = urgency if urgency in ("urgent", "high", "normal", "low") else "normal"

                event_html.append(
                    f'<span class="calendar-event{done_class} urgency-{urgency}" '
                    f'title="{full_description}">'
                    f'<span class="calendar-event-label">{escaped_short}</span>'
                    f'<span class="calendar-tooltip">{full_description}</span>'
                    f'</span>'
                )

            extra_count = len(day_tasks) - 3

            if extra_count > 0:

                event_html.append(
                    f'<span class="calendar-more">'
                    f'+{extra_count}개 더 있음'
                    f'</span>'
                )

            rows.append(
                f'<td class="{" ".join(classes)}">'
                f'<span class="calendar-day">{day.day}</span>'
                + "".join(event_html)
                + "</td>"
            )

        rows.append("</tr>")

    rows.append("</table>")

    st.markdown(
        "".join(rows),
        unsafe_allow_html=True
    )

    st.caption(
        "일정 칸에 마우스를 올리면 자세한 내용을 볼 수 있습니다. "
        "연한 빨강은 긴급, 연한 주황은 높음, 민트는 보통, 연한 파랑은 낮음이며 "
        "회색 취소선은 완료된 업무입니다."
    )

    st.divider()

    # 현재 보고 있는 달에 맞춰 날짜 선택
    default_day = min(
        now_kst().day,
        calendar.monthrange(year, month)[1]
    )

    selected_default = datetime(
        year,
        month,
        default_day
    ).date()

    chosen = st.date_input(
        "업무를 확인할 날짜",
        value=selected_default,
        key=f"calendar_day_{year}_{month}"
    )

    matching = [
        task for task in tasks
        if task["deadline"] == chosen.isoformat()
    ]

    st.subheader(
        f"{chosen:%Y년 %m월 %d일} 업무"
    )

    if not matching:

        st.info(
            "선택한 날짜에 등록된 업무가 없습니다."
        )

    for task in matching:

        with st.container(border=True):

            left, right = st.columns(
                [4, 3]
            )

            with left:

                if task.get("is_done", False):

                    st.markdown(
                        f"~~{task['task']}~~"
                    )

                    st.caption("완료된 업무")

                else:

                    st.markdown(
                        f"**{task['task']}**"
                    )

                    st.caption("진행 또는 예정 업무")

                if task["time"]:
                    st.caption(
                        "시간: " + task["time"]
                    )

                if task["detail"]:
                    st.write(task["detail"])

                if st.button("🔎 업무 상세 팝업", key=f"calendar_detail_{task['id']}"):
                    task_detail_dialog(task["id"])

            with right:
                render_task_actions(task, "calendar")

    # 기한을 지정하지 않은 업무도 확인 가능
    undated_tasks = [
        task for task in tasks
        if not task["deadline"]
    ]

    if undated_tasks:

        st.divider()

        with st.expander(
            f"기한 미정 업무 · {len(undated_tasks)}건",
            expanded=True
        ):

            for task in undated_tasks:

                with st.container(border=True):

                    left, right = st.columns(
                        [4, 3]
                    )

                    with left:

                        if task.get("is_done", False):
                            st.markdown(
                                f"~~{task['task']}~~"
                            )
                        else:
                            st.markdown(
                                f"**{task['task']}**"
                            )

                        if task["detail"]:
                            st.caption(
                                task["detail"]
                            )

                    with right:
                        render_task_actions(task, "calendar_undated")

    # 전체 업무 목록
    with st.expander("전체 등록 업무 보기"):

        if not tasks:
            st.caption(
                "등록된 업무가 없습니다."
            )

        for task in tasks:

            status = (
                "완료"
                if task.get("is_done", False)
                else "미완료"
            )

            st.write(
                f"• [{status}] "
                f"{task['task']} · "
                f"{task['deadline'] or '기한 미정'}"
            )
            with st.container(border=True):
                render_task_actions(task, "calendar_all")
