"""
rebalancing.py
Rebalancing recommendations — connects idle equipment (Part 1) to forecasted
demand (Part 3) to recommend proactive repositioning before a customer asks.
Depends on rhythm_engine.py, forecast.py, and overdue_alerts.py.
"""

from datetime import date, timedelta
import pandas as pd
from rhythm_engine import load_data, build_rhythm_profile
from forecast import forecast_demand
from overdue_alerts import compute_risk_score, latest_booking_per_equipment, compute_due_date, flag_data_anomalies

TRANSIT_TIME_DAYS = 3
BUFFER_DAYS = 2
HIGH_IDLE_THRESHOLD = 0.6


def is_currently_committed(df, as_of):
    """True if as_of falls between Check-In and Check-Out — i.e. someone is
    actively paying for this machine right now."""
    as_of_ts = pd.Timestamp(as_of)
    return (df["Check-In Date"] <= as_of_ts) & (as_of_ts <= df["Check-Out Date"])


def eligibility_report(df, as_of=None):
    """
    Tags every piece of equipment as:
      - eligible_for_rebalancing: idle AND not currently committed → free to move
      - underutilized_but_committed: idle BUT mid-rental → billing insight only, no move
      - top_priority: idle + overdue + unassigned → most urgent

    Anomaly rows (no operator/no site) are excluded from all three buckets
    since we can't safely act on their location/ownership data.
    """
    if as_of is None:
        as_of = date.today()
    as_of_ts = pd.Timestamp(as_of)

    flagged = flag_data_anomalies(df)
    clean = flagged[~flagged["is_data_anomaly"]].copy()

    scored = compute_risk_score(clean, as_of)
    latest = latest_booking_per_equipment(scored, as_of)
    latest = compute_due_date(latest)

    latest["is_committed"] = is_currently_committed(latest, as_of)
    latest["eligible_for_rebalancing"] = (~latest["is_committed"]) & (latest["idle_ratio"] > HIGH_IDLE_THRESHOLD)
    latest["underutilized_but_committed"] = latest["is_committed"] & (latest["idle_ratio"] > HIGH_IDLE_THRESHOLD)

    is_overdue = (latest["due_date"] < as_of_ts) & (~latest["is_committed"])
    is_unassigned = latest["Last Operator ID"].isna()
    latest["top_priority"] = latest["idle_ratio"].gt(HIGH_IDLE_THRESHOLD) & is_overdue & is_unassigned

    return latest


def recommend_moves(df, as_of=None):
    """
    For each genuinely-free idle machine at Site A: check if the same Type
    is trending/spiking at another Site B, and whether transit + buffer time
    still lands before that site's forecasted need date. If so, recommend
    the move — proactively, before any customer request comes in.
    """
    if as_of is None:
        as_of = date.today()

    tagged = eligibility_report(df, as_of)
    forecast = forecast_demand(df)
    profile = build_rhythm_profile(df)

    spiking = profile[profile["spike_detected"]][["Site ID", "Type"]].drop_duplicates()

    recommendations = []
    eligible_rows = tagged[tagged["eligible_for_rebalancing"]]

    for _, row in eligible_rows.iterrows():
        equip_type = row["Type"]
        home_site = row["Site ID"]

        candidates = spiking[(spiking["Type"] == equip_type) & (spiking["Site ID"] != home_site)]
        if candidates.empty:
            continue

        type_forecast = forecast[forecast["Type"] == equip_type]
        best = None
        for _, cand in candidates.iterrows():
            match = type_forecast[type_forecast["Site ID"] == cand["Site ID"]]
            if not match.empty:
                fc = match.iloc[0]
                if best is None or fc["forecast_count"] > best["forecast_count"]:
                    best = fc

        if best is None:
            continue

        forecast_month_start = pd.Period(best["forecast_month"]).start_time
        arrival_date = pd.Timestamp(as_of) + timedelta(days=TRANSIT_TIME_DAYS + BUFFER_DAYS)

        if arrival_date <= forecast_month_start + pd.Timedelta(days=27):
            recommendations.append({
                "Equipment ID": row["Equipment ID"],
                "Type": equip_type,
                "from_site": home_site,
                "to_site": best["Site ID"],
                "idle_ratio": round(row["idle_ratio"], 3),
                "destination_confidence": best["confidence"],
                "destination_forecast_count": best["forecast_count"],
                "recommended_arrival_by": arrival_date.date(),
            })

    return pd.DataFrame(recommendations)


if __name__ == "__main__":
    df = load_data("dataset/bookings.csv")

    tagged = eligibility_report(df)

    print("--- TOP PRIORITY (idle + overdue + unassigned) ---")
    tp = tagged[tagged["top_priority"]][["Equipment ID", "Type", "Site ID", "idle_ratio"]]
    print(tp.to_string(index=False) if not tp.empty else "None")

    print("\n--- UNDERUTILIZED BUT COMMITTED (billing insight, no move) ---")
    uc = tagged[tagged["underutilized_but_committed"]][["Equipment ID", "Type", "Site ID", "idle_ratio"]]
    print(uc.to_string(index=False) if not uc.empty else "None")

    print("\n--- MOVE RECOMMENDATIONS ---")
    moves = recommend_moves(df)
    print(moves.to_string(index=False) if not moves.empty else "None")