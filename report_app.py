import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG: your Google Sheet
SHEET_ID = "1oEJNDoyP80Sy1cOOn6dvgZaevKJxiSu3Z5AEce8WInE"   # the long ID between /d/ and /edit in your sheet URL
SHEET_NAME = "Sheet1"     # change if your first tab has a different name
APP_TITLE = "Team Orders – Reports"
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title=APP_TITLE, layout="wide")

# ------------------------- Auth & Users -------------------------
USERS = {
    "admin": {"password": "admin123", "role": "admin"},
    "wolf1": {"password": "wolfpass1", "role": "team"},
    "wolf2": {"password": "wolfpass2", "role": "team"},
    # add more team users here
}

def login_ui():
    st.sidebar.header("Login")
    u = st.sidebar.text_input("Username")
    p = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Login"):
        user = USERS.get(u)
        if user and user["password"] == p:
            st.session_state["auth"] = {"username": u, "role": user["role"]}
            st.rerun()
        else:
            st.sidebar.error("Invalid username or password")

def ensure_logged_in():
    if "auth" not in st.session_state:
        login_ui()
        st.stop()

def logout_button():
    if st.sidebar.button("Logout"):
        st.session_state.pop("auth", None)
        st.rerun()

# --------------------- Google Sheets Client ---------------------
def get_gsheet():
    """Authorize via Streamlit Secrets and return a gspread Worksheet."""
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]

    # Expecting secrets as a TOML table: [gcp_service_account] ...fields...
    svc_info = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(svc_info, scope)
    client = gspread.authorize(creds)

    sh = client.open_by_key(SHEET_ID)
    try:
        ws = sh.worksheet(SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=SHEET_NAME, rows=1000, cols=20)

    # Ensure header row
    header = ["Timestamp","User","TeamMember","Client","Store","OrderID","Amount","Notes","OrderDate"]
    values = ws.get_all_values()
    if not values:
        ws.append_row(header)
    else:
        first_row = ws.row_values(1)
        if first_row != header:
            st.warning("Sheet header differs. Expected: " + ", ".join(header))

    return ws

@st.cache_data(ttl=30)
def load_dataframe():
    ws = get_gsheet()
    records = ws.get_all_records()
    df = pd.DataFrame(records)
    if df.empty:
        df = pd.DataFrame(columns=["Timestamp","User","TeamMember","Client","Store","OrderID","Amount","Notes","OrderDate"])
    if "Amount" in df.columns:
        df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0)
    return df

def append_row(row_list):
    ws = get_gsheet()
    ws.append_row(row_list)

# --------------------------- UI Blocks --------------------------
def team_reporter(username):
    st.title("📝 Team Reporter")
    st.caption(f"Logged in as **{username}**")

    # Persist team member display name per user
    key_tm = f"tm_name_{username}"
    team_member = st.text_input("Team member (display name)", st.session_state.get(key_tm, username))
    st.session_state[key_tm] = team_member

    colA, colB, colC = st.columns(3)
    with colA:
        order_date = st.date_input("Order date", value=date.today())
    with colB:
        client = st.text_input("Client")
    with colC:
        store = st.text_input("Store")

    order_id = st.text_input("Order ID")
    amount = st.number_input("Amount", min_value=0.0, step=0.01)
    notes = st.text_area("Notes", placeholder="Optional notes…")

    if st.button("Submit Order"):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_row = [
            ts, username, team_member, client, store, order_id, float(amount), notes,
            order_date.strftime("%Y-%m-%d")
        ]
        try:
            append_row(new_row)
            st.success("✅ Order submitted.")
            st.experimental_rerun()
        except Exception as e:
            st.error(f"Failed to submit: {e}")

    st.divider()
    st.subheader("My recent submissions")
    df = load_dataframe()
    mine = df[df["User"] == username].sort_values("Timestamp", ascending=False).head(100)
    st.dataframe(mine, use_container_width=True)

def manager_dashboard():
    st.title("📊 Manager Dashboard (Admin)")
    df = load_dataframe()

    if df.empty:
        st.info("No reports yet.")
        return

    # Filters
    with st.expander("Filters", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        users = ["(All)"] + sorted(df["User"].dropna().unique().tolist())
        team_members = ["(All)"] + sorted(df["TeamMember"].dropna().unique().tolist())
        selected_user = c1.selectbox("Filter by Username", users)
        selected_tm = c2.selectbox("Filter by Team Member", team_members)
        date_from = c3.date_input("From", value=None)
        date_to = c4.date_input("To", value=None)

    f = df.copy()
    if selected_user != "(All)":
        f = f[f["User"] == selected_user]
    if selected_tm != "(All)":
        f = f[f["TeamMember"] == selected_tm]
    if date_from:
        f = f[pd.to_datetime(f["OrderDate"], errors="coerce") >= pd.to_datetime(date_from)]
    if date_to:
        f = f[pd.to_datetime(f["OrderDate"], errors="coerce") <= pd.to_datetime(date_to)]

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Orders", f"{len(f):,}")
    col2.metric("Total Amount", f"${f['Amount'].sum():,.2f}")
    col3.metric("Unique Clients", f["Client"].nunique())
    col4.metric("Team Members", f["TeamMember"].nunique())

    st.divider()
    cA, cB = st.columns(2)
    with cA:
        st.subheader("By Team Member")
        if not f.empty:
            st.bar_chart(f.groupby("TeamMember")["Amount"].sum().sort_values(ascending=False))
    with cB:
        st.subheader("By Client")
        if not f.empty:
            st.bar_chart(f.groupby("Client")["Amount"].sum().sort_values(ascending=False))

    st.subheader("All Orders")
    st.dataframe(f.sort_values("Timestamp", ascending=False), use_container_width=True)

    # Export
    st.download_button("⬇ Download CSV", f.to_csv(index=False).encode("utf-8"),
                       "all_reports.csv", "text/csv")

# --------------------------- Router -----------------------------
ensure_logged_in()
logout_button()

role = st.session_state["auth"]["role"]
username = st.session_state["auth"]["username"]

if role == "admin":
    manager_dashboard()
else:
    team_reporter(username)
