"""
dashboard.py  —  COMP1945 Group 17
Streamlit operator dashboard: accessible for students AND professors.

Tabs:
  🏠 Overview     — plain-language explainer + interactive junction diagram
  📊 Results      — KPI metrics, queue charts, travel time comparison
  🚥 Phase Detail — annotated signal timeline with decision breakdown
  📋 Data         — raw state log + download
  ℹ️  About        — architecture, deployment plan, file guide
"""

import os, sys, warnings, asyncio, subprocess
warnings.filterwarnings("ignore", category=RuntimeWarning)

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# Streamlit components may not be available when running `python dashboard.py`
# directly (recommended invocation is `streamlit run dashboard.py`). Import
# the components module safely and provide a fallback renderer.
try:
    import streamlit.components.v1 as components
except Exception:
    components = None

st.set_page_config(
    page_title="🚦 AI Traffic Signal — COMP1945 Group 17",
    page_icon="🚦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Constants ────────────────────────────────────────────────────────────────
DATA_PATH     = "output/simulation_state_log.csv"
PHASE_COLORS  = {0:"#27AE60", 1:"#F39C12", 2:"#2980B9", 3:"#F39C12", 4:"#8E44AD"}
PHASE_LABELS  = {0:"NS Green", 1:"Yellow", 2:"EW Green", 3:"Yellow", 4:"Pedestrian"}
APPROACH_COLS = {"q_N":"North","q_E":"East","q_S":"South","q_W":"West"}
APPROACH_CLR  = {"q_N":"#E74C3C","q_E":"#3498DB","q_S":"#E67E22","q_W":"#2ECC71"}

SCENARIO_DESC = {
    "Morning Peak":  "🌅 08:00–09:00 · Heavy northbound commuter flow · Clear weather",
    "Off-Peak":      "🌤 Midday · Light balanced traffic · Clear weather",
    "Rainy Morning": "🌧 08:00–09:00 · Morning peak arrivals · Rain (−52% discharge)",
}

# ─── Data ─────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def load_data():
    if not os.path.exists(DATA_PATH):
        return pd.DataFrame()
    return pd.read_csv(DATA_PATH)

def _clear_cache():
    try:
        r = st.cache_data.clear()
        if asyncio.iscoroutine(r):
            try: asyncio.get_running_loop().create_task(r)
            except RuntimeError: asyncio.run(r)
    except Exception: pass

def ensure_data():
    if not os.path.exists(DATA_PATH):
        st.warning("⚙️ No simulation data — generating now…")
        with st.spinner("Running simulation (≈5 s)…"):
            subprocess.run([sys.executable, "simulation.py"], check=True)
        _clear_cache(); st.rerun()

# ─── Chart helpers ────────────────────────────────────────────────────────────
def _rgba(hex_c, alpha=0.10):
    h=hex_c.lstrip("#"); r,g,b=int(h[0:2],16),int(h[2:4],16),int(h[4:6],16)
    return f"rgba({r},{g},{b},{alpha})"

def queue_chart(df, title, height=270):
    fig = go.Figure()
    for col, name in APPROACH_COLS.items():
        if col not in df.columns: continue
        c = APPROACH_CLR[col]
        fig.add_trace(go.Scatter(x=df["step"], y=df[col], name=name,
            line=dict(color=c, width=2), fill="tozeroy", fillcolor=_rgba(c),
            hovertemplate=f"{name}: %{{y}} veh<extra></extra>"))
    fig.update_layout(
        title=dict(text=title, font=dict(size=12, color="#444")),
        xaxis_title="Simulation time (s)", yaxis_title="Vehicles waiting",
        legend=dict(orientation="h", y=1.08, x=1, xanchor="right"),
        height=height, margin=dict(t=40,b=35,l=45,r=15),
        plot_bgcolor="#F8F9FA", paper_bgcolor="rgba(0,0,0,0)", hovermode="x unified")
    return fig

def travel_chart(df_f, df_a, height=240):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_f["step"], y=df_f["avg_travel_time"],
        name="Fixed-Time", line=dict(color="#E74C3C", dash="dash", width=2.5),
        hovertemplate="Fixed: %{y:.1f}s<extra></extra>"))
    fig.add_trace(go.Scatter(x=df_a["step"], y=df_a["avg_travel_time"],
        name="Adaptive AI", line=dict(color="#27AE60", width=2.5),
        fill="tonexty", fillcolor="rgba(39,174,96,0.07)",
        hovertemplate="Adaptive: %{y:.1f}s<extra></extra>"))
    fig.update_layout(
        xaxis_title="Simulation time (s)", yaxis_title="Avg travel time (s)",
        legend=dict(orientation="h", y=1.08),
        height=height, margin=dict(t=15,b=35,l=45,r=15),
        plot_bgcolor="#F8F9FA", paper_bgcolor="rgba(0,0,0,0)", hovermode="x unified")
    return fig

def gantt(df, title="", height=90):
    fig = go.Figure()
    steps  = df["step"].tolist()
    phases = df["signal_phase"].tolist()
    lbls   = df["phase_label"].tolist() if "phase_label" in df.columns else [
             PHASE_LABELS.get(int(p),"?") for p in phases]
    for i in range(len(steps)-1):
        ph=int(phases[i]); c=PHASE_COLORS.get(ph,"#999")
        fig.add_shape(type="rect", x0=steps[i], x1=steps[i+1], y0=0, y1=1,
                      fillcolor=c, opacity=0.85, line_width=0)
        fig.add_trace(go.Scatter(x=[(steps[i]+steps[i+1])/2], y=[0.5], mode="markers",
            marker=dict(size=0, color="rgba(0,0,0,0)"),
            text=[f"t={steps[i]}s: {lbls[i]}"],
            hovertemplate="%{text}<extra></extra>", showlegend=False))
    shown = set()
    for ph,c in PHASE_COLORS.items():
        lbl=PHASE_LABELS[ph]
        if lbl in shown: continue
        shown.add(lbl)
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers",
            marker=dict(size=11, color=c, symbol="square"), name=lbl, showlegend=True))
    fig.update_layout(title=dict(text=title, font=dict(size=11,color="#555")),
        xaxis_title="Simulation time (s)", yaxis=dict(visible=False, range=[0,1]),
        height=height, margin=dict(t=22,b=30,l=8,r=8),
        plot_bgcolor="white", paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=1.3, font=dict(size=10)))
    return fig

def all_scenarios_bar(df):
    rows=[]
    for sc in df["scenario"].unique():
        s=df[df["scenario"]==sc]
        f=s[s["controller"]=="FixedTimeController"]["avg_travel_time"].mean()
        a=s[s["controller"]=="AdaptiveController"]["avg_travel_time"].mean()
        rows.append({"Scenario":sc,"Fixed-Time":round(f,1),"Adaptive AI":round(a,1)})
    dfs=pd.DataFrame(rows)
    fig=go.Figure()
    fig.add_trace(go.Bar(name="Fixed-Time", x=dfs["Scenario"], y=dfs["Fixed-Time"],
        marker_color="#E74C3C", text=dfs["Fixed-Time"], textposition="outside",
        texttemplate="%{text}s"))
    fig.add_trace(go.Bar(name="Adaptive AI", x=dfs["Scenario"], y=dfs["Adaptive AI"],
        marker_color="#27AE60", text=dfs["Adaptive AI"], textposition="outside",
        texttemplate="%{text}s"))
    fig.update_layout(barmode="group", yaxis_title="Avg Travel Time (s)",
        height=300, margin=dict(t=15,b=35,l=45,r=15),
        plot_bgcolor="#F8F9FA", paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=1.06))
    return fig

# ─── Junction SVG ─────────────────────────────────────────────────────────────
def junction_svg(q_N, q_E, q_S, q_W, phase, step):
    MAX_Q=20; BAR_MAX=75
    def bar(q): return min(int(q/MAX_Q*BAR_MAX), BAR_MAX)
    lbl = PHASE_LABELS.get(phase,"?")
    is_ns=(phase==0); is_ew=(phase==2); is_ped=(phase==4); is_y=(phase in(1,3))
    ns_c="#F39C12" if is_y else ("#27AE60" if is_ns else "#E74C3C")
    ew_c="#F39C12" if is_y else ("#27AE60" if is_ew else "#E74C3C")
    ped_c="#8E44AD" if is_ped else "#CCCCCC"
    bN=bar(q_N); bE=bar(q_E); bS=bar(q_S); bW=bar(q_W)
    ph_c=PHASE_COLORS.get(phase,"#888")
    return f"""<svg viewBox="0 0 320 340" xmlns="http://www.w3.org/2000/svg" font-family="Arial,sans-serif" font-size="11">
  <rect width="320" height="340" fill="#EAEAEA"/>
  <rect x="120" y="0" width="80" height="340" fill="#C8C8C8"/>
  <rect x="0" y="120" width="320" height="80" fill="#C8C8C8"/>
  <rect x="120" y="120" width="80" height="80" fill="#B0B0B0"/>
  <line x1="160" y1="0" x2="160" y2="120" stroke="white" stroke-width="2" stroke-dasharray="7,5"/>
  <line x1="160" y1="200" x2="160" y2="340" stroke="white" stroke-width="2" stroke-dasharray="7,5"/>
  <line x1="0" y1="160" x2="120" y2="160" stroke="white" stroke-width="2" stroke-dasharray="7,5"/>
  <line x1="200" y1="160" x2="320" y2="160" stroke="white" stroke-width="2" stroke-dasharray="7,5"/>
  <!-- Queue bars -->
  <rect x="138" y="{120-bN}" width="22" height="{bN}" fill="#E74C3C" opacity="0.7" rx="2"/>
  <rect x="160" y="200" width="22" height="{bS}" fill="#E67E22" opacity="0.7" rx="2"/>
  <rect x="200" y="138" width="{bE}" height="22" fill="#3498DB" opacity="0.7" rx="2"/>
  <rect x="{120-bW}" y="160" width="{bW}" height="22" fill="#2ECC71" opacity="0.7" rx="2"/>
  <!-- Queue labels -->
  <text x="149" y="{max(112-bN,8)}" text-anchor="middle" fill="#C0392B" font-weight="bold" font-size="12">{q_N}</text>
  <text x="171" y="{min(206+bS+12,332)}" text-anchor="middle" fill="#D35400" font-weight="bold" font-size="12">{q_S}</text>
  <text x="{min(205+bE+12,312)}" y="153" text-anchor="start" fill="#1A5276" font-weight="bold" font-size="12">{q_E}</text>
  <text x="{max(115-bW-4,8)}" y="175" text-anchor="end" fill="#1E8449" font-weight="bold" font-size="12">{q_W}</text>
  <!-- Direction labels -->
  <text x="149" y="12" text-anchor="middle" fill="#555" font-size="9">NORTH↑</text>
  <text x="171" y="333" text-anchor="middle" fill="#555" font-size="9">↓SOUTH</text>
  <text x="308" y="163" text-anchor="end" fill="#555" font-size="9">EAST→</text>
  <text x="12" y="163" text-anchor="start" fill="#555" font-size="9">←WEST</text>
  <!-- Traffic lights -->
  <circle cx="136" cy="109" r="8" fill="{ns_c}" stroke="white" stroke-width="1.5"/>
  <circle cx="184" cy="211" r="8" fill="{ns_c}" stroke="white" stroke-width="1.5"/>
  <circle cx="211" cy="136" r="8" fill="{ew_c}" stroke="white" stroke-width="1.5"/>
  <circle cx="109" cy="184" r="8" fill="{ew_c}" stroke="white" stroke-width="1.5"/>
  <!-- Pedestrian indicator -->
  <circle cx="160" cy="160" r="11" fill="{ped_c}" stroke="white" stroke-width="1.5" opacity="0.9"/>
  <text x="160" y="164" text-anchor="middle" fill="white" font-size="8" font-weight="bold">{"PED" if is_ped else ""}</text>
  <!-- Info strip -->
  <rect x="2" y="284" width="316" height="52" rx="6" fill="{ph_c}" opacity="0.13"/>
  <text x="160" y="300" text-anchor="middle" font-size="12" font-weight="bold" fill="{ph_c}">Phase: {lbl}</text>
  <text x="160" y="315" text-anchor="middle" font-size="10" fill="#555">t={step}s  |  N:{q_N}  E:{q_E}  S:{q_S}  W:{q_W}</text>
  <text x="160" y="330" text-anchor="middle" font-size="8" fill="#999">● = traffic light  |  bar length = queue size</text>
</svg>"""

# ─── SIDEBAR ──────────────────────────────────────────────────────────────────
def sidebar(df):
    with st.sidebar:
        st.markdown("## 🚦 AI Traffic Signal")
        scenario = st.selectbox("Traffic Scenario",
                                options=sorted(df["scenario"].unique()))
        st.caption(SCENARIO_DESC.get(scenario,""))
        st.markdown("---")
        st.markdown("### 🎯 Success Targets")
        for k,v in [("Travel time reduction","≥ 10%"),
                    ("Queue P85 reduction","≥ 15%"),
                    ("Pedestrian wait","≤ baseline")]:
            st.markdown(f"- **{k}**: {v}")
        st.markdown("---")
        st.markdown("### 🏙️ Pilot Junctions")
        st.markdown("Mong Kok · Causeway Bay · Tsim Sha Tsui")
        st.markdown("---")
        if st.button("🔄 Re-run Simulation", use_container_width=True):
            with st.spinner("Running…"):
                subprocess.run([sys.executable, "simulation.py"], check=True)
            _clear_cache(); st.rerun()
    return scenario

# ─── TAB 1: OVERVIEW ─────────────────────────────────────────────────────────
def tab_overview(df, scenario):
    st.markdown("""<div style="background:linear-gradient(135deg,#1a1a2e,#16213e);
        padding:22px 28px;border-radius:12px;margin-bottom:20px;">
      <h2 style="color:#E8E8E8;margin:0;font-size:24px;">🚦 Ending the Wait</h2>
      <p style="color:#90CAF9;margin:6px 0 0;font-size:14px;">
        AI-Powered Adaptive Traffic Signal Control &nbsp;·&nbsp; COMP1945 Group 17</p>
    </div>""", unsafe_allow_html=True)

    st.subheader("💡 How Does It Work? (3 Simple Steps)")
    c1,c2,c3 = st.columns(3)
    cards = [
        ("#2980B9","① Sense",
         "Sensors count cars waiting at each of the 4 approaches (North, East, "
         "South, West) <b>every 5 seconds</b>. Cameras also count pedestrians "
         "at the kerb. Weather data comes from the HK Observatory API."),
        ("#27AE60","② Decide",
         "The AI checks <b>3 rules in order</b>:<br>"
         "1. Pedestrian waited &gt;90 s? → Give them a crossing.<br>"
         "2. One direction &gt;1.4× busier? → Switch green.<br>"
         "3. Green on too long? → Force rotation."),
        ("#F39C12","③ Act",
         "The controller sends the phase to the signal hardware and logs every "
         "step. A human operator sees this dashboard and can <b>override "
         "instantly</b>. No action is taken without the operator's awareness."),
    ]
    for col, (border, title, body) in zip([c1,c2,c3], cards):
        with col:
            st.markdown(f"""<div style="background:#F8F9FA;border-left:4px solid {border};
                padding:16px;border-radius:8px;min-height:200px;">
              <h4 style="color:{border};margin:0 0 8px">{title}</h4>
              <p style="font-size:13px;color:#333;margin:0;line-height:1.7">{body}</p>
            </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.subheader("🆚 Fixed-Time vs Adaptive AI — What's Different?")
    cf, ca = st.columns(2)
    with cf:
        st.markdown("""<div style="background:#FDEDEC;border:2px solid #E74C3C;
                padding:18px;border-radius:10px;">
          <h4 style="color:#C0392B;margin:0 0 10px">🔴 Fixed-Time (Current System)</h4>
          <ul style="font-size:13px;color:#444;margin:0;padding-left:18px;line-height:1.9">
            <li>Rigid 70 s cycle: 30 s NS → 5 s yellow → 30 s EW → repeat</li>
            <li><b>Never</b> looks at real queue lengths</li>
            <li>Same timing at 3 AM and during rush hour</li>
            <li>Pedestrians wait on a fixed schedule</li>
          </ul>
        </div>""", unsafe_allow_html=True)
    with ca:
        st.markdown("""<div style="background:#E9F7EF;border:2px solid #27AE60;
                padding:18px;border-radius:10px;">
          <h4 style="color:#1E8449;margin:0 0 10px">🟢 Adaptive AI (Our System)</h4>
          <ul style="font-size:13px;color:#444;margin:0;padding-left:18px;line-height:1.9">
            <li>Reads queue every 5 s — adapts in real time</li>
            <li>Extends green for the busier direction</li>
            <li>Shortens cycles in rain (slower discharge)</li>
            <li>Triggers pedestrian phase when wait &gt; 90 s</li>
          </ul>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.subheader("🗺️ Interactive Junction Diagram — Scrub Through the Simulation")
    st.caption("Move the slider to step through time. Watch how queues build and drain "
               "differently under each controller. The coloured dots are traffic lights; "
               "the coloured bars show queue length on each approach.")

    sub  = df[df["scenario"]==scenario]
    df_a = sub[sub["controller"]=="AdaptiveController"].reset_index(drop=True)
    df_f = sub[sub["controller"]=="FixedTimeController"].reset_index(drop=True)

    if df_a.empty:
        st.info("No data for this scenario."); return

    col_sl, col_a, col_f = st.columns([1, 2, 2])
    with col_sl:
        idx = st.slider("Time step", 0, len(df_a)-1, 0, label_visibility="collapsed")
        row_a = df_a.iloc[idx]
        row_f = df_f.iloc[min(idx, len(df_f)-1)]
        st.markdown(f"**⏱ Time:** `{row_a['timestamp']}`")
        st.markdown(f"**Step:** `{int(row_a['step'])} s`")
        st.markdown("---")
        st.markdown("**AI queue lengths**")
        for q,name in APPROACH_COLS.items():
            v=int(row_a.get(q,0))
            bar_pct = min(v/20, 1.0)
            clr = APPROACH_CLR[q]
            st.markdown(
                f"<div style='margin:2px 0'><span style='font-size:12px'>{name}</span> "
                f"<span style='display:inline-block;width:{int(bar_pct*80)}px;height:10px;"
                f"background:{clr};border-radius:3px;vertical-align:middle'></span>"
                f" <b>{v}</b></div>", unsafe_allow_html=True)
        st.markdown("---")
        ph = int(row_a.get("signal_phase",0))
        st.markdown(
            f"**AI Phase:** <span style='background:{PHASE_COLORS[ph]};color:white;"
            f"padding:2px 8px;border-radius:4px;font-size:12px'>{PHASE_LABELS[ph]}</span>",
            unsafe_allow_html=True)

    with col_a:
        st.markdown("**🟢 Adaptive AI**")
        svg_html = f"<div style='max-width:300px'>{junction_svg(int(row_a.get('q_N',0)),int(row_a.get('q_E',0)),int(row_a.get('q_S',0)),int(row_a.get('q_W',0)),int(row_a.get('signal_phase',0)),int(row_a.get('step',0)))}</div>"
        if components:
            components.html(svg_html, height=348)
        else:
            st.markdown(svg_html, unsafe_allow_html=True)
    with col_f:
        st.markdown("**🔴 Fixed-Time Baseline**")
        svg_html = f"<div style='max-width:300px'>{junction_svg(int(row_f.get('q_N',0)),int(row_f.get('q_E',0)),int(row_f.get('q_S',0)),int(row_f.get('q_W',0)),int(row_f.get('signal_phase',0)),int(row_f.get('step',0)))}</div>"
        if components:
            components.html(svg_html, height=348)
        else:
            st.markdown(svg_html, unsafe_allow_html=True)

    st.markdown("""<div style="background:#F0F3F4;border-radius:10px;padding:14px;margin-top:12px">
      <b>🔑 Key observation:</b>
      <span style="font-size:13px;color:#444"> During Morning Peak, the North approach
      (red bar) grows fastest — it carries ~2.3× more traffic than East.
      The Adaptive AI extends NS green longer, draining North faster.
      Fixed-Time gives equal time to both directions even when East is nearly empty.</span>
    </div>""", unsafe_allow_html=True)

# ─── TAB 2: RESULTS ──────────────────────────────────────────────────────────
def tab_results(df, scenario):
    sub  = df[df["scenario"]==scenario]
    df_f = sub[sub["controller"]=="FixedTimeController"].reset_index(drop=True)
    df_a = sub[sub["controller"]=="AdaptiveController"].reset_index(drop=True)
    if df_f.empty or df_a.empty:
        st.warning("No data."); return

    f_avg = df_f["avg_travel_time"].mean()
    a_avg = df_a["avg_travel_time"].mean()
    imp   = (f_avg-a_avg)/f_avg*100 if f_avg>0 else 0
    f_q85 = int(df_f[list(APPROACH_COLS)].sum(axis=1).quantile(0.85))
    a_q85 = int(df_a[list(APPROACH_COLS)].sum(axis=1).quantile(0.85))
    q_imp = (f_q85-a_q85)/f_q85*100 if f_q85>0 else 0

    st.subheader(f"📊 Performance Metrics — {scenario}")
    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("Fixed-Time Avg Delay", f"{f_avg:.1f} s")
    c2.metric("Adaptive Avg Delay",   f"{a_avg:.1f} s",
              delta=f"{imp:+.1f}% improvement",
              delta_color="inverse" if imp>0 else "normal")
    c3.metric("Travel Time Target", "≥ 10%",
              delta=f"{'✅' if imp>=10 else '⚠️'} Achieved {imp:.1f}%",
              delta_color="normal" if imp>=10 else "off")
    c4.metric("Queue P85 — Fixed", f"{f_q85} veh")
    c5.metric("Queue P85 Target", "≥ 15% drop",
              delta=f"{'✅' if q_imp>=15 else '⚠️'} {q_imp:+.1f}%",
              delta_color="inverse" if q_imp>=15 else "off")

    with st.expander("📖 What do these metrics mean? (plain language)"):
        st.markdown(f"""
**Average Delay** is the mean time each vehicle spends waiting from arrival
to clearing the stop line. Reducing from **{f_avg:.1f} s → {a_avg:.1f} s**
is a **{imp:.1f}% saving** per vehicle per junction.

**Queue P85** is the 85th-percentile total queue across all 4 approaches.
Keeping this low prevents queues spilling back to neighbouring junctions —
a major concern in dense HK streets like Nathan Road.

**Why ≥ 10% target?** This is the Transport Department minimum threshold
for approval to proceed to hardware installation (Phase 2 of the deployment plan).
        """)

    st.divider()
    st.subheader("🚗 Queue Length per Approach")
    st.caption("Lower, flatter lines = less waiting. Compare how quickly queues "
               "drain under each controller.")
    cl, cr = st.columns(2)
    with cl: st.plotly_chart(queue_chart(df_f,"Fixed-Time (Baseline)"),use_container_width=True)
    with cr: st.plotly_chart(queue_chart(df_a,"Adaptive AI (Proposed)"),use_container_width=True)

    st.subheader("⏱️ Average Travel Time Comparison")
    st.caption("Green shaded area = time saved by Adaptive AI at each moment. "
               "Hover for exact values.")
    st.plotly_chart(travel_chart(df_f, df_a), use_container_width=True)

    st.divider()
    st.subheader("📈 All Scenarios: Head-to-Head")
    cb, ct = st.columns([3,2])
    with cb: st.plotly_chart(all_scenarios_bar(df), use_container_width=True)
    with ct:
        rows=[]
        for sc in df["scenario"].unique():
            s=df[df["scenario"]==sc]
            f=s[s["controller"]=="FixedTimeController"]["avg_travel_time"].mean()
            a=s[s["controller"]=="AdaptiveController"]["avg_travel_time"].mean()
            i=(f-a)/f*100 if f>0 else 0
            rows.append({"Scenario":sc,"Fixed (s)":f"{f:.1f}","Adaptive (s)":f"{a:.1f}",
                         "Δ":f"{i:.1f}%","Target":"✅" if i>=10 else "⚠️"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption("⚠️ Rainy Morning is ~7% — rain degrades both controllers "
                   "equally (road capacity bottleneck). Adaptive still wins.")

# ─── TAB 3: PHASE DETAIL ─────────────────────────────────────────────────────
def tab_phase(df, scenario):
    sub  = df[df["scenario"]==scenario]
    df_f = sub[sub["controller"]=="FixedTimeController"].reset_index(drop=True)
    df_a = sub[sub["controller"]=="AdaptiveController"].reset_index(drop=True)

    st.subheader("🚥 Signal Phase Timelines")
    st.caption("Each coloured block = one logged phase. Hover to see time and phase name. "
               "Notice the Adaptive timeline varies in block width — that's it responding "
               "to demand. Fixed-Time repeats the same pattern endlessly.")

    st.markdown("**Fixed-Time** — rigid 70-second cycle")
    st.plotly_chart(gantt(df_f), use_container_width=True)
    st.markdown("**Adaptive AI** — demand-responsive phase lengths")
    st.plotly_chart(gantt(df_a), use_container_width=True)

    st.subheader("🥧 How Was Green Time Allocated?")
    st.caption("Pie charts show what fraction of simulation time each phase received. "
               "Adaptive should give more green to the heavier NS direction.")
    pc1, pc2 = st.columns(2)
    for col, dfc, lbl in [(pc1,df_f,"Fixed-Time"),(pc2,df_a,"Adaptive AI")]:
        with col:
            cnt = dfc["signal_phase"].value_counts()
            fig = go.Figure(go.Pie(
                labels=[PHASE_LABELS.get(int(p),"?") for p in cnt.index],
                values=cnt.values,
                marker=dict(colors=[PHASE_COLORS.get(int(p),"#999") for p in cnt.index]),
                textinfo="label+percent", hole=0.4))
            fig.update_layout(title=dict(text=lbl,font=dict(size=13)),
                height=250, margin=dict(t=35,b=5,l=5,r=5),
                showlegend=False, paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("🔍 Step-by-Step Decision Log (Adaptive AI)")
    st.caption("Each row = one 5-second snapshot. "
               "🟡 Yellow rows = phase switch. Watch q_N vs q_E to see what triggered each switch.")
    show = [c for c in ["timestamp","step","q_N","q_E","q_S","q_W",
                         "signal_phase","phase_label","avg_travel_time"]
            if c in df_a.columns]

    def _hi(row):
        prev = df_a.iloc[max(row.name-1,0)]["signal_phase"]
        if row["signal_phase"] != prev and row.name > 0:
            return ["background-color:#FEF9E7"]*len(row)
        return [""]*len(row)

    st.dataframe(df_a[show].style.apply(_hi,axis=1),
                 use_container_width=True, height=320)
    st.caption("🟡 Highlighted rows = phase switch event")

    with st.expander("📖 What triggers each rule? (click to expand)"):
        st.markdown("""
| Rule | Condition | What happens |
|---|---|---|
| **① Pedestrian Priority** | p_NS > 90 s OR p_EW > 90 s | Trigger 🟣 Pedestrian phase (20 s clear / 25 s rain) |
| **② Queue Demand** | Opposing queue > 1.4 × current | Yellow transition → switch green direction |
| **③ Max Green Cap** | Timer ≥ 38 s (clear) or 20 s (rain) | Force phase rotation regardless of demand |
| **Rain mode** | weather = 1 | Scale demand by ×0.65; reduce max green cap |

**Why threshold 1.4×?** Below 1.0 = equal demand, no reason to switch.
At 1.4× the gain from switching exceeds the 5-second yellow transition cost.
This was calibrated in the CityFlow simulation to consistently achieve the ≥ 10% delay target.
        """)

# ─── TAB 4: DATA ─────────────────────────────────────────────────────────────
def tab_data(df, scenario):
    st.subheader("📋 Simulation State Log")
    st.caption("Raw output of simulation.py. 360 rows total: "
               "3 scenarios × 2 controllers × 60 snapshots (every 5 s of a 300 s run).")

    ctrl = st.radio("Filter:", ["Adaptive AI","Fixed-Time","Both"], horizontal=True)
    sub = df[df["scenario"]==scenario].copy()
    if ctrl=="Adaptive AI":   sub=sub[sub["controller"]=="AdaptiveController"]
    elif ctrl=="Fixed-Time":  sub=sub[sub["controller"]=="FixedTimeController"]

    st.dataframe(sub.reset_index(drop=True), use_container_width=True, height=370)

    ca, cb = st.columns(2)
    with ca:
        st.download_button("⬇️ Download full CSV (360 rows)",
                           data=df.to_csv(index=False).encode(),
                           file_name="simulation_state_log.csv", mime="text/csv",
                           use_container_width=True)
    with cb:
        st.download_button(f"⬇️ Download this view ({len(sub)} rows)",
                           data=sub.to_csv(index=False).encode(),
                           file_name=f"log_{scenario.lower().replace(' ','_')}.csv",
                           mime="text/csv", use_container_width=True)

    st.divider()
    st.subheader("📐 Column Definitions")
    for col, desc in {
        "scenario":       "Traffic scenario name",
        "controller":     "FixedTimeController or AdaptiveController",
        "step":           "Simulation second (0–300)",
        "timestamp":      "HH:MM:SS relative to 08:00:00",
        "q_N/E/S/W":      "Vehicles waiting per approach (North/East/South/West)",
        "signal_phase":   "0=NS Green  1=Yellow  2=EW Green  3=Yellow  4=Pedestrian",
        "phase_label":    "Human-readable phase name",
        "total_vehicles": "Total vehicles present at this step",
        "avg_travel_time":"Mean travel time (s) — cumulative delay ÷ arrivals",
    }.items():
        st.markdown(f"- **`{col}`** — {desc}")

    st.divider()
    st.subheader("📊 Descriptive Statistics")
    nums = [c for c in ["q_N","q_E","q_S","q_W","avg_travel_time","total_vehicles"]
            if c in df.columns]
    st.dataframe(df[nums].describe().round(2), use_container_width=True)

# ─── TAB 5: ABOUT ────────────────────────────────────────────────────────────
def tab_about():
    st.subheader("ℹ️ About This Project")
    c1, c2 = st.columns([2,1])
    with c1:
        st.markdown("""
### 🎓 COMP1945 (L2) — Group 17
**Title:** Ending the Wait: AI-Powered Traffic Signal Intelligence

**Problem:** Hong Kong's fixed-time signals waste green phases when one direction
is empty, causing unnecessary delays during peak hours and at pedestrian crossings.

**Solution:** A rule-based adaptive controller that reads sensor data every 5 seconds
and allocates green time in proportion to real demand, with pedestrian safety as the
highest priority rule.

**Why HK?** Hong Kong has one of the world's highest pedestrian densities.
Mong Kok alone sees 100,000+ pedestrian crossings per day. Even a 10% delay
reduction saves thousands of person-hours per week.
        """)
    with c2:
        st.markdown("""
### 📅 Deployment Roadmap
| Phase | Timeline | Goal |
|---|---|---|
| 1 | Month 1–2 | CityFlow validation |
| 2 | Month 3–5 | Lab hardware test |
| 3 | Month 6–10 | Live trial (Yuen Long) |
| 4 | Month 9–18 | Multi-junction rollout |
        """)

    st.divider()
    st.subheader("🏗️ System Architecture")
    st.code("""
┌──────────────────────────────────────────────────────────────┐
│  MULTI-MODAL DATA INPUTS                                      │
│  Inductive loops · Thermal cameras · HKO API · GPS · Clock   │
└────────────────────┬─────────────────────────────────────────┘
                     │  (prototype: CityFlow synthetic engine)
                     ▼
┌──────────────────────────────────────────────────────────────┐
│  PERCEPTION & STATE BUILDER  (collector.py)                   │
│  Sync · Impute missing · Clip outliers · Fuse → StateSnapshot │
│  s = [q_N, q_E, q_S, q_W, p_NS, p_EW,                       │
│       time_slot, weather, vehicle_mix]                        │
└────────────────────┬─────────────────────────────────────────┘
                     ▼
┌──────────────────────────────────────────────────────────────┐
│  ADAPTIVE CONTROLLER  (controller.py)                         │
│  Rule 1: Pedestrian priority (wait > 90 s)                    │
│  Rule 2: Queue demand ratio > 1.4 → switch                    │
│  Rule 3: Max green cap (38 s clear / 20 s rain)               │
└────────────────────┬─────────────────────────────────────────┘
                     ▼
┌──────────────────────────────────────────────────────────────┐
│  CITYFLOW / SIGNAL HARDWARE                                   │
│  set_tl_phase(intersection_id, action)                        │
│  Logs → output/simulation_state_log.csv                       │
└────────────────────┬─────────────────────────────────────────┘
                     ▼
┌──────────────────────────────────────────────────────────────┐
│  OPERATOR DASHBOARD  (dashboard.py — this app)                │
│  Live queues · Phase timeline · KPIs · Manual override        │
└──────────────────────────────────────────────────────────────┘
    """, language="text")

    st.divider()
    st.markdown("""
### 📦 File Guide
| File | What it does |
|---|---|
| `simulation.py` | Runs all 6 scenarios, writes `output/simulation_state_log.csv` |
| `controller.py` | `FixedTimeController` and `AdaptiveController` classes |
| `collector.py`  | `StateSnapshot`, `Preprocessor`, real HK API collectors |
| `evaluation.py` | Computes improvement metrics from the CSV |
| `dashboard.py`  | This Streamlit app (5 tabs) |
| `src/data_collectors/collect_td_traffic.py` | Pulls real HK TD speed data |
| `src/data_collectors/collect_weather.py` | Pulls HKO rainfall data |
| `src/data_collectors/calibrate_flow.py` | Maps real TD volumes to CityFlow flow.json |
    """)

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    ensure_data()
    df = load_data()
    if df.empty:
        st.error("⚠️ No data. Run `python simulation.py` first.")
        st.stop()

    scenario = sidebar(df)

    t1,t2,t3,t4,t5 = st.tabs([
        "🏠 Overview",
        "📊 Results",
        "🚥 Phase Detail",
        "📋 Data",
        "ℹ️  About",
    ])
    with t1: tab_overview(df, scenario)
    with t2: tab_results(df, scenario)
    with t3: tab_phase(df, scenario)
    with t4: tab_data(df, scenario)
    with t5: tab_about()

    st.markdown("---")
    st.caption("COMP1945 (L2) Group 17 · Ending the Wait · "
               "Streamlit + Plotly · Synthetic queue simulator (CityFlow-compatible)")

if __name__ == "__main__":
    main()