import streamlit as st
import requests
import os

# ── Config ──────────────────────────────────────────────────────────────────
API_BASE = os.getenv("API_BASE_URL", "http://localhost:5000")
APP_VERSION = "v6"

st.set_page_config(
    page_title="Task Manager",
    page_icon="✅",
    layout="centered",
)

# ── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
    <style>
        .version-badge {
            position: fixed;
            bottom: 1rem;
            right: 1rem;
            background-color: #FF4B4B;
            color: white;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: bold;
            z-index: 9999;
        }
        .task-card {
            border-radius: 8px;
            padding: 0.5rem;
        }
        .header-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
    </style>
    <div class="version-badge">""" + APP_VERSION + """</div>
""", unsafe_allow_html=True)

# ── Helpers ──────────────────────────────────────────────────────────────────

def api_get(path: str):
    try:
        r = requests.get(f"{API_BASE}{path}", timeout=5)
        r.raise_for_status()
        return r.json(), None
    except requests.exceptions.ConnectionError:
        return None, "Cannot reach the API. Is it running?"
    except requests.exceptions.HTTPError as e:
        return None, str(e)


def api_post(path: str, payload: dict):
    try:
        r = requests.post(f"{API_BASE}{path}", json=payload, timeout=5)
        r.raise_for_status()
        return r.json(), None
    except requests.exceptions.ConnectionError:
        return None, "Cannot reach the API. Is it running?"
    except requests.exceptions.HTTPError as e:
        return None, e.response.json().get("error", str(e))


def api_delete(path: str):
    try:
        r = requests.delete(f"{API_BASE}{path}", timeout=5)
        r.raise_for_status()
        return r.json(), None
    except requests.exceptions.ConnectionError:
        return None, "Cannot reach the API. Is it running?"
    except requests.exceptions.HTTPError as e:
        return None, e.response.json().get("error", str(e))


# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ Settings")
    st.caption(f"API: `{API_BASE}`")
    st.caption(f"Version: `{APP_VERSION}`")

    health_data, err = api_get("/health")
    if health_data:
        st.success("API is **healthy** ✅")
        st.caption(f"Checked at: {health_data.get('timestamp', '')}")
    else:
        st.error(f"API unreachable ❌\n\n{err}")

    if st.button("🔄 Refresh"):
        st.rerun()

# ── Header ────────────────────────────────────────────────────────────────────
col_title, col_badge = st.columns([5, 1])
with col_title:
    st.title("✅ Task Manager")
with col_badge:
    st.markdown(f"<br><span style='background:#FF4B4B;color:white;padding:3px 9px;border-radius:10px;font-size:13px;font-weight:bold'>{APP_VERSION}</span>", unsafe_allow_html=True)

st.caption("A simple task tracker powered by Flask + Streamlit.")
st.divider()

# ── Stats row ─────────────────────────────────────────────────────────────────
data, _ = api_get("/tasks")
total = data["count"] if data else 0
done  = sum(1 for t in data["tasks"] if t["done"]) if data else 0
pending = total - done

col1, col2, col3 = st.columns(3)
col1.metric("Total Tasks", total)
col2.metric("Completed", done)
col3.metric("Pending", pending)

st.divider()

# ── Create task ───────────────────────────────────────────────────────────────
st.subheader("➕ Add a New Task")

with st.form("create_task_form", clear_on_submit=True):
    title       = st.text_input("Title *", placeholder="e.g. Buy groceries")
    description = st.text_area("Description", placeholder="Optional details…", height=80)
    priority    = st.selectbox("Priority", ["🟢 Low", "🟡 Medium", "🔴 High"])
    submitted   = st.form_submit_button("Create Task", use_container_width=True)

if submitted:
    if not title.strip():
        st.warning("Title is required.")
    else:
        result, err = api_post("/tasks", {
            "title": title.strip(),
            "description": f"[{priority}] {description.strip()}" if description.strip() else f"[{priority}]",
        })
        if result:
            st.success(f"Task **#{result['id']}** created: *{result['title']}*")
            st.rerun()
        else:
            st.error(f"Failed to create task: {err}")

st.divider()

# ── Task list ─────────────────────────────────────────────────────────────────
st.subheader("📋 All Tasks")

# Re-fetch after potential creation
data, err = api_get("/tasks")

if err:
    st.error(err)
elif data and data["count"] == 0:
    st.info("No tasks yet. Add one above!")
else:
    tasks = data["tasks"]

    # Search / filter
    search = st.text_input("🔍 Search tasks", placeholder="Filter by title…")
    if search:
        tasks = [t for t in tasks if search.lower() in t["title"].lower()]

    st.caption(f"Showing {len(tasks)} of {data['count']} task(s)")

    for task in tasks:
        with st.container(border=True):
            col_info, col_btn = st.columns([5, 1])

            with col_info:
                status_icon = "✅" if task["done"] else "🔲"
                st.markdown(f"**{status_icon} #{task['id']} — {task['title']}**")
                if task["description"]:
                    st.caption(task["description"])
                st.caption(f"Created: {task['created_at']}")

            with col_btn:
                if st.button("🗑️", key=f"del_{task['id']}", help="Delete this task"):
                    result, err = api_delete(f"/tasks/{task['id']}")
                    if result:
                        st.success(f"Task #{task['id']} deleted.")
                        st.rerun()
                    else:
                        st.error(err)
