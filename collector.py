"""
data_pipeline/collector.py
--------------------------
Multi-modal data ingestion layer for the HK Adaptive Traffic Signal System.

In DEPLOYMENT mode: pulls from real HK government APIs (Transport Dept, HK Observatory).
In PROTOTYPE mode:  generates synthetic state from CityFlow simulation outputs.

The controller.py layer consumes the unified StateSnapshot regardless of mode.
"""

import json
import math
import random
import time
import datetime
import requests
from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# 1. DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StateSnapshot:
    """
    Unified 9-dimensional state vector fed to the adaptive controller.
    Constructed every Δt = 5 seconds from any data source.

    Fields match Section 3.3 of the report:
        s = [q_N, q_E, q_S, q_W, p_NS, p_EW, time_slot, weather, vehicle_mix]
    """
    # Queue lengths (vehicles waiting per approach)
    q_N: float = 0.0   # Northbound queue
    q_E: float = 0.0   # Eastbound queue
    q_S: float = 0.0   # Southbound queue
    q_W: float = 0.0   # Westbound queue

    # Pedestrian demand (seconds already waited per crossing direction)
    p_NS: float = 0.0  # NS crossing pedestrian wait time (s)
    p_EW: float = 0.0  # EW crossing pedestrian wait time (s)

    # Temporal context
    time_slot: int = 8  # Hour of day (0-23); 8 = morning peak

    # Environmental context
    weather: int = 0    # 0 = clear, 1 = rain

    # Vehicle composition
    vehicle_mix: float = 0.0  # 0.0 = all private cars, 1.0 = all HGV/buses
    # Transit-signal priority flag (0/1). When set, controllers may extend
    # green times to allow an approaching bus through the intersection.
    bus_approaching: int = 0

    # ── Derived helpers ───────────────────────────────────────────────────
    @property
    def ns_demand(self) -> float:
        return self.q_N + self.q_S

    @property
    def ew_demand(self) -> float:
        return self.q_E + self.q_W

    @property
    def total_queue(self) -> float:
        return self.q_N + self.q_E + self.q_S + self.q_W

    def to_vector(self) -> list:
        return [self.q_N, self.q_E, self.q_S, self.q_W,
                self.p_NS, self.p_EW, self.time_slot,
                self.weather, self.vehicle_mix]

    def __repr__(self):
        return (f"StateSnapshot(q=[{self.q_N:.0f},{self.q_E:.0f},"
                f"{self.q_S:.0f},{self.q_W:.0f}] "
                f"ped=[NS:{self.p_NS:.0f}s EW:{self.p_EW:.0f}s] "
                f"t={self.time_slot}h weather={'rain' if self.weather else 'clear'})")


# ─────────────────────────────────────────────────────────────────────────────
# 2. PREPROCESSING UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

class Preprocessor:
    """
    Implements Section 2.4 preprocessing pipeline:
      2.4.1  Synchronisation     – align timestamps to UTC
      2.4.2  Missing data fill   – forward-fill / historical average imputation
      2.4.3  Outlier removal     – domain-constrained clipping
      2.4.4  Sensor fusion       – merge multi-rate streams into 5-second snapshot
    """

    # HK road reality constraints for outlier clipping (Section 2.4.3)
    MAX_QUEUE_PER_LANE = 50       # vehicles
    MAX_SPEED_KMH      = 80       # km/h on urban arterials
    MAX_PED_WAIT       = 300      # seconds (5 min = extreme outlier)
    MAX_RAIN_MM_HR     = 200      # mm/hr (T10 typhoon upper bound)

    def __init__(self):
        self._history: dict = {}   # {key: [last_good_value, ...]} for imputation

    # ── 2.4.1 Synchronisation ─────────────────────────────────────────────
    @staticmethod
    def now_utc_ms() -> int:
        """Return current UTC time in milliseconds (NTP reference)."""
        return int(time.time() * 1000)

    # ── 2.4.2 Missing data imputation ────────────────────────────────────
    def impute(self, key: str, value: Optional[float],
               gap_seconds: int = 0) -> float:
        """
        If value is None (sensor dropout):
          - gap ≤ 2s  → forward-fill (assume unchanged)
          - gap  > 2s → use same-time-yesterday average from history buffer
        """
        if value is not None:
            buf = self._history.setdefault(key, [])
            buf.append(value)
            if len(buf) > 288:   # keep 24h × 12 samples/hr
                buf.pop(0)
            return value

        buf = self._history.get(key, [])
        if not buf:
            return 0.0
        if gap_seconds <= 2:
            return buf[-1]       # forward-fill
        # historical average of same time slot
        return sum(buf) / len(buf)

    # ── 2.4.3 Outlier removal ────────────────────────────────────────────
    @staticmethod
    def clip_queue(v: float) -> float:
        return max(0.0, min(v, Preprocessor.MAX_QUEUE_PER_LANE))

    @staticmethod
    def clip_ped_wait(v: float) -> float:
        return max(0.0, min(v, Preprocessor.MAX_PED_WAIT))

    @staticmethod
    def classify_weather(rainfall_mm_hr: float) -> int:
        """Map HK Observatory rainfall intensity to binary weather flag."""
        return 1 if rainfall_mm_hr >= 10.0 else 0   # ≥10 mm/hr = rain

    # ── 2.4.4 Sensor fusion ──────────────────────────────────────────────
    def fuse(self,
             loop_counts: dict,          # {lane_id: vehicle_count}
             ped_wait_ns: float,
             ped_wait_ew: float,
             rainfall_mm_hr: float,
             timestamp: datetime.datetime,
             vehicle_mix: float = 0.0,
             bus_approaching: int = 0) -> StateSnapshot:
        """
        Merge all sensor streams into a single StateSnapshot.
        Lane IDs follow CityFlow roadnet.json naming:
          road_0_1_0  → N approach
          road_2_1_0  → E approach
          road_3_1_0  → S approach
          road_4_1_0  → W approach
        """
        q_N = self.clip_queue(
            sum(v for k, v in loop_counts.items() if 'road_0' in k))
        q_E = self.clip_queue(
            sum(v for k, v in loop_counts.items() if 'road_2' in k))
        q_S = self.clip_queue(
            sum(v for k, v in loop_counts.items() if 'road_3' in k))
        q_W = self.clip_queue(
            sum(v for k, v in loop_counts.items() if 'road_4' in k))

        return StateSnapshot(
            q_N=q_N, q_E=q_E, q_S=q_S, q_W=q_W,
            p_NS=self.clip_ped_wait(ped_wait_ns),
            p_EW=self.clip_ped_wait(ped_wait_ew),
            time_slot=timestamp.hour,
            weather=self.classify_weather(rainfall_mm_hr),
            vehicle_mix=max(0.0, min(1.0, vehicle_mix)),
            bus_approaching=1 if int(bus_approaching) != 0 else 0,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. DEPLOYMENT DATA COLLECTORS (real HK APIs)
# ─────────────────────────────────────────────────────────────────────────────

class HKObservatoryCollector:
    """
    Section 2.3.1: HK Observatory Open API
    Endpoint: https://data.weather.gov.hk/weatherAPI/opendata/weather.php
    Update frequency: ~15 minutes
    """
    API_URL = "https://data.weather.gov.hk/weatherAPI/opendata/weather.php"

    def fetch_rainfall(self, station: str = "HKO") -> Optional[float]:
        """
        Returns current hourly rainfall in mm/hr for the given station.
        Returns None on network failure (caller will impute).
        """
        try:
            resp = requests.get(
                self.API_URL,
                params={"dataType": "rhrread", "lang": "en"},
                timeout=5
            )
            resp.raise_for_status()
            data = resp.json()
            # Find the station in the rainfall array
            for item in data.get("rainfall", {}).get("data", []):
                if item.get("station") == station:
                    val = item.get("max")
                    return float(val) if val not in (None, "") else 0.0
            return 0.0
        except Exception:
            return None   # signal missing data to Preprocessor


class HKTransportCollector:
    """
    Section 2.3.1: DATA.GOV.HK Traffic Speed Map API
    Endpoint: https://resource.data.one.gov.hk/td/speedmap.xml
    Update frequency: ~2 minutes
    Returns speed per road segment; we map segments to junction approaches.
    """
    API_URL = "https://resource.data.one.gov.hk/td/speedmap.xml"

    # Mapping from DATA.GOV.HK road IDs to our junction approach directions.
    # Replace with real segment IDs from the target junction in deployment.
    ROAD_TO_DIRECTION = {
        "SEGMENT_N": "N",
        "SEGMENT_E": "E",
        "SEGMENT_S": "S",
        "SEGMENT_W": "W",
    }

    def fetch_speeds(self) -> dict:
        """
        Returns {direction: speed_kmh}.
        Lower speed → higher queue inference (congestion proxy).
        """
        try:
            resp = requests.get(self.API_URL, timeout=8)
            resp.raise_for_status()
            # XML parsing (simplified; real deployment would parse properly)
            speeds = {}
            for seg_id, direction in self.ROAD_TO_DIRECTION.items():
                # NOT IMPLEMENTED: XML parsing omitted for this prototype.
                # Fallback speed is used so the pipeline remains operational.
                speeds[direction] = 30.0
            return speeds
        except Exception:
            return {}


class BusETACollector:
    """
    Section 2.3.1: KMB Open API
    Endpoint: https://data.etabus.gov.hk/v1/transport/kmb/stop-eta/{stop_id}
    Used to detect incoming heavy vehicles (buses) for vehicle_mix estimation.
    """
    BASE_URL = "https://data.etabus.gov.hk/v1/transport/kmb/stop-eta"

    def fetch_next_bus_seconds(self, stop_id: str) -> Optional[float]:
        """Returns seconds until next bus at stop_id, or None on failure."""
        try:
            resp = requests.get(f"{self.BASE_URL}/{stop_id}", timeout=5)
            resp.raise_for_status()
            data = resp.json()
            etas = data.get("data", [])
            if etas:
                eta_str = etas[0].get("eta", "")
                if eta_str:
                    eta_dt = datetime.datetime.fromisoformat(
                        eta_str.replace("Z", "+00:00"))
                    delta = (eta_dt - datetime.datetime.now(
                        datetime.timezone.utc)).total_seconds()
                    return max(0.0, delta)
            return None
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# 4. PROTOTYPE SYNTHETIC STATE BUILDER (CityFlow-backed)
# ─────────────────────────────────────────────────────────────────────────────

class SyntheticStateBuilder:
    """
    Generates realistic StateSnapshots from CityFlow lane data.
    Used in prototype mode (no physical sensors required).

    Pedestrian demand is simulated via a Poisson process:
      - clear day: λ = 0.3 pedestrians/second per crossing
      - rainy day: λ = 0.5 pedestrians/second (more people, slower crossing)
    """

    def __init__(self, weather: int = 0, start_hour: int = 8):
        self.weather = weather
        self.start_hour = start_hour
        self._ped_wait_ns = 0.0
        self._ped_wait_ew = 0.0
        self._preprocessor = Preprocessor()
        # Pedestrian arrival rates (arrivals/second)
        self._ped_lambda = 0.5 if weather == 1 else 0.3

    def build(self, lane_waiting: dict, step: int,
              current_phase: int) -> StateSnapshot:
        """
        Construct state vector from CityFlow get_lane_waiting_vehicle_count().

        lane_waiting: dict returned by CityFlow engine
        step: simulation step (seconds)
        current_phase: 0=NS green, 1=yellow, 2=EW green, 3=yellow
        """
        # ── Pedestrian simulation - only update every 5 seconds ──────────
        if step % 5 == 0:
            arrivals = random.randint(0, int(self._ped_lambda * 5 * 2))
            if current_phase in (0, 1):    # NS vehicles green → EW peds waiting
                self._ped_wait_ew += 5 + arrivals
                self._ped_wait_ns = max(0.0, self._ped_wait_ns - 5 * 0.3)
            elif current_phase in (2, 3):  # EW vehicles green → NS peds waiting
                self._ped_wait_ns += 5 + arrivals
                self._ped_wait_ew = max(0.0, self._ped_wait_ew - 5 * 0.3)
            else:                          # pedestrian phase – both reset
                self._ped_wait_ns = 0.0
                self._ped_wait_ew = 0.0

        hour = (self.start_hour + step // 3600) % 24

        # ── Simulated rainfall in mm/hr ───────────────────────────────────
        rainfall = 15.0 if self.weather == 1 else 0.0

        return self._preprocessor.fuse(
            loop_counts=lane_waiting,
            ped_wait_ns=self._ped_wait_ns,
            ped_wait_ew=self._ped_wait_ew,
            rainfall_mm_hr=rainfall,
            timestamp=datetime.datetime(2026, 5, 1, hour, 0, 0),
            vehicle_mix=0.05 if self.weather == 1 else 0.0,
            bus_approaching=0
        )

    def reset_pedestrians(self):
        """Call when pedestrian phase completes to reset waiting counters."""
        self._ped_wait_ns = 0.0
        self._ped_wait_ew = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 5. DEPLOYMENT STATE BUILDER (wires real collectors through preprocessor)
# ─────────────────────────────────────────────────────────────────────────────

class DeploymentStateBuilder:
    """
    Wires the real HK API collectors through the Preprocessor to produce
    StateSnapshots for live deployment (Phases 3-4 of the deployment plan).

    In Phase 1-2, replace with SyntheticStateBuilder.
    """

    def __init__(self, bus_stop_id: str = "HK_STOP_001"):
        self._weather_api = HKObservatoryCollector()
        self._transport_api = HKTransportCollector()
        self._bus_api = BusETACollector()
        self._preprocessor = Preprocessor()
        self._bus_stop_id = bus_stop_id
        self._ped_wait_ns = 0.0
        self._ped_wait_ew = 0.0

    def build(self, loop_counts: dict, current_phase: int) -> StateSnapshot:
        """Fetch all sensors and return fused state vector."""
        # Weather
        rainfall = self._weather_api.fetch_rainfall()
        rainfall = self._preprocessor.impute("rainfall", rainfall,
                                             gap_seconds=0)

        # Bus proximity → vehicle_mix
        bus_eta = self._bus_api.fetch_next_bus_seconds(self._bus_stop_id)
        vehicle_mix = 0.15 if (bus_eta is not None and bus_eta < 30) else 0.02
        # Transit signal priority flag: set if a bus is approaching within 60s
        bus_approaching = 1 if (bus_eta is not None and bus_eta < 60) else 0

        # Pedestrian waiting (physical sensor would replace this)
        dt = 5
        if current_phase in (0, 1):
            self._ped_wait_ew += dt
        else:
            self._ped_wait_ns += dt

        return self._preprocessor.fuse(
            loop_counts=loop_counts,
            ped_wait_ns=self._ped_wait_ns,
            ped_wait_ew=self._ped_wait_ew,
            rainfall_mm_hr=rainfall,
            timestamp=datetime.datetime.now(),
            vehicle_mix=vehicle_mix,
            bus_approaching=bus_approaching
        )


# ─────────────────────────────────────────────────────────────────────────────
# QUICK SELF-TEST
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("── Preprocessor self-test ──")
    pp = Preprocessor()
    snap = pp.fuse(
        loop_counts={"road_0_1_0": 8, "road_2_1_0": 3,
                     "road_3_1_0": 6, "road_4_1_0": 2},
        ped_wait_ns=45.0,
        ped_wait_ew=72.0,
        rainfall_mm_hr=18.0,
        timestamp=datetime.datetime(2026, 5, 1, 8, 15, 0),
        vehicle_mix=0.05,
        bus_approaching=0
    )
    print(snap)
    print("State vector:", snap.to_vector())
    print("NS demand:", snap.ns_demand, " EW demand:", snap.ew_demand)

    print("\n── SyntheticStateBuilder self-test ──")
    sb = SyntheticStateBuilder(weather=1, start_hour=8)
    fake_lanes = {"road_0_1_0": 10, "road_2_1_0": 4,
                  "road_3_1_0": 8, "road_4_1_0": 3}
    snap2 = sb.build(fake_lanes, step=30, current_phase=0)
    print(snap2)