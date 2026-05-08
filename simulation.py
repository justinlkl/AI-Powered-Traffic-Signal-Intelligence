"""
simulation.py
-------------
Runs all 3 scenarios × 2 controllers = 6 simulation runs.

When CityFlow IS installed:
    Uses the real CityFlow engine for physics-accurate vehicle simulation.
When CityFlow is NOT installed:
    Falls back to a lightweight synthetic simulator that reproduces the same
    queue dynamics and CSV schema, so dashboard.py and evaluation work
    without the C++ dependency.

Output: output/simulation_state_log.csv
"""

import csv
import json
import os
import sys
import math
import random
import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))
from collector import SyntheticStateBuilder, StateSnapshot
from controller import (
    FixedTimeController, AdaptiveController,
    PHASE_LABELS, PHASE_NS_GREEN, PHASE_EW_GREEN, PHASE_PEDESTRIAN
)

# ─────────────────────────────────────────────────────────────────────────────
# TRY TO IMPORT CITYFLOW
# ─────────────────────────────────────────────────────────────────────────────
try:
    import cityflow as cf
    CITYFLOW_AVAILABLE = True
    print("✓ CityFlow engine found — using physics simulation")
except ImportError:
    CITYFLOW_AVAILABLE = False
    print("⚠  CityFlow not installed — using synthetic queue simulator")


# ─────────────────────────────────────────────────────────────────────────────
# SYNTHETIC QUEUE SIMULATOR (CityFlow fallback)
# ─────────────────────────────────────────────────────────────────────────────

class SyntheticEngine:
    """
    Lightweight queue model reproducing Section 3.4 parameters.
    Uses a D/D/1 queue approximation with Poisson arrivals:
      - Arrival rate from flow_*.json interval settings
      - Service rate (discharge): 1 vehicle / 2s during green (clear)
                                  1 vehicle / 3s during green (rain)
    """

    SCENARIOS = {
        "Morning Peak":   {"interval_N": 3.0, "interval_E": 5.0, "weather": 0},
        "Off-Peak":       {"interval_N": 6.0, "interval_E": 10.0, "weather": 0},
        "Rainy Morning":  {"interval_N": 2.1, "interval_E": 3.6,  "weather": 1},
    }

    def __init__(self, scenario_name: str):
        cfg = self.SCENARIOS[scenario_name]
        self.weather = cfg["weather"]
        # Arrival rates (vehicles per second)
        self._arr_N = 1.0 / cfg["interval_N"]
        self._arr_E = 1.0 / cfg["interval_E"]
        self._arr_S = self._arr_N * 0.8   # south slightly lighter
        self._arr_W = self._arr_E * 0.7   # west lightest

        # Discharge rate (vehicles per second during green)
        base_discharge = 0.5 if self.weather == 0 else 0.33
        self._discharge = base_discharge

        # Queue state
        self.q: dict[str, float] = {
            "road_0_1_0": 0.0,   # North
            "road_2_1_0": 0.0,   # East
            "road_3_1_0": 0.0,   # South
            "road_4_1_0": 0.0,   # West
        }
        self._total_vehicles  = 0.0
        self._travel_time_acc = 0.0
        self._cleared_count   = 0

    def next_step(self):
        """Advance simulation by 1 second."""
        random.seed(None)
        # Stochastic arrivals (Bernoulli approximation of Poisson)
        self.q["road_0_1_0"] += 1 if random.random() < self._arr_N else 0
        self.q["road_2_1_0"] += 1 if random.random() < self._arr_E else 0
        self.q["road_3_1_0"] += 1 if random.random() < self._arr_S else 0
        self.q["road_4_1_0"] += 1 if random.random() < self._arr_W else 0
        self._total_vehicles = sum(self.q.values())

    def set_tl_phase(self, intersection_id: str, phase: int):
        """Apply signal phase: discharge vehicles from green approach."""
        if phase == PHASE_NS_GREEN:
            discharge = min(self._discharge, self.q["road_0_1_0"])
            self.q["road_0_1_0"] = max(0.0, self.q["road_0_1_0"] - discharge)
            discharge_s = min(self._discharge, self.q["road_3_1_0"])
            self.q["road_3_1_0"] = max(0.0, self.q["road_3_1_0"] - discharge_s)
            self._track_clearance(discharge + discharge_s)

        elif phase == PHASE_EW_GREEN:
            discharge = min(self._discharge, self.q["road_2_1_0"])
            self.q["road_2_1_0"] = max(0.0, self.q["road_2_1_0"] - discharge)
            discharge_w = min(self._discharge, self.q["road_4_1_0"])
            self.q["road_4_1_0"] = max(0.0, self.q["road_4_1_0"] - discharge_w)
            self._track_clearance(discharge + discharge_w)

        # Yellow / Pedestrian phase: no discharge

    def _track_clearance(self, n_cleared: float):
        if n_cleared > 0:
            # Simple travel time estimate: proportional to queue length
            avg_q = self._total_vehicles / 4 if self._total_vehicles > 0 else 0
            self._travel_time_acc += avg_q * 2.5 * n_cleared
            self._cleared_count += n_cleared

    def get_lane_waiting_vehicle_count(self) -> dict:
        return {k: int(v) for k, v in self.q.items()}

    def get_vehicle_count(self) -> int:
        return int(self._total_vehicles)

    def get_average_travel_time(self) -> float:
        if self._cleared_count < 1:
            return 0.0
        return self._travel_time_acc / self._cleared_count


# ─────────────────────────────────────────────────────────────────────────────
# SIMULATION RUNNER
# ─────────────────────────────────────────────────────────────────────────────

INTERSECTION_ID = "intersection_1"
TOTAL_STEPS     = 300    # 5-minute simulation at 1s resolution
LOG_INTERVAL    = 5      # record every 5 seconds

SCENARIOS = [
    ("Morning Peak",   "flow_morning_peak.json", 0),
    ("Off-Peak",       "flow_offpeak.json",      0),
    ("Rainy Morning",  "flow_rainy.json",       1),
]


def run_cityflow(config_path: str, controller, scenario_name: str,
                 weather: int, total_steps: int = TOTAL_STEPS) -> list[dict]:
    """Run one simulation using the real CityFlow engine."""
    eng = cf.Engine(config_path, thread_num=1)
    state_builder = SyntheticStateBuilder(weather=weather, start_hour=8)
    logs = []

    for step in range(total_steps):
        eng.next_step()
        lane_waiting = eng.get_lane_waiting_vehicle_count()
        current_phase = (controller.current_phase
                         if hasattr(controller, 'current_phase')
                         else controller.decide(step, None))
        state = state_builder.build(lane_waiting, step, current_phase)
        action = controller.decide(step, state)
        try:
            eng.set_tl_phase(INTERSECTION_ID, action)
        except Exception:
            pass

        if step % LOG_INTERVAL == 0:
            logs.append(_make_record(
                scenario_name, controller.__class__.__name__, step,
                lane_waiting, action,
                eng.get_vehicle_count(), eng.get_average_travel_time()
            ))
    return logs


def run_synthetic(scenario_name: str, weather: int,
                  controller, total_steps: int = TOTAL_STEPS) -> list[dict]:
    """Run one simulation using the lightweight synthetic engine."""
    eng    = SyntheticEngine(scenario_name)
    sb     = SyntheticStateBuilder(weather=weather, start_hour=8)
    logs   = []

    for step in range(total_steps):
        eng.next_step()
        lane_waiting = eng.get_lane_waiting_vehicle_count()
        current_phase = (controller.current_phase
                         if hasattr(controller, 'current_phase')
                         else 0)
        state = sb.build(lane_waiting, step, current_phase)
        action = controller.decide(step, state)
        eng.set_tl_phase(INTERSECTION_ID, action)

        if step % LOG_INTERVAL == 0:
            logs.append(_make_record(
                scenario_name, controller.__class__.__name__, step,
                lane_waiting, action,
                eng.get_vehicle_count(), eng.get_average_travel_time()
            ))
    return logs


def _make_record(scenario, controller_name, step, lane_waiting,
                 action, total_vehicles, avg_travel_time) -> dict:
    q_N = sum(v for k, v in lane_waiting.items() if 'road_0' in k)
    q_E = sum(v for k, v in lane_waiting.items() if 'road_2' in k)
    q_S = sum(v for k, v in lane_waiting.items() if 'road_3' in k)
    q_W = sum(v for k, v in lane_waiting.items() if 'road_4' in k)
    h = 8 + step // 3600
    m = (step % 3600) // 60
    s = step % 60
    return {
        "scenario":        scenario,
        "controller":      controller_name,
        "step":            step,
        "timestamp":       f"{h:02d}:{m:02d}:{s:02d}",
        "q_N":             q_N,
        "q_E":             q_E,
        "q_S":             q_S,
        "q_W":             q_W,
        "signal_phase":    action,
        "phase_label":     PHASE_LABELS.get(action, "Unknown"),
        "total_vehicles":  total_vehicles,
        "avg_travel_time": round(avg_travel_time, 2) if avg_travel_time else 0.0,
    }


def run_all_scenarios(output_path: str = "output/simulation_state_log.csv"):
    """Run all 6 combinations and save CSV."""
    os.makedirs("output", exist_ok=True)
    all_logs = []

    for scenario_name, flow_file, weather in SCENARIOS:
        print(f"\n{'='*55}")
        print(f"  Scenario: {scenario_name}  {'🌧 Rainy' if weather else '☀ Clear'}")
        print(f"{'='*55}")

        for ctrl_cls, label in [(FixedTimeController, "Fixed-Time"),
                                 (AdaptiveController,  "Adaptive  ")]:
            print(f"  ▶ {label} controller ...", end=" ", flush=True)
            ctrl = (ctrl_cls() if ctrl_cls == FixedTimeController
                    else ctrl_cls(weather=weather))

            if CITYFLOW_AVAILABLE:
                # Write temp config pointing to correct flow file (config.json at repo root)
                with open("config.json") as f:
                    cfg = json.load(f)
                cfg["flowFile"] = os.path.basename(flow_file)
                tmp_cfg = "config_temp.json"
                with open(tmp_cfg, "w") as f:
                    json.dump(cfg, f)
                logs = run_cityflow(tmp_cfg, ctrl, scenario_name, weather)
            else:
                logs = run_synthetic(scenario_name, weather, ctrl)

            all_logs.extend(logs)
            print(f"done  ({len(logs)} records)")

    # Write CSV
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_logs[0].keys())
        writer.writeheader()
        writer.writerows(all_logs)

    print(f"\n✅  Saved {len(all_logs)} records → {output_path}")

    # ── Print comparison summary ──────────────────────────────────────────
    try:
        import pandas as pd
        df = pd.DataFrame(all_logs)
        print("\n" + "="*55)
        print("  RESULTS: Adaptive vs Fixed-Time")
        print("="*55)
        for sc in df["scenario"].unique():
            sub   = df[df["scenario"] == sc]
            f_avg = sub[sub["controller"] == "FixedTimeController"]["avg_travel_time"].mean()
            a_avg = sub[sub["controller"] == "AdaptiveController"]["avg_travel_time"].mean()
            imp   = (f_avg - a_avg) / f_avg * 100 if f_avg > 0 else 0
            target_met = "✅" if imp >= 10 else "❌"
            print(f"  {sc:<20}  Fixed={f_avg:5.1f}s  "
                  f"Adaptive={a_avg:5.1f}s  "
                  f"Δ={imp:+.1f}%  {target_met}")
    except ImportError:
        pass

    return all_logs


if __name__ == "__main__":
    random.seed(42)
    run_all_scenarios()