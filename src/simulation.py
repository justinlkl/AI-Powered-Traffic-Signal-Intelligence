#!/usr/bin/env python3
"""Wrapper to run single scenarios from the root `simulation.py`.

Usage examples:
  python src/simulation.py --scenario morning_peak --seed 0
  python src/simulation.py --scenario all --seed 0

This script runs both controllers for the chosen scenario and writes
per-scenario CSVs to `output/simulation_state_log_{scenario}.csv` and
`output/all_scenarios_merged.csv` for convenience.
"""

import argparse
import os
import sys
import json
import csv

# Ensure project root is on path so we can import the root-level simulation module
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

import simulation as sim
from controller import FixedTimeController, AdaptiveController

SCEN_MAP = {
    'morning_peak': ('Morning Peak', 'flow_morning_peak.json', 0),
    'off_peak':     ('Off-Peak',     'flow_offpeak.json',     0),
    'rainy_peak':   ('Rainy Morning','flow_rainy.json',      1),
}


def run_single(skey: str, seed: int = 42) -> list:
    if skey not in SCEN_MAP:
        raise SystemExit(f'Unknown scenario key: {skey}')

    scenario_name, flow_file, weather = SCEN_MAP[skey]
    merged = []

    os.makedirs('output', exist_ok=True)

    for ctrl_cls in (FixedTimeController, AdaptiveController):
        ctrl = (ctrl_cls() if ctrl_cls == FixedTimeController
                else ctrl_cls(weather=weather))

        if sim.CITYFLOW_AVAILABLE:
            # mirror run_all_scenarios behaviour
            with open('config.json') as f:
                cfg = json.load(f)
            cfg['flowFile'] = os.path.basename(flow_file)
            tmp_cfg = 'config_temp.json'
            with open(tmp_cfg, 'w') as f:
                json.dump(cfg, f)
            logs = sim.run_cityflow(tmp_cfg, ctrl, scenario_name, weather)
            try:
                os.remove(tmp_cfg)
            except Exception:
                pass
        else:
            logs = sim.run_synthetic(scenario_name, weather, ctrl)

        merged.extend(logs)

    out_path = os.path.join('output', f'simulation_state_log_{skey}.csv')
    if merged:
        with open(out_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=merged[0].keys())
            writer.writeheader()
            writer.writerows(merged)
        print(f"Saved {len(merged)} records → {out_path}")
    else:
        print(f"No logs produced for scenario {skey}")

    return merged


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenario', default='all',
                        help='one of: morning_peak, off_peak, rainy_peak, all')
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()

    import random
    random.seed(args.seed)

    all_merged = []
    keys = list(SCEN_MAP.keys()) if args.scenario == 'all' else [args.scenario]

    for idx, k in enumerate(keys, 1):
        print(f"\nRunning ({idx}/{len(keys)}): {k}")
        logs = run_single(k, seed=args.seed)
        all_merged.extend(logs)

    # write merged file
    if all_merged:
        out_all = os.path.join('output', 'all_scenarios_merged.csv')
        with open(out_all, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=all_merged[0].keys())
            writer.writeheader()
            writer.writerows(all_merged)
        print(f"\nSaved merged file → {out_all}")


if __name__ == '__main__':
    main()
