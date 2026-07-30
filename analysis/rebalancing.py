"""
rebalancing.py
Rebalancing recommendations — the final layer.
Depends on rhythm_engine.py, forecast.py, and overdue_alerts.py
(all must be in the same analysis/ folder).
"""

from datetime import date, timedelta
import pandas as pd
from rhythm_engine import load_data, build_rhythm_profile
from forecast import forecast_demand
from overdue_alerts import compute_risk_score, latest_booking_per_equipment

# ASSUMPTION: transit time between sites isn't in the dataset, so this is a
# flat placeholder. Swap for a real Site-to-Site distance/time lookup if
# your team has one — this is the one number in the whole module that's
# not derived directly from your columns.
TRANSIT_TIME_DAYS = 3
BUFFER_DAYS = 2
HIGH_IDLE_THRESHOLD = 0.6  # idle_ratio above this = "high idle" at a site


def is_currently_committed(df, as_of):
    """is_currently_committed = simulated_today between Check-In and Check-Out."""
    as_of_ts = pd.Timestamp(as_of)
    return (df["Check-In Date"] <= as_of_ts) & (as_of_ts <= df["Check-Out Date"])


def eligibility_report(df, as_of):
    """
    Tags every piece of equipment as:
      - eligible_for_rebalancing (idle, not currently committed)
      - underutilized_but_committed (idle, but mid-rental — billing insight, no move)
      - top_priority (idle + overdue + unassigned)

    Risk scores are computed on the FULL dataset (so type averages stay
    accurate), then collapsed to one row per Equipment ID (latest STARTED
    booking as of as_of, via the shared function in overdue_alerts.py) before
    tagging — so each physical machine only shows up once, based on its true
    current status.
    """
    scored = compute_risk_score(df)  # full history, accurate type averages
    latest = latest_booking_per_equipment(scored, as_of)  # one row per machine, status-accurate

    latest["is_committed"] = is_currently_committed(latest, as_of)
    latest["eligible_for_rebalancing"] = (~latest["is_committed"]) & (latest["idle_ratio"] > HIGH_IDLE_THRESHOLD)
    latest["underutilized_but_committed"] = latest["is_committed"] & (latest["idle_ratio"] > HIGH_IDLE_THRESHOLD)

    as_of_ts = pd.Timestamp(as_of)
    is_overdue = (latest["Check-Out Date"] < as_of_ts) & (~latest["is_committed"])
    is_unassigned = latest["Last Operator ID"].isna()
    latest["top_priority"] = latest["idle_ratio"].gt(HIGH_IDLE_THRESHOLD) & is_overdue & is_unassigned

    return latest


def recommend_moves(df, as_of):
    """
    For each eligible idle piece of equipment (latest STARTED booking only)
    at Site A, checks if the same Type is trending/spiking at another Site B,
    and whether transit + buffer still beats the forecasted need date.
    """
    tagged = eligibility_report(df, as_of)   # already deduped to latest-per-equipment
    forecast = forecast_demand(df)
    profile = build_rhythm_profile(df)

    spiking = profile[profile["spike_detected"]][["Site ID", "Type"]].drop_duplicates()

    recommendations = []
    eligible_rows = tagged[tagged["eligible_for_rebalancing"]]

    for _, row in eligible_rows.iterrows():
        equip_type = row["Type"]
        home_site = row["Site ID"]

        # candidate destination sites: same Type, spiking, different site
        candidates = spiking[(spiking["Type"] == equip_type) & (spiking["Site ID"] != home_site)]
        if candidates.empty:
            continue

        # pick the candidate with the highest forecasted demand for that type
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

        if arrival_date <= forecast_month_start + pd.Timedelta(days=27):  # within the forecast month
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

    SIMULATED_TODAY = date(2026, 7, 30)  # adjust to match your demo date

    tagged = eligibility_report(df, SIMULATED_TODAY)

    print("--- TOP PRIORITY (idle + overdue + unassigned) ---")
    tp = tagged[tagged["top_priority"]][["Equipment ID", "Type", "Site ID", "idle_ratio"]]
    print(tp.to_string(index=False) if not tp.empty else "None")

    print("\n--- UNDERUTILIZED BUT COMMITTED (billing insight, no move) ---")
    uc = tagged[tagged["underutilized_but_committed"]][["Equipment ID", "Type", "Site ID", "idle_ratio"]]
    print(uc.to_string(index=False) if not uc.empty else "None")

    print("\n--- MOVE RECOMMENDATIONS ---")
    moves = recommend_moves(df, SIMULATED_TODAY)
    print(moves.to_string(index=False) if not moves.empty else "None")