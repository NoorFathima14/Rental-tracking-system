"""
overdue_alerts.py
Overdue Alerts & Notification Engine — risk score + escalation + anomaly detection.

Overdue rule: due_date = Check-In Date + Rental Days.
A booking is overdue once the real current date has passed due_date + grace_days.
as_of defaults to date.today() — no simulated/manual date anywhere.
"""

from datetime import date
import pandas as pd

# Escalation now keyed on OVERRUN RATIO (elapsed / expected duration for
# that equipment type), not a flat day count — a 5-day overrun means very
# different things for a 3-day rental vs a 60-day rental.
ESCALATION_TABLE = [
    (1.00, 1.25, "Neutral reminder", "In-app",        "Renter/site",         "Yellow"),
    (1.25, 1.60, "Firm",             "In-app+SMS",    "+Supervisor",          "Orange"),
    (1.60, 2.20, "Escalated",        "+Email",        "Dealer ops",           "Red"),
    (2.20, float("inf"), "Critical", "All channels",  "Recovery/audit team",  "Red pulsing"),
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


def flag_data_anomalies(df):
    """
    PART 2 (new): if a row has no Last Operator ID or no Site ID, there's
    literally nobody to notify — flag it as a data anomaly instead of
    silently dropping it or (worse) letting it fall through the escalation
    logic and never get looked at.
    """
    df = df.copy()
    df["missing_operator"] = df["Last Operator ID"].isna()
    df["missing_site"] = df["Site ID"].isna()
    df["is_data_anomaly"] = df["missing_operator"] | df["missing_site"]

    reasons = []
    for _, row in df.iterrows():
        r = []
        if row["missing_operator"]:
            r.append("no operator on record")
        if row["missing_site"]:
            r.append("no site on record")
        reasons.append("; ".join(r) if r else None)
    df["anomaly_reason"] = reasons

    return df


def compute_risk_score(df, as_of):
    """
    PART 1: risk = 0.5 * idle_ratio + 0.5 * duration_overrun

    - idle_ratio: fraction of a machine's logged hours spent idle vs running.
    - duration_overrun: elapsed rental time so far vs the TYPICAL rental
      length for that equipment Type, clipped at 2x so one extreme outlier
      doesn't blow out the whole scale. Uses ACTUAL elapsed time (as_of -
      Check-In), not the planned Rental Days, so risk updates every day
      the machine is still out — a rental running 15 days past plan is
      riskier than one that already came back on time.
    """
    df = df.copy()
    as_of_ts = pd.Timestamp(as_of)

    total_hours = df["Engine Hours/Day"] + df["Idle Hours/Day"]
    df["idle_ratio"] = (df["Idle Hours/Day"] / total_hours).fillna(0)

    elapsed_days = (as_of_ts - df["Check-In Date"]).dt.days.clip(lower=0)
    type_avg_days = df.groupby("Type")["Rental Days"].transform("mean")

    df["overrun_ratio"] = elapsed_days / type_avg_days  # used for escalation tier
    df["duration_overrun"] = df["overrun_ratio"].clip(upper=2.0) / 2.0  # used for risk score

    df["risk_score"] = 0.5 * df["idle_ratio"] + 0.5 * df["duration_overrun"]
    df["risk_tier"] = pd.cut(
        df["risk_score"],
        bins=[-0.01, 0.33, 0.66, 1.0],
        labels=["Low", "Medium", "High"],
    )
    return df


def latest_booking_per_equipment(df, as_of):
    """One row per Equipment ID = its most recent booking that has actually
    STARTED by as_of. Prevents stale, superseded records from being flagged."""
    as_of_ts = pd.Timestamp(as_of)
    started = df[df["Check-In Date"] <= as_of_ts]

    if started.empty:
        return df.iloc[0:0]

    return (
        started.sort_values("Check-In Date")
        .groupby("Equipment ID", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )


def compute_due_date(df):
    df = df.copy()
    df["due_date"] = df["Check-In Date"] + pd.to_timedelta(df["Rental Days"], unit="D")
    return df


def _escalation_row(overrun_ratio):
    for min_r, max_r, message, channel, notified, badge in ESCALATION_TABLE:
        if min_r <= overrun_ratio < max_r:
            return message, channel, notified, badge
    return None


def get_all_operator_ids(df):
    return sorted(df["Last Operator ID"].dropna().unique().tolist())


def _build_notification_text(row):
    equip = f"{row['Type']} {row['Equipment ID']}"
    if row["status"] == "OVERDUE":
        return f"⚠ {equip}: return overdue by {row['days_overdue']} day(s). {row['notified']} notified."
    elif row["status"] == "DUE_TOMORROW":
        return f"🟡 {equip}: return due tomorrow."
    elif row["status"] == "DUE_SOON":
        return f"🟢 {equip}: upcoming return in {row['days_until_due']} day(s)."
    return f"{equip}: status unknown."


def generate_notifications(df, as_of=None, operator_id=None, grace_days=0, upcoming_window=3):
    """
    Unified notification panel: PRE-DUE reminders (before the due date, so
    people get a heads-up) + OVERDUE escalation, in one prioritized list.
    Data anomalies (no operator/site) are split off separately so they
    don't silently disappear or get sent nowhere.
    """
    if as_of is None:
        as_of = date.today()
    as_of_ts = pd.Timestamp(as_of)

    anomalies = flag_data_anomalies(df)
    clean = anomalies[~anomalies["is_data_anomaly"]].copy()
    anomaly_rows = anomalies[anomalies["is_data_anomaly"]].copy()

    scored = compute_risk_score(clean, as_of)
    latest = latest_booking_per_equipment(scored, as_of)
    latest = compute_due_date(latest)

    latest["due_with_grace"] = latest["due_date"] + pd.Timedelta(days=grace_days)
    latest["days_overdue"] = (as_of_ts - latest["due_with_grace"]).dt.days
    latest["days_until_due"] = (latest["due_date"] - as_of_ts).dt.days

    if operator_id is not None:
        latest = latest[latest["Last Operator ID"] == operator_id]

    # --- Overdue slice ---
    overdue = latest[latest["days_overdue"] >= 1].copy()
    esc = overdue["overrun_ratio"].apply(_escalation_row)
    overdue["escalation_message"] = esc.apply(lambda x: x[0] if x else None)
    overdue["channel"] = esc.apply(lambda x: x[1] if x else None)
    overdue["notified"] = esc.apply(lambda x: x[2] if x else None)
    overdue["badge"] = esc.apply(lambda x: x[3] if x else None)
    overdue["status"] = "OVERDUE"
    overdue["priority"] = 100 + overdue["risk_score"] * overdue["days_overdue"]

    # --- Pre-due slice (BEFORE the rental is due — the "notify before due date" ask) ---
    pending = latest[
        (latest["days_until_due"] >= 0) &
        (latest["days_until_due"] <= upcoming_window)
    ].copy()
    pending["status"] = pending["days_until_due"].apply(lambda d: "DUE_TOMORROW" if d <= 1 else "DUE_SOON")
    pending["escalation_message"] = None
    pending["channel"] = "In-app"
    pending["notified"] = "Renter/site"
    pending["badge"] = pending["status"].apply(lambda s: "Orange" if s == "DUE_TOMORROW" else "Yellow")
    pending["priority"] = pending["risk_score"] * (upcoming_window - pending["days_until_due"] + 1)

    combined = pd.concat([overdue, pending], ignore_index=True)
    combined["notification_text"] = combined.apply(_build_notification_text, axis=1)

    cols = ["Equipment ID", "Type", "Site ID", "Last Operator ID", "status",
            "notification_text", "priority", "risk_score", "risk_tier",
            "badge", "channel", "notified", "due_date",
            "days_overdue", "days_until_due"]

    result = combined[cols].sort_values("priority", ascending=False).reset_index(drop=True)
    return result, anomaly_rows


if __name__ == "__main__":
    df = load_data("dataset/bookings.csv")

    operators = get_all_operator_ids(df)
    print(f"--- OPERATOR DROPDOWN OPTIONS ({len(operators)}) ---")
    print(operators)

    panel_all, anomalies = generate_notifications(df)
    print(f"\n--- NOTIFICATION PANEL, ALL OPERATORS ({len(panel_all)}) ---")
    print(panel_all.to_string(index=False) if not panel_all.empty else "None")

    print(f"\n--- DATA ANOMALIES — nobody to notify ({len(anomalies)}) ---")
    if not anomalies.empty:
        print(anomalies[["Equipment ID", "Type", "Site ID", "Last Operator ID", "anomaly_reason"]].to_string(index=False))
    else:
        print("None")