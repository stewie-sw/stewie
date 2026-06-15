"""Batch 8: PitBackend -- a REAL RCBackend that drives the dirt-pit rover over John's CCSDS Space
Packet link (scripts/ccsds_ros_nav, CONTRACT.md). Commands (GoTo/Safe/SetSim) are encoded to TC
packets and sent on the link; Pose/Leg telemetry is decoded from the TM packets the flight side
returns. STEWIE drives the pit through the SAME RCBackend seam + SF-01 SafingWatchdog as the sim --
only the transport differs.

Verified on the deterministic in-process LoopbackLink, which packs/unpacks the REAL wire octets
(ccsds.SpacePacket.pack/unpack). The LIVE wire (UdpLink + light-time/loss + the ROS bridge node) is
John's container package -- GATED, exercised there, not here.
"""
from __future__ import annotations

from stewie.bridge import pit_backend as PB
from stewie.bridge import rc_contract as RC


def _wire():
    return PB.load_ccsds_nav()                      # (ccsds, link, messages)


def test_goto_is_encoded_as_a_ccsds_tc_packet_on_the_wire():
    ccsds, link, messages = _wire()
    ground, flight = link.loopback_pair()
    pit = PB.PitBackend(ground)
    pit.submit(RC.GoTo(leg_id=7, goal_row=12.0, goal_col=34.0, v_max_mps=0.25, goal_radius_cells=2.0))
    pkt = flight.recv(timeout=1.0)
    assert pkt is not None
    assert pkt.apid == RC.APID_CMD_GOTO and pkt.packet_type == ccsds.TYPE_TC
    assert pkt.met is not None                       # CONTRACT.md §1: every packet carries the MET header
    msg = messages.decode(pkt)
    assert isinstance(msg, messages.GoTo)
    assert (msg.leg_id, msg.goal_row, msg.goal_col, msg.v_max_mps, msg.goal_radius_cells) \
        == (7, 12.0, 34.0, 0.25, 2.0)


def test_safe_and_setsim_encode_to_their_contract_apids():
    ccsds, link, messages = _wire()
    ground, flight = link.loopback_pair()
    pit = PB.PitBackend(ground)
    pit.submit(RC.Safe(reason=RC.SAFE_REASON_WATCHDOG))
    pit.submit(RC.SetSim(time_factor=8.0))
    p1, p2 = flight.recv(timeout=1.0), flight.recv(timeout=1.0)
    assert p1.apid == RC.APID_CMD_SAFE and messages.decode(p1).reason == RC.SAFE_REASON_WATCHDOG
    assert p2.apid == RC.APID_CMD_SETSIM and messages.decode(p2).time_factor == 8.0
    assert p1.packet_type == ccsds.TYPE_TC and p2.packet_type == ccsds.TYPE_TC


def test_pose_and_leg_telemetry_decode_from_the_wire():
    _ccsds, link, messages = _wire()
    ground, flight = link.loopback_pair()
    pit = PB.PitBackend(ground)
    flight.send(messages.encode(messages.Pose(leg_id=3, row=1.0, col=2.0, yaw_rad=0.5, v_achieved_mps=0.2,
                slip=0.1, sinkage_m=0.01, slope_rad=0.05, soc=0.9, entrapped=False), met=1.0))
    flight.send(messages.encode(messages.Leg(leg_id=3, status=0, commanded_dist_m=5.0, achieved_dist_m=4.9,
                energy_J=100.0, mass_kg=30.0, final_row=1.0, final_col=2.0), met=2.0))
    tlm = pit.poll()
    assert [t.kind for t in tlm] == ["pose", "leg"]
    pose = tlm[0]
    assert isinstance(pose, RC.Pose) and pose.leg_id == 3 and pose.col == 2.0 and pose.soc == 0.9
    leg = tlm[1]
    assert isinstance(leg, RC.Leg) and leg.status == 0 and leg.mass_kg == 30.0


def test_poll_is_empty_when_no_telemetry_is_waiting():
    _ccsds, link, _messages = _wire()
    ground, _flight = link.loopback_pair()
    assert PB.PitBackend(ground).poll() == []        # non-blocking drain, no fabricated telemetry


def test_safing_watchdog_safes_the_pit_over_the_wire():
    # SF-01 [REQ:SF-01]: the dead-man switch reaches the REAL backend over the CCSDS link
    _ccsds, link, messages = _wire()
    ground, flight = link.loopback_pair()
    pit = PB.PitBackend(ground)
    wd = RC.SafingWatchdog(pit, deadline_s=2.0)
    wd.submit(RC.GoTo(leg_id=0, goal_row=0.0, goal_col=5.0, v_max_mps=0.3, goal_radius_cells=1.0), now=0.0)
    assert flight.recv(timeout=1.0).apid == RC.APID_CMD_GOTO
    assert wd.tick(now=3.0) and wd.tripped           # past the deadline -> auto-safe
    safe_pkt = flight.recv(timeout=1.0)
    assert safe_pkt is not None and safe_pkt.apid == RC.APID_CMD_SAFE
    assert messages.decode(safe_pkt).reason == RC.SAFE_REASON_WATCHDOG


def test_end_to_end_goto_drives_a_conserved_flight_executive_over_the_link():
    # the full seam: PitBackend(ground) <-> CCSDS wire <-> a conserved flight executive (SimBackend).
    # A GoTo drives the rover toward the goal and Pose telemetry returns over the wire.
    _ccsds, link, messages = _wire()
    ground, flight = link.loopback_pair()
    pit = PB.PitBackend(ground)
    flight_exec = RC.SimBackend(start_rc=(0.0, 0.0), cell_m=1.0)
    pit.submit(RC.GoTo(leg_id=1, goal_row=0.0, goal_col=10.0, v_max_mps=0.3, goal_radius_cells=1.0))
    poses = []
    for _ in range(80):
        pkt = flight.recv(timeout=0)                 # flight receives + decodes the uplinked TC
        if pkt is not None:
            m = messages.decode(pkt)
            flight_exec.submit(RC.GoTo(leg_id=m.leg_id, goal_row=m.goal_row, goal_col=m.goal_col,
                                       v_max_mps=m.v_max_mps, goal_radius_cells=m.goal_radius_cells))
        for t in flight_exec.poll():                 # conserved drive -> Pose TM downlinked over the wire
            if t.kind == "pose":
                flight.send(messages.encode(messages.Pose(
                    leg_id=t.leg_id, row=t.row, col=t.col, yaw_rad=t.yaw_rad, v_achieved_mps=t.v_achieved_mps,
                    slip=t.slip, sinkage_m=t.sinkage_m, slope_rad=t.slope_rad, soc=t.soc,
                    entrapped=t.entrapped), met=0.0))
        poses += [t for t in pit.poll() if t.kind == "pose"]
    assert poses, "no Pose telemetry returned over the CCSDS link"
    assert poses[-1].col > poses[0].col              # the rover drove toward goal_col=10 over the wire
    assert poses[-1].col <= 10.0 + 1e-6              # never overshoots
