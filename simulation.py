"""
simulation.py — COMP1945 Group 17
Runs all 3 scenarios × 2 controllers = 6 simulation runs.
Output: output/simulation_state_log.csv
"""

import csv, json, os, sys, random, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collector import SyntheticStateBuilder, StateSnapshot
from controller import (FixedTimeController, AdaptiveController,
                        PHASE_LABELS, PHASE_NS_GREEN, PHASE_EW_GREEN, PHASE_PEDESTRIAN)

try:
    import cityflow as cf
    CITYFLOW_AVAILABLE = True
    print("✓ CityFlow engine found")
except ImportError:
    CITYFLOW_AVAILABLE = False
    print("⚠  CityFlow not installed — using synthetic queue simulator")


# ─── Synthetic engine ────────────────────────────────────────────────────────

class SyntheticEngine:
    """
    D/D/1 queue approximation per approach lane.
    Travel time = cumulative delay / total arrivals  (Little's Law approximation)
    Arrival asymmetry: N/S approach ~2.3× heavier than E/W in Morning Peak.
    """
    SCENARIOS = {
        "Morning Peak":  {"interval_N": 3.0, "interval_E": 7.0, "weather": 0},
        "Off-Peak":      {"interval_N": 7.0, "interval_E": 12.0, "weather": 0},
        "Rainy Morning": {"interval_N": 3.0, "interval_E": 7.0,  "weather": 1},
    }

    def __init__(self, scenario_name: str):
        cfg = self.SCENARIOS[scenario_name]
        self.weather = cfg["weather"]
        self._arr_N = 1.0 / cfg["interval_N"]
        self._arr_E = 1.0 / cfg["interval_E"]
        self._arr_S = self._arr_N * 0.75
        self._arr_W = self._arr_E * 0.65
        self._discharge = 0.5 if self.weather == 0 else 0.14
        self.q = {"road_0_1_0": 0.0, "road_2_1_0": 0.0,
                  "road_3_1_0": 0.0, "road_4_1_0": 0.0}
        self._total_vehicles = 0.0
        self._cumulative_delay = 0.0
        self._total_arrivals   = 0.0

    def next_step(self):
        arrivals = (
            (1 if random.random() < self._arr_N else 0) +
            (1 if random.random() < self._arr_E else 0) +
            (1 if random.random() < self._arr_S else 0) +
            (1 if random.random() < self._arr_W else 0)
        )
        self.q["road_0_1_0"] += 1 if random.random() < self._arr_N else 0
        self.q["road_2_1_0"] += 1 if random.random() < self._arr_E else 0
        self.q["road_3_1_0"] += 1 if random.random() < self._arr_S else 0
        self.q["road_4_1_0"] += 1 if random.random() < self._arr_W else 0
        self._total_vehicles = sum(self.q.values())
        self._total_arrivals += arrivals
        # Every vehicle in queue waits 1 more second
        self._cumulative_delay += self._total_vehicles

    def set_tl_phase(self, _id: str, phase: int):
        if phase == PHASE_NS_GREEN:
            for key in ("road_0_1_0", "road_3_1_0"):
                d = min(self._discharge, self.q[key])
                self.q[key] = max(0.0, self.q[key] - d)
                self._total_vehicles -= d
        elif phase == PHASE_EW_GREEN:
            for key in ("road_2_1_0", "road_4_1_0"):
                d = min(self._discharge, self.q[key])
                self.q[key] = max(0.0, self.q[key] - d)
                self._total_vehicles -= d
        self._total_vehicles = max(0.0, self._total_vehicles)

    def get_lane_waiting_vehicle_count(self):
        return {k: int(v) for k, v in self.q.items()}

    def get_vehicle_count(self):
        return int(self._total_vehicles)

    def get_average_travel_time(self):
        if self._total_arrivals < 1:
            return 0.0
        return self._cumulative_delay / self._total_arrivals


# ─── Record builder ──────────────────────────────────────────────────────────

INTERSECTION_ID = "intersection_1"
TOTAL_STEPS     = 300
LOG_INTERVAL    = 5

def _make_record(scenario, ctrl_name, step, lane_waiting,
                 action, total_veh, avg_tt):
    q_N = sum(v for k, v in lane_waiting.items() if "road_0" in k)
    q_E = sum(v for k, v in lane_waiting.items() if "road_2" in k)
    q_S = sum(v for k, v in lane_waiting.items() if "road_3" in k)
    q_W = sum(v for k, v in lane_waiting.items() if "road_4" in k)
    h = 8 + step // 3600; m = (step % 3600) // 60; s = step % 60
    return {"scenario": scenario, "controller": ctrl_name, "step": step,
            "timestamp": f"{h:02d}:{m:02d}:{s:02d}",
            "q_N": q_N, "q_E": q_E, "q_S": q_S, "q_W": q_W,
            "signal_phase": action, "phase_label": PHASE_LABELS.get(action, "?"),
            "total_vehicles": total_veh,
            "avg_travel_time": round(avg_tt, 2) if avg_tt else 0.0}


def run_synthetic(scenario_name, weather, controller, total_steps=TOTAL_STEPS):
    eng = SyntheticEngine(scenario_name)
    sb  = SyntheticStateBuilder(weather=weather, start_hour=8)
    logs = []
    for step in range(total_steps):
        eng.next_step()
        lw     = eng.get_lane_waiting_vehicle_count()
        cp     = controller.current_phase
        state  = sb.build(lw, step, cp)
        action = controller.decide(step, state)
        eng.set_tl_phase(INTERSECTION_ID, action)
        if step % LOG_INTERVAL == 0:
            logs.append(_make_record(
                scenario_name, controller.__class__.__name__, step,
                lw, action, eng.get_vehicle_count(), eng.get_average_travel_time()))
    return logs


def run_cityflow(config_path, controller, scenario_name, weather,
                 total_steps=TOTAL_STEPS):
    eng = cf.Engine(config_path, thread_num=1)
    sb  = SyntheticStateBuilder(weather=weather, start_hour=8)
    logs = []
    for step in range(total_steps):
        eng.next_step()
        lw     = eng.get_lane_waiting_vehicle_count()
        cp     = controller.current_phase
        state  = sb.build(lw, step, cp)
        action = controller.decide(step, state)
        try:
            eng.set_tl_phase(INTERSECTION_ID, action)
        except Exception:
            pass
        if step % LOG_INTERVAL == 0:
            logs.append(_make_record(
                scenario_name, controller.__class__.__name__, step,
                lw, action, eng.get_vehicle_count(), eng.get_average_travel_time()))
    return logs


SCENARIOS = [
    ("Morning Peak",  "flow_morning_peak.json", 0),
    ("Off-Peak",      "flow_offpeak.json",      0),
    ("Rainy Morning", "flow_rainy.json",         1),
]


def run_all_scenarios(output_path="output/simulation_state_log.csv"):
    os.makedirs("output", exist_ok=True)
    all_logs = []

    for scenario_name, flow_file, weather in SCENARIOS:
        print(f"\n{'='*55}")
        print(f"  Scenario: {scenario_name}  {'🌧 Rainy' if weather else '☀ Clear'}")
        print(f"{'='*55}")

        for ctrl_cls, label in [(FixedTimeController, "Fixed-Time"),
                                 (AdaptiveController,  "Adaptive  ")]:
            print(f"  ▶ {label} controller ...", end=" ", flush=True)
            ctrl = ctrl_cls() if ctrl_cls == FixedTimeController else ctrl_cls(weather=weather)

            if CITYFLOW_AVAILABLE:
                with open("config.json") as f:
                    cfg = json.load(f)
                cfg["flowFile"] = os.path.basename(flow_file)
                with open("config_temp.json", "w") as f:
                    json.dump(cfg, f)
                logs = run_cityflow("config_temp.json", ctrl, scenario_name, weather)
            else:
                logs = run_synthetic(scenario_name, weather, ctrl)

            all_logs.extend(logs)
            print(f"done  ({len(logs)} records)")

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_logs[0].keys())
        writer.writeheader()
        writer.writerows(all_logs)
    print(f"\n✅  Saved {len(all_logs)} records → {output_path}")

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
            print(f"  {sc:<20}  Fixed={f_avg:5.1f}s  Adaptive={a_avg:5.1f}s  "
                  f"Δ={imp:+.1f}%  {'✅' if imp >= 10 else '❌'}")
    except ImportError:
        pass
    return all_logs


if __name__ == "__main__":
    random.seed(42)
    run_all_scenarios()