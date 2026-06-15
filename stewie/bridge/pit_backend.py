"""PitBackend (#66 / Batch 8): the RCBackend that drives the dirt-pit rover over the CCSDS Space
Packet link, instead of stepping the conserved authority in-process (SimBackend).

STEWIE presents ONE remote-control seam (rc_contract.RCBackend: GoTo/Safe/SetSim commands, Pose/Leg
telemetry) whether the target is the sim or a real pit robot. PitBackend is the real-hardware target:
it ENCODES each command as a CCSDS telecommand packet and sends it on the link, and DECODES the Pose/
Leg telemetry packets the flight side returns. The SF-01 SafingWatchdog wraps it identically -- so a
comms/operator dropout auto-SAFEs the real machine over the wire, not just the sim.

The wire codec is John's frozen package (scripts/ccsds_ros_nav: ccsds + messages + link), per
CONTRACT.md -- cited, not duplicated. PitBackend translates between rc_contract's dataclasses and
John's wire dataclasses (identical CONTRACT.md §3 fields) and drives an injected ``Link``.

GATED (build-to-contract + flag): the LIVE wire is John's ``UdpLink`` (datagram + light-time delay +
loss) and the ROS bridge node, exercised in John's container. This adapter is verified on the
in-process ``LoopbackLink``, which packs/unpacks the REAL wire octets (``SpacePacket.pack/unpack``);
the live UDP/ROS binding is John's package, not claimed here.
"""
from __future__ import annotations

import os
import sys

from stewie.bridge import rc_contract as RC

#: John's frozen CCSDS/ROS nav package (not pip-installed; a sibling tree under scripts/).
_CCSDS_NAV_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "ccsds_ros_nav"))
_codec_cache = None


def load_ccsds_nav():
    """Import John's frozen wire codec (ccsds, link, messages) from scripts/ccsds_ros_nav and cache it.

    These are bare-import modules (no package __init__), so their directory is prepended to sys.path
    once -- exactly how John's own tests import them. Returns ``(ccsds, link, messages)``.
    """
    global _codec_cache
    if _codec_cache is None:
        if _CCSDS_NAV_DIR not in sys.path:
            sys.path.insert(0, _CCSDS_NAV_DIR)
        import ccsds  # type: ignore  # noqa: I001
        import link  # type: ignore
        import messages  # type: ignore
        _codec_cache = (ccsds, link, messages)
    return _codec_cache


def _to_wire(cmd, M):
    """rc_contract command -> John's wire message (identical CONTRACT.md §3 fields)."""
    if cmd.kind == "goto":
        return M.GoTo(leg_id=int(cmd.leg_id), goal_row=float(cmd.goal_row), goal_col=float(cmd.goal_col),
                      v_max_mps=float(cmd.v_max_mps), goal_radius_cells=float(cmd.goal_radius_cells))
    if cmd.kind == "safe":
        return M.Safe(reason=int(cmd.reason))
    if cmd.kind == "setsim":
        return M.SetSim(time_factor=float(cmd.time_factor))
    raise ValueError(f"PitBackend cannot encode command kind {cmd.kind!r}")


def _from_wire(msg, M):
    """John's wire telemetry -> rc_contract telemetry (Pose/Leg). Non-Pose/Leg TM (e.g. Img) -> None."""
    if isinstance(msg, M.Pose):
        return RC.Pose(leg_id=msg.leg_id, row=msg.row, col=msg.col, yaw_rad=msg.yaw_rad,
                       v_achieved_mps=msg.v_achieved_mps, slip=msg.slip, sinkage_m=msg.sinkage_m,
                       slope_rad=msg.slope_rad, soc=msg.soc, entrapped=bool(msg.entrapped))
    if isinstance(msg, M.Leg):
        return RC.Leg(leg_id=msg.leg_id, status=msg.status, commanded_dist_m=msg.commanded_dist_m,
                      achieved_dist_m=msg.achieved_dist_m, energy_J=msg.energy_J, mass_kg=msg.mass_kg,
                      final_row=msg.final_row, final_col=msg.final_col)
    return None


class PitBackend(RC.RCBackend):
    """Drive the dirt-pit rover over a CCSDS link. ``link`` is a John ``Link`` (the ground end of a
    ``loopback_pair`` in tests, a ``UdpLink`` against the container in deployment). ``met_source`` is a
    callable returning the Mission Elapsed Time [s] stamped into each packet's secondary header
    (default 0.0; a deployment injects the mission clock). Sequence count rides the CCSDS primary
    header and wraps at 14 bits, per CONTRACT.md §1."""

    def __init__(self, link, *, codec=None, met_source=None, seq_start: int = 0) -> None:
        self._link = link
        self._M = codec if codec is not None else load_ccsds_nav()[2]
        self._met_source = met_source if met_source is not None else (lambda: 0.0)
        self._seq = int(seq_start)

    def submit(self, cmd) -> None:
        pkt = self._M.encode(_to_wire(cmd, self._M), seq_count=self._seq & 0x3FFF,
                             met=float(self._met_source()))
        self._link.send(pkt)
        self._seq += 1

    def poll(self) -> list:
        out: list = []
        while True:
            pkt = self._link.recv(timeout=0)         # non-blocking drain
            if pkt is None:
                break
            tlm = _from_wire(self._M.decode(pkt), self._M)
            if tlm is not None:
                out.append(tlm)
        return out
