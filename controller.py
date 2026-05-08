"""
controller.py
-------------
Adaptive and Fixed-Time signal controllers for COMP1945 Group 17.
Imported by simulation.py and dashboard.py.

Phase encoding (matches CityFlow roadnet trafficLight.lightphases indices):
    0 = NS Green  (road_0_1_0 + road_3_1_0 open)
    1 = Yellow    (all-red transition after NS)
    2 = EW Green  (road_2_1_0 + road_4_1_0 open)
    3 = Yellow    (all-red transition after EW)
    4 = Pedestrian phase (all vehicles red, conceptual)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from collector import StateSnapshot

# ─────────────────────────────────────────────────────────────────────────────
# PHASE CONSTANTS  (exported for simulation.py and dashboard.py)
# ─────────────────────────────────────────────────────────────────────────────

PHASE_NS_GREEN   = 0
PHASE_YELLOW_NS  = 1
PHASE_EW_GREEN   = 2
PHASE_YELLOW_EW  = 3
PHASE_PEDESTRIAN = 4   # synthetic phase (CityFlow uses phase 1/3 all-red)

PHASE_LABELS = {
    PHASE_NS_GREEN:   "NS Green",
    PHASE_YELLOW_NS:  "Yellow",
    PHASE_EW_GREEN:   "EW Green",
    PHASE_YELLOW_EW:  "Yellow",
    PHASE_PEDESTRIAN: "Pedestrian",
}

# ─────────────────────────────────────────────────────────────────────────────
# BASE CLASS
# ─────────────────────────────────────────────────────────────────────────────

class BaseController:
    """Common interface for all controllers."""

    def __init__(self):
        self.current_phase: int = PHASE_NS_GREEN
        self._step_in_phase: int = 0   # seconds spent in current phase

    def decide(self, step: int, state: Optional["StateSnapshot"]) -> int:
        """
        Called every simulation step.
        Returns the CityFlow phase index to apply (0, 1, 2, or 3).
        Phase 4 (pedestrian) is mapped to phase 1 (all-red) for CityFlow.
        """
        raise NotImplementedError

    @staticmethod
    def cityflow_phase(phase: int) -> int:
        """Map internal phase (0-4) to CityFlow lightphase index (0-3)."""
        if phase == PHASE_PEDESTRIAN:
            return PHASE_YELLOW_NS  # use all-red slot in CityFlow
        return phase


# ─────────────────────────────────────────────────────────────────────────────
# 1. FIXED-TIME CONTROLLER  (baseline)
# ─────────────────────────────────────────────────────────────────────────────

class FixedTimeController(BaseController):
    """
    Fixed pre-timed signal plan (Section 3.4.1 baseline):
        NS Green  : 30 s
        Yellow    :  5 s
        EW Green  : 30 s
        Yellow    :  5 s
    Total cycle  : 70 s  (matches CityFlow roadnet.json lightphases)
    """

    CYCLE = [
        (PHASE_NS_GREEN,  30),
        (PHASE_YELLOW_NS,  5),
        (PHASE_EW_GREEN,  30),
        (PHASE_YELLOW_EW,  5),
    ]

    def __init__(self):
        super().__init__()
        self._cycle_step = 0          # index into CYCLE list
        self._elapsed   = 0           # seconds in current phase

    def decide(self, step: int, state: Optional["StateSnapshot"]) -> int:
        phase_id, duration = self.CYCLE[self._cycle_step]
        self.current_phase = phase_id
        self._elapsed += 1
        if self._elapsed >= duration:
            self._elapsed = 0
            self._cycle_step = (self._cycle_step + 1) % len(self.CYCLE)
        return self.cityflow_phase(phase_id)


# ─────────────────────────────────────────────────────────────────────────────
# 2. ADAPTIVE RULE-BASED CONTROLLER  (proposed system)
# ─────────────────────────────────────────────────────────────────────────────

class AdaptiveController(BaseController):
    """
    Rule-based adaptive signal controller (Section 3.3.1 algorithm).

    Decision logic (evaluated every Δt = 5 seconds):
    1. Apply weather discharge penalty if weather == 1.
    2. Trigger pedestrian phase if ped wait > PED_WAIT_THRESHOLD.
    3. Favour NS or EW if demand ratio > DEMAND_RATIO_THRESHOLD.
    4. Extend green for heavy-vehicle mix (vehicle_mix > HGV_THRESHOLD).
    5. Apply transit-signal priority (TSP) if bus_approaching flag is set.

    Yellow transitions are always inserted between phase changes.
    """

    # ── Tuning parameters (Section 3.3.1) ────────────────────────────────────
    MIN_GREEN           = 10    # seconds — minimum green time
    MAX_GREEN           = 60    # seconds — maximum green time (saturation limit)
    YELLOW_TIME         =  5    # seconds — fixed yellow/all-red
    DEMAND_RATIO_THRESH = 1.5   # NS/EW demand ratio to trigger phase switch
    PED_WAIT_THRESHOLD  = 60    # seconds — force pedestrian phase
    HGV_EXTENSION       = 10    # extra seconds for heavy-vehicle majority
    STD_EXTENSION       =  6    # extra seconds for normal conditions
    TSP_EXTENSION       =  8    # extra seconds for approaching bus
    BASE_GREEN          = 20    # default green when demand is balanced

    def __init__(self, weather: int = 0):
        super().__init__()
        # Store scenario weather (0=clear, 1=rain) for any controller-level
        # tuning that might depend on weather. State snapshots also include
        # weather, but keeping this value ensures compatibility with
        # simulation.py which constructs controllers with a `weather` arg.
        self.weather = weather
        self.current_phase   = PHASE_NS_GREEN
        self._phase_timer    = 0          # seconds spent in current phase
        self._yellow_pending = False      # True when a yellow phase is queued
        self._yellow_timer   = 0
        self._next_phase     = PHASE_EW_GREEN
        self._ped_phase_active = False
        self._ped_timer      = 0
        self.PED_PHASE_TIME  = 15         # pedestrian phase duration (s)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _green_duration(self, state: "StateSnapshot",
                        favoured_ns: bool) -> int:
        """Compute adaptive green duration from state."""
        base = self.BASE_GREEN

        # Weather penalty: rain slows discharge, so we allow longer green
        if state.weather == 1:
            base += 5

        # Heavy vehicle extension
        if state.vehicle_mix > 0.30:
            extension = self.HGV_EXTENSION
        else:
            extension = self.STD_EXTENSION

        # Transit signal priority
        tsp_bonus = self.TSP_EXTENSION if getattr(state, "bus_approaching", 0) else 0

        duration = base + extension + tsp_bonus
        return max(self.MIN_GREEN, min(self.MAX_GREEN, duration))

    def _should_switch_to_ew(self, state: "StateSnapshot") -> bool:
        ew = state.ew_demand
        ns = state.ns_demand
        if ns == 0:
            return True   # NS empty, give EW a turn
        return (ew / ns) > self.DEMAND_RATIO_THRESH

    def _should_switch_to_ns(self, state: "StateSnapshot") -> bool:
        ns = state.ns_demand
        ew = state.ew_demand
        if ew == 0:
            return True
        return (ns / ew) > self.DEMAND_RATIO_THRESH

    def _ped_needed(self, state: "StateSnapshot") -> bool:
        return (state.p_NS > self.PED_WAIT_THRESHOLD or
                state.p_EW > self.PED_WAIT_THRESHOLD or
                (state.p_NS + state.p_EW) > 30)

    # ── Main decision loop (called every second) ──────────────────────────────

    def decide(self, step: int, state: Optional["StateSnapshot"]) -> int:
        """
        Returns CityFlow phase index.
        State may be None on the very first step (before first perception tick).
        """
        if state is None:
            return self.cityflow_phase(self.current_phase)

        # ── Pedestrian phase active ───────────────────────────────────────────
        if self._ped_phase_active:
            self._ped_timer += 1
            if self._ped_timer >= self.PED_PHASE_TIME:
                self._ped_phase_active = False
                self._ped_timer = 0
                self.current_phase = PHASE_NS_GREEN
                self._phase_timer  = 0
            return self.cityflow_phase(PHASE_PEDESTRIAN)

        # ── Yellow transition (process every step, not just every 5) ─────────
        if self._yellow_pending:
            self._yellow_timer += 1
            leaving = (PHASE_YELLOW_NS
                       if self._next_phase in (PHASE_EW_GREEN, PHASE_PEDESTRIAN)
                       else PHASE_YELLOW_EW)
            if self._yellow_timer >= self.YELLOW_TIME:
                self._yellow_pending = False
                self._yellow_timer   = 0
                if self._next_phase == PHASE_PEDESTRIAN:
                    self._ped_phase_active = True
                    self._ped_timer        = 0
                    self.current_phase     = PHASE_PEDESTRIAN
                else:
                    self.current_phase = self._next_phase
                self._phase_timer = 0
            return self.cityflow_phase(leaving)

        # ── Count time in current phase ───────────────────────────────────────
        self._phase_timer += 1

        # ── Only re-evaluate every 5 seconds ─────────────────────────────────
        if self._phase_timer % 5 != 0:
            return self.cityflow_phase(self.current_phase)

        # ── Compute green duration for current phase ──────────────────────────
        green_dur = self._green_duration(
            state, favoured_ns=(self.current_phase == PHASE_NS_GREEN))

        # ── Pedestrian priority ───────────────────────────────────────────────
        if self._ped_needed(state) and self._phase_timer >= self.MIN_GREEN:
            self._yellow_pending = True
            self._yellow_timer   = 0
            self._next_phase     = PHASE_PEDESTRIAN
            return self.cityflow_phase(PHASE_YELLOW_NS
                                       if self.current_phase == PHASE_NS_GREEN
                                       else PHASE_YELLOW_EW)

        # ── Vehicle demand check ──────────────────────────────────────────────
        if self.current_phase == PHASE_NS_GREEN:
            if self._phase_timer >= green_dur or self._should_switch_to_ew(state):
                self._yellow_pending = True
                self._yellow_timer   = 0
                self._next_phase     = PHASE_EW_GREEN

        elif self.current_phase == PHASE_EW_GREEN:
            if self._phase_timer >= green_dur or self._should_switch_to_ns(state):
                self._yellow_pending = True
                self._yellow_timer   = 0
                self._next_phase     = PHASE_NS_GREEN

        return self.cityflow_phase(self.current_phase)


# ─────────────────────────────────────────────────────────────────────────────
# QUICK SELF-TEST
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from collector import StateSnapshot

    print("── FixedTimeController ──")
    ft = FixedTimeController()
    phases = [ft.decide(s, None) for s in range(80)]
    print("First 80 steps phases:", phases)

    print("\n── AdaptiveController (morning peak state) ──")
    ac = AdaptiveController()
    state = StateSnapshot(q_N=10, q_E=3, q_S=8, q_W=2,
                          p_NS=20, p_EW=70,
                          time_slot=8, weather=0, vehicle_mix=0.05)
    for s in range(0, 100, 5):
        ph = ac.decide(s, state)
        print(f"  step={s:3d}  phase={ph} ({PHASE_LABELS.get(ph,'?')})")
