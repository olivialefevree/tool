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
