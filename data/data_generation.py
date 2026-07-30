# """
# Synthetic Data Generator — Smart Rental Tracking System
# =========================================================
# Generates a fleet of equipment, a year of rental bookings, and daily usage
# logs (engine hrs, idle hrs, fuel, location), with:
#   - overall seasonal demand trend (low in winter, peak around July)
#   - per-site behavioural profiles (e.g. waterlogging site -> high idle in monsoon)
#   - realistic per-type engine/idle/fuel patterns (Crane can legitimately be 0 engine hrs)
#   - injectable anomalies via a standalone function you can call as many times as you want

# Every function is independent so you can re-run just the piece you need
# (e.g. call `inject_anomalies()` again later to add more bad rows).

# Output columns match your base sample table, plus a `usage_logs` table for
# daily-level fuel/location/idle detail (needed for the Usage Logging module).
# """

# import numpy as np
# import pandas as pd
# from datetime import date, timedelta

# RNG = np.random.default_rng(42)  # fixed seed -> reproducible demo data

# # ---------------------------------------------------------------------------
# # 1. REFERENCE DATA
# # ---------------------------------------------------------------------------

# EQUIPMENT_TYPES = ["Excavator", "Crane", "Bulldozer", "Grader"]

# # 5 sites, each with a distinct behavioural profile.
# # `profile` is used later by site_idle_modifier() / site_demand_modifier().
# SITES = {
#     "S001": {"name": "Site S001 - Coastal Lowland",     "profile": "waterlogging"},
#     "S002": {"name": "Site S002 - Urban Core",           "profile": "steady"},
#     "S003": {"name": "Site S003 - Highland Quarry",      "profile": "pre_monsoon_peak"},
#     "S004": {"name": "Site S004 - Rural Highway",        "profile": "winter_slowdown"},
#     "S005": {"name": "Site S005 - New Development Zone", "profile": "ramping_up"},
# }
# SITE_IDS = list(SITES.keys())

# # Small, fixed operator pool (per your note: keep it small to see patterns repeat)
# OPERATORS = [f"OP10{i}" for i in range(1, 9)]  # OP101 ... OP108

# # Fixed fleet: 4 units per equipment type = 16 machines total
# FLEET_SIZE_PER_TYPE = 4


# def build_fleet():
#     """Create the fixed equipment fleet (equipment_id <-> type mapping)."""
#     fleet = []
#     eq_counter = 1001
#     for eq_type in EQUIPMENT_TYPES:
#         for _ in range(FLEET_SIZE_PER_TYPE):
#             fleet.append({"equipment_id": f"EQX{eq_counter}", "type": eq_type})
#             eq_counter += 1
#     return pd.DataFrame(fleet)


# # ---------------------------------------------------------------------------
# # 2. SEASONAL / SITE PATTERN FUNCTIONS
# #    (kept separate so you can tune each independently)
# # ---------------------------------------------------------------------------

# def overall_seasonal_demand_weight(month: int) -> float:
#     """
#     Overall fleet-wide demand weight by month (1-12).
#     Low in winter (Dec-Feb), ramps up, peaks around July, tapers after.
#     Returned value scales the probability a booking starts in that month.
#     """
#     weights = {
#         1: 0.5, 2: 0.5, 3: 0.7, 4: 0.9, 5: 1.0,
#         6: 1.1, 7: 1.3, 8: 1.2, 9: 1.0, 10: 0.9,
#         11: 0.7, 12: 0.5,
#     }
#     return weights[month]


# def site_idle_modifier(site_id: str, current_date: date) -> float:
#     """
#     Multiplier applied to a day's idle hours based on site profile + date.
#     >1 means "more idle than normal" (e.g. waterlogging shuts work down).
#     """
#     profile = SITES[site_id]["profile"]
#     month = current_date.month

#     if profile == "waterlogging":
#         # Monsoon months: Jun-Sep -> heavy idle spike
#         return 2.5 if month in (6, 7, 8, 9) else 1.0

#     if profile == "winter_slowdown":
#         # Workforce/holiday slowdown Dec-Feb -> more idle
#         return 1.8 if month in (12, 1, 2) else 1.0

#     if profile == "pre_monsoon_peak":
#         # Very active Mar-May (low idle), quieter/more idle Jun-Sep (monsoon access issues)
#         if month in (3, 4, 5):
#             return 0.6
#         if month in (6, 7, 8, 9):
#             return 1.6
#         return 1.0

#     if profile == "ramping_up":
#         # New site: starts underused (high idle), idle shrinks as year progresses
#         return max(1.6 - (month - 1) * 0.1, 0.7)

#     return 1.0  # "steady" profile - no seasonal effect


# def site_demand_modifier(site_id: str) -> float:
#     """Relative booking-frequency weight per site (independent of season)."""
#     profile = SITES[site_id]["profile"]
#     return {
#         "waterlogging": 0.9,
#         "steady": 1.3,          # urban core -> consistently busiest site
#         "pre_monsoon_peak": 1.0,
#         "winter_slowdown": 0.8,
#         "ramping_up": 0.7,      # new site -> fewer bookings overall
#     }[profile]


# # Baseline expected engine-hours/day and idle-hours/day per equipment type,
# # before site/season modifiers are applied.
# TYPE_BASELINES = {
#     # engine_hours_mean, idle_hours_mean, fuel_active_lph, fuel_idle_lph
#     "Excavator": {"engine_mean": 6.5, "idle_mean": 3.0, "fuel_active": 18, "fuel_idle": 4},
#     "Crane":     {"engine_mean": 3.0, "idle_mean": 6.0, "fuel_active": 12, "fuel_idle": 2},
#     "Bulldozer": {"engine_mean": 7.0, "idle_mean": 2.5, "fuel_active": 22, "fuel_idle": 5},
#     "Grader":    {"engine_mean": 5.5, "idle_mean": 3.5, "fuel_active": 15, "fuel_idle": 3},
# }


# # ---------------------------------------------------------------------------
# # 3. BOOKING GENERATION (the summary table matching your base sample)
# # ---------------------------------------------------------------------------

# def generate_bookings(fleet_df: pd.DataFrame, start_date: date, end_date: date, num_bookings: int = 1400) -> pd.DataFrame:
#     """
#     Generates rental bookings across an arbitrary date range (can span multiple years).
#     Each (year, month) combo in the range is weighted by overall_seasonal_demand_weight()
#     using its calendar month, so seasonality repeats correctly across both 2025 and 2026.
#     """
#     # Build list of every (year, month) pair in the range
#     year_months = []
#     y, m = start_date.year, start_date.month
#     while (y, m) <= (end_date.year, end_date.month):
#         year_months.append((y, m))
#         m += 1
#         if m > 12:
#             m = 1
#             y += 1

#     month_weights = np.array([overall_seasonal_demand_weight(m) for (_, m) in year_months])
#     month_probs = month_weights / month_weights.sum()

#     site_weights = np.array([site_demand_modifier(s) for s in SITE_IDS])
#     site_probs = site_weights / site_weights.sum()

#     rows = []
#     for i in range(num_bookings):
#         eq_row = fleet_df.sample(1, random_state=RNG.integers(0, 1_000_000)).iloc[0]
#         equipment_id, eq_type = eq_row["equipment_id"], eq_row["type"]

#         ym_idx = RNG.choice(len(year_months), p=month_probs)
#         year, month = year_months[ym_idx]
#         day = RNG.integers(1, 28)
#         checkin_date = date(year, month, day)

#         site_id = RNG.choice(SITE_IDS, p=site_probs)

#         rental_days = int(RNG.integers(7, 31))
#         checkout_date = checkin_date + timedelta(days=rental_days)

#         operator_id = RNG.choice(OPERATORS)

#         baseline = TYPE_BASELINES[eq_type]
#         idle_mult = site_idle_modifier(site_id, checkin_date)

#         engine_hours_day = max(0, RNG.normal(baseline["engine_mean"], 1.2))
#         idle_hours_day = max(0, RNG.normal(baseline["idle_mean"] * idle_mult, 1.0))

#         if eq_type == "Crane" and RNG.random() < 0.25:
#             engine_hours_day = 0.0

#         rows.append({
#             "Equipment ID": equipment_id,
#             "Type": eq_type,
#             "Site ID": site_id,
#             "Check-In Date": checkin_date,
#             "Check-Out Date": checkout_date,
#             "Engine Hours/Day": round(engine_hours_day, 1),
#             "Idle Hours/Day": round(idle_hours_day, 1),
#             "Rental Days": rental_days,
#             "Last Operator ID": operator_id,
#         })

#     df = pd.DataFrame(rows)
#     df["booking_id"] = [f"BKG{1000+i}" for i in range(len(df))]
#     return df

# def recompute_rental_days(df: pd.DataFrame) -> pd.DataFrame:
#     """Utility: rental days must always be derived from checkin/checkout dates.
#     Check-Out Date (return) is later than Check-In Date (equipment goes out)."""
#     df = df.copy()
#     df["Rental Days"] = (
#         pd.to_datetime(df["Check-Out Date"]) - pd.to_datetime(df["Check-In Date"])
#     ).dt.days
#     return df


# # ---------------------------------------------------------------------------
# # 4. ANOMALY INJECTION — call this as many times as you like to add more
# # ---------------------------------------------------------------------------

# def inject_anomalies(df: pd.DataFrame, num_anomalies: int = 5, anomaly_types: list = None) -> pd.DataFrame:
#     """
#     Injects anomalies into a COPY of the bookings dataframe and returns it.
#     Call this multiple times (on the growing df) to keep adding more anomalies.

#     anomaly_types: subset of
#         ["missing_site", "missing_operator", "zero_engine_nonCrane",
#          "excessive_idle", "negative_or_zero_rental_days"]
#         If None, picks randomly from all types each call.
#     """
#     df = df.copy()
#     all_types = [
#         "missing_site", "missing_operator", "zero_engine_nonCrane",
#         "excessive_idle", "negative_or_zero_rental_days",
#     ]
#     types_pool = anomaly_types if anomaly_types else all_types

#     idx_choices = RNG.choice(df.index, size=min(num_anomalies, len(df)), replace=False)

#     for idx in idx_choices:
#         anomaly = RNG.choice(types_pool)

#         if anomaly == "missing_site":
#             df.loc[idx, "Site ID"] = None

#         elif anomaly == "missing_operator":
#             df.loc[idx, "Last Operator ID"] = None

#         elif anomaly == "zero_engine_nonCrane":
#             if df.loc[idx, "Type"] != "Crane":
#                 df.loc[idx, "Engine Hours/Day"] = 0.0

#         elif anomaly == "excessive_idle":
#             # near-full-day idle -> clearly abnormal, machine essentially parked but billed
#             df.loc[idx, "Idle Hours/Day"] = round(float(RNG.uniform(20, 23)), 1)
#             df.loc[idx, "Engine Hours/Day"] = round(float(RNG.uniform(0, 1)), 1)

#         elif anomaly == "negative_or_zero_rental_days":
#             # simulate a data-entry glitch: checkout (return) same as checkin (out-date)
#             df.loc[idx, "Check-Out Date"] = df.loc[idx, "Check-In Date"]

#     df = recompute_rental_days(df)
#     return df


# # ---------------------------------------------------------------------------
# # 5. DAILY USAGE LOGS (fuel + location + day-by-day idle/engine split)
# #    Expands each booking into one row per rental day.
# # ---------------------------------------------------------------------------

# # Small fixed base coordinates per site (fictional), used with jitter to
# # simulate GPS pings without needing a real map/GPS feed.
# SITE_COORDS = {
#     "S001": (13.0500, 80.2500),
#     "S002": (13.0827, 80.2707),
#     "S003": (13.1200, 80.2200),
#     "S004": (12.9900, 80.1800),
#     "S005": (13.0300, 80.3100),
# }


# def generate_usage_logs(bookings_df: pd.DataFrame) -> pd.DataFrame:
#     """
#     Expands each booking row into a daily usage log:
#     engine_hours, idle_hours, fuel_consumed_litres, lat, lon.
#     Applies site_idle_modifier() per actual calendar day (not just booking average),
#     so within one long rental you can see e.g. a monsoon idle spike mid-booking.
#     """
#     logs = []
#     for _, b in bookings_df.iterrows():
#         if pd.isnull(b["Check-Out Date"]) or pd.isnull(b["Rental Days"]) or b["Rental Days"] <= 0:
#             continue  # skip corrupted/anomalous bookings with no valid date range

#         eq_type = b["Type"]
#         site_id = b["Site ID"]
#         baseline = TYPE_BASELINES.get(eq_type, TYPE_BASELINES["Excavator"])
#         base_lat, base_lon = SITE_COORDS.get(site_id, (13.05, 80.25))

#         start_date = pd.to_datetime(b["Check-In Date"]).date()  # equipment goes out to site

#         for d in range(int(b["Rental Days"])):
#             current_day = start_date + timedelta(days=d)

#             idle_mult = site_idle_modifier(site_id, current_day) if pd.notnull(site_id) else 1.2
#             engine_hours = max(0, RNG.normal(baseline["engine_mean"], 1.0))
#             idle_hours = max(0, RNG.normal(baseline["idle_mean"] * idle_mult, 0.8))

#             if eq_type == "Crane" and RNG.random() < 0.25:
#                 engine_hours = 0.0

#             fuel = round(
#                 engine_hours * baseline["fuel_active"] + idle_hours * baseline["fuel_idle"], 1
#             )

#             logs.append({
#                 "booking_id": b["booking_id"],
#                 "equipment_id": b["Equipment ID"],
#                 "date": current_day,
#                 "engine_hours": round(engine_hours, 1),
#                 "idle_hours": round(idle_hours, 1),
#                 "fuel_consumed_litres": fuel,
#                 "lat": round(base_lat + RNG.uniform(-0.002, 0.002), 5),
#                 "lon": round(base_lon + RNG.uniform(-0.002, 0.002), 5),
#             })

#     return pd.DataFrame(logs)


# # ---------------------------------------------------------------------------
# # 6. MAIN — wire it all together
# # ---------------------------------------------------------------------------

# def main():
#     from datetime import date

#     fleet_df = build_fleet()

#     bookings_df = generate_bookings(
#         fleet_df,
#         start_date=date(2025, 1, 1),
#         end_date=date(2026, 7, 30),
#         num_bookings=1400
#     )

#     bookings_df = inject_anomalies(bookings_df, num_anomalies=70)  # scale anomaly count with row count too

#     print(bookings_df.shape)
#     print(bookings_df.head())
#     bookings_df.to_csv("dataset/bookings.csv", index=False)

# if __name__ == "__main__":
#     main()

"""
Synthetic Data Generator — Smart Rental Tracking System
=========================================================
v2: fixes two issues from the first version:
  1. Rental Days is now a PLANNED value set at check-in time, independent of
     the actual return date - this is what makes "overdue" possible at all.
  2. Bookings are generated per-equipment as a SEQUENTIAL, non-overlapping
     timeline (rental -> idle yard gap -> next rental), instead of random
     independent rows that could double-book the same machine.

Check-In Date  = when the equipment goes out (known upfront)
Rental Days    = the AGREED/PLANNED rental duration (known upfront)
Check-Out Date = the ACTUAL date it was returned - NULL if still out.
                 Overdue = actual return (or "today" if still out) is later
                 than Check-In Date + Rental Days.
"""

import numpy as np
import pandas as pd
from datetime import date, timedelta

RNG = np.random.default_rng(42)  # fixed seed -> reproducible demo data

TODAY = date(2026, 7, 30)
START_DATE = date(2025, 1, 1)

# ---------------------------------------------------------------------------
# 1. REFERENCE DATA (unchanged)
# ---------------------------------------------------------------------------

EQUIPMENT_TYPES = ["Excavator", "Crane", "Bulldozer", "Grader"]

SITES = {
    "S001": {"name": "Site S001 - Coastal Lowland",     "profile": "waterlogging"},
    "S002": {"name": "Site S002 - Urban Core",           "profile": "steady"},
    "S003": {"name": "Site S003 - Highland Quarry",      "profile": "pre_monsoon_peak"},
    "S004": {"name": "Site S004 - Rural Highway",        "profile": "winter_slowdown"},
    "S005": {"name": "Site S005 - New Development Zone", "profile": "ramping_up"},
}
SITE_IDS = list(SITES.keys())

OPERATORS = [f"OP10{i}" for i in range(1, 9)]  # OP101 ... OP108

FLEET_SIZE_PER_TYPE = 6


def build_fleet():
    """Create the fixed equipment fleet (equipment_id <-> type mapping)."""
    fleet = []
    eq_counter = 1001
    for eq_type in EQUIPMENT_TYPES:
        for _ in range(FLEET_SIZE_PER_TYPE):
            fleet.append({"equipment_id": f"EQX{eq_counter}", "type": eq_type})
            eq_counter += 1
    return pd.DataFrame(fleet)


# ---------------------------------------------------------------------------
# 2. SEASONAL / SITE PATTERN FUNCTIONS (unchanged)
# ---------------------------------------------------------------------------

def overall_seasonal_demand_weight(month: int) -> float:
    weights = {
        1: 0.5, 2: 0.5, 3: 0.7, 4: 0.9, 5: 1.0,
        6: 1.1, 7: 1.3, 8: 1.2, 9: 1.0, 10: 0.9,
        11: 0.7, 12: 0.5,
    }
    return weights[month]


def site_idle_modifier(site_id: str, current_date: date) -> float:
    profile = SITES[site_id]["profile"]
    month = current_date.month

    if profile == "waterlogging":
        return 2.5 if month in (6, 7, 8, 9) else 1.0
    if profile == "winter_slowdown":
        return 1.8 if month in (12, 1, 2) else 1.0
    if profile == "pre_monsoon_peak":
        if month in (3, 4, 5):
            return 0.6
        if month in (6, 7, 8, 9):
            return 1.6
        return 1.0
    if profile == "ramping_up":
        return max(1.6 - (month - 1) * 0.1, 0.7)
    return 1.0  # "steady"


def site_demand_modifier(site_id: str) -> float:
    profile = SITES[site_id]["profile"]
    return {
        "waterlogging": 0.9,
        "steady": 1.3,
        "pre_monsoon_peak": 1.0,
        "winter_slowdown": 0.8,
        "ramping_up": 0.7,
    }[profile]


TYPE_BASELINES = {
    "Excavator": {"engine_mean": 6.5, "idle_mean": 3.0, "fuel_active": 18, "fuel_idle": 4},
    "Crane":     {"engine_mean": 3.0, "idle_mean": 6.0, "fuel_active": 12, "fuel_idle": 2},
    "Bulldozer": {"engine_mean": 7.0, "idle_mean": 2.5, "fuel_active": 22, "fuel_idle": 5},
    "Grader":    {"engine_mean": 5.5, "idle_mean": 3.5, "fuel_active": 15, "fuel_idle": 3},
}

SITE_PROBS = np.array([site_demand_modifier(s) for s in SITE_IDS])
SITE_PROBS = SITE_PROBS / SITE_PROBS.sum()


# ---------------------------------------------------------------------------
# 3. SEQUENTIAL PER-EQUIPMENT BOOKING GENERATION
# ---------------------------------------------------------------------------

RECENT_WINDOW_DAYS = 7  

def generate_bookings_for_equipment(equipment_id: str, eq_type: str) -> list:
    rows = []
    current_date = START_DATE + timedelta(days=int(RNG.integers(0, 20)))

    while current_date <= TODAY:
        check_in_date = current_date
        rental_days = int(RNG.integers(7, 31))
        planned_checkout = check_in_date + timedelta(days=rental_days)
        site_id = RNG.choice(SITE_IDS, p=SITE_PROBS)
        operator_id = RNG.choice(OPERATORS)

        baseline = TYPE_BASELINES[eq_type]
        idle_mult = site_idle_modifier(site_id, check_in_date)
        engine_hours_day = max(0, RNG.normal(baseline["engine_mean"], 1.2))
        idle_hours_day = max(0, RNG.normal(baseline["idle_mean"] * idle_mult, 1.0))
        if eq_type == "Crane" and RNG.random() < 0.25:
            engine_hours_day = 0.0

        base_row = {
            "Equipment ID": equipment_id,
            "Type": eq_type,
            "Site ID": site_id,
            "Check-In Date": check_in_date,
            "Engine Hours/Day": round(engine_hours_day, 1),
            "Idle Hours/Day": round(idle_hours_day, 1),
            "Rental Days": rental_days,
            "Last Operator ID": operator_id,
        }

        if planned_checkout > TODAY:
            # Hasn't reached its planned end yet -> currently ACTIVE, straddling today
            base_row["Check-Out Date"] = None
            rows.append(base_row)
            break

        days_since_planned_checkout = (TODAY - planned_checkout).days

        if days_since_planned_checkout <= RECENT_WINDOW_DAYS:
            # Within the last week of its planned checkout - plausible it's
            # genuinely still overdue and hasn't been returned yet.
            outcome = RNG.choice(
                ["on_time", "late_returned", "still_open_overdue"], p=[0.70, 0.15, 0.15]
            )
        else:
            # More than a week past planned checkout -> must have already been
            # returned (on time or late). No equipment stays stuck this long.
            outcome = RNG.choice(["on_time", "late_returned"], p=[0.85, 0.15])

        if outcome == "on_time":
            actual_checkout = planned_checkout
        elif outcome == "late_returned":
            late_days = int(RNG.integers(1, 11))
            actual_checkout = planned_checkout + timedelta(days=late_days)
            if actual_checkout > TODAY:
                actual_checkout = None
        else:  # still_open_overdue
            actual_checkout = None

        base_row["Check-Out Date"] = actual_checkout
        rows.append(base_row)

        if actual_checkout is None:
            break  # genuinely stuck overdue right now, can't start a new cycle

        gap_days = int(RNG.integers(1, 16))
        current_date = actual_checkout + timedelta(days=gap_days)

    return rows


def generate_bookings(fleet_df: pd.DataFrame) -> pd.DataFrame:
    """Builds the full bookings table across all equipment."""
    all_rows = []
    for _, eq in fleet_df.iterrows():
        all_rows.extend(generate_bookings_for_equipment(eq["equipment_id"], eq["type"]))

    df = pd.DataFrame(all_rows)
    df["booking_id"] = [f"BKG{1000+i}" for i in range(len(df))]
    return df


# ---------------------------------------------------------------------------
# 4. ANOMALY INJECTION — call this as many times as you like to add more
# ---------------------------------------------------------------------------

def inject_anomalies(df: pd.DataFrame, num_anomalies: int = 5, anomaly_types: list = None) -> pd.DataFrame:
    """
    Injects anomalies into a COPY of the bookings dataframe. Call repeatedly to add more.

    anomaly_types: subset of
        ["missing_site", "missing_operator", "zero_engine_nonCrane",
         "excessive_idle", "invalid_rental_days"]
    """
    df = df.copy()
    all_types = [
        "missing_site", "missing_operator", "zero_engine_nonCrane",
        "excessive_idle", "invalid_rental_days",
    ]
    types_pool = anomaly_types if anomaly_types else all_types

    idx_choices = RNG.choice(df.index, size=min(num_anomalies, len(df)), replace=False)

    for idx in idx_choices:
        anomaly = RNG.choice(types_pool)

        if anomaly == "missing_site":
            df.loc[idx, "Site ID"] = None
        elif anomaly == "missing_operator":
            df.loc[idx, "Last Operator ID"] = None
        elif anomaly == "zero_engine_nonCrane":
            if df.loc[idx, "Type"] != "Crane":
                df.loc[idx, "Engine Hours/Day"] = 0.0
        elif anomaly == "excessive_idle":
            df.loc[idx, "Idle Hours/Day"] = round(float(RNG.uniform(20, 23)), 1)
            df.loc[idx, "Engine Hours/Day"] = round(float(RNG.uniform(0, 1)), 1)
        elif anomaly == "invalid_rental_days":
            # data-entry glitch: a nonsensical planned rental length
            df.loc[idx, "Rental Days"] = int(RNG.choice([0, -1]))

    return df


# ---------------------------------------------------------------------------
# 5. MAIN
# ---------------------------------------------------------------------------

def main():
    fleet_df = build_fleet()
    bookings_df = generate_bookings(fleet_df)
    bookings_df = inject_anomalies(bookings_df, num_anomalies=15)

    print(f"Generated {len(bookings_df)} bookings across {fleet_df.shape[0]} equipment units")
    print(bookings_df.head(10).to_string(index=False))

    open_bookings = bookings_df[bookings_df["Check-Out Date"].isnull()]
    print(f"\nCurrently open bookings (still checked out) as of {TODAY}: {len(open_bookings)}")

    equipment_with_open = set(open_bookings["Equipment ID"])
    available_now = set(fleet_df["equipment_id"]) - equipment_with_open
    print(f"Equipment available (no open booking) as of {TODAY}: {len(available_now)} -> {sorted(available_now)}")

    bookings_df.to_csv("dataset/bookings.csv", index=False)


if __name__ == "__main__":
    main()