import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date
import json
import streamlit_authenticator as stauth

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG: your Google Sheet
SHEET_ID = "1oEJNDoyP80Sy1cOOn6dvgZaevKJxiSu3Z5AEce8WInE"   # your sheet ID
ORDERS_SHEET = "Sheet1"                                     # tab for orders
CLIENTS_SHEET = "Clients"                                   # tab for client list
APP_TITLE = "Team Orders – Reports"
EXPECTED_HEADER = ["Timestamp","User","Client","OrderID","Amount","OrderDate"]
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title=APP_TITLE, layout="wide")

# ------------------------- Auth & Users -------------------------
# Accounts: Jerry (admin), Wolf 1/2/3/8/9, King 3
NAMES      = ["Jerry", "Wolf 1", "Wolf 2", "Wolf 3", "Wolf 8", "Wolf 9", "King 3"]
USERNAMES  = ["jerry", "wolf1", "wolf2", "wolf3", "wolf8", "wolf9", "king3"]
PASSWORDS  = [
    "Qa9$gH!7k2@",   # jerry
    "tu8*NMh2!5",    # wolf1
    "Rb4)fKz7^1",    # wolf2
    "xE3@pL9!q6",    # wolf3
    "Jh7$wT2%v8",    # wolf8
    "mN5#cR8&d4",    # wolf9
    "zT6*Ya3@e9",    # king3
]
ROLES = {
    "jerry": "admin",
    "wolf1": "team",
    "wolf2": "team",
    "wolf3": "team",
    "wolf8": "team",
    "wolf9": "team",
    "king3": "team",
}

# Cookies (persistent login)
COOKIE_NAME = "orders_auth_v2"
COOKIE_KEY  = "hQ8$3nV@71!xXo^p4GmJz2#fK9rT6e"   # change to a long random string
COOKIE_EXPIRY_DAYS = 180

# --------------------- Google Sheets helpers -------------------
def _load_service_account_from_secrets():
    """Support TOML-table or JSON-string secrets."""
    raw = st.secrets["gcp_service_account"]
    if isinstance(raw, str):
        return json.loads(raw)
    return dict(raw)

def _gs_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    svc = _load_service_account_from_secrets()
    creds = ServiceAccountCredentials.from_json_keyfile_dict(svc, scope)
    return gspread.authorize(creds)

def _open_ws(title):
    sh = _gs_client().open_by_key(SHEET_ID)
    try:
        return sh.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=1000, cols=20)

def get_orders_ws():
    ws = _open_ws(ORDERS_SHEET)
    values = ws.get_all_values()
    if not values:
        ws.update("A1:F1", [EXPECTED_HEADER])
    else:
        first_row = ws.row_values(1)
        if first_row != EXPECTED_HEADER:
            st.warning("Orders sheet header differs. Use Admin tools → Fix orders header.")
    return ws

def get_clients_ws():
    ws = _open_ws(CLIENTS_SHEET)
    header = ["User","Client"]
    values = ws.get_all_values()
    if not values or ws.row_values(1) != header:
        ws.update("A1:B1", [header])
    return ws

@st.cache_data(ttl=30)
def load_orders_df() -> pd.DataFrame:
    ws = get_orders_ws()
    records = ws.get_all_records()  # first row as header
    df = pd.DataFrame(records)
    if df.empty:
        df = pd.DataFrame(columns=EXPECTED_HEADER)
    else:
        for c in EXPECTED_HEADER:
            if c not in df.columns:
                df[c] = "" if c != "Amount" else 0.0
        df = df[EXPECTED_HEADER]
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0)
    return df

@st.cache_data(ttl=15)
def load_clients_df() -> pd.DataFrame:
    ws = get_clients_ws()
    records = ws.get_all_records()
    df = pd.DataFrame(records)
    if df.empty:
        df = pd.DataFrame(columns=["User","Client"])
    else:
        for c in ["User","Client"]:
            if c not in df.columns:
                df[c] = ""
        df = df[["User","Client"]]
    return df

def append_order_row(row_list):
    ws = get_orders_ws()
    ws.append_row(row_list)

def add_client(user: str, client_name: str):
    if not client_name.strip():
        return
    ws = get_clients_ws()
    ws.append_row([user, client_name.strip()])

def delete_client(user: str, client_name: str):
    ws = get_clients_ws()
    vals = ws.get_all_values()
    for i in range(len(vals)-1, 0, -1):  # skip header
        row = vals[i]
        if len(row) >= 2 and row[0] == user and row[1] == client_name:
            ws.delete_rows(i+1)

def fix_orders_header():
    ws = get_orders_ws()
    ws.update("A1:F1", [EXPECTED_HEADER])

# --------------------------- UI: Team ---------------------------
def team_reporter(username):
    st.title("📝 Team Reporter")
    st.caption(f"Logged in as **{username}**")

    clients_df = load_clients_df()
    my_clients = sorted(clients_df[clients_df["User"] == username]["Client"].dropna().unique().tolist())

    with st.expander("My clients"):
        c1, c2 = st.columns([2,1])
        with c1:
            new_client = st.text_input("Add new client")
        with c2:
            if st.button("➕ Add client"):
                add_client(username, new_client)
                load_clients_df.clear()
                st.success(f"Added client: {new_client}")
                st.rerun()

        if my_clients:
            del_col1, del_col2 = st.columns([2,1])
            with del_col1:
                client_to_delete = st.selectbox("Delete one of my clients", my_clients)
            with del_col2:
                if st.button("🗑️ Delete selected"):
                    delete_client(username, client_to_delete)
                    load_clients_df.clear()
                    st.success(f"Deleted client: {client_to_delete}")
                    st.rerun()
        else:
            st.info("No clients yet. Add one above.")

    client_options = ["(choose)"] + my_clients
    client = st.selectbox("Client (choose from your list)", client_options, index=0)

    colA, colB = st.columns(2)
    with colA:
        order_date = st.date_input("Order date", value=date.today())
    with colB:
        order_id = st.text_input("Order ID")

    amount = st.number_input("Amount", min_value=0.0, step=0.01)

    if st.button("Submit Order"):
        if client == "(choose)":
            st.error("Please choose a client (or add one in 'My clients').")
        elif not order_id.strip():
            st.error("Order ID is required.")
        else:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            new_row = [ts, username, client, order_id.strip(), float(amount), order_date.strftime("%Y-%m-%d")]
            try:
                append_order_row(new_row)
                load_orders_df.clear()
                st.success("✅ Order submitted.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to submit: {e}")

    st.divider()
    st.subheader("My recent submissions")
    df = load_orders_df()
    mine = df[df["User"] == username].sort_values("Timestamp", ascending=False).head(100)
    st.dataframe(mine, use_container_width=True)

# ------------------------- UI: Dashboard ------------------------
def manager_dashboard():
    st.title("📊 Manager Dashboard (Admin)")
    df = load_orders_df()
    if df.empty:
        st.info("No reports yet.")
        return

    with st.expander("Filters", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        users   = ["(All)"] + sorted(df["User"].dropna().unique().tolist())
        clients = ["(All)"] + sorted(df["Client"].dropna().unique().tolist())
        selected_user   = c1.selectbox("Filter by Username", users)
        selected_client = c2.selectbox("Filter by Client", clients)
        date_from = c3.date_input("From", value=None)
        date_to   = c4.date_input("To",   value=None)

    with st.expander("Admin tools"):
        if st.button("Fix orders header (overwrite row 1)"):
            fix_orders_header()
            load_orders_df.clear()
            st.success("Header fixed. Reloading…")
            st.rerun()

    f = df.copy()
    if selected_user != "(All)":
        f = f[f["User"] == selected_user]
    if selected_client != "(All)":
        f = f[f["Client"] == selected_client]
    if date_from:
        f = f[pd.to_datetime(f["OrderDate"], errors="coerce") >= pd.to_datetime(date_from)]
    if date_to:
        f = f[pd.to_datetime(f["OrderDate"], errors="coerce") <= pd.to_datetime(date_to)]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Orders", f"{len(f):,}")
    col2.metric("Total Amount", f"${f['Amount'].sum():,.2f}")
    col3.metric("Unique Clients", f["Client"].nunique())
    col4.metric("Users", f["User"].nunique())

    st.divider()
    cA, cB = st.columns(2)
    with cA:
        st.subheader("By Client")
        if not f.empty:
            st.bar_chart(f.groupby("Client")["Amount"].sum().sort_values(ascending=False))
    with cB:
        st.subheader("By User")
        if not f.empty:
            st.bar_chart(f.groupby("User")["Amount"].sum().sort_values(ascending=False))

    st.subheader("All Orders")
    st.dataframe(f.sort_values("Timestamp", ascending=False), use_container_width=True)
    st.download_button("⬇ Download CSV", f.to_csv(index=False).encode("utf-8"),
                       "all_orders.csv", "text/csv")

# --------------------------- Auth (persistent) ------------------
def run_app():
    # Hash passwords (runtime is fine for an internal tool)
    try:
    hashed_passwords = stauth.Hasher(PASSWORDS).generate()
except Exception as e:
    st.error("Password hashing failed. Check Python version and requirements.")
    st.stop()


    authenticator = stauth.Authenticate(
        NAMES, USERNAMES, hashed_passwords,
        COOKIE_NAME, COOKIE_KEY, cookie_expiry_days=COOKIE_EXPIRY_DAYS
    )

    # Sidebar login; cookie keeps users logged in across sessions
    name, auth_status, username = authenticator.login("Login", "sidebar")

    if auth_status is False:
        st.sidebar.error("Invalid username or password")
        st.stop()
    if auth_status is None:
        st.stop()

    # Show logout in sidebar
    authenticator.logout("Logout", "sidebar")

    # Route by role
    role = ROLES.get(username, "team")
    if role == "admin":
        manager_dashboard()
    else:
        team_reporter(username)

# --------------------------- Main -------------------------------
if __name__ == "__main__":
    run_app()

