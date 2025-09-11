import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date, timedelta, timezone
import json, hmac, hashlib, base64, time, random, string

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
SHEET_ID = "1oEJNDoyP80Sy1cOOn6dvgZaevKJxiSu3Z5AEce8WInE"   # Google Sheet ID
ORDERS_SHEET = "Sheet1"                                     # orders tab
CLIENTS_SHEET = "Clients"                                   # clients tab
USERS_SHEET   = "Users"                                     # users tab (new)
PRESETS_SHEET = "FilterPresets"                             # presets tab (new)
AUDIT_SHEET   = "AuditLog"                                  # audit tab (new)
APP_TITLE = "Team Orders – Reports"

# Orders schema (unchanged from last build)
EXPECTED_HEADER = ["Timestamp","User","Client","Amount","ProfitPct","ProfitAmt","Status"]

# Initial built-in accounts (seeded to Users sheet only once)
SEED_USERS = [
    {"Username":"jerry","DisplayName":"Jerry","Role":"admin","Password":"Qa9$gH!7k2@","Active":"TRUE"},
    {"Username":"wolf1","DisplayName":"Wolf 1","Role":"team","Password":"tu8*NMh2!5","Active":"TRUE"},
    {"Username":"wolf2","DisplayName":"Wolf 2","Role":"team","Password":"Rb4)fKz7^1","Active":"TRUE"},
    {"Username":"wolf3","DisplayName":"Wolf 3","Role":"team","Password":"xE3@pL9!q6","Active":"TRUE"},
    {"Username":"wolf8","DisplayName":"Wolf 8","Role":"team","Password":"Jh7$wT2%v8","Active":"TRUE"},
    {"Username":"wolf9","DisplayName":"Wolf 9","Role":"team","Password":"mN5#cR8&d4","Active":"TRUE"},
    {"Username":"king3","DisplayName":"King 3","Role":"team","Password":"zT6*Ya3@e9","Active":"TRUE"},
]

# Persistent login
COOKIE_NAME = "orders_auth_v2"
COOKIE_SECRET = "hQ8$3nV@71!xXo^p4GmJz2#fK9rT6e"  # ← set once & keep stable
COOKIE_EXPIRY_DAYS = 180
SESSION_TOKEN_KEY = "auth_token"
POST_LOGOUT_FLAG  = "__just_logged_out"
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title=APP_TITLE, layout="wide")

# Center credit badge
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

import extra_streamlit_components as stx
cookie_manager = stx.CookieManager()
def set_cookie(value: str):
    cookie_manager.set(COOKIE_NAME, value, max_age=COOKIE_EXPIRY_DAYS*24*3600, path="/", same_site="Lax", secure=True)
def clear_cookie():
    try:
        cookie_manager.set(COOKIE_NAME, "", max_age=0, path="/", same_site="Lax", secure=True); time.sleep(0.02)
    except Exception:
        pass

# --------------------- Google Sheets helpers -------------------
def _load_service_account_from_secrets():
    raw = st.secrets["gcp_service_account"]
    if isinstance(raw, str):
        return json.loads(raw)
    return dict(raw)

def _gs_client():
    scope = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
    svc = _load_service_account_from_secrets()
    creds = ServiceAccountCredentials.from_json_keyfile_dict(svc, scope)
    return gspread.authorize(creds)

def _open_ws(title):
    sh = _gs_client().open_by_key(SHEET_ID)
    try:
        return sh.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=3000, cols=30)

def ensure_orders_header():
    ws = _open_ws(ORDERS_SHEET)
    values = ws.get_all_values()
    if not values or ws.row_values(1) != EXPECTED_HEADER:
        ws.update(f"A1:{chr(ord('A')+len(EXPECTED_HEADER)-1)}1", [EXPECTED_HEADER])
    return ws

def ensure_clients_header():
    ws = _open_ws(CLIENTS_SHEET)
    header = ["User","Client","OpenDate"]
    values = ws.get_all_values()
    if not values or ws.row_values(1) != header:
        ws.update("A1:C1", [header])
    return ws

def ensure_users_sheet_seed():
    ws = _open_ws(USERS_SHEET)
    header = ["Username","DisplayName","Role","Password","Active"]
    values = ws.get_all_values()
    if not values:
        ws.update("A1:E1", [header])
        ws.update("A2:E8", [[u["Username"],u["DisplayName"],u["Role"],u["Password"],u["Active"]] for u in SEED_USERS])
    elif ws.row_values(1) != header:
        ws.update("A1:E1", [header])
    return ws

def ensure_presets_header():
    ws = _open_ws(PRESETS_SHEET)
    header = ["Name","User","Client","Status","FromDate","ToDate"]
    values = ws.get_all_values()
    if not values or ws.row_values(1) != header:
        ws.update("A1:F1", [header])
    return ws

def ensure_audit_header():
    ws = _open_ws(AUDIT_SHEET)
    header = ["At","Actor","Action","TargetSheet","SheetRow","Reason","OldJSON","NewJSON"]
    values = ws.get_all_values()
    if not values or ws.row_values(1) != header:
        ws.update("A1:H1", [header])
    return ws

# Initialize sheets
def init_all_sheets():
    ensure_orders_header()
    ensure_clients_header()
    ensure_users_sheet_seed()
    ensure_presets_header()
    ensure_audit_header()

# Row-numbered loaders (so we can edit/delete specific rows)
def load_orders_with_rows() -> pd.DataFrame:
    ws = ensure_orders_header()
    rows = ws.get_all_values()
    if len(rows) <= 1:
        return pd.DataFrame(columns=["SheetRow"]+EXPECTED_HEADER)
    data = []
    hdr = rows[0]
    for i, r in enumerate(rows[1:], start=2):  # sheet row index
        rec = {h: (r[idx] if idx < len(r) else "") for idx, h in enumerate(hdr)}
        rec["SheetRow"] = i
        data.append(rec)
    df = pd.DataFrame(data)
    # normalize dtypes
    for c in EXPECTED_HEADER:
        if c not in df.columns:
            df[c] = ""
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0)
    df["ProfitPct"] = pd.to_numeric(df["ProfitPct"], errors="coerce").fillna(0.0)
    df["ProfitAmt"] = pd.to_numeric(df["ProfitAmt"], errors="coerce").fillna(0.0)
    # compute live status (>=120h old → Completed)
    now = pd.Timestamp.utcnow()
    ts = pd.to_datetime(df["Timestamp"], errors="coerce", utc=True)
    age_h = (now - ts).dt.total_seconds()/3600.0
    df["Status"] = ["Completed" if (h >= 120) else "In Process" for h in age_h.fillna(0)]
    return df[["SheetRow"]+EXPECTED_HEADER]

@st.cache_data(ttl=30)
def load_orders_df_cached() -> pd.DataFrame:
    return load_orders_with_rows().drop(columns=["SheetRow"])

@st.cache_data(ttl=15)
def load_clients_df() -> pd.DataFrame:
    ws = ensure_clients_header()
    rows = ws.get_all_values()
    if len(rows) <= 1:
        return pd.DataFrame(columns=["SheetRow","User","Client","OpenDate"])
    data = []
    hdr = rows[0]
    for i, r in enumerate(rows[1:], start=2):
        rec = {h: (r[idx] if idx < len(r) else "") for idx, h in enumerate(hdr)}
        rec["SheetRow"] = i
        data.append(rec)
    df = pd.DataFrame(data)
    return df[["SheetRow","User","Client","OpenDate"]]

def load_users_df() -> pd.DataFrame:
    ws = ensure_users_sheet_seed()
    rows = ws.get_all_values()
    if len(rows) <= 1:
        return pd.DataFrame(columns=["SheetRow","Username","DisplayName","Role","Password","Active"])
    data = []
    hdr = rows[0]
    for i, r in enumerate(rows[1:], start=2):
        rec = {h: (r[idx] if idx < len(r) else "") for idx, h in enumerate(hdr)}
        rec["SheetRow"] = i
        data.append(rec)
    df = pd.DataFrame(data)
    return df[["SheetRow","Username","DisplayName","Role","Password","Active"]]

def append_order_row(row_list):
    ws = ensure_orders_header()
    ws.append_row(row_list)

def update_order_row(sheet_row:int, new_values:dict, actor:str, reason:str, old_record:dict):
    ws = ensure_orders_header()
    full = old_record.copy()
    full.update(new_values)
    # recompute ProfitAmt and Status
    full["Amount"] = float(full.get("Amount",0))
    full["ProfitPct"] = float(full.get("ProfitPct",0))
    full["ProfitAmt"] = round(full["Amount"]*full["ProfitPct"]/100.0,2)
    # compute Status live by timestamp
    try:
        ts = pd.to_datetime(full["Timestamp"], utc=True)
    except Exception:
        ts = pd.Timestamp.utcnow()
    age_h = (pd.Timestamp.utcnow() - ts).total_seconds()/3600.0
    full["Status"] = "Completed" if age_h >= 120 else "In Process"
    # update row
    values = [full.get(h,"") for h in EXPECTED_HEADER]
    ws.update(f"A{sheet_row}:{chr(ord('A')+len(EXPECTED_HEADER)-1)}{sheet_row}", [values])
    # audit
    log_audit(actor, "EDIT_ORDER", ORDERS_SHEET, sheet_row, reason, old_record, full)

def delete_order_row(sheet_row:int, actor:str, reason:str, old_record:dict):
    ws = ensure_orders_header()
    ws.delete_rows(sheet_row)
    log_audit(actor, "DELETE_ORDER", ORDERS_SHEET, sheet_row, reason, old_record, None)

def add_client(user: str, client_name: str, open_date: date):
    if not client_name.strip(): return
    ws = ensure_clients_header()
    ws.append_row([user, client_name.strip(), open_date.strftime("%Y-%m-%d")])

def update_client(sheet_row:int, user:str, client:str, open_date:date, actor:str):
    ws = ensure_clients_header()
    ws.update(f"A{sheet_row}:C{sheet_row}", [[user, client, open_date.strftime("%Y-%m-%d")]])
    log_audit(actor, "EDIT_CLIENT", CLIENTS_SHEET, sheet_row, "-", None, {"User":user,"Client":client,"OpenDate":str(open_date)})

def delete_client_row(sheet_row:int, actor:str, reason:str, old_record:dict):
    ws = ensure_clients_header()
    ws.delete_rows(sheet_row)
    log_audit(actor, "DELETE_CLIENT", CLIENTS_SHEET, sheet_row, reason, old_record, None)

def save_preset(name, user, client, status, dfrom, dto, actor):
    ws = ensure_presets_header()
    ws.append_row([name, user or "", client or "", status or "", dfrom or "", dto or ""])
    log_audit(actor, "SAVE_PRESET", PRESETS_SHEET, "-", "-", None, {"Name":name})

def delete_preset_by_name(name, actor):
    ws = ensure_presets_header()
    vals = ws.get_all_values()
    for i in range(len(vals)-1, 0, -1):
        row = vals[i]
        if len(row) >= 1 and row[0] == name:
            ws.delete_rows(i+1)
            log_audit(actor, "DELETE_PRESET", PRESETS_SHEET, i+1, "-", {"Name":name}, None)
            break

def list_presets_df():
    ws = ensure_presets_header()
    vals = ws.get_all_values()
    if len(vals)<=1: return pd.DataFrame(columns=["Name","User","Client","Status","FromDate","ToDate"])
    hdr = vals[0]
    recs = []
    for r in vals[1:]:
        recs.append({hdr[i]: (r[i] if i<len(r) else "") for i in range(len(hdr))})
    return pd.DataFrame(recs)

def log_audit(actor, action, target_sheet, sheet_row, reason, old_obj, new_obj):
    ws = ensure_audit_header()
    at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    ws.append_row([at, actor, action, target_sheet, str(sheet_row), reason or "-", json.dumps(old_obj or {}), json.dumps(new_obj or {})])

def random_password(n=12):
    chars = string.ascii_letters + string.digits + "!@#$%^&*()_-+"
    return "".join(random.choice(chars) for _ in range(n))

# --------------------------- Auth (dynamic users) ---------------
def get_active_users():
    users = load_users_df()
    users["Active"] = users["Active"].astype(str).str.upper().isin(["TRUE","1","YES","Y"])
    active = users[users["Active"]==True]
    return active

def get_user_record(username):
    users = load_users_df()
    row = users[users["Username"]==username]
    if row.empty: return None
    rec = row.iloc[0].to_dict()
    rec["Active"] = str(rec["Active"]).upper() in ["TRUE","1","YES","Y"]
    return rec

# --------------------------- UI: Team ---------------------------
def team_reporter(display_name):
    st.title("📝 Team Reporter")
    st.caption(f"Logged in as **{display_name}**")

    clients_df = load_clients_df()
    my_clients = sorted(clients_df[clients_df["User"] == display_name]["Client"].dropna().unique().tolist())

    with st.expander("My clients"):
        c1, c2, c3 = st.columns([2,1,1])
        with c1:
            new_client = st.text_input("Client name")
        with c2:
            open_date = st.date_input("Opening date", value=date.today())
        with c3:
            if st.button("➕ Add client"):
                add_client(display_name, new_client, open_date)
                load_clients_df.clear()
                st.success(f"Added client: {new_client} ({open_date})")
                st.rerun()

        if my_clients:
            del_col1, del_col2 = st.columns([3,1])
            with del_col1:
                client_to_delete = st.selectbox("Delete one of my clients", my_clients)
            with del_col2:
                if st.button("🗑️ Delete selected"):
                    # find that row for current user
                    df = load_clients_df()
                    row = df[(df["User"]==display_name) & (df["Client"]==client_to_delete)].head(1)
                    if not row.empty:
                        delete_client_row(int(row.iloc[0]["SheetRow"]), display_name, "User-initiated delete", row.iloc[0].to_dict())
                        load_clients_df.clear()
                        st.success(f"Deleted client: {client_to_delete}")
                        st.rerun()
        else:
            st.info("No clients yet. Add one above.")

    st.subheader("➕ New Order")
    client = st.selectbox("Client", ["(choose)"]+my_clients, index=0)
    cA, cB = st.columns(2)
    with cA:
        amount = st.number_input("Order amount", min_value=0.0, step=0.01)
    with cB:
        profit_pct = st.number_input("Profit %", min_value=0.0, max_value=100.0, step=0.1, help="Not critical, can remain 0")

    if st.button("Submit Order"):
        if client == "(choose)":
            st.error("Please choose a client.")
        else:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            profit_amt = round(float(amount) * float(profit_pct) / 100.0, 2)
            status = "In Process"
            new_row = [ts, display_name, client, float(amount), float(profit_pct), profit_amt, status]
            try:
                append_order_row(new_row)
                load_orders_df_cached.clear()
                st.success("✅ Order submitted.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to submit: {e}")

    st.divider()
    st.subheader("My recent submissions")
    df = load_orders_df_cached()
    mine = df[df["User"] == display_name].copy().sort_values("Timestamp", ascending=False).head(100)
    st.dataframe(mine, use_container_width=True)

# ------------------------- UI: Admin Tools ----------------------
def admin_tools(actor_display):
    st.subheader("🛠️ Admin tools")

    # Tabs for features
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Edit/Delete Orders", "Filter Presets", "Global Client Manager", "User Management", "Looker Studio"
    ])

    # --- Edit/Delete Orders ---
    with tab1:
        all_df = load_orders_with_rows()
        st.caption("Select a row to edit or delete. Reason is required.")
        st.dataframe(all_df.sort_values("Timestamp", ascending=False), use_container_width=True, height=320)

        # pick row by SheetRow
        sheet_row = st.number_input("Sheet row to modify (see leftmost 'SheetRow')", min_value=2, step=1)
        if sheet_row:
            current = all_df[all_df["SheetRow"]==sheet_row]
            if not current.empty:
                cur = current.iloc[0].to_dict()
                st.write(f"Editing row {sheet_row}:")
                col1, col2, col3 = st.columns(3)
                with col1:
                    new_client = st.text_input("Client", value=cur["Client"])
                with col2:
                    new_amount = st.number_input("Amount", value=float(cur.get("Amount",0.0)), step=0.01)
                with col3:
                    new_profit = st.number_input("Profit %", value=float(cur.get("ProfitPct",0.0)), step=0.1)
                reason = st.text_input("Reason (required)")

                cA, cB = st.columns(2)
                with cA:
                    if st.button("💾 Save changes"):
                        if not reason.strip():
                            st.error("Reason is required.")
                        else:
                            update_order_row(int(sheet_row),
                                             {"Client":new_client, "Amount":new_amount, "ProfitPct":new_profit},
                                             actor_display, reason, {k:cur.get(k,"") for k in EXPECTED_HEADER})
                            load_orders_df_cached.clear()
                            st.success("Updated.")
                            st.rerun()
                with cB:
                    if st.button("🗑️ Delete this order"):
                        if not reason.strip():
                            st.error("Reason is required.")
                        else:
                            delete_order_row(int(sheet_row), actor_display, reason, {k:cur.get(k,"") for k in EXPECTED_HEADER})
                            load_orders_df_cached.clear()
                            st.success("Deleted.")
                            st.rerun()
            else:
                st.info("Enter a valid Sheet row number from the table above.")

    # --- Filter Presets ---
    with tab2:
        df = load_orders_df_cached()
        users   = [""] + sorted(df["User"].dropna().unique().tolist())
        clients = [""] + sorted(df["Client"].dropna().unique().tolist())
        statuses = ["","In Process","Completed"]

        st.caption("Save current filters as a preset, or apply an existing one.")
        c1,c2,c3,c4,c5 = st.columns(5)
        with c1:
            sel_user = st.selectbox("User", users)
        with c2:
            sel_client = st.selectbox("Client", clients)
        with c3:
            sel_status = st.selectbox("Status", statuses)
        with c4:
            from_date = st.date_input("From (Timestamp)", value=None)
        with c5:
            to_date = st.date_input("To (Timestamp)", value=None)

        name = st.text_input("Preset name")
        if st.button("💾 Save preset"):
            if not name.strip():
                st.error("Give the preset a name.")
            else:
                save_preset(name, sel_user or "", sel_client or "", sel_status or "",
                            str(from_date) if from_date else "", str(to_date) if to_date else "", actor_display)
                st.success("Preset saved.")
                st.rerun()

        st.divider()
        presets = list_presets_df()
        if presets.empty:
            st.info("No presets yet.")
        else:
            st.dataframe(presets, use_container_width=True)
            pname = st.selectbox("Apply or delete preset", [""] + presets["Name"].tolist())
            cA, cB = st.columns(2)
            with cA:
                if st.button("✅ Apply preset"):
                    if pname:
                        row = presets[presets["Name"]==pname].iloc[0].to_dict()
                        st.session_state["preset_applied"] = row  # app reads this in dashboard filters
                        st.success(f"Applied preset '{pname}'. Go to dashboard filters above.")
            with cB:
                if st.button("🗑️ Delete preset"):
                    if pname:
                        delete_preset_by_name(pname, actor_display)
                        st.success("Preset deleted.")
                        st.rerun()

    # --- Global Client Manager ---
    with tab3:
        cdf = load_clients_df()
        st.dataframe(cdf.sort_values(["User","Client"]), use_container_width=True, height=320)
        st.markdown("**Add new client (for any user)**")
        users_df = get_active_users()
        add_u, add_c, add_d = st.columns([2,2,1])
        with add_u:
            chosen_user = st.selectbox("User (DisplayName)", users_df["DisplayName"].tolist())
        with add_c:
            new_client = st.text_input("Client name (global add)")
        with add_d:
            new_date = st.date_input("Open date", value=date.today())
        if st.button("➕ Add client (global)"):
            add_client(chosen_user, new_client, new_date)
            load_clients_df.clear()
            st.success("Client added.")
            st.rerun()

        st.divider()
        st.markdown("**Edit / Delete existing client**")
        rownum = st.number_input("Client Sheet row", min_value=2, step=1)
        if st.button("Load client row"):
            st.session_state["client_row_to_edit"] = int(rownum)
        if "client_row_to_edit" in st.session_state:
            row_id = st.session_state["client_row_to_edit"]
            row = cdf[cdf["SheetRow"]==row_id]
            if not row.empty:
                rec = row.iloc[0].to_dict()
                e1,e2,e3 = st.columns([2,2,1])
                with e1:
                    eu = st.text_input("User (DisplayName)", value=rec["User"])
                with e2:
                    ec = st.text_input("Client", value=rec["Client"])
                with e3:
                    try:
                        dt = pd.to_datetime(rec["OpenDate"]).date() if rec["OpenDate"] else date.today()
                    except Exception:
                        dt = date.today()
                    ed = st.date_input("OpenDate", value=dt)
                cA,cB = st.columns(2)
                with cA:
                    if st.button("💾 Save client"):
                        update_client(int(row_id), eu, ec, ed, actor_display)
                        load_clients_df.clear()
                        st.success("Client updated.")
                        st.rerun()
                with cB:
                    reason = st.text_input("Reason for delete (required)")
                    if st.button("🗑️ Delete client"):
                        if not reason.strip():
                            st.error("Reason is required.")
                        else:
                            delete_client_row(int(row_id), actor_display, reason, rec)
                            load_clients_df.clear()
                            st.success("Client deleted.")
                            st.rerun()
            else:
                st.info("Enter a valid client Sheet row.")

    # --- User Management ---
    with tab4:
        udf = load_users_df()
        st.dataframe(udf[["SheetRow","Username","DisplayName","Role","Active"]], use_container_width=True, height=320)

        st.markdown("**Add new user**")
        u1,u2,u3,u4 = st.columns([2,2,1,1])
        with u1:
            new_un = st.text_input("Username (no spaces)")
        with u2:
            new_dn = st.text_input("Display name")
        with u3:
            new_role = st.selectbox("Role", ["team","admin"])
        with u4:
            gen_pw = st.checkbox("Generate password", value=True)
        pw_val = random_password(12) if gen_pw else st.text_input("Password (plain)")

        if st.button("➕ Create user"):
            if not new_un or not new_dn:
                st.error("Username and Display name required.")
            else:
                ws = ensure_users_sheet_seed()
                # ensure unique username
                if not udf[udf["Username"]==new_un].empty:
                    st.error("Username already exists.")
                else:
                    ws.append_row([new_un, new_dn, new_role, pw_val, "TRUE"])
                    log_audit(actor_display, "ADD_USER", USERS_SHEET, "-", "-", None, {"Username":new_un})
                    st.success(f"User created. Password: {pw_val}")
                    st.rerun()

        st.divider()
        st.markdown("**Reset password / Change role / Activate or Deactivate**")
        sel_user = st.selectbox("Pick user", udf["Username"].tolist())
        if sel_user:
            row = udf[udf["Username"]==sel_user].iloc[0].to_dict()
            c1,c2,c3 = st.columns(3)
            with c1:
                new_role2 = st.selectbox("Role", ["team","admin"], index=0 if row["Role"]=="team" else 1)
            with c2:
                active2 = st.selectbox("Active", ["TRUE","FALSE"], index=0 if str(row["Active"]).upper() in ["TRUE","1","YES","Y"] else 1)
            with c3:
                new_pw2 = st.text_input("New password (leave blank to keep)")
            if st.button("💾 Update user"):
                ws = ensure_users_sheet_seed()
                ws.update(f"A{row['SheetRow']}:E{row['SheetRow']}",
                          [[row["Username"], row["DisplayName"], new_role2, new_pw2 or row["Password"], active2]])
                log_audit(actor_display, "UPDATE_USER", USERS_SHEET, row["SheetRow"], "-", None, {"Username":row["Username"]})
                st.success("User updated.")
                st.rerun()

    # --- Looker Studio ---
    with tab5:
        st.markdown("**Use this Google Sheet as the data source in Looker Studio**:")
        st.code(f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")
        st.write("- Data ranges:")
        st.write(f"  - Orders: `{ORDERS_SHEET}!A:G`  (Timestamp, User, Client, Amount, ProfitPct, ProfitAmt, Status)")
        st.write(f"  - Clients: `{CLIENTS_SHEET}!A:C`  (User, Client, OpenDate)")
        st.write(f"  - Users: `{USERS_SHEET}!A:E`  (Username, DisplayName, Role, Active)")
        st.info("In Looker Studio: Create → Data Source → Google Sheets → pick this file → select the tabs you need → Create Report.")

# ------------------------- UI: Dashboard ------------------------
def manager_dashboard(actor_display):
    st.title("📊 Manager Dashboard (Admin)")
    df = load_orders_df_cached()
    if df.empty:
        st.info("No reports yet.")
    # Filters (with preset apply)
    preset = st.session_state.pop("preset_applied", None)
    c1, c2, c3, c4, c5 = st.columns(5)
    users   = ["(All)"] + sorted(df["User"].dropna().unique().tolist())
    clients = ["(All)"] + sorted(df["Client"].dropna().unique().tolist())
    statuses = ["(All)", "In Process", "Completed"]

    def preset_or(default, key):
        return preset.get(key, default) if preset else default

    sel_user   = c1.selectbox("User", users, index=users.index(preset_or("(All)","User")) if preset and preset.get("User") in users else 0)
    sel_client = c2.selectbox("Client", clients, index=clients.index(preset_or("(All)","Client")) if preset and preset.get("Client") in clients else 0)
    sel_status = c3.selectbox("Status", statuses, index=statuses.index(preset_or("(All)","Status")) if preset and preset.get("Status") in statuses else 0)
    from_raw = preset_or("", "FromDate"); to_raw = preset_or("", "ToDate")
    sel_from = c4.date_input("From (Timestamp)", value=None if not from_raw else pd.to_datetime(from_raw).date())
    sel_to   = c5.date_input("To (Timestamp)",   value=None if not to_raw else pd.to_datetime(to_raw).date())

    # Apply filters
    f = df.copy()
    if sel_user != "(All)":   f = f[f["User"] == sel_user]
    if sel_client != "(All)": f = f[f["Client"] == sel_client]
    if sel_status != "(All)": f = f[f["Status"] == sel_status]
    if sel_from: f = f[pd.to_datetime(f["Timestamp"], errors="coerce") >= pd.to_datetime(sel_from)]
    if sel_to:   f = f[pd.to_datetime(f["Timestamp"], errors="coerce") <= pd.to_datetime(sel_to) + pd.Timedelta(days=1)]

    # KPIs
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Orders", f"{len(f):,}")
    k2.metric("Total Amount", f"${f['Amount'].sum():,.2f}")
    k3.metric("Completed %", f"{(100.0* (f['Status']=='Completed').mean()):.1f}%" if not f.empty else "0.0%")
    k4.metric("Unique Clients", f["Client"].nunique())

    st.divider()
    a,b = st.columns(2)
    with a:
        st.subheader("By Client (Amount)")
        if not f.empty:
            st.bar_chart(f.groupby("Client")["Amount"].sum().sort_values(ascending=False))
    with b:
        st.subheader("By User (Orders)")
        if not f.empty:
            st.bar_chart(f.groupby("User")["Amount"].count().sort_values(ascending=False))

    st.subheader("All Orders")
    st.dataframe(f.sort_values("Timestamp", ascending=False), use_container_width=True)
    st.download_button("⬇ Download CSV", f.to_csv(index=False).encode("utf-8"), "all_orders.csv", "text/csv")

    st.divider()
    admin_tools(actor_display)

# --------------------------- Auth + Router ----------------------
def render_login(dynamic_users: pd.DataFrame):
    st.sidebar.header("Login")
    # Only active users
    active = dynamic_users[dynamic_users["Active"].astype(str).str.upper().isin(["TRUE","1","YES","Y"])]
    usernames = active["Username"].tolist()
    if not usernames:
        st.sidebar.error("No active users found.")
        return
    username = st.sidebar.selectbox("User", usernames, format_func=lambda u: active[active["Username"]==u]["DisplayName"].iloc[0])
    password = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Login"):
        row = active[active["Username"]==username].iloc[0].to_dict()
        if password == row["Password"]:
            token = issue_token(row["Username"], row["DisplayName"])
            st.session_state[SESSION_TOKEN_KEY] = token
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
    import gspread
from gspread.exceptions import APIError

def debug_google_access():
    st.sidebar.markdown("### 🧪 Google Access Debug")
    # Show which service account we are actually using
    try:
        svc = _load_service_account_from_secrets()
        st.sidebar.write("Service account:", svc.get("client_email", "(missing)"))
    except Exception as e:
        st.sidebar.error(f"Could not read st.secrets['gcp_service_account']: {e}")
        return

    st.sidebar.write("SHEET_ID:", SHEET_ID)

    # Try to open the sheet
    try:
        gc = _gs_client()
        sh = gc.open_by_key(SHEET_ID)
        st.sidebar.success(f"Connected to: {sh.title}")
        st.sidebar.write("Worksheets:", [ws.title for ws in sh.worksheets()])
    except APIError as e:
        code = getattr(getattr(e, "response", None), "status_code", "n/a")
        try:
            msg = e.response.json().get("error", {}).get("message")
        except Exception:
            msg = str(e)
        st.sidebar.error(f"APIError HTTP {code}: {msg}")
        st.sidebar.caption("Most common fixes: share the Sheet with the service account as Editor; check SHEET_ID; ensure secrets JSON matches the active key.")
    except Exception as ex:
        st.sidebar.error(f"Unexpected error: {ex}")

    init_all_sheets()  # ensure tabs exist
    cookies = cookie_manager.get_all()

    # Handle logout cycle
    if st.session_state.get(POST_LOGOUT_FLAG):
        if cookies and cookies.get(COOKIE_NAME):
            clear_cookie(); st.info("Logging out…"); st.stop()
        st.session_state.pop(POST_LOGOUT_FLAG, None)
        render_login(get_active_users()); st.stop()

    # Fresh session token → route immediately and set cookie if needed
    sess_token = st.session_state.get(SESSION_TOKEN_KEY)
    if sess_token:
        user = verify_token(sess_token)
        if user:
            # Check user still active
            rec = get_user_record(user["username"])
            if not rec or not rec["Active"]:
                st.warning("Your account is inactive. Contact admin.")
                st.session_state.pop(SESSION_TOKEN_KEY, None)
                clear_cookie()
                render_login(get_active_users()); st.stop()
            if cookies is not None and not cookies.get(COOKIE_NAME):
                set_cookie(sess_token)
            render_logout_panel(user["name"])
            if rec["Role"] == "admin":
                manager_dashboard(user["name"])
            else:
                team_reporter(user["name"])
            return

    # Returning visit → use cookie
    if cookies is None: st.stop()
    token_from_cookie = cookies.get(COOKIE_NAME)
    user = verify_token(token_from_cookie) if token_from_cookie else None
    if user:
        rec = get_user_record(user["username"])
        if not rec or not rec["Active"]:
            st.warning("Your account is inactive. Contact admin.")
            clear_cookie()
            render_login(get_active_users()); st.stop()
        render_logout_panel(user["name"])
        if rec["Role"] == "admin":
            manager_dashboard(user["name"])
        else:
            team_reporter(user["name"])
        return

    # No auth → show login
    render_login(get_active_users()); st.stop()

# --------------------------- Main -------------------------------
if __name__ == "__main__":
    st.title(APP_TITLE)
    main_router()
    debug_google_access()

