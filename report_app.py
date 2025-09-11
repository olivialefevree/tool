import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date, timedelta, timezone
import json, hmac, hashlib, base64
import extra_streamlit_components as stx
import time

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
SHEET_ID = "1oEJNDoyP80Sy1cOOn6dvgZaevKJxiSu3Z5AEce8WInE"   # your Google Sheet ID
ORDERS_SHEET = "Sheet1"                                     # orders tab
CLIENTS_SHEET = "Clients"                                   # clients tab
APP_TITLE = "Team Orders – Reports"

# New orders schema (no OrderID/OrderDate; keep User internally)
EXPECTED_HEADER = ["Timestamp","User","Client","Amount","ProfitPct","ProfitAmt","Status"]

# Accounts
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
ROLES = { "jerry":"admin", "wolf1":"team", "wolf2":"team", "wolf3":"team",
          "wolf8":"team", "wolf9":"team", "king3":"team" }

# Persistent login
COOKIE_NAME = "orders_auth_v2"
COOKIE_SECRET = "hQ8$3nV@71!xXo^p4GmJz2#fK9rT6e"  # ← CHANGE to a long random string and keep it stable
COOKIE_EXPIRY_DAYS = 180
SESSION_TOKEN_KEY = "auth_token"
POST_LOGOUT_FLAG  = "__just_logged_out"
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title=APP_TITLE, layout="wide")

# Optional centered credit badge
st.markdown("""
<style>
#center-top-badge{ position:fixed; top:56px; left:0; right:0; display:flex; justify-content:center; z-index:99999; pointer-events:none;}
#center-top-badge>span{background:rgba(0,0,0,.65); color:#fff; padding:6px 12px; border-radius:12px; font-size:12px; line-height:1; }
@media (max-width:640px){ #center-top-badge{ top:64px; } }
</style>
<div id="center-top-badge"><span>Made by 战狼 - Jerry</span></div>
""", unsafe_allow_html=True)

# --------------------- Token + cookie helpers ------------------
def _sign(s: str) -> str:
    return hmac.new(COOKIE_SECRET.encode("utf-8"), s.encode("utf-8"), hashlib.sha256).hexdigest()

def issue_token(username: str, name: str) -> str:
    exp = int((datetime.now(timezone.utc) + timedelta(days=COOKIE_EXPIRY_DAYS)).timestamp())
    payload = f"{username}|{name}|{exp}"
    sig = _sign(payload)
    token = f"{payload}|{sig}"
    return base64.urlsafe_b64encode(token.encode("utf-8")).decode("utf-8")

def verify_token(token_b64: str):
    try:
        token = base64.urlsafe_b64decode(token_b64.encode("utf-8")).decode("utf-8")
        username, name, exp_str, sig = token.split("|", 3)
        payload = f"{username}|{name}|{exp_str}"
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        if int(exp_str) < int(datetime.now(timezone.utc).timestamp()):
            return None
        return {"username": username, "name": name}
    except Exception:
        return None

cookie_manager = stx.CookieManager()

def set_cookie(value: str):
    cookie_manager.set(
        COOKIE_NAME, value,
        max_age=COOKIE_EXPIRY_DAYS * 24 * 3600,
        path="/", same_site="Lax", secure=True
    )

def clear_cookie():
    try:
        cookie_manager.set(
            COOKIE_NAME, "", max_age=0,
            path="/", same_site="Lax", secure=True
        )
        time.sleep(0.02)
    except Exception:
        pass

# --------------------- Google Sheets helpers -------------------
def _load_service_account_from_secrets():
    raw = st.secrets["gcp_service_account"]
    if isinstance(raw, str):
        return json.loads(raw)
    return dict(raw)

def _gs_client():
    scope = ["https://spreadsheets.google.com/feeds",
             "https://www.googleapis.com/auth/drive"]
    svc = _load_service_account_from_secrets()
    creds = ServiceAccountCredentials.from_json_keyfile_dict(svc, scope)
    return gspread.authorize(creds)

def _open_ws(title):
    sh = _gs_client().open_by_key(SHEET_ID)
    try:
        return sh.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=2000, cols=30)

def get_orders_ws():
    ws = _open_ws(ORDERS_SHEET)
    values = ws.get_all_values()
    if not values:
        ws.update("A1:G1", [EXPECTED_HEADER])
    else:
        first_row = ws.row_values(1)
        if first_row != EXPECTED_HEADER:
            st.warning("Orders sheet header differs. Use Admin tools → Fix orders header (new schema).")
    return ws

def get_clients_ws():
    ws = _open_ws(CLIENTS_SHEET)
    header = ["User","Client","OpenDate"]
    values = ws.get_all_values()
    if not values or ws.row_values(1) != header:
        ws.update("A1:C1", [header])
    return ws

@st.cache_data(ttl=30)
def load_orders_df() -> pd.DataFrame:
    ws = get_orders_ws()
    records = ws.get_all_records()
    df = pd.DataFrame(records)
    # normalize columns
    for c in EXPECTED_HEADER:
        if c not in df.columns:
            df[c] = 0.0 if c in ("Amount","ProfitPct","ProfitAmt") else ""
    df = df[EXPECTED_HEADER]
    # numeric coercions
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0)
    df["ProfitPct"] = pd.to_numeric(df["ProfitPct"], errors="coerce").fillna(0.0)
    df["ProfitAmt"] = pd.to_numeric(df["ProfitAmt"], errors="coerce").fillna(0.0)
    # compute status dynamically (>=120 hours old → Completed)
    now = pd.Timestamp.utcnow()
    ts = pd.to_datetime(df["Timestamp"], errors="coerce", utc=True)
    age_hours = (now - ts).dt.total_seconds() / 3600.0
    computed_status = age_hours.where(age_hours.notna(), 0)
    df["Status"] = ["Completed" if (h >= 120) else "In Process" for h in computed_status]
    return df

@st.cache_data(ttl=15)
def load_clients_df() -> pd.DataFrame:
    ws = get_clients_ws()
    records = ws.get_all_records()
    df = pd.DataFrame(records)
    for c in ["User","Client","OpenDate"]:
        if c not in df.columns:
            df[c] = ""
    return df[["User","Client","OpenDate"]]

def append_order_row(row_list):
    ws = get_orders_ws()
    ws.append_row(row_list)

def add_client(user: str, client_name: str, open_date: date):
    if not client_name.strip():
        return
    ws = get_clients_ws()
    ws.append_row([user, client_name.strip(), open_date.strftime("%Y-%m-%d")])

def delete_client(user: str, client_name: str):
    ws = get_clients_ws()
    vals = ws.get_all_values()
    # delete matching rows (skip header)
    for i in range(len(vals)-1, 0, -1):
        row = vals[i]
        if len(row) >= 2 and row[0] == user and row[1] == client_name:
            ws.delete_rows(i+1)

def fix_orders_header():
    ws = get_orders_ws()
    ws.update("A1:G1", [EXPECTED_HEADER])

# --------------------------- UI: Team ---------------------------
def team_reporter(username_display):
    st.title("📝 Team Reporter")
    st.caption(f"Logged in as **{username_display}**")

    clients_df = load_clients_df()
    my_clients_df = clients_df[clients_df["User"] == username_display].copy()
    my_clients_df["OpenDate"] = pd.to_datetime(my_clients_df["OpenDate"], errors="coerce").dt.date
    my_clients = sorted(my_clients_df["Client"].dropna().unique().tolist())

    with st.expander("My clients"):
        c1, c2, c3 = st.columns([2,1,1])
        with c1:
            new_client = st.text_input("Client name")
        with c2:
            open_date = st.date_input("Opening date", value=date.today())
        with c3:
            if st.button("➕ Add client"):
                add_client(username_display, new_client, open_date)
                load_clients_df.clear()
                st.success(f"Added client: {new_client} ({open_date})")
                st.rerun()

        if not my_clients_df.empty:
            st.write("Your clients:")
            st.dataframe(my_clients_df.sort_values("OpenDate", na_position="last"),
                         use_container_width=True, hide_index=True)
            del_col1, del_col2 = st.columns([3,1])
            with del_col1:
                client_to_delete = st.selectbox("Delete one of my clients", my_clients)
            with del_col2:
                if st.button("🗑️ Delete selected"):
                    delete_client(username_display, client_to_delete)
                    load_clients_df.clear()
                    st.success(f"Deleted client: {client_to_delete}")
                    st.rerun()
        else:
            st.info("No clients yet. Add one above.")

    # ---- Order form (Timestamp auto; Client dropdown; Amount; Profit %) ----
    client_options = ["(choose)"] + my_clients
    client = st.selectbox("Client", client_options, index=0)

    col1, col2 = st.columns(2)
    with col1:
        amount = st.number_input("Order amount", min_value=0.0, step=0.01)
    with col2:
        profit_pct = st.number_input("Profit %", min_value=0.0, max_value=100.0, step=0.1)

    if st.button("Submit Order"):
        if client == "(choose)":
            st.error("Please choose a client (or add one in 'My clients').")
        else:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            profit_amt = round(float(amount) * float(profit_pct) / 100.0, 2)
            status = "In Process"  # will auto-switch to Completed after 120h
            new_row = [ts, username_display, client, float(amount), float(profit_pct), profit_amt, status]
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
    mine = df[df["User"] == username_display].copy()
    mine = mine.sort_values("Timestamp", ascending=False).head(100)
    st.dataframe(mine, use_container_width=True)

# ------------------------- UI: Dashboard ------------------------
def manager_dashboard():
    st.title("📊 Manager Dashboard (Admin)")
    df = load_orders_df()
    if df.empty:
        st.info("No reports yet.")
        return

    # Filters
    with st.expander("Filters", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        users   = ["(All)"] + sorted(df["User"].dropna().unique().tolist())
        clients = ["(All)"] + sorted(df["Client"].dropna().unique().tolist())
        statuses = ["(All)", "In Process", "Completed"]
        selected_user   = c1.selectbox("Filter by Username", users)
        selected_client = c2.selectbox("Filter by Client", clients)
        selected_status = c3.selectbox("Filter by Status", statuses)
        # date range based on Timestamp
        date_from = c4.date_input("From (by Timestamp)", value=None)
        date_to   = st.date_input("To (by Timestamp)", value=None)

    # Admin tools
    with st.expander("Admin tools"):
        if st.button("Fix orders header (new schema)"):
            fix_orders_header()
            load_orders_df.clear()
            st.success("Header fixed. Reloading…")
            st.rerun()

    # Apply filters
    f = df.copy()
    if selected_user != "(All)":
        f = f[f["User"] == selected_user]
    if selected_client != "(All)":
        f = f[f["Client"] == selected_client]
    if selected_status != "(All)":
        f = f[f["Status"] == selected_status]
    if date_from:
        f = f[pd.to_datetime(f["Timestamp"], errors="coerce") >= pd.to_datetime(date_from)]
    if date_to:
        f = f[pd.to_datetime(f["Timestamp"], errors="coerce") <= pd.to_datetime(date_to) + pd.Timedelta(days=1)]

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Orders", f"{len(f):,}")
    col2.metric("Total Amount", f"${f['Amount'].sum():,.2f}")
    col3.metric("Total Profit", f"${f['ProfitAmt'].sum():,.2f}")
    col4.metric("Completed %", f"{(100.0* (f['Status']=='Completed').mean()):.1f}%" if not f.empty else "0.0%")

    st.divider()
    cA, cB = st.columns(2)
    with cA:
        st.subheader("By Client (Amount)")
        if not f.empty:
            st.bar_chart(f.groupby("Client")["Amount"].sum().sort_values(ascending=False))
    with cB:
        st.subheader("By User (Profit)")
        if not f.empty:
            st.bar_chart(f.groupby("User")["ProfitAmt"].sum().sort_values(ascending=False))

    st.subheader("All Orders")
    st.dataframe(f.sort_values("Timestamp", ascending=False), use_container_width=True)
    st.download_button("⬇ Download CSV", f.to_csv(index=False).encode("utf-8"),
                       "all_orders.csv", "text/csv")

# --------------------------- Auth + Router ----------------------
def render_login():
    st.sidebar.header("Login")
    username = st.sidebar.selectbox("User", USERNAMES, format_func=lambda u: NAMES[USERNAMES.index(u)])
    password = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Login"):
        idx = USERNAMES.index(username)
        if PASSWORDS[idx] == password:
            token = issue_token(username, NAMES[idx])
            st.session_state[SESSION_TOKEN_KEY] = token  # show app immediately
            st.rerun()
        else:
            st.sidebar.error("Invalid username or password")

def render_logout_panel(display_name):
    st.sidebar.success(f"Logged in as {display_name}")
    if st.sidebar.button("Logout"):
        st.session_state[POST_LOGOUT_FLAG] = True
        st.session_state.pop(SESSION_TOKEN_KEY, None)
        clear_cookie()
        st.rerun()

def main_router():
    # Read cookies once per run (may be None very first render)
    cookies = cookie_manager.get_all()
    # Handle logout cycle (ignore lingering cookie until gone)
    if st.session_state.get(POST_LOGOUT_FLAG):
        if cookies and cookies.get(COOKIE_NAME):
            clear_cookie()
            st.info("Logging out…")
            st.stop()
        st.session_state.pop(POST_LOGOUT_FLAG, None)
        render_login()
        st.stop()

    # Fresh session token → route now; set cookie opportunistically
    session_token = st.session_state.get(SESSION_TOKEN_KEY)
    if session_token:
        user = verify_token(session_token)
        if user:
            if cookies is not None and not cookies.get(COOKIE_NAME):
                set_cookie(session_token)
            render_logout_panel(user["name"])
            return manager_dashboard() if ROLES.get(user["username"]) == "admin" else team_reporter(user["name"])

    # Returning visit → use cookie
    if cookies is None:
        st.stop()  # wait one render for cookies
    token_from_cookie = cookies.get(COOKIE_NAME)
    user = verify_token(token_from_cookie) if token_from_cookie else None
    if user:
        render_logout_panel(user["name"])
        return manager_dashboard() if ROLES.get(user["username"]) == "admin" else team_reporter(user["name"])

    # No auth yet → show login
    render_login()
    st.stop()

# --------------------------- Main -------------------------------
if __name__ == "__main__":
    st.title(APP_TITLE)
    main_router()
