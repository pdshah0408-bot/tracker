"""
GATE CSE 2027 Preparation Tracker
----------------------------------
Log daily study hours, track subject-wise progress against your roadmap,
and see whether your current pace is on track to hit your deadlines.

Run with:
    pip install streamlit pandas plotly
    streamlit run gate_tracker.py

Your data is stored locally in gate_tracker.db (SQLite), in the same folder
as this script. Nothing leaves your machine.
"""

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
DB_PATH = Path(__file__).parent / "gate_tracker.db"

ACTIVITY_TYPES = [
    "Lecture", "Notes", "Practice Problems", "PYQs", "Revision",
    "Mock Test", "Other",
]

STATUS_OPTIONS = ["Not Started", "In Progress", "Completed"]

# Default roadmap, seeded into the DB the first time the app runs.
# Edit dates/hours later from the Settings tab if your real pace differs.
DEFAULT_SUBJECTS = [
    # name, sort_order, start_date, deadline, est_hours
    ("C Programming",                         1,  "2026-06-01", "2026-06-30",  30),
    ("Data Structures",                       2,  "2026-07-01", "2026-07-20",  70),
    ("Discrete Mathematics",                  3,  "2026-07-21", "2026-08-07",  50),
    ("Engineering Mathematics",                4,  "2026-08-08", "2026-08-27",  65),
    ("Digital Logic",                         5,  "2026-08-28", "2026-09-09",  40),
    ("Computer Organization & Architecture",  6,  "2026-09-10", "2026-09-30",  60),
    ("Algorithms",                            7,  "2026-10-01", "2026-10-17",  55),
    ("Operating Systems",                     8,  "2026-10-18", "2026-11-10",  65),
    ("DBMS",                                  9,  "2026-11-11", "2026-11-28",  50),
    ("Computer Networks",                     10, "2026-11-29", "2026-12-14",  50),
    ("Theory of Computation",                 11, "2026-12-15", "2026-12-31",  50),
    ("Compiler Design",                       12, "2027-01-01", "2027-01-07",  25),
    ("Second Revision (All Subjects)",        13, "2027-01-08", "2027-01-22",  80),
    ("Mocks + Final Taper",                   14, "2027-01-23", "2027-02-06", 100),
]

# Phase-wise expected daily hours, used to judge whether today's pace is on track.
PHASES = [
    ("2026-06-21", "2026-07-14", 3.5, "Foundation Phase"),
    ("2026-07-15", "2026-09-30", 4.5, "Build-up Phase"),
    ("2026-10-01", "2026-12-31", 5.5, "Core Phase"),
    ("2027-01-01", "2027-02-06", 7.5, "Revision & Mock Phase"),
]

CORE_SUBJECT_NAMES = [
    s[0] for s in DEFAULT_SUBJECTS
    if s[0] not in ("Second Revision (All Subjects)", "Mocks + Final Taper")
]

# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            sort_order INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            deadline TEXT NOT NULL,
            est_hours REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'Not Started'
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date TEXT NOT NULL,
            subject TEXT NOT NULL,
            hours REAL NOT NULL,
            activity TEXT NOT NULL,
            topic TEXT,
            notes TEXT,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM subjects")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO subjects (name, sort_order, start_date, deadline, est_hours) "
            "VALUES (?, ?, ?, ?, ?)",
            DEFAULT_SUBJECTS,
        )
        conn.commit()

    cur.execute("SELECT value FROM settings WHERE key = 'exam_date'")
    if cur.fetchone() is None:
        cur.execute("INSERT INTO settings (key, value) VALUES ('exam_date', '2027-02-06')")
        conn.commit()

    conn.close()


def get_setting(key, default=None):
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row[0] if row else default


def set_setting(key, value):
    conn = get_conn()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def get_subjects_df():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM subjects ORDER BY sort_order", conn)
    conn.close()
    return df


def get_logs_df():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM logs ORDER BY log_date DESC, id DESC", conn)
    conn.close()
    if not df.empty:
        df["log_date"] = pd.to_datetime(df["log_date"]).dt.date
    return df


def add_log(log_date, subject, hours, activity, topic, notes):
    conn = get_conn()
    conn.execute(
        "INSERT INTO logs (log_date, subject, hours, activity, topic, notes, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (str(log_date), subject, hours, activity, topic, notes, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def delete_log(log_id):
    conn = get_conn()
    conn.execute("DELETE FROM logs WHERE id = ?", (log_id,))
    conn.commit()
    conn.close()


def update_subject_status(name, status):
    conn = get_conn()
    conn.execute("UPDATE subjects SET status = ? WHERE name = ?", (status, name))
    conn.commit()
    conn.close()


def update_subject_full(name, start_date, deadline, est_hours, status):
    conn = get_conn()
    conn.execute(
        "UPDATE subjects SET start_date = ?, deadline = ?, est_hours = ?, status = ? "
        "WHERE name = ?",
        (str(start_date), str(deadline), float(est_hours), status, name),
    )
    conn.commit()
    conn.close()


def reset_logs():
    conn = get_conn()
    conn.execute("DELETE FROM logs")
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# Calculation helpers
# --------------------------------------------------------------------------

def hours_by_subject(logs_df):
    if logs_df.empty:
        return {}
    return logs_df.groupby("subject")["hours"].sum().to_dict()


def current_streak(logs_df):
    if logs_df.empty:
        return 0
    log_dates = set(logs_df["log_date"].unique())
    today = date.today()
    cursor_date = today if today in log_dates else today - timedelta(days=1)
    streak = 0
    while cursor_date in log_dates:
        streak += 1
        cursor_date -= timedelta(days=1)
    return streak


def expected_daily_hours_today():
    today = date.today()
    for start, end, hrs, label in PHASES:
        if date.fromisoformat(start) <= today <= date.fromisoformat(end):
            return hrs, label
    return PHASES[-1][2], PHASES[-1][3]


def recent_pace(logs_df, days=14):
    """Average hours/day over the last `days` calendar days (skipped days count as 0)."""
    if logs_df.empty:
        return 0.0, 0
    cutoff = date.today() - timedelta(days=days)
    recent = logs_df[logs_df["log_date"] >= cutoff]
    n_days_with_data = recent["log_date"].nunique()
    if n_days_with_data == 0:
        return 0.0, 0
    total_hours = recent["hours"].sum()
    first_log_date = logs_df["log_date"].min()
    window_days = min(days, (date.today() - first_log_date).days + 1)
    window_days = max(window_days, 1)
    return total_hours / window_days, n_days_with_data


def project_completion(remaining_hours, pace_hours_per_day):
    if remaining_hours <= 0:
        return date.today()
    if pace_hours_per_day <= 0:
        return None
    days_needed = remaining_hours / pace_hours_per_day
    return date.today() + timedelta(days=round(days_needed))


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------

st.set_page_config(page_title="GATE CSE 2027 Tracker", page_icon="📚", layout="wide")
init_db()

subjects_df = get_subjects_df()
logs_df = get_logs_df()
hours_done = hours_by_subject(logs_df)

exam_date = date.fromisoformat(get_setting("exam_date", "2027-02-06"))
days_to_exam = (exam_date - date.today()).days

total_planned = subjects_df["est_hours"].sum()
total_logged = logs_df["hours"].sum() if not logs_df.empty else 0.0


def subject_pct(row):
    logged = hours_done.get(row["name"], 0.0)
    if row["status"] == "Completed":
        return 100.0
    if row["est_hours"] <= 0:
        return 0.0
    return min(100.0, 100.0 * logged / row["est_hours"])


subjects_df["logged_hours"] = subjects_df["name"].map(lambda n: hours_done.get(n, 0.0))
subjects_df["pct_complete"] = subjects_df.apply(subject_pct, axis=1)
overall_pct = subjects_df["pct_complete"].mean() if not subjects_df.empty else 0.0

streak = current_streak(logs_df)
exp_hours_today, phase_label = expected_daily_hours_today()
pace14, days_with_data14 = recent_pace(logs_df, days=14)

# ---------------- Sidebar ----------------
with st.sidebar:
    st.title("📚 GATE CSE 2027")
    st.metric("Days to exam", days_to_exam if days_to_exam >= 0 else "Exam day passed")
    st.metric("Overall progress", f"{overall_pct:.1f}%")
    st.metric("Current streak", f"{streak} day(s)")
    st.metric("Current phase", phase_label)
    st.caption(f"Expected pace this phase: **{exp_hours_today} hrs/day**")
    st.progress(min(1.0, overall_pct / 100))
    st.caption(f"Total logged: {total_logged:.1f} / {total_planned:.0f} hrs")

st.title("GATE CSE 2027 Preparation Tracker")

tab_log, tab_progress, tab_analytics, tab_settings = st.tabs(
    ["📝 Daily Log", "📊 Subject Progress", "📈 Analytics & Pace", "⚙️ Settings"]
)

# ---------------- Daily Log ----------------
with tab_log:
    st.subheader("Log today's work")
    not_completed = subjects_df[subjects_df["status"] != "Completed"]["name"].tolist()
    subject_options = not_completed if not_completed else subjects_df["name"].tolist()

    with st.form("log_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            log_date = st.date_input("Date", value=date.today())
            subject = st.selectbox("Subject", subject_options)
            hours = st.number_input("Hours studied", min_value=0.0, max_value=16.0,
                                     step=0.5, value=2.0)
        with c2:
            activity = st.selectbox("Activity type", ACTIVITY_TYPES)
            topic = st.text_input("Topic (optional)", placeholder="e.g. Binary Search Trees")
        notes = st.text_area("Notes (optional)", placeholder="What went well, what didn't...")
        submitted = st.form_submit_button("Add entry", width="stretch")
        if submitted:
            if hours <= 0:
                st.warning("Enter hours greater than 0.")
            else:
                add_log(log_date, subject, hours, activity, topic, notes)
                st.success(f"Logged {hours} hrs of {activity} — {subject}")
                st.rerun()

    st.divider()
    st.subheader("Recent entries")
    if logs_df.empty:
        st.info("No entries yet. Add your first one above.")
    else:
        recent = logs_df.head(15)
        header = st.columns([2, 3, 1.5, 2, 3, 1])
        for h, t in zip(header, ["Date", "Subject", "Hours", "Activity", "Topic", ""]):
            h.markdown(f"**{t}**")
        for _, row in recent.iterrows():
            cols = st.columns([2, 3, 1.5, 2, 3, 1])
            cols[0].write(str(row["log_date"]))
            cols[1].write(row["subject"])
            cols[2].write(f"{row['hours']} hrs")
            cols[3].write(row["activity"])
            cols[4].write(row["topic"] or "—")
            if cols[5].button("🗑️", key=f"del_{row['id']}"):
                delete_log(row["id"])
                st.rerun()

# ---------------- Subject Progress ----------------
with tab_progress:
    st.subheader("Subject-wise progress")
    today = date.today()
    for _, row in subjects_df.iterrows():
        deadline = date.fromisoformat(row["deadline"])
        days_left = (deadline - today).days
        if row["status"] == "Completed":
            badge = "✅ Completed"
        elif days_left < 0:
            badge = f"🔴 {abs(days_left)} day(s) overdue"
        elif days_left <= 3:
            badge = f"🟡 {days_left} day(s) left"
        else:
            badge = f"🟢 {days_left} day(s) left"

        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown(f"**{row['name']}**  ·  {badge}")
                st.progress(
                    min(1.0, row["pct_complete"] / 100),
                    text=f"{row['logged_hours']:.1f} / {row['est_hours']:.0f} hrs "
                         f"({row['pct_complete']:.0f}%)",
                )
                st.caption(f"Deadline: {row['deadline']}")
            with c2:
                new_status = st.selectbox(
                    "Status", STATUS_OPTIONS,
                    index=STATUS_OPTIONS.index(row["status"]),
                    key=f"status_{row['id']}",
                    label_visibility="collapsed",
                )
                if new_status != row["status"]:
                    update_subject_status(row["name"], new_status)
                    st.rerun()

# ---------------- Analytics & Pace ----------------
with tab_analytics:
    st.subheader("Where you actually stand")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total hours logged", f"{total_logged:.1f}")
    c2.metric("Avg hrs/day (last 14d)", f"{pace14:.2f}")
    c3.metric("Expected hrs/day now", f"{exp_hours_today}")
    pace_delta = pace14 - exp_hours_today
    c4.metric("Pace vs expected", f"{pace14:.2f} hrs/day", delta=f"{pace_delta:+.2f}")

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=overall_pct,
        title={"text": "Overall Syllabus Progress"},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": "#2563eb"},
            "steps": [
                {"range": [0, 33], "color": "#fee2e2"},
                {"range": [33, 66], "color": "#fef9c3"},
                {"range": [66, 100], "color": "#dcfce7"},
            ],
        },
    ))
    fig.update_layout(height=300, margin=dict(t=50, b=10))
    st.plotly_chart(fig, width="stretch")

    st.divider()
    st.subheader("⏱️ Do you need to extend your timeline?")

    core_df = subjects_df[subjects_df["name"].isin(CORE_SUBJECT_NAMES)]
    core_remaining_series = (core_df["est_hours"] - core_df["logged_hours"]).clip(lower=0)
    core_remaining = core_remaining_series[core_df["status"] != "Completed"].sum()

    last_core_deadline = date.fromisoformat(
        subjects_df.loc[subjects_df["name"] == "Compiler Design", "deadline"].values[0]
    )
    days_left_core = (last_core_deadline - today).days

    if pace14 <= 0:
        st.warning(
            "Not enough recent log data to project a pace yet. Log at least a "
            "few days this week to get a real projection."
        )
    elif days_left_core <= 0:
        st.error(
            f"Your core-syllabus target date ({last_core_deadline.strftime('%d %b %Y')}) "
            f"has already passed in the plan. Either update your deadlines in Settings "
            f"to reflect reality, or treat remaining core subjects as urgent."
        )
    else:
        projected = project_completion(core_remaining, pace14)
        required_pace = core_remaining / days_left_core

        cc1, cc2, cc3 = st.columns(3)
        cc1.metric("Hours left (core syllabus)", f"{core_remaining:.0f}")
        cc2.metric(f"Required pace to hit {last_core_deadline.strftime('%d %b')}",
                   f"{required_pace:.2f} hrs/day")
        cc3.metric("Your current pace", f"{pace14:.2f} hrs/day")

        if projected and projected > last_core_deadline:
            extra_days = (projected - last_core_deadline).days
            st.error(
                f"At your current pace, first-pass syllabus completion lands around "
                f"**{projected.strftime('%d %b %Y')}** — about **{extra_days} day(s)** "
                f"past your **{last_core_deadline.strftime('%d %b %Y')}** target. "
                f"This eats directly into your revision buffer.\n\n"
                f"To stay on schedule, raise your pace to **{required_pace:.1f} hrs/day** "
                f"from here on, or accept the slip and compress Second Revision "
                f"and Compiler Design instead."
            )
        elif projected:
            spare_days = (last_core_deadline - projected).days
            st.success(
                f"At your current pace, you're projected to finish the core syllabus "
                f"around **{projected.strftime('%d %b %Y')}** — "
                f"**{spare_days} day(s) ahead** of your "
                f"{last_core_deadline.strftime('%d %b %Y')} target. That extra time is "
                f"a gift to your revision phase — don't spend it slacking off."
            )

    st.divider()
    st.subheader("Hours logged per day")
    if logs_df.empty:
        st.info("Log some entries to see your trend.")
    else:
        daily = logs_df.groupby("log_date")["hours"].sum().reset_index().sort_values("log_date")
        fig2 = go.Figure()
        fig2.add_bar(x=daily["log_date"], y=daily["hours"], name="Hours studied",
                     marker_color="#3b82f6")
        fig2.add_hline(y=exp_hours_today, line_dash="dash", line_color="red",
                        annotation_text=f"Expected pace ({exp_hours_today} hrs)")
        fig2.update_layout(height=350, xaxis_title="Date", yaxis_title="Hours")
        st.plotly_chart(fig2, width="stretch")

        st.subheader("Hours by activity type")
        by_activity = logs_df.groupby("activity")["hours"].sum().reset_index()
        fig3 = go.Figure(go.Pie(labels=by_activity["activity"], values=by_activity["hours"],
                                 hole=0.45))
        fig3.update_layout(height=350)
        st.plotly_chart(fig3, width="stretch")

# ---------------- Settings ----------------
with tab_settings:
    st.subheader("Exam date")
    new_exam_date = st.date_input("GATE exam date", value=exam_date)
    if st.button("Save exam date"):
        set_setting("exam_date", str(new_exam_date))
        st.success("Saved.")
        st.rerun()

    st.divider()
    st.subheader("Edit subject plan")
    st.caption("Adjust deadlines or hour estimates if your real pace differs from the plan.")

    display_df = subjects_df[["name", "start_date", "deadline", "est_hours", "status"]].copy()
    display_df["start_date"] = pd.to_datetime(display_df["start_date"]).dt.date
    display_df["deadline"] = pd.to_datetime(display_df["deadline"]).dt.date

    edited = st.data_editor(
        display_df,
        column_config={
            "start_date": st.column_config.DateColumn("Start date"),
            "deadline": st.column_config.DateColumn("Deadline"),
            "est_hours": st.column_config.NumberColumn("Est. hours", min_value=0, step=5),
            "status": st.column_config.SelectboxColumn("Status", options=STATUS_OPTIONS),
        },
        disabled=["name"],
        hide_index=True,
        width="stretch",
        key="subject_editor",
    )
    if st.button("Save subject plan changes"):
        for _, r in edited.iterrows():
            update_subject_full(r["name"], r["start_date"], r["deadline"],
                                 r["est_hours"], r["status"])
        st.success("Subject plan updated.")
        st.rerun()

    st.divider()
    st.subheader("Data")
    if not logs_df.empty:
        csv = logs_df.to_csv(index=False).encode("utf-8")
        st.download_button("Download logs as CSV", csv, "gate_logs.csv", "text/csv")
    st.caption(f"Database file: `{DB_PATH}`")

    with st.expander("⚠️ Danger zone"):
        confirm = st.checkbox("I understand this deletes all logged entries permanently")
        if st.button("Clear all logs", disabled=not confirm):
            reset_logs()
            st.success("All logs cleared.")
            st.rerun()