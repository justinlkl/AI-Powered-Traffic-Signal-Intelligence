# AI-Powered Traffic Signal Intelligence

COMP1945 (L2) Group 17 — simulation, controller algorithms, evaluation,
and a Streamlit dashboard for visualising results.

Overview
--------
This repository implements a small traffic simulation environment, two
traffic-signal controllers (Fixed-Time and a rule-based Adaptive controller),
an evaluation script to compute performance metrics, and a Streamlit
dashboard for visualization.

Features
--------
- Synthetic queue simulator fallback (no CityFlow required)
- `FixedTimeController` baseline and `AdaptiveController` rule-based agent
- `simulation.py` runs three scenarios × two controllers
- `evaluation.py` computes metrics and improvement tables
- `dashboard.py` provides a Streamlit UI for charts and KPIs

Quick start
-----------
1. Create and activate a virtual environment, then install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Run the simulation (generates CSV in `output/`):

```bash
python simulation.py
```

3. Compute evaluation metrics:

```bash
python evaluation.py
```

4. Launch the dashboard:

```bash
streamlit run dashboard.py
```

Data collection & calibration
-----------------------------
You can collect real-world data and calibrate CityFlow flows using the
included collector scripts under `src/data_collectors`:

1. Fetch TD traffic detectors (one-off or cron):

```bash
python src/data_collectors/collect_td_traffic.py --output data/raw/td_traffic.csv
```

2. Fetch HKO weather (appends to CSV):

```bash
python src/data_collectors/collect_weather.py --output data/raw/weather.csv
```

3. Calibrate a CityFlow flow.json from collected TD data:

```bash
python src/data_collectors/calibrate_flow.py --input data/raw/td_traffic.csv \
  --output data/raw/flow_calibrated.json
```

4. Use the calibrated flow with your CityFlow runner (or adapt
   `simulation.py` to point at `data/raw/flow_calibrated.json`).

These scripts are intentionally simple examples to demonstrate a
lightweight hybrid workflow (real-data → simulation calibration).

Notes
-----
- This repository has been cleaned: generated outputs and cache files are
  excluded from version control via `.gitignore`. Run `python simulation.py`
  to regenerate data in `output/`.
- If you use CityFlow, place its environment files under `cityflow_env/` and
  update `simulation.py` to point at the correct `flow_*.json` files.

Known limitations
-----------------
- Pedestrian phase in the controller is conceptual: the code uses an
  internal `PHASE_PEDESTRIAN` (4) which is mapped to CityFlow's all-red
  phase (one of the yellow/all-red slots). As a result the dashboard and
  CSV logs will show a `phase_label` of "Pedestrian" while CityFlow
  actually applies an all-red transition. This is a prototype
  approximation and is documented in the report.
- Transit-signal-priority (`bus_approaching`) is supported by the
  controller. The `StateSnapshot` dataclass includes a `bus_approaching`
  flag, and the `DeploymentStateBuilder` sets it when a bus ETA is near.
  The synthetic state builder currently leaves this flag unset (0).

Files of interest
-----------------
- `controller.py` — controller implementations and phase constants
- `simulation.py` — scenario runner and synthetic engine
- `evaluation.py` — summary metrics and improvement tables
- `dashboard.py` — Streamlit visualization
- `collector.py` — state builder used by the runner and dashboard
