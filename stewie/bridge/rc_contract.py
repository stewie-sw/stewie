"""#66 + SF-01: the pluggable remote-control contract + the safing watchdog.

THE SEAM (deduced from John's frozen CONTRACT.md, scripts/ccsds_ros_nav/CONTRACT.md §2/§3): the
dirt-pit RC interface is a small command set (GoTo / Safe / SetSim) and a telemetry stream
(Pose / Leg / Img) carried as CCSDS Space Packets. STEWIE presents this SAME contract whether it
drives the conserved sim authority or a real pit robot -- the contract is the seam, the backend is
pluggable. This module is the STEWIE-side adapter; the wire codec + ROS bindings live in John's
ccsds_ros_nav package (cited, not duplicated).

SF-01 (the architecture's flagged-REQUIRED-and-missing node, "must be Phase 0 / Week 4"): the
command-timeout SafingWatchdog -- a dead-man switch that auto-issues SAFE to whatever backend is
plugged in if valid commands stop arriving. The class boundary the audit named: the moment STEWIE
commands real hardware, the command path is safety-relevant, and this is its interlock.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# --- APID registry (CONTRACT.md §2, verbatim -- wire-compatible with John's messages.py) ----------
APID_CMD_GOTO = 0x0C8
APID_CMD_SAFE = 0x0C9
APID_CMD_SETSIM = 0x0CA
APID_TLM_POSE = 0x064
APID_TLM_LEG = 0x065
APID_TLM_IMG = 0x066

#: Safe.reason codes (CONTRACT.md §3 + the SF-01 watchdog cause)
SAFE_REASON_OPERATOR = 0
SAFE_REASON_WATCHDOG = 1          # SF-01: command-timeout dead-man trip
SAFE_REASON_HAZARD = 2


# --- Commands (TC, ground -> rover) ---------------------------------------------------------------
@dataclass(frozen=True)
class GoTo:
    """Drive to a waypoint (CONTRACT.md §3 GoTo)."""
    leg_id: int
    goal_row: float
    goal_col: float
    v_max_mps: float = 0.3
    goal_radius_cells: float = 1.0
    kind: str = field(default="goto", init=False)
    director_only: bool = field(default=False, init=False)


@dataclass(frozen=True)
class Safe:
    """All-stop / safe the rover (CONTRACT.md §3 Safe)."""
    reason: int = SAFE_REASON_OPERATOR
    kind: str = field(default="safe", init=False)
    director_only: bool = field(default=False, init=False)


@dataclass(frozen=True)
class SetSim:
    """Set the sim time-acceleration factor (CONTRACT.md §3 SetSim). A TRAINING toggle: it bends
    mission time, so it is DIRECTOR-ONLY (#68) -- an operator cannot fast-forward past real latency."""
    time_factor: float = 1.0
    kind: str = field(default="setsim", init=False)
    director_only: bool = field(default=True, init=False)


# --- Telemetry (TM, rover -> ground) --------------------------------------------------------------
@dataclass(frozen=True)
class Pose:
    """A single drive-tick state sample (CONTRACT.md §3 Pose)."""
    leg_id: int
    row: float
    col: float
    yaw_rad: float = 0.0
    v_achieved_mps: float = 0.0
    slip: float = 0.0
    sinkage_m: float = 0.0
    slope_rad: float = 0.0
    soc: float = 1.0
    entrapped: bool = False
    kind: str = field(default="pose", init=False)


@dataclass(frozen=True)
class Leg:
    """Leg-complete summary (CONTRACT.md §3 Leg). status: 0=REACHED 1=ENTRAPPED 2=LOW_BATTERY
    3=MAX_STEPS 4=SAFED."""
    leg_id: int
    status: int
    commanded_dist_m: float = 0.0
    achieved_dist_m: float = 0.0
    energy_J: float = 0.0
    mass_kg: float = 0.0
    final_row: float = 0.0
    final_col: float = 0.0
    kind: str = field(default="leg", init=False)


# --- The pluggable backend contract ---------------------------------------------------------------
class RCBackend(ABC):
    """The seam every RC target implements -- the conserved SimBackend OR the real dirt-pit robot.
    STEWIE (and the SafingWatchdog) only ever talk to this interface, so the simulator and the pit
    are swappable without touching the command/telemetry path (the rung-4 pluggability goal)."""

    @abstractmethod
    def submit(self, cmd) -> None:
        """Accept a command (GoTo/Safe/SetSim)."""

    @abstractmethod
    def poll(self) -> list:
        """Drain and return any telemetry (Pose/Leg) produced since the last poll."""


class RecordingBackend(RCBackend):
    """A backend that just records commands -- for tests and as the watchdog's null target."""

    def __init__(self) -> None:
        self.commands: list = []

    def submit(self, cmd) -> None:
        self.commands.append(cmd)

    def poll(self) -> list:
        return []


class SimBackend(RCBackend):
    """The conserved-authority backend: executes a GoTo by stepping a unicycle toward the goal and
    emitting Pose telemetry. Kinematic (the drive authority's pose integrator); a real terramechanics
    SimBackend wraps drive.drive_step the same way -- this is the contract-level stand-in that proves
    the seam end to end without a terrain load. SAFE halts; SetSim bends the step rate."""

    def __init__(self, start_rc=(0.0, 0.0), *, cell_m: float = 1.0, dt_s: float = 1.0) -> None:
        self.row, self.col = float(start_rc[0]), float(start_rc[1])
        self.cell_m = float(cell_m)
        self.dt_s = float(dt_s)
        self.time_factor = 1.0
        self._goal = None
        self._leg_id = 0
        self._out: list = []
        self._safed = False

    def submit(self, cmd) -> None:
        if cmd.kind == "goto":
            self._goal = cmd
            self._leg_id = cmd.leg_id
            self._safed = False
        elif cmd.kind == "safe":
            self._goal = None
            self._safed = True
        elif cmd.kind == "setsim":
            self.time_factor = max(1e-6, float(cmd.time_factor))

    def poll(self) -> list:
        if self._goal is not None and not self._safed:
            self._step()
        out, self._out = self._out, []
        return out

    def _step(self) -> None:
        g = self._goal
        if g is None:
            return
        drow, dcol = g.goal_row - self.row, g.goal_col - self.col
        dist_cells = math.hypot(drow, dcol)
        if dist_cells <= g.goal_radius_cells:                     # reached -> emit a Leg, stop
            self._out.append(Leg(leg_id=self._leg_id, status=0, final_row=self.row,
                                 final_col=self.col))
            self._goal = None
            return
        step_cells = (g.v_max_mps * self.dt_s * self.time_factor) / self.cell_m
        step_cells = min(step_cells, dist_cells)                 # never overshoot
        self.row += step_cells * drow / dist_cells
        self.col += step_cells * dcol / dist_cells
        self._out.append(Pose(leg_id=self._leg_id, row=self.row, col=self.col,
                              yaw_rad=math.atan2(drow, dcol),
                              v_achieved_mps=g.v_max_mps * self.time_factor))


def commands_from_plan(mission, *, cell_m: float = 5.0, dem=None, dem_origin=(0.0, 0.0),
                       v_max_mps: float = 0.3) -> list:
    """#66 (Aaron: "plan should output cmds for reuse"): convert a plan into a REUSABLE GoTo
    command sequence -- one GoTo per ordered site, in metres->cells (row=y/cell, col=x/cell). The
    output replays through any RCBackend (sim or pit), so a reviewed plan becomes a command tape:
    plan once, command many. A VIEW over the planner's resolved trips (RB-03), not a re-solve."""
    from lode import mission_planner as MP
    result = MP.plan(mission, dem=dem, dem_origin=dem_origin)
    cmds: list = []
    leg_id = 0
    for tr in result.trips:
        site = tr.get("site")
        if not site:
            continue
        x, y = float(site[0]), float(site[1])
        cmds.append(GoTo(leg_id=leg_id, goal_row=y / cell_m, goal_col=x / cell_m,
                         v_max_mps=v_max_mps, goal_radius_cells=1.0))
        leg_id += 1
    return cmds


# --- SF-01: the safing watchdog (the dead-man switch) ---------------------------------------------
class SafingWatchdog:
    """SF-01 [REQ:SF-01]: wrap any backend with a command-timeout interlock. Every valid command
    feeds the watchdog; if ``deadline_s`` elapses with no feed, ``tick`` auto-issues a SAFE to the
    backend (reason=WATCHDOG) and latches ``tripped``. This is the safety boundary the audit named:
    once the command path can reach real hardware, an operator/comms dropout MUST stop the machine,
    not leave it driving on a stale command. Time is injected (``now``) so it is deterministic and
    testable; a real deployment feeds it a monotonic clock."""

    def __init__(self, backend: RCBackend, *, deadline_s: float = 5.0) -> None:
        self.backend = backend
        self.deadline_s = float(deadline_s)
        self._last_feed: float | None = None
        self.tripped = False

    def feed(self, *, now: float) -> None:
        """Register a valid command/heartbeat at time ``now`` (resets the dead-man timer)."""
        self._last_feed = float(now)
        self.tripped = False

    def submit(self, cmd, *, now: float) -> None:
        """Forward a command to the backend AND feed the watchdog (the normal command path)."""
        self.backend.submit(cmd)
        self.feed(now=now)

    def tick(self, *, now: float) -> bool:
        """Advance the clock. Returns True if the watchdog is (now or already) tripped; on the
        transition it issues SAFE(reason=WATCHDOG) to the backend exactly once."""
        if self.tripped:
            return True
        if self._last_feed is not None and (now - self._last_feed) > self.deadline_s:
            self.backend.submit(Safe(reason=SAFE_REASON_WATCHDOG))
            self.tripped = True
        return self.tripped
