"""
rhythm_engine.py
Shared time-intelligence layer — feeds both Overdue Alerts and Demand Forecasting.
"""

import pandas as pd
import numpy as np


def load_data(csv_path):
    df = pd.read_csv(csv_path, dtype=str)
    df = df.replace(r'^\s*$', pd.NA, regex=True)

    numeric_cols = ["Engine Hours/Day", "Idle Hours/Day", "Rental Days"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["Check-In Date", "Check-Out Date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    return df


def business_days_in_month(period):
    """Business days (Mon-Fri) in a given month period."""
    start = period.start_time
    end = period.end_time
    return np.busday_count(start.date(), (end + pd.Timedelta(days=1)).date())


def build_rhythm_profile(df, group_cols=["Site ID", "Type"], min_months_for_seasonality=3):
    """
    Returns one row per (Site ID, Type, month) with:
      - rental_count
      - weekday_adjusted_rate = rental_count / business_days_in_period
      - seasonal_index[month] = avg rentals that month / avg rentals overall
      - spike_detected = rental_count > baseline_average * 1.3

    NOTE: rows with NULL Site ID are dropped — untracked equipment can't be
    attributed to a site's demand pattern.

    CHANGE: seasonal_index now falls back to neutral (1.0) for any
    Site+Type that has fewer than `min_months_for_seasonality` distinct
    months of history — otherwise a single early/late month gets treated
    as a "seasonal pattern" when it's really just noise from a small sample.
    """
    df = df.copy()
    df = df.dropna(subset=["Site ID"])
    df["month"] = df["Check-In Date"].dt.to_period("M")

    counts = (
        df.groupby(group_cols + ["month"])
        .size()
        .reset_index(name="rental_count")
    )
    counts["business_days"] = counts["month"].apply(business_days_in_month)
    counts["weekday_adjusted_rate"] = counts["rental_count"] / counts["business_days"]

    month_counts = (
        df.groupby(group_cols + [df["Check-In Date"].dt.month.rename("month_num")])
        .size()
        .reset_index(name="month_count")
    )
    monthly_avg = month_counts.groupby(group_cols + ["month_num"])["month_count"].mean().reset_index()
    overall_avg = month_counts.groupby(group_cols)["month_count"].mean().reset_index().rename(
        columns={"month_count": "overall_avg"}
    )
    n_months = df.groupby(group_cols)["month"].nunique().reset_index(name="n_months")

    seasonal = monthly_avg.merge(overall_avg, on=group_cols).merge(n_months, on=group_cols)
    seasonal["seasonal_index"] = np.where(
        seasonal["n_months"] >= min_months_for_seasonality,
        seasonal["month_count"] / seasonal["overall_avg"],
        1.0,
    )

    counts["month_num"] = counts["month"].dt.month
    counts = counts.merge(
        seasonal[group_cols + ["month_num", "seasonal_index"]],
        on=group_cols + ["month_num"], how="left"
    )
    counts["seasonal_index"] = counts["seasonal_index"].fillna(1.0)

    baseline = counts.groupby(group_cols)["rental_count"].transform("mean")
    counts["baseline_average"] = baseline
    counts["spike_detected"] = counts["rental_count"] > (baseline * 1.3)

    return counts.drop(columns=["month_num"])


if __name__ == "__main__":
    df = load_data("dataset/bookings.csv")
    profile = build_rhythm_profile(df)
    print(profile.to_string(index=False))