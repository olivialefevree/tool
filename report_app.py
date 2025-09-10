"""
Streamlit Team Orders App

This app allows team members to submit orders into a Google Sheet and managers to
monitor aggregated statistics. It has been customised to only capture
`Timestamp`, `User`, `Client`, `OrderID`, `Amount` and `OrderDate` fields for
each order. Users can maintain a personal list of clients (with optional
addresses); a simple interface lets team members add new clients and pick from
their existing clients when recording an order.

The application uses two worksheets within a single Google Sheets document:

* The main orders sheet defined by ``SHEET_NAME_ORDERS`` holds the orders.
  Columns: ``Timestamp``, ``User``, ``Client``, ``OrderID``, ``Amount`` and
  ``OrderDate``. These columns are enforced on startup to ensure the sheet
  header matches expectations.
* A secondary clients sheet defined by ``CLIENTS_SHEET_NAME`` stores a list of
  clients per user. Columns: ``User``, ``Client`` and ``Address``. New
  clients are appended here when added via the UI. When submitting an order
  the user selects from the clients associated with their account. If no
  clients exist, the dropdown will be empty until at least one client is
  added.

Authentication is performed locally against the ``USERS`` dictionary. You
should store the credentials for your Google service account in
``st.secrets["gcp_service_account"]``. See the existing project README for
details on setting up this secret. Make sure the service account has read
and write access to the specified Google Sheet.

"""

import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date
import json

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG: your Google Sheet
SHEET_ID = "1oEJNDoyP80Sy1cOOn6dvgZaevKJxiSu3Z5AEce8WInE"   # Google Sheet ID
SHEET_NAME_ORDERS = "Sheet1"       # Worksheet storing orders
CLIENTS_SHEET_NAME = "Clients"     # Worksheet storing client lists per user
APP_TITLE = "Team Orders – Reports"
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title=APP_TITLE, layout="wide")

# ------------------------- Auth & Users -------------------------
# In-memory user store. In a real world scenario you would replace this with
# your own authentication backend. Passwords are stored in plain text here for
# demonstration only.
USERS = {
    "admin": {"password": "admin123", "role": "admin"},
    "wolf1": {"password": "wolfpass1", "role": "team"},
    "wolf2": {"password": "wolfpass2", "role": "team"},
}

def login_ui():
    """Render a login form in the sidebar. Updates session state upon success."""
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
    """Ensure the user is authenticated before continuing. Renders login form if not."""
    if "auth" not in st.session_state:
        login_ui()
        st.stop()

def logout_button():
    """Render a logout button in the sidebar."""
    if st.sidebar.button("Logout"):
        st.session_state.pop("auth", None)
        st.rerun()

# --------------------- Google Sheets Client ---------------------
def _load_service_account_from_secrets():
    """Load the service account credentials from Streamlit secrets.

    Supports both TOML-table or JSON-string secrets. Returns a dictionary
    suitable for ``ServiceAccountCredentials.from_json_keyfile_dict``.
    """
    raw = st.secrets["gcp_service_account"]
    if isinstance(raw, str):
        return json.loads(raw)
    return dict(raw)

def _authorize_client():
    """Authorize and return a gspread client using the service account credentials."""
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    svc_info = _load_service_account_from_secrets()
    creds = ServiceAccountCredentials.from_json_keyfile_dict(svc_info, scope)
    return gspread.authorize(creds)

def get_worksheet(sheet_name: str):
    """Open a worksheet by name, creating it with the appropriate header if missing.

    Depending on ``sheet_name``, a different header is enforced. If the worksheet
    does not exist, it is created with 1000 rows and 20 columns. If the first
    row does not match the expected header, a warning is displayed.
    """
    client = _authorize_client()
    sh = client.open_by_key(SHEET_ID)
    try:
        ws = sh.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=sheet_name, rows=1000, cols=20)

    # Determine expected header
    if sheet_name == SHEET_NAME_ORDERS:
        header = ["Timestamp", "User", "Client", "OrderID", "Amount", "OrderDate"]
    elif sheet_name == CLIENTS_SHEET_NAME:
        header = ["User", "Client", "Address"]
    else:
        raise ValueError(f"Unknown sheet name: {sheet_name}")

    values = ws.get_all_values()
    if not values:
        ws.append_row(header)
    else:
        first_row = ws.row_values(1)
        if first_row != header:
            st.warning(
                f"Sheet '{sheet_name}' header differs. Expected: {', '.join(header)}"
            )
    return ws

@st.cache_data(ttl=30)
def load_orders_df():
    """Load the orders worksheet into a DataFrame.

    Ensures the 'Amount' column is numeric and fills NaN with 0.0. If the sheet
    is empty, an empty DataFrame with the correct columns is returned.
    """
    ws = get_worksheet(SHEET_NAME_ORDERS)
    records = ws.get_all_records()
    df = pd.DataFrame(records)
    if df.empty:
        df = pd.DataFrame(
            columns=["Timestamp", "User", "Client", "OrderID", "Amount", "OrderDate"]
        )
    if "Amount" in df.columns:
        df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0)
    return df

@st.cache_data(ttl=30)
def load_clients_df():
    """Load the clients worksheet into a DataFrame.

    Returns an empty DataFrame with the correct columns if no data exists.
    """
    ws = get_worksheet(CLIENTS_SHEET_NAME)
    records = ws.get_all_records()
    df = pd.DataFrame(records)
    if df.empty:
        df = pd.DataFrame(columns=["User", "Client", "Address"])
    return df

def append_order_row(row_list):
    """Append a new order row to the orders worksheet."""
    ws = get_worksheet(SHEET_NAME_ORDERS)
    ws.append_row(row_list)

def append_client_row(row_list):
    """Append a new client row to the clients worksheet."""
    ws = get_worksheet(CLIENTS_SHEET_NAME)
    ws.append_row(row_list)

# --------------------------- UI Blocks --------------------------
def team_reporter(username: str):
    """Render the team reporter interface for a given user.

    Allows the user to manage their client list (add new clients) and submit
    new orders. The order submission form only includes Client, OrderID,
    Amount and OrderDate; timestamp and username are captured automatically.
    """
    st.title("📝 Team Reporter")
    st.caption(f"Logged in as **{username}**")

    # Section to add a new client
    st.subheader("Add New Client")
    with st.form(key="add_client_form"):
        new_client_name = st.text_input("Client Name", key="new_client_name")
        new_client_address = st.text_input("Client Address (optional)", key="new_client_address")
        add_client_submitted = st.form_submit_button("Add Client")
        if add_client_submitted:
            if not new_client_name.strip():
                st.warning("Please enter a client name.")
            else:
                # Append the new client to the clients sheet
                append_client_row([username, new_client_name.strip(), new_client_address.strip()])
                st.success(f"Client '{new_client_name}' added.")
                # Clear cache so dropdown updates immediately
                load_clients_df.clear()
                st.experimental_rerun()

    st.divider()

    # Load the user's client list for the dropdown
    clients_df = load_clients_df()
    user_clients = clients_df[clients_df["User"] == username]
    if not user_clients.empty:
        # Display clients as "Name (Address)" when address is provided
        def format_client(row):
            if row["Address"]:
                return f"{row['Client']} – {row['Address']}"
            return row["Client"]
        client_options = user_clients.apply(format_client, axis=1).tolist()
    else:
        client_options = []

    # Order submission form
    st.subheader("Submit Order")
    with st.form(key="submit_order_form"):
        selected_client = st.selectbox(
            "Client", client_options, index=0 if client_options else None,
            help="Select an existing client or add one above."
        )
        order_id = st.text_input("Order ID")
        amount = st.number_input("Amount", min_value=0.0, step=0.01)
        order_date = st.date_input("Order Date", value=date.today())
        submit = st.form_submit_button("Submit Order")
        if submit:
            if not selected_client:
                st.warning("Please select a client.")
            else:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # Extract just the client name (drop the address portion if present)
                client_name = selected_client.split(" – ")[0]
                new_row = [
                    ts, username, client_name, order_id.strip(), float(amount),
                    order_date.strftime("%Y-%m-%d"),
                ]
                try:
                    append_order_row(new_row)
                    st.success("✅ Order submitted.")
                    # Clear caches and rerun to update the table
                    load_orders_df.clear()
                    st.experimental_rerun()
                except Exception as e:
                    st.error(f"Failed to submit: {e}")

    st.divider()
    st.subheader("My Recent Submissions")
    orders_df = load_orders_df()
    # Filter by current user
    mine = orders_df[orders_df["User"] == username]
    mine = mine.sort_values("Timestamp", ascending=False).head(100)
    st.dataframe(mine, use_container_width=True)

def manager_dashboard():
    """Render the manager dashboard for admin users.

    Displays summary metrics and breakdowns by client. Filters are provided to
    narrow down the dataset by user or date range.
    """
    st.title("📊 Manager Dashboard (Admin)")
    df = load_orders_df()
    if df.empty:
        st.info("No reports yet.")
        return

    with st.expander("Filters", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        users = ["(All)"] + sorted(df["User"].dropna().unique().tolist())
        clients = ["(All)"] + sorted(df["Client"].dropna().unique().tolist())
        selected_user = c1.selectbox("Filter by Username", users)
        selected_client = c2.selectbox("Filter by Client", clients)
        date_from = c3.date_input("From", value=None)
        date_to = c4.date_input("To", value=None)

    # Apply filters
    f = df.copy()
    if selected_user != "(All)":
        f = f[f["User"] == selected_user]
    if selected_client != "(All)":
        f = f[f["Client"] == selected_client]
    if date_from:
        f = f[pd.to_datetime(f["OrderDate"], errors="coerce") >= pd.to_datetime(date_from)]
    if date_to:
        f = f[pd.to_datetime(f["OrderDate"], errors="coerce") <= pd.to_datetime(date_to)]

    # Compute metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Orders", f"{len(f):,}")
    col2.metric("Total Amount", f"${f['Amount'].sum():,.2f}")
    col3.metric("Unique Clients", f["Client"].nunique())
    col4.metric("Users", f["User"].nunique())

    st.divider()
    cA, cB = st.columns(2)
    with cA:
        st.subheader("Amount by Client")
        if not f.empty:
            # Group by Client
            summary = f.groupby("Client")["Amount"].sum().sort_values(ascending=False)
            st.bar_chart(summary)
    with cB:
        st.subheader("Orders per User")
        if not f.empty:
            summary = f.groupby("User")["Amount"].sum().sort_values(ascending=False)
            st.bar_chart(summary)

    st.subheader("All Orders")
    st.dataframe(f.sort_values("Timestamp", ascending=False), use_container_width=True)
    st.download_button(
        "⬇ Download CSV", f.to_csv(index=False).encode("utf-8"),
        "all_orders.csv", "text/csv"
    )

# --------------------------- Router -----------------------------
ensure_logged_in()
logout_button()

role = st.session_state["auth"]["role"]
username = st.session_state["auth"]["username"]

if role == "admin":
    manager_dashboard()
else:
    team_reporter(username)import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date
import json

EXPECTED_HEADER = ["Timestamp","User","TeamMember","Client","Store","OrderID","Amount","Notes","OrderDate"]
ALIASES = {
    # map common variations → expected column names
    "username": "User",
    "user name": "User",
    "team member": "TeamMember",
    "team_member": "TeamMember",
    "client name": "Client",
    "order id": "OrderID",
    "orderid": "OrderID",
    "amount($)": "Amount",
}

def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Make sure dataframe has the expected columns, even if the sheet header differs."""
    if df is None or df.empty:
        return pd.DataFrame(columns=EXPECTED_HEADER)

    # trim header whitespace & lower map
    df = df.rename(columns=lambda c: str(c).strip())
    lower_to_actual = {c.lower(): c for c in df.columns}

    # apply alias mapping if expected column is missing
    for alias_lower, target in ALIASES.items():
        if target not in df.columns and alias_lower in lower_to_actual:
            df[target] = df.pop(lower_to_actual[alias_lower])

    # ensure all expected columns exist
    for col in EXPECTED_HEADER:
        if col not in df.columns:
            df[col] = 0.0 if col == "Amount" else ""

    # coerce amount
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0)

    # return in the canonical order
    return df[EXPECTED_HEADER]

def fix_header():
    """Overwrite row 1 with the expected header."""
    ws = get_gsheet()
    ws.update("A1:I1", [EXPECTED_HEADER])

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG: your Google Sheet
SHEET_ID = "1oEJNDoyP80Sy1cOOn6dvgZaevKJxiSu3Z5AEce8WInE"   # your sheet ID
SHEET_NAME = "Sheet1"                                       # tab name
APP_TITLE = "Team Orders – Reports"
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title=APP_TITLE, layout="wide")

# ------------------------- Auth & Users -------------------------
USERS = {
    "admin": {"password": "admin123", "role": "admin"},
    "wolf1": {"password": "wolfpass1", "role": "team"},
    "wolf2": {"password": "wolfpass2", "role": "team"},
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
def _load_service_account_from_secrets():
    """Support TOML-table or JSON-string secrets."""
    raw = st.secrets["gcp_service_account"]
    if isinstance(raw, str):
        return json.loads(raw)
    return dict(raw)

def get_gsheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    svc_info = _load_service_account_from_secrets()
    creds = ServiceAccountCredentials.from_json_keyfile_dict(svc_info, scope)
    client = gspread.authorize(creds)

    sh = client.open_by_key(SHEET_ID)
    try:
        ws = sh.worksheet(SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=SHEET_NAME, rows=1000, cols=20)

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
@st.cache_data(ttl=30)
def load_dataframe():
    ws = get_gsheet()
    records = ws.get_all_records()   # uses first row as header
    df = pd.DataFrame(records)
    df = normalize_df(df)
    return df


def append_row(row_list):
    ws = get_gsheet()
    ws.append_row(row_list)

# --------------------------- UI Blocks --------------------------
def team_reporter(username):
    st.title("📝 Team Reporter")
    st.caption(f"Logged in as **{username}**")

    key_tm = f"tm_name_{username}"
    team_member = st.text_input("Team member (display name)", st.session_state.get(key_tm, username))
    st.session_state[key_tm] = team_member

    colA, colB, colC = st.columns(3)
    with colA: order_date = st.date_input("Order date", value=date.today())
    with colB: client = st.text_input("Client")
    with colC: store = st.text_input("Store")

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
            st.rerun()
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

    # ── Filters ───────────────────────────────────────────────
    with st.expander("Filters", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        users = ["(All)"] + sorted(df["User"].dropna().unique().tolist())
        team_members = ["(All)"] + sorted(df["TeamMember"].dropna().unique().tolist())
        selected_user = c1.selectbox("Filter by Username", users)
        selected_tm   = c2.selectbox("Filter by Team Member", team_members)
        date_from     = c3.date_input("From", value=None)
        date_to       = c4.date_input("To", value=None)

    # ── Admin tools (separate expander, not nested) ───────────
    with st.expander("Admin tools"):
        if st.button("Fix header (overwrite row 1)"):
            fix_header()
            st.success("Header fixed. Reloading…")
            st.rerun()



    f = df.copy()
    if selected_user != "(All)": f = f[f["User"] == selected_user]
    if selected_tm != "(All)": f = f[f["TeamMember"] == selected_tm]
    if date_from: f = f[pd.to_datetime(f["OrderDate"], errors="coerce") >= pd.to_datetime(date_from)]
    if date_to:   f = f[pd.to_datetime(f["OrderDate"], errors="coerce") <= pd.to_datetime(date_to)]

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



