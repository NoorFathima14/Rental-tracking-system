"""
forecast.py
Demand Forecasting — trend + seasonal-adjusted forecast with confidence rating.
Depends on rhythm_engine.py.
"""

import numpy as np
import pandas as pd
from rhythm_engine import load_data, build_rhythm_profile, business_days_in_month


def forecast_demand(df, group_cols=["Site ID", "Type"]):
    """
    For each Site+Type: fits a trend line over weekday-adjusted rental rate,
    projects it one month forward, applies that month's seasonal factor,
    and rates confidence (High/Medium/Low) based on how consistent the
    historical trend has been (lower residual noise = higher confidence).
    """
    profile = build_rhythm_profile(df, group_cols)
    results = []

    for keys, group in profile.groupby(group_cols):
        group = group.sort_values("month").reset_index(drop=True)
        rates = group["weekday_adjusted_rate"].values
        n = len(rates)

        if n < 2:
            slope, intercept = 0.0, rates[-1] if n else 0.0
            confidence = "Low"
        else:
            x = np.arange(n)
            slope, intercept = np.polyfit(x, rates, 1)
            residuals = rates - (intercept + slope * x)
            cv = np.std(residuals) / (np.mean(rates) + 1e-9)

            if n >= 4 and cv < 0.3:
                confidence = "High"
            elif n >= 3 and cv < 0.6:
                confidence = "Medium"
            else:
                confidence = "Low"

        predicted_rate = max(0.0, intercept + slope * n)

        next_month = group["month"].max() + 1
        next_month_num = next_month.month
        next_business_days = business_days_in_month(next_month)

        seasonal_lookup = {m.month: s for m, s in zip(group["month"], group["seasonal_index"])}
        seasonal_factor = seasonal_lookup.get(next_month_num, 1.0)

        forecast_count = predicted_rate * next_business_days * seasonal_factor

        row = dict(zip(group_cols, keys if isinstance(keys, tuple) else (keys,)))
        row.update({
            "forecast_month": str(next_month),
            "predicted_weekday_rate": round(predicted_rate, 4),
            "seasonal_factor": round(seasonal_factor, 3),
            "forecast_count": round(forecast_count, 1),
            "confidence": confidence,
            "data_points_used": n,
        })
        results.append(row)

    return pd.DataFrame(results).sort_values("forecast_count", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    df = load_data("dataset/bookings.csv")
    forecast = forecast_demand(df)
    print(forecast.to_string(index=False))