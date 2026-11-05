"""모든 탭에서 같은 업무 DB를 읽는 좌측 '다가오는 일정' 패널."""
import html

import streamlit as st

from .core import load_tasks, now_kst, set_task_done
from .widgets import task_editor


def sidebar_upcoming_tasks(tasks, today=None, limit=5):
    """날짜 있는 미완료 업무 중 오늘 이후 일정만 날짜·시간순으로 표시."""
    cutoff = (today or now_kst().date()).isoformat()
    selected = [item for item in tasks if not item.get("is_done")
                and item.get("deadline") and item["deadline"] >= cutoff]
    weight = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    return sorted(selected, key=lambda item:
                  (item["deadline"], item.get("time") or "",
                   weight.get(item.get("urgency"), 2), item["task"]))[:limit]


def _tooltip(task):
    lines = [task.get("task", ""),
             "마감: " + (task.get("deadline") or "미정")
             + (" " + task["time"] if task.get("time") else "")]
    if task.get("detail"):
        lines.append("내용: " + task["detail"])
    return html.escape("\n".join(lines), quote=True)


def render_sidebar_upcoming():
    st.markdown('<div class="sidebar-upcoming-head">'
                '<span>다가오는 일정</span><small>UPCOMING</small></div>',
                unsafe_allow_html=True)
    items = sidebar_upcoming_tasks(load_tasks())
    if not items:
        st.caption("예정된 미완료 업무가 없습니다.")
        return

    for item in items:
        key = "sidebar_schedule_" + item["id"].replace("-", "_")
        urgency = item.get("urgency")
        if urgency not in {"urgent", "high", "normal", "low"}:
            urgency = "normal"
        date_label = item["deadline"][5:].replace("-", "/")
        if item.get("time"):
            date_label += " " + item["time"]

        with st.container(key=key):
            # title 속성: 마우스를 올리면 내용·기한 전체를 볼 수 있습니다.
            st.markdown(
                f'<div class="sidebar-schedule-strip urgency-{urgency}" '
                f'title="{_tooltip(item)}" tabindex="0" '
                f'aria-label="{_tooltip(item)}">'
                f'<span class="sidebar-strip-date">{html.escape(date_label)}</span>'
                f'<strong>{html.escape(item["task"])}</strong>'
                '</div>', unsafe_allow_html=True
            )
            done_col, edit_col = st.columns(2, gap="small")
            with done_col:
                if st.button("✓ 완료", key=f"sidebar_done_{item['id']}",
                             use_container_width=True,
                             help="업무 완료로 변경 · 홈/내 일정에 즉시 반영"):
                    set_task_done(item["id"], True)
                    st.rerun()
            with edit_col:
                if st.button("✎ 수정", key=f"sidebar_edit_{item['id']}",
                             use_container_width=True, help="업무 내용 및 기한 수정"):
                    task_editor(item["id"])

    if st.button("전체 일정 보기", key="sidebar_all_tasks",
                 icon=":material/calendar_month:", use_container_width=True):
        st.query_params["view"] = "calendar"
        st.rerun()
