"""
overdue_alerts.py
Overdue Alerts & Notification module — risk score + escalation logic.

"today" is simulated via a variable (as_of_date), never real-time,
so overdue status can be demoed live by moving the date.

IMPORTANT: only each Equipment ID's most recent booking that has actually
STARTED by as_of is evaluated — otherwise old, already-superseded rental
records (equipment that's since been re-rented) would incorrectly show up
as permanently overdue.
"""

from datetime import date, timedelta
import pandas as pd

ESCALATION_TABLE = [
    (1, 2,   "Neutral reminder", "In-app",       "Renter/site",          "Yellow"),
    (3, 5,   "Firm",             "In-app+SMS",    "+Supervisor",          "Orange"),
    (6, 9,   "Escalated",        "+Email",         "Dealer ops",          "Red"),
    (10, float("inf"), "Critical", "All channels", "Recovery/audit team", "Red pulsing"),
]


def load_data(csv_path):
    df = pd.read_csv(csv_path, dtype=str)
    df = df.replace(r'^\s*$', pd.NA, regex=True)

    numeric_cols = ["Engine Hours/Day", "Idle Hours/Day", "Rental Days"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["Check-In Date", "Check-Out Date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    return df


def compute_risk_score(df):
    df = df.copy()

    total_hours = df["Engine Hours/Day"] + df["Idle Hours/Day"]
    df["idle_ratio"] = (df["Idle Hours/Day"] / total_hours).fillna(0)

    type_avg_days = df.groupby("Type")["Rental Days"].transform("mean")
    raw_overrun = df["Rental Days"] / type_avg_days
    df["duration_overrun"] = raw_overrun.clip(upper=2.0) / 2.0

    df["risk_score"] = 0.5 * df["idle_ratio"] + 0.5 * df["duration_overrun"]

    df["risk_tier"] = pd.cut(
        df["risk_score"],
        bins=[-0.01, 0.33, 0.66, 1.0],
        labels=["Low", "Medium", "High"],
    )
    return df


def latest_booking_per_equipment(df, as_of):
    """
    Collapses to one row per Equipment ID = its most recent booking that
    has actually STARTED by as_of (Check-In <= as_of). This is the
    "current status snapshot" — it prevents old, already-superseded
    rental records from being flagged as still overdue.
    """
    as_of_ts = pd.Timestamp(as_of)
    started = df[df["Check-In Date"] <= as_of_ts]

    if started.empty:
        return df.iloc[0:0]

    return (
        started.sort_values("Check-Out Date")
        .groupby("Equipment ID", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )


def _effective_due_date(check_out):
    if pd.isna(check_out):
        return check_out
    if check_out.weekday() in (5, 6):   # Sat or Sun
        return check_out - timedelta(days=1)
    return check_out


def _escalation_row(days_overdue):
    for min_d, max_d, message, channel, notified, badge in ESCALATION_TABLE:
        if min_d <= days_overdue <= max_d:
            return message, channel, notified, badge
    return None


def flag_overdue(df, as_of, grace_days=0):
    scored = compute_risk_score(df)          # full history -> accurate type averages
    latest = latest_booking_per_equipment(scored, as_of)   # current status only

    as_of_ts = pd.Timestamp(as_of)
    # NOTE: overdue day-count uses the actual Check-Out Date, unshifted.
    # The weekend rule only affects when reminders fire (see flag_pre_due),
    # not how many days something is counted as overdue.
    latest["due_with_grace"] = latest["Check-Out Date"] + pd.Timedelta(days=grace_days)
    latest["days_overdue"] = (as_of_ts - latest["due_with_grace"]).dt.days

    overdue = latest[latest["days_overdue"] >= 1].copy()

    esc = overdue["days_overdue"].apply(_escalation_row)
    overdue["escalation_message"] = esc.apply(lambda x: x[0] if x else None)
    overdue["channel"] = esc.apply(lambda x: x[1] if x else None)
    overdue["notified"] = esc.apply(lambda x: x[2] if x else None)
    overdue["badge"] = esc.apply(lambda x: x[3] if x else None)

    cols = ["Equipment ID", "Type", "Site ID", "Check-Out Date", "days_overdue",
            "risk_score", "risk_tier", "escalation_message", "channel",
            "notified", "badge"]
    return overdue[cols].sort_values("days_overdue", ascending=False).reset_index(drop=True)


def flag_pre_due(df, as_of):
    scored = compute_risk_score(df)
    latest = latest_booking_per_equipment(scored, as_of)

    as_of_ts = pd.Timestamp(as_of)
    # Weekend rule lives HERE only: if the real Check-Out Date is a Sat/Sun,
    # the reminder fires a day earlier (on the Friday) than it otherwise would.
    latest["effective_due"] = latest["Check-Out Date"].apply(_effective_due_date)
    latest["days_until_due"] = (latest["effective_due"] - as_of_ts).dt.days

    latest["reminder_window"] = latest["risk_tier"].apply(lambda t: 5 if t == "High" else 3)
    pending = latest[
        (latest["days_until_due"] >= 0) &
        (latest["days_until_due"] <= latest["reminder_window"])
    ].copy()

    cols = ["Equipment ID", "Type", "Site ID", "Check-Out Date",
            "days_until_due", "risk_score", "risk_tier", "reminder_window"]
    return pending[cols].sort_values("days_until_due").reset_index(drop=True)

if __name__ == "__main__":
    df = load_data("dataset/bookings.csv")

    #SIMULATED_TODAY = date(2026, 7, 30)
    SIMULATED_TODAY = date(2026, 7, 28)

    overdue = flag_overdue(df, as_of=SIMULATED_TODAY, grace_days=0)
    print(f"--- OVERDUE ({len(overdue)}) ---")
    print(overdue.to_string(index=False) if not overdue.empty else "None")

    print()
    pre_due = flag_pre_due(df, as_of=SIMULATED_TODAY)
    print(f"--- PRE-DUE REMINDERS ({len(pre_due)}) ---")
    print(pre_due.to_string(index=False) if not pre_due.empty else "None")