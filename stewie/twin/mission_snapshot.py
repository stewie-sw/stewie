"""[REQ:BR-02] Mission-snapshot versioning -- the branchable replay/ML lineage unit.

A COMPLETED mission (MO-02 ``MissionExecutive`` in ``COMPLETED``, carrying a signed released revision)
writes an IMMUTABLE ``MissionSnapshot`` into a per-body ``MissionLineage`` (Moon -> mission 000 -> 001
-> ... -> N). Each snapshot binds the mission's immutable identities under a content-addressed
``snapshot_id``:

* the DT-01 ``world_sha`` -- the terminal linked world state the mission left (``twin.envelope``);
* the MO-02 ``SignedRevision.content_hash`` -- the immutable released plan (``contracts.executive``);
* a ``ReplayKey`` -- the deterministic RS-04 replay inputs (the real DEM window's content sha + the run
  params) and the ``run_sha`` the keystone loop produced (``runtime.replay_loop``).

Two things follow, and they ARE the acceptance:

* it REPLAYS DETERMINISTICALLY -- ``ReplayKey.replay`` re-runs the recorded inputs through the RS-04
  keystone over the SAME real DEM window and reproduces the recorded ``run_sha`` bit-exact (the loop is
  deterministic); a different DEM window (a different world) is refused;
* it is SELECTABLE AS A BRANCH PARENT -- ``branch_from(snapshot)`` forks a what-if / retrain child whose
  ``parent_id`` is that snapshot, so the lineage is a DAG: one snapshot may fan out to many children.

This is the missing ``mission_snapshot`` PRODUCER (the ingredients existed -- the DT-01 world
transaction, the MO-02 signed revision, the RS-04 deterministic replay -- but nothing bound a completed
mission into a branchable, replayable lineage unit). It adds no new physics/perception; it VERSIONS
completed missions so the replay/train path has a stable, branchable unit to key on. (extends BR-01/EG-03)
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:                                            # avoid import-time cost / cycles
    from stewie.contracts.executive import MissionExecutive
    from stewie.runtime.replay_loop import EvidenceBundle


_UNSET = object()                                            # "caller did not pass parent_id" sentinel


def dem_window_sha(window: Any) -> str:
    """A deterministic content sha over a real DEM window (float64 native bytes) -- the identity of the
    replayed frame. Two byte-identical windows hash identically; any changed cell moves the sha, so a
    ``ReplayKey`` can refuse to replay a mission against a different world."""
    return hashlib.sha256(
        np.ascontiguousarray(np.asarray(window, dtype=np.float64)).tobytes()).hexdigest()


def _xy(v: Any) -> tuple[float, float]:
    """JSON round-trips a tuple as a list; coerce a 2-list back to an (x, y) float tuple."""
    a, b = v
    return (float(a), float(b))


def _opt_rc(v: Any) -> tuple[int, int] | None:
    """Coerce an optional (row, col) 2-list back to an int tuple, or pass None through."""
    if v is None:
        return None
    r, c = v
    return (int(r), int(c))


@dataclass(frozen=True)
class ReplayKey:
    """The deterministic replay descriptor of a completed mission's RS-04 run: the content identity of
    the real DEM window plus the run inputs, and the ``run_sha`` the keystone loop produced. Replaying
    these inputs over the same window reproduces ``expected_run_sha`` bit-exact (RS-04 is deterministic)."""
    dem_window_sha: str
    cell_m: float
    start_xy: tuple[float, float]
    goal_xy: tuple[float, float]
    expected_run_sha: str
    seed_hazard_rc: tuple[int, int] | None = None
    seed_rock_rc: tuple[int, int] | None = None
    seed_uncertainty_rc: tuple[int, int] | None = None
    eligible: bool = True
    site: str = "haworth"

    def replay(self, dem_window: Any, *, wss: Any) -> "EvidenceBundle":
        """Deterministically re-run this mission's RS-04 keystone over the SAME real DEM window and verify
        the recorded ``run_sha`` reproduces bit-exact. A window whose content sha does not match the
        recorded frame is REFUSED (you cannot replay a mission against a different world). ``wss`` is a
        real ``WorldStateService`` the replayed world transaction commits to."""
        got = dem_window_sha(dem_window)
        if got != self.dem_window_sha:
            raise ValueError(
                f"BR-02: replay DEM-window sha {got[:12]} != the recorded mission frame "
                f"{self.dem_window_sha[:12]} -- this is not the mission's replayed frame")
        from stewie.runtime.replay_loop import run_replay
        b = run_replay(np.asarray(dem_window, dtype=float), self.cell_m, self.start_xy, self.goal_xy,
                       wss=wss, site=self.site, seed_hazard_rc=self.seed_hazard_rc,
                       seed_rock_rc=self.seed_rock_rc, seed_uncertainty_rc=self.seed_uncertainty_rc,
                       eligible=self.eligible)
        if b.run_sha != self.expected_run_sha:
            raise ValueError(
                "BR-02: RS-04 replay run_sha mismatch -- the recorded mission did not reproduce")
        return b

    @classmethod
    def from_dict(cls, d: dict) -> "ReplayKey":
        """Rebuild a ``ReplayKey`` from its journalled dict, coercing JSON lists back to tuples."""
        return cls(dem_window_sha=str(d["dem_window_sha"]), cell_m=float(d["cell_m"]),
                   start_xy=_xy(d["start_xy"]), goal_xy=_xy(d["goal_xy"]),
                   expected_run_sha=str(d["expected_run_sha"]),
                   seed_hazard_rc=_opt_rc(d.get("seed_hazard_rc")),
                   seed_rock_rc=_opt_rc(d.get("seed_rock_rc")),
                   seed_uncertainty_rc=_opt_rc(d.get("seed_uncertainty_rc")),
                   eligible=bool(d.get("eligible", True)), site=str(d.get("site", "haworth")))


@dataclass(frozen=True)
class MissionSnapshot:
    """One immutable, content-addressed snapshot of a completed mission -- a node in a ``MissionLineage``.

    ``mission_number`` is the mission's position in the body's global sequence (000, 001, ... N) and
    ``mission_name`` its label -- both are lineage-assigned POSITIONAL METADATA, deliberately NOT part
    of ``snapshot_id``. ``parent_id`` encodes the branch topology (None = a root mission of the body;
    otherwise the snapshot this one continues or forks from). The ``snapshot_id`` is the sha256 over the
    mission's CONTENT -- body, parent, ``world_sha`` (DT-01 terminal state), ``plan_content_hash``
    (MO-02 released plan), ``replay`` (RS-04 deterministic run), provenance -- so the SAME completed
    mission against the SAME world with the SAME parent is ONE immutable snapshot (a re-write is refused),
    and any content change yields a different id."""
    body: str
    mission_number: int
    mission_name: str
    parent_id: str | None
    world_sha: str
    plan_content_hash: str
    replay: ReplayKey
    provenance: str
    snapshot_id: str

    @staticmethod
    def _content(*, body: str, parent_id: str | None, world_sha: str, plan_content_hash: str,
                 replay: ReplayKey, provenance: str) -> dict:
        """The mission CONTENT the ``snapshot_id`` binds -- everything EXCEPT the id itself and the
        lineage-assigned positional metadata (``mission_number``/``mission_name``). Stable key order via
        json ``sort_keys`` at hashing time; the nested ``ReplayKey`` is flattened via ``asdict``."""
        return {"body": body, "parent_id": parent_id, "world_sha": world_sha,
                "plan_content_hash": plan_content_hash, "replay": asdict(replay),
                "provenance": provenance}

    @staticmethod
    def _id(content: dict) -> str:
        return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    @classmethod
    def make(cls, *, body: str, mission_number: int, mission_name: str, parent_id: str | None,
             world_sha: str, plan_content_hash: str, replay: ReplayKey,
             provenance: str) -> "MissionSnapshot":
        content = cls._content(body=body, parent_id=parent_id, world_sha=world_sha,
                               plan_content_hash=plan_content_hash, replay=replay, provenance=provenance)
        return cls(body=body, mission_number=mission_number, mission_name=mission_name,
                   parent_id=parent_id, world_sha=world_sha, plan_content_hash=plan_content_hash,
                   replay=replay, provenance=provenance, snapshot_id=cls._id(content))

    def recomputed_id(self) -> str:
        """Re-derive the ``snapshot_id`` from this snapshot's own content -- must equal ``snapshot_id``
        for an untampered record (the immutability check)."""
        return self._id(self._content(
            body=self.body, parent_id=self.parent_id, world_sha=self.world_sha,
            plan_content_hash=self.plan_content_hash, replay=self.replay, provenance=self.provenance))

    @classmethod
    def from_record(cls, rec: dict) -> "MissionSnapshot":
        """Rebuild a snapshot from its journalled record by RE-DERIVING its id (never trusting the stored
        one blindly): a tampered record's re-derived id will not match its stored id."""
        snap = cls.make(body=str(rec["body"]), mission_number=int(rec["mission_number"]),
                        mission_name=str(rec["mission_name"]), parent_id=rec["parent_id"],
                        world_sha=str(rec["world_sha"]), plan_content_hash=str(rec["plan_content_hash"]),
                        replay=ReplayKey.from_dict(rec["replay"]), provenance=str(rec["provenance"]))
        if snap.snapshot_id != rec["snapshot_id"]:
            raise ValueError(
                f"BR-02: mission-snapshot journal record {str(rec['snapshot_id'])[:12]} was altered "
                f"(re-derived {snap.snapshot_id[:12]})")
        return snap


@dataclass
class MissionLineage:
    """A per-body, append-only, BRANCHABLE lineage of ``MissionSnapshot`` records (Moon -> 000 -> 001 ->
    ... -> N). Only completed missions are written (``write_completed_mission``), only immutable
    snapshots are appended (never edited), and any snapshot is selectable as a branch parent -- so the
    lineage is a DAG rooted at the body. With a ``journal_path`` it is DURABLE: each write appends
    fsync-on-event and ``from_journal`` cold-restores, re-deriving every ``snapshot_id`` bit-exact."""
    body: str
    journal_path: str | None = None
    snapshots: list[MissionSnapshot] = field(default_factory=list)

    def _index(self) -> dict[str, MissionSnapshot]:
        return {s.snapshot_id: s for s in self.snapshots}

    # ---- queries --------------------------------------------------------------------------------
    def get(self, snapshot_id: str) -> MissionSnapshot | None:
        return self._index().get(snapshot_id)

    def latest(self) -> MissionSnapshot | None:
        return self.snapshots[-1] if self.snapshots else None

    def root_missions(self) -> list[MissionSnapshot]:
        return [s for s in self.snapshots if s.parent_id is None]

    def children_of(self, snapshot_id: str) -> list[MissionSnapshot]:
        return [s for s in self.snapshots if s.parent_id == snapshot_id]

    # ---- write ----------------------------------------------------------------------------------
    def write_completed_mission(self, *, executive: "MissionExecutive", world_txn: Any,
                                replay: ReplayKey, provenance: str,
                                parent_id: Any = _UNSET) -> MissionSnapshot:
        """Write an immutable snapshot of a COMPLETED mission into the lineage. The executive MUST be in
        ``COMPLETED`` and carry a signed released revision (else ``ValueError``). ``world_txn`` is the
        DT-01 world transaction (a dict or a ``WorldTransaction``); its ``world_sha`` is the terminal
        world state. ``parent_id`` defaults to the latest snapshot (a LINEAR continuation), or None for
        the first mission; pass an explicit parent (via ``branch_from``) to FORK a what-if/retrain child.
        The ``mission_number`` is the body's next global sequence index (000, 001, ...)."""
        from stewie.contracts.executive import ExecutiveState
        if executive.state is not ExecutiveState.COMPLETED:
            raise ValueError(
                f"BR-02: only a COMPLETED mission may be snapshotted (state={executive.state.value})")
        revision = executive.released_revision
        if revision is None:
            raise ValueError("BR-02: a completed mission must carry a signed released revision")
        world_sha = world_txn["world_sha"] if isinstance(world_txn, dict) else world_txn.world_sha

        if parent_id is _UNSET:                              # default: continue the lineage linearly
            parent_id = self.snapshots[-1].snapshot_id if self.snapshots else None
        if parent_id is not None and parent_id not in self._index():
            raise ValueError(
                f"BR-02: branch parent {str(parent_id)[:12]} is not a snapshot in this lineage")

        number = len(self.snapshots)
        snap = MissionSnapshot.make(
            body=self.body, mission_number=number, mission_name=f"mission_{number:03d}",
            parent_id=parent_id, world_sha=str(world_sha),
            plan_content_hash=revision.content_hash, replay=replay, provenance=provenance)
        if snap.snapshot_id in self._index():
            raise ValueError(
                f"BR-02: refusing to write a duplicate immutable snapshot {snap.snapshot_id[:12]} "
                "(same completed mission, same world state, same parent)")
        self._append(snap)
        return snap

    def branch_from(self, snapshot: "MissionSnapshot | str") -> str:
        """Select a snapshot as a branch parent for a what-if / retrain child. Returns its
        ``snapshot_id`` (to pass as ``write_completed_mission(parent_id=...)``); refuses an id that is
        not a snapshot in THIS lineage."""
        sid = snapshot.snapshot_id if isinstance(snapshot, MissionSnapshot) else str(snapshot)
        if sid not in self._index():
            raise ValueError(
                f"BR-02: {sid[:12]} is not a snapshot in this lineage -- cannot branch from it")
        return sid

    def _append(self, snap: MissionSnapshot) -> None:
        """Durably journal (fsync-on-event) BEFORE the in-memory append, so a write/fsync failure leaves
        memory == disk (never memory-ahead), then append."""
        if self.journal_path:
            rec = {"body": snap.body, "mission_number": snap.mission_number,
                   "mission_name": snap.mission_name, "parent_id": snap.parent_id,
                   "world_sha": snap.world_sha, "plan_content_hash": snap.plan_content_hash,
                   "replay": asdict(snap.replay), "provenance": snap.provenance,
                   "snapshot_id": snap.snapshot_id}
            with open(self.journal_path, "a") as fh:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        self.snapshots.append(snap)

    # ---- cold restore ---------------------------------------------------------------------------
    @classmethod
    def from_journal(cls, body: str, journal_path: str) -> "MissionLineage":
        """Cold-restore the lineage from its durable journal ALONE, re-deriving every ``snapshot_id``
        (a tampered record raises). A crash mid-fsync tears only the FINAL line -> keep every complete
        prior record; an interior torn line is real history loss -> surface it (refuse a silent partial
        restore)."""
        lin = cls(body=body, journal_path=None)              # replay WITHOUT re-journalling
        if os.path.exists(journal_path):
            lines = [ln for ln in open(journal_path).read().splitlines() if ln.strip()]
            for i, line in enumerate(lines):
                try:
                    rec: dict[str, Any] = json.loads(line)
                except json.JSONDecodeError:
                    if i == len(lines) - 1:                  # torn tail: stop, keep prior records
                        break
                    raise ValueError(
                        f"BR-02: mission-snapshot journal corrupt at interior line {i} (not the tail) "
                        "-- refusing a partial silent restore")
                lin.snapshots.append(MissionSnapshot.from_record(rec))
        lin.journal_path = journal_path                      # future writes journal again
        return lin
