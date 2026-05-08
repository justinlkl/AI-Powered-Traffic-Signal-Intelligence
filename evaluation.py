"""
evaluation.py
-------------
Reads output/simulation_state_log.csv and produces:
  • Table 3: per-scenario metric comparison (Fixed vs Adaptive)
  • Percentage improvement calculations
  • output/evaluation_summary.csv  (for dashboard and report)

Run standalone:
    python evaluation.py

Or import:
    from evaluation import compute_summary
"""

import os
import sys
import pandas as pd

LOG_PATH     = "output/simulation_state_log.csv"
SUMMARY_PATH = "output/evaluation_summary.csv"

# ─────────────────────────────────────────────────────────────────────────────
# METRICS
# ─────────────────────────────────────────────────────────────────────────────

def compute_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Group by (scenario, controller) and compute:
      - avg_travel_time_s   : mean of avg_travel_time_s
      - avg_queue_length    : mean of (q_N + q_E + q_S + q_W) / 4
      - max_queue           : peak total queue across all steps
      - throughput          : total vehicles that passed (vehicle_count at end)
      - ped_wait_ns_avg     : mean pedestrian wait NS
      - ped_wait_ew_avg     : mean pedestrian wait EW
    """
    df = df.copy()

    # Normalize column names from different simulation output versions:
    # - older scripts wrote `avg_travel_time` and `total_vehicles`
    # - current evaluation expects `avg_travel_time_s` and `vehicle_count`
    if "avg_travel_time_s" not in df.columns and "avg_travel_time" in df.columns:
        df["avg_travel_time_s"] = df["avg_travel_time"]
    if "vehicle_count" not in df.columns and "total_vehicles" in df.columns:
        df["vehicle_count"] = df["total_vehicles"]

    # Queue columns
    q_cols = [c for c in ["q_N", "q_E", "q_S", "q_W"] if c in df.columns]
    if q_cols:
        df["total_queue"] = df[q_cols].sum(axis=1)
        df["avg_queue"]   = df["total_queue"] / len(q_cols)
    else:
        df["total_queue"] = 0
        df["avg_queue"]   = 0

    grp = df.groupby(["scenario", "controller"])

    summary = grp.agg(
        avg_travel_time_s  = ("avg_travel_time_s",  "mean"),
        avg_queue_length   = ("avg_queue",           "mean"),
        max_queue          = ("total_queue",          "max"),
        ped_wait_ns_avg    = ("p_NS",                 "mean") if "p_NS" in df.columns else ("avg_queue", "mean"),
        ped_wait_ew_avg    = ("p_EW",                 "mean") if "p_EW" in df.columns else ("avg_queue", "mean"),
    ).reset_index()

    # Add throughput (last vehicle_count per run)
    if "vehicle_count" in df.columns:
        throughput = grp["vehicle_count"].last().reset_index()
        throughput.rename(columns={"vehicle_count": "throughput"}, inplace=True)
        summary = summary.merge(throughput, on=["scenario", "controller"])
    else:
        summary["throughput"] = 0

    summary = summary.round(2)
    return summary


def improvement_table(summary: pd.DataFrame) -> pd.DataFrame:
    """
    Pivot to side-by-side Fixed vs Adaptive and compute % improvement.
    Improvement = (Fixed - Adaptive) / Fixed × 100  (positive = better).
    """
    rows = []
    scenarios = summary["scenario"].unique()
    for sc in scenarios:
        sub = summary[summary["scenario"] == sc]
        fixed_row    = sub[sub["controller"].str.contains("Fixed",    case=False)]
        adaptive_row = sub[sub["controller"].str.contains("Adaptive", case=False)]

        if fixed_row.empty or adaptive_row.empty:
            continue

        f = fixed_row.iloc[0]
        a = adaptive_row.iloc[0]

        def pct(metric):
            fv = f.get(metric, 0)
            av = a.get(metric, 0)
            if fv == 0:
                return 0.0
            return round((fv - av) / fv * 100, 1)

        rows.append({
            "Scenario":               sc,
            "Fixed Travel Time (s)":  round(f["avg_travel_time_s"], 2),
            "Adaptive Travel Time (s)": round(a["avg_travel_time_s"], 2),
            "Travel Time Improvement (%)": pct("avg_travel_time_s"),
            "Fixed Avg Queue":        round(f["avg_queue_length"], 2),
            "Adaptive Avg Queue":     round(a["avg_queue_length"], 2),
            "Queue Improvement (%)":  pct("avg_queue_length"),
            "Fixed Throughput":       int(f.get("throughput", 0)),
            "Adaptive Throughput":    int(a.get("throughput", 0)),
        })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def run_evaluation(log_path: str = LOG_PATH,
                   summary_path: str = SUMMARY_PATH) -> None:
    if not os.path.exists(log_path):
        print(f"[evaluation] No log found at {log_path}")
        print("[evaluation] Run simulation.py first.")
        sys.exit(1)

    df = pd.read_csv(log_path)
    print(f"[evaluation] Loaded {len(df)} log rows from {log_path}")

    summary = compute_summary(df)
    impr    = improvement_table(summary)

    os.makedirs(os.path.dirname(summary_path), exist_ok=True)
    summary.to_csv(summary_path, index=False)
    print(f"[evaluation] Summary saved → {summary_path}")

    print("\n══ Evaluation Summary ══")
    print(summary.to_string(index=False))

    print("\n══ Improvement vs Fixed-Time Baseline ══")
    print(impr.to_string(index=False))

    # Save improvement table separately
    impr_path = summary_path.replace("evaluation_summary", "improvement_table")
    impr.to_csv(impr_path, index=False)
    print(f"[evaluation] Improvement table saved → {impr_path}")


if __name__ == "__main__":
    run_evaluation()
