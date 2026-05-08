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
pip install -r requirement.txt
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

Notes
-----
- This repository has been cleaned: generated outputs and cache files are
  excluded from version control via `.gitignore`. Run `python simulation.py`
  to regenerate data in `output/`.
- If you use CityFlow, place its environment files under `cityflow_env/` and
  update `simulation.py` to point at the correct `flow_*.json` files.

Files of interest
-----------------
- `controller.py` — controller implementations and phase constants
- `simulation.py` — scenario runner and synthetic engine
- `evaluation.py` — summary metrics and improvement tables
- `dashboard.py` — Streamlit visualization
- `collector.py` — state builder used by the runner and dashboard

License
-------
Add your project's license here.

