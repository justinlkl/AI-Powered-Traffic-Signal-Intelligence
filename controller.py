"""
controller.py  (project root — flat layout for GitHub Codespaces)
------------------------------------------------------------------
Fixed-Time and Adaptive Rule-Based signal controllers.

Phase encoding (CityFlow roadnet lightphases indices):
    0 = NS Green   (road_0_1_0 + road_3_1_0 open)
    1 = Yellow     (all-red transition)
    2 = EW Green   (road_2_1_0 + road_4_1_0 open)
    3 = Yellow     (all-red transition)
    4 = Pedestrian (synthetic — mapped to all-red in CityFlow)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from collector import StateSnapshot

# ─── Phase constants ───────────────────────────────────────────────────────
PHASE_NS_GREEN   = 0
PHASE_YELLOW_NS  = 1
PHASE_EW_GREEN   = 2
PHASE_YELLOW_EW  = 3
PHASE_PEDESTRIAN = 4

PHASE_LABELS = {
    0: "NS Green",
    1: "Yellow",
    2: "EW Green",
    3: "Yellow",
    4: "Pedestrian",
}

PHASE_COLORS = {
    0: "#27AE60",
    1: "#F39C12",
    2: "#2980B9",
    3: "#F39C12",
    4: "#8E44AD",
}


# ─────────────────────────────────────────────────────────────────────────────
# 1. FIXED-TIME CONTROLLER  (baseline)
# ─────────────────────────────────────────────────────────────────────────────

class FixedTimeController:
    """
    Rigid pre-timed 70-second cycle:
        NS Green 30s → Yellow 5s → EW Green 30s → Yellow 5s
    Represents current HK Transport Department fixed-plan operation.
    """

    CYCLE = [
        (PHASE_NS_GREEN,  30),
        (PHASE_YELLOW_NS,  5),
        (PHASE_EW_GREEN,  30),
        (PHASE_YELLOW_EW,  5),
    ]

    def __init__(self):
        self.current_phase: int = PHASE_NS_GREEN
        self._cycle_idx: int = 0
        self._elapsed:   int = 0

    def decide(self, step: int, state=None) -> int:
        phase_id, duration = self.CYCLE[self._cycle_idx]
        self.current_phase = phase_id
        self._elapsed += 1
        if self._elapsed >= duration:
            self._elapsed = 0
            self._cycle_idx = (self._cycle_idx + 1) % len(self.CYCLE)
        return phase_id   # CityFlow uses 0-3 directly

    def reset(self):
        self.current_phase = PHASE_NS_GREEN
        self._cycle_idx = 0
        self._elapsed = 0


# ─────────────────────────────────────────────────────────────────────────────
# 2. ADAPTIVE RULE-BASED CONTROLLER
# ─────────────────────────────────────────────────────────────────────────────

class AdaptiveController:
    """
    Rule-based adaptive controller (Section 3.3 of the report).

    Three prioritised rules evaluated every MIN_EVAL_INTERVAL seconds:

    Rule 1 – Pedestrian priority
        If p_NS > PED_WAIT_THRESHOLD OR p_EW > PED_WAIT_THRESHOLD
        AND at least MIN_GREEN seconds have elapsed:
            → Trigger pedestrian phase (PED_PHASE_DUR seconds).

    Rule 2 – Queue demand comparison
        If opposing demand > DEMAND_RATIO × current demand:
            → Switch phase.
        Rain: demand estimates scaled by RAIN_DISCHARGE_FACTOR (0.65).

    Rule 3 – Max green cap
        If phase_timer ≥ MAX_GREEN → force rotation regardless of demand.

    Yellow transitions (YELLOW_DUR seconds) are inserted on every switch.
    """

    # ── Tuning knobs ──────────────────────────────────────────────────────
    MIN_GREEN            = 12    # minimum green before any switch
    MAX_GREEN            = 38    # hard cap on green extension
    YELLOW_DUR           =  5    # yellow/all-red transition
    PED_PHASE_DUR        = 20    # pedestrian crossing window (clear)
    PED_PHASE_DUR_RAIN   = 25    # pedestrian crossing window (rain)
    PED_WAIT_THRESHOLD   = 90    # seconds before forced ped phase (raised from 60)
    DEMAND_RATIO         = 1.4   # switch if opposing > this × current (was 1.5)
    RAIN_DISCHARGE       = 0.65  # effective discharge in rain
    MIN_EVAL_INTERVAL    =  5    # only re-evaluate every N seconds
    TSP_EXTENSION        =  8    # extra green for approaching bus

    def __init__(self, weather: int = 0):
        self.weather           = weather
        self.current_phase: int = PHASE_NS_GREEN
        self._phase_timer      = 0    # seconds in current phase
        self._in_yellow        = False
        self._yellow_timer     = 0
        self._next_phase       = PHASE_EW_GREEN
        self._in_pedestrian    = False
        self._ped_timer        = 0

    # ── Public API ────────────────────────────────────────────────────────

    def decide(self, step: int, state) -> int:
        """Called every simulation second. Returns CityFlow phase index."""
        if state is None:
            return self.current_phase

        self._phase_timer += 1

        # ── Handle pedestrian phase ────────────────────────────────────
        if self._in_pedestrian:
            self._ped_timer += 1
            dur = (self.PED_PHASE_DUR_RAIN if self.weather == 1
                   else self.PED_PHASE_DUR)
            if self._ped_timer >= dur:
                self._in_pedestrian = False
                self._ped_timer     = 0
                self._start_phase(PHASE_NS_GREEN)
            # Map pedestrian to CityFlow all-red (yellow slot)
            return PHASE_YELLOW_NS

        # ── Handle yellow transition ───────────────────────────────────
        if self._in_yellow:
            self._yellow_timer += 1
            leaving = (PHASE_YELLOW_NS if self.current_phase == PHASE_NS_GREEN
                       else PHASE_YELLOW_EW)
            if self._yellow_timer >= self.YELLOW_DUR:
                self._in_yellow    = False
                self._yellow_timer = 0
                if self._next_phase == PHASE_PEDESTRIAN:
                    self._in_pedestrian = True
                    self._ped_timer     = 0
                    self.current_phase  = PHASE_PEDESTRIAN
                else:
                    self._start_phase(self._next_phase)
            return leaving

        # ── Re-evaluate only every MIN_EVAL_INTERVAL steps ─────────────
        if self._phase_timer % self.MIN_EVAL_INTERVAL != 0:
            return self.current_phase

        # ── Rule 1: Pedestrian priority ────────────────────────────────
        if (self._phase_timer >= self.MIN_GREEN and
                (state.p_NS > self.PED_WAIT_THRESHOLD or
                 state.p_EW > self.PED_WAIT_THRESHOLD)):
            self._trigger_yellow(PHASE_PEDESTRIAN)
            return (PHASE_YELLOW_NS if self.current_phase == PHASE_NS_GREEN
                    else PHASE_YELLOW_EW)

        # ── Rule 2: Queue demand comparison ───────────────────────────
        if self._phase_timer >= self.MIN_GREEN:
            ns_dem = state.ns_demand
            ew_dem = state.ew_demand

            # Rain: scale demand by reduced discharge capacity
            if state.weather == 1:
                ns_dem *= self.RAIN_DISCHARGE
                ew_dem *= self.RAIN_DISCHARGE

            # TSP: if bus approaching and currently red for its direction,
            # give extra time before switching
            tsp_bonus = self.TSP_EXTENSION if getattr(state, "bus_approaching", 0) else 0
            # Rain: shorter max green forces faster rotation → better load balancing
            weather_cap = 20 if (state.weather == 1) else self.MAX_GREEN
            effective_max = min(weather_cap, weather_cap + tsp_bonus)

            if self.current_phase == PHASE_NS_GREEN:
                should_switch = (ew_dem > ns_dem * self.DEMAND_RATIO or
                                 self._phase_timer >= effective_max)
                if should_switch:
                    self._trigger_yellow(PHASE_EW_GREEN)

            elif self.current_phase == PHASE_EW_GREEN:
                should_switch = (ns_dem > ew_dem * self.DEMAND_RATIO or
                                 self._phase_timer >= effective_max)
                if should_switch:
                    self._trigger_yellow(PHASE_NS_GREEN)

        # ── Rule 3: Absolute max green cap ────────────────────────────
        if self._phase_timer >= self.MAX_GREEN:
            if self.current_phase == PHASE_NS_GREEN:
                self._trigger_yellow(PHASE_EW_GREEN)
            elif self.current_phase == PHASE_EW_GREEN:
                self._trigger_yellow(PHASE_NS_GREEN)

        return self.current_phase

    def reset(self):
        self.current_phase  = PHASE_NS_GREEN
        self._phase_timer   = 0
        self._in_yellow     = False
        self._yellow_timer  = 0
        self._in_pedestrian = False
        self._ped_timer     = 0

    # ── Internal helpers ─────────────────────────────────────────────

    def _start_phase(self, phase: int):
        self.current_phase = phase
        self._phase_timer  = 0

    def _trigger_yellow(self, next_phase: int):
        self._in_yellow    = True
        self._yellow_timer = 0
        self._next_phase   = next_phase


# ─────────────────────────────────────────────────────────────────────────────
# SELF-TEST
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        from collector import StateSnapshot
    except ImportError:
        from dataclasses import dataclass as _dc
        @_dc
        class StateSnapshot:
            q_N: float = 0; q_E: float = 0; q_S: float = 0; q_W: float = 0
            p_NS: float = 0; p_EW: float = 0; time_slot: int = 8
            weather: int = 0; vehicle_mix: float = 0; bus_approaching: int = 0
            @property
            def ns_demand(self): return self.q_N + self.q_S
            @property
            def ew_demand(self): return self.q_E + self.q_W

    print("── FixedTimeController (first 80 steps) ──")
    ft = FixedTimeController()
    dist = {}
    for s in range(80):
        p = ft.decide(s, None)
        dist[PHASE_LABELS[p]] = dist.get(PHASE_LABELS[p], 0) + 1
    print("Phase distribution:", dist)

    print("\n── AdaptiveController (morning peak, 300 steps) ──")
    ac = AdaptiveController(weather=0)
    state = StateSnapshot(q_N=10, q_E=4, q_S=8, q_W=3,
                          p_NS=20, p_EW=20, time_slot=8, weather=0)
    dist2 = {}
    for s in range(300):
        p = ac.decide(s, state)
        dist2[PHASE_LABELS[p]] = dist2.get(PHASE_LABELS[p], 0) + 1
    print("Phase distribution:", dist2)
    print("NS green %:", round(dist2.get("NS Green", 0) / 300 * 100, 1))
    print("EW green %:", round(dist2.get("EW Green", 0) / 300 * 100, 1))