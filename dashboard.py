"""
dashboard.py
------------
Streamlit operator dashboard for the COMP1945 Group 17 traffic signal project.
Section 3.2: Operator Dashboard component.

Run with:
    streamlit run dashboard.py

Features:
  • Scenario / controller selector
  • Live queue evolution (all 4 approaches)
  • Signal phase timeline (colour-coded)
  • Average travel time comparison
  • KPI metrics with improvement %
  • All-scenarios summary table
  • Raw state log viewer
"""

import warnings
# Suppress Streamlit's known (benign) RuntimeWarning about an
# un-awaited `expire_cache` coroutine; this originates from
# streamlit.util.TimedCleanupCache when asyncio loop timing races
# cause a coroutine object to be created but not awaited.
warnings.filterwarnings(
    "ignore",
    message="coroutine 'expire_cache' was never awaited",
    category=RuntimeWarning,
)
import os
import sys
import asyncio
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="🚦 AI Traffic Signal — COMP1945 Group 17",
    page_icon="🚦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
DATA_PATH = "output/simulation_state_log.csv"

PHASE_COLORS = {
    0: "#27AE60",   # NS Green
    1: "#F39C12",   # Yellow
    2: "#2980B9",   # EW Green
    3: "#F39C12",   # Yellow
    4: "#8E44AD",   # Pedestrian
}

PHASE_LABELS = {
    0: "NS Green",
    1: "Yellow",
    2: "EW Green",
    3: "Yellow",
    4: "Pedestrian",
}

APPROACH_COLORS = {
    "q_N": "#E74C3C",
    "q_E": "#3498DB",
    "q_S": "#E67E22",
    "q_W": "#2ECC71",
}

APPROACH_NAMES = {
    "q_N": "North",
    "q_E": "East",
    "q_S": "South",
    "q_W": "West",
}

# ─────────────────────────────────────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def load_data(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    return df


def ensure_data():
    """Run simulation if CSV doesn't exist yet."""
    if not os.path.exists(DATA_PATH):
        st.warning("⚙️  No simulation data found. Running simulation now…")
        with st.spinner("Simulating 6 scenarios (this takes ~10 seconds)…"):
            import subprocess, sys
            subprocess.run([sys.executable, "simulation.py"], check=True)
        _clear_cache_safe()
        st.rerun()


def _clear_cache_safe() -> None:
    """Safely clear Streamlit's `cache_data`.

    Some Streamlit versions return a coroutine from `st.cache_data.clear()`
    which needs to be awaited; calling it directly in sync code can leave a
    coroutine un-awaited and trigger a RuntimeWarning. This helper runs the
    coroutine if there is no running loop, or schedules it on the current
    loop if one exists.
    """
    try:
        result = st.cache_data.clear()
    except Exception:
        # If clearing fails for any reason, ignore to avoid crashing the app.
        return

    if asyncio.iscoroutine(result):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop — run to completion
            try:
                asyncio.run(result)
            except Exception:
                pass
        else:
            # Schedule the coroutine on the running loop
            try:
                loop.create_task(result)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# CHART HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _plotly_fillcolor(color: str, alpha: float = 0.08) -> str:
    """Return a Plotly-safe fillcolor string with the requested alpha.

    Accepts inputs like '#RRGGBB', 'rgb(r,g,b)', or '#RRGGBBAA' and
    outputs an 'rgba(r, g, b, a)' string which Plotly accepts reliably.
    """
    if not isinstance(color, str):
        return color

    c = color.strip()
    # Already rgba
    if c.startswith("rgba"):
        return c

    # Convert rgb(...) -> rgba(..., alpha)
    if c.startswith("rgb(") and c.endswith(")"):
        return c.replace("rgb(", "rgba(").replace(")", f", {alpha})")

    # Hex colors
    if c.startswith("#"):
        hexv = c.lstrip("#")
        try:
            if len(hexv) == 6:
                r = int(hexv[0:2], 16)
                g = int(hexv[2:4], 16)
                b = int(hexv[4:6], 16)
                return f"rgba({r}, {g}, {b}, {alpha})"
            if len(hexv) == 8:
                r = int(hexv[0:2], 16)
                g = int(hexv[2:4], 16)
                b = int(hexv[4:6], 16)
                a = int(hexv[6:8], 16) / 255.0
                return f"rgba({r}, {g}, {b}, {a:.2f})"
        except Exception:
            return color

    return color

def queue_chart(df: pd.DataFrame, title: str) -> go.Figure:
    fig = go.Figure()
    for col, color in APPROACH_COLORS.items():
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=df["step"], y=df[col],
                name=APPROACH_NAMES[col],
                line=dict(color=color, width=2),
                fill="tozeroy",
                fillcolor=_plotly_fillcolor(color, alpha=0.08),
                hovertemplate=f"{APPROACH_NAMES[col]}: %{{y}} veh<extra></extra>"
            ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=13)),
        xaxis_title="Time (s)",
        yaxis_title="Vehicles in queue",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=280,
        margin=dict(t=45, b=40, l=50, r=20),
        plot_bgcolor="#F8F9FA",
        paper_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
    )
    return fig


def travel_time_chart(df_fixed: pd.DataFrame,
                       df_adaptive: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_fixed["step"], y=df_fixed["avg_travel_time"],
        name="Fixed-Time", line=dict(color="#E74C3C", dash="dash", width=2.5),
        hovertemplate="Fixed: %{y:.1f}s<extra></extra>"
    ))
    fig.add_trace(go.Scatter(
        x=df_adaptive["step"], y=df_adaptive["avg_travel_time"],
        name="Adaptive", line=dict(color="#27AE60", width=2.5),
        fill="tonexty",
        fillcolor="rgba(39, 174, 96, 0.07)",
        hovertemplate="Adaptive: %{y:.1f}s<extra></extra>"
    ))
    fig.update_layout(
        xaxis_title="Time (s)",
        yaxis_title="Avg Travel Time (s)",
        height=260,
        margin=dict(t=20, b=40, l=50, r=20),
        plot_bgcolor="#F8F9FA",
        paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        hovermode="x unified",
    )
    return fig


def phase_timeline(df: pd.DataFrame, controller_label: str) -> go.Figure:
    """Draw coloured phase timeline bar."""
    fig = go.Figure()
    steps = df["step"].tolist()
    phases = df["signal_phase"].tolist()

    for i in range(len(steps) - 1):
        phase = int(phases[i])
        color = PHASE_COLORS.get(phase, "#95A5A6")
        label = PHASE_LABELS.get(phase, str(phase))
        fig.add_shape(
            type="rect",
            x0=steps[i], x1=steps[i + 1],
            y0=0, y1=1,
            fillcolor=color, opacity=0.85, line_width=0,
        )
        # Invisible scatter for hover
        fig.add_trace(go.Scatter(
            x=[(steps[i] + steps[i + 1]) / 2],
            y=[0.5],
            mode="markers",
            marker=dict(size=0, color="rgba(0,0,0,0)"),
            text=[f"Step {steps[i]}: {label}"],
            hovertemplate="%{text}<extra></extra>",
            showlegend=False
        ))

    # Legend items
    for phase, color in PHASE_COLORS.items():
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(size=12, color=color, symbol="square"),
            name=PHASE_LABELS.get(phase, str(phase)),
            showlegend=True,
        ))

    fig.update_layout(
        xaxis_title="Time (s)",
        yaxis=dict(visible=False, range=[0, 1]),
        height=100,
        margin=dict(t=10, b=35, l=10, r=10),
        plot_bgcolor="white",
        paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.1,
                    font=dict(size=10)),
    )
    return fig


def all_scenarios_bar(df: pd.DataFrame) -> go.Figure:
    """Grouped bar: fixed vs adaptive avg travel time per scenario."""
    rows = []
    for sc in df["scenario"].unique():
        sub = df[df["scenario"] == sc]
        f = sub[sub["controller"] == "FixedTimeController"]["avg_travel_time"].mean()
        a = sub[sub["controller"] == "AdaptiveController"]["avg_travel_time"].mean()
        rows.append({"Scenario": sc, "Fixed-Time": round(f, 1),
                     "Adaptive": round(a, 1)})
    dfs = pd.DataFrame(rows)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Fixed-Time", x=dfs["Scenario"], y=dfs["Fixed-Time"],
        marker_color="#E74C3C", text=dfs["Fixed-Time"],
        textposition="outside", texttemplate="%{text}s"
    ))
    fig.add_trace(go.Bar(
        name="Adaptive", x=dfs["Scenario"], y=dfs["Adaptive"],
        marker_color="#27AE60", text=dfs["Adaptive"],
        textposition="outside", texttemplate="%{text}s"
    ))
    fig.update_layout(
        barmode="group",
        yaxis_title="Avg Travel Time (s)",
        height=320,
        margin=dict(t=20, b=40, l=50, r=20),
        plot_bgcolor="#F8F9FA",
        paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# MAIN APP
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ensure_data()
    df = load_data(DATA_PATH)

    if df.empty:
        st.error("⚠️ Could not load simulation data. "
                 "Run `python simulation.py` first.")
        st.stop()

    # ── Header ───────────────────────────────────────────────────────────
    st.markdown("""
    <div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                padding: 20px 28px; border-radius: 10px; margin-bottom: 18px;'>
      <h2 style='color: #E8E8E8; margin: 0; font-size: 22px;'>🚦 Ending the Wait</h2>
      <p style='color: #90CAF9; margin: 4px 0 0; font-size: 13px;'>
        AI-Powered Traffic Signal Intelligence · COMP1945 Group 17
      </p>
    </div>
    """, unsafe_allow_html=True)

    # ── Sidebar ───────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### ⚙️ Configuration")
        scenario = st.selectbox(
            "Traffic Scenario",
            options=sorted(df["scenario"].unique()),
            index=0,
        )
        weather_icon = "🌧️ Rainy" if "Rainy" in scenario else "☀️ Clear"
        st.info(f"**Weather:** {weather_icon}")

        st.markdown("---")
        st.markdown("### 📖 Phase Guide")
        for ph, lbl in {0: "NS Green", 2: "EW Green",
                         1: "Yellow", 4: "Pedestrian"}.items():
            color = PHASE_COLORS[ph]
            st.markdown(
                f"<span style='background:{color}; color:white; "
                f"padding:2px 8px; border-radius:4px; font-size:12px'>"
                f"{lbl}</span>",
                unsafe_allow_html=True,
            )
            st.write("")

        st.markdown("---")
        st.markdown("### 🎯 Targets")
        st.markdown("- Wait time **≥10%** reduction")
        st.markdown("- Queue **≥15%** reduction (P85)")
        st.markdown("- Accuracy **≥85%**")

        if st.button("🔄 Re-run Simulation"):
            import subprocess
            with st.spinner("Running simulation…"):
                subprocess.run([sys.executable, "simulation.py"], check=True)
            _clear_cache_safe()
            st.rerun()

    # ── Filter data ───────────────────────────────────────────────────────
    sub = df[df["scenario"] == scenario]
    df_fixed    = sub[sub["controller"] == "FixedTimeController"].reset_index(drop=True)
    df_adaptive = sub[sub["controller"] == "AdaptiveController"].reset_index(drop=True)

    # ── KPI row ───────────────────────────────────────────────────────────
    st.subheader(f"📊 {scenario}")
    c1, c2, c3, c4, c5 = st.columns(5)

    f_avg = df_fixed["avg_travel_time"].mean()
    a_avg = df_adaptive["avg_travel_time"].mean()
    imp_pct = (f_avg - a_avg) / f_avg * 100 if f_avg > 0 else 0

    f_q_peak = int(df_fixed[["q_N","q_E","q_S","q_W"]].sum(axis=1).quantile(0.85))
    a_q_peak = int(df_adaptive[["q_N","q_E","q_S","q_W"]].sum(axis=1).quantile(0.85))
    q_imp    = (f_q_peak - a_q_peak) / f_q_peak * 100 if f_q_peak > 0 else 0

    c1.metric("Fixed-Time Avg Delay",   f"{f_avg:.1f} s")
    c2.metric("Adaptive Avg Delay",     f"{a_avg:.1f} s",
              delta=f"{imp_pct:.1f}% vs fixed",
              delta_color="inverse" if imp_pct > 0 else "normal")
    c3.metric("Travel Time Improvement",
              f"{imp_pct:.1f}%",
              delta="✅ Target met" if imp_pct >= 10 else "❌ Below 10% target",
              delta_color="normal" if imp_pct >= 10 else "off")
    c4.metric("Queue P85 (Fixed)",       f"{f_q_peak} veh")
    c5.metric("Queue P85 (Adaptive)",    f"{a_q_peak} veh",
              delta=f"{q_imp:.1f}% vs fixed",
              delta_color="inverse" if q_imp > 0 else "normal")

    st.divider()

    # ── Queue evolution ───────────────────────────────────────────────────
    st.subheader("🚗 Queue Length per Approach")
    col_left, col_right = st.columns(2)
    with col_left:
        st.plotly_chart(
            queue_chart(df_fixed, "Fixed-Time Controller (Baseline)"),
            use_container_width=True
        )
    with col_right:
        st.plotly_chart(
            queue_chart(df_adaptive, "Adaptive Controller (Proposed)"),
            use_container_width=True
        )

    # ── Travel time comparison ────────────────────────────────────────────
    st.subheader("⏱️ Average Travel Time: Adaptive vs Fixed-Time")
    st.plotly_chart(
        travel_time_chart(df_fixed, df_adaptive),
        use_container_width=True
    )

    # ── Phase timelines ───────────────────────────────────────────────────
    st.subheader("🚥 Signal Phase Timelines")
    st.markdown("**Fixed-Time** (rigid 70-second cycle)")
    st.plotly_chart(phase_timeline(df_fixed, "Fixed"), use_container_width=True)
    st.markdown("**Adaptive** (demand-responsive — phase lengths vary)")
    st.plotly_chart(phase_timeline(df_adaptive, "Adaptive"),
                    use_container_width=True)

    st.divider()

    # ── All scenarios summary ─────────────────────────────────────────────
    st.subheader("📈 All Scenarios: Performance Summary")
    col_bar, col_table = st.columns([3, 2])
    with col_bar:
        st.plotly_chart(all_scenarios_bar(df), use_container_width=True)
    with col_table:
        rows = []
        for sc in df["scenario"].unique():
            s = df[df["scenario"] == sc]
            f = s[s["controller"] == "FixedTimeController"]["avg_travel_time"].mean()
            a = s[s["controller"] == "AdaptiveController"]["avg_travel_time"].mean()
            imp = (f - a) / f * 100 if f > 0 else 0
            rows.append({
                "Scenario":        sc,
                "Fixed (s)":       round(f, 1),
                "Adaptive (s)":    round(a, 1),
                "Improvement":     f"{imp:.1f}%",
                "≥10% Target":     "✅" if imp >= 10 else "❌",
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True,
                     use_container_width=True)

    st.divider()

    # ── State log sample ──────────────────────────────────────────────────
    st.subheader("📋 State Log (Adaptive Controller — first 20 rows)")
    cols = ["timestamp", "step", "q_N", "q_E", "q_S", "q_W",
            "phase_label", "total_vehicles", "avg_travel_time"]
    show_cols = [c for c in cols if c in df_adaptive.columns]
    st.dataframe(
        df_adaptive[show_cols].head(20).reset_index(drop=True),
        use_container_width=True,
    )

    # ── Download button ───────────────────────────────────────────────────
    csv_bytes = df.to_csv(index=False).encode()
    st.download_button(
        label="⬇️  Download Full CSV",
        data=csv_bytes,
        file_name="simulation_state_log.csv",
        mime="text/csv",
    )

    # ── Footer ────────────────────────────────────────────────────────────
    st.markdown("---")
    st.caption(
        "COMP1945 (L2) Group 17 — Ending the Wait: AI-Powered Traffic Signal Intelligence  |  "
        "Simulation: CityFlow (synthetic fallback)  |  "
        "Dashboard: Streamlit + Plotly"
    )


if __name__ == "__main__":
    main()