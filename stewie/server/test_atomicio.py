"""atomicio regression guards for the #122 read-during-write race.

The bug: a truncating `open(path, "w")` empties bodies.json before rewriting it, so a concurrent
reader (body_density / the /bodies.json route) catches an empty file -> JSONDecodeError. This surfaced
under `pytest -n auto`. write_*_atomic uses temp + os.replace, which is atomic on POSIX: a reader's
open() resolves to either the old or the new COMPLETE file, never a half-written one. These tests hammer
that concurrency directly, so a regression to a non-atomic write would raise here (deterministically
safe with the atomic implementation -- asserting no-exception against a correct impl is not flaky).
"""
from __future__ import annotations

import json
import os
import threading

from stewie.server.atomicio import write_bytes_atomic, write_json_atomic

import lode.mission_planner as MP

_BODIES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bodies.json")


def test_round_trip_json(tmp_path):
    p = str(tmp_path / "x.json")
    obj = {"a": 1, "nested": {"b": [1, 2, 3]}, "s": "hi"}
    write_json_atomic(p, obj, indent=2)
    with open(p) as f:
        assert json.load(f) == obj


def test_round_trip_bytes_overwrite(tmp_path):
    p = str(tmp_path / "y.bin")
    write_bytes_atomic(p, b"first-and-much-longer-payload")
    write_bytes_atomic(p, b"second")                 # overwrite a longer file with a shorter one
    with open(p, "rb") as f:
        assert f.read() == b"second"                 # no leftover bytes from the longer first write


def test_no_temp_files_left_behind(tmp_path):
    p = str(tmp_path / "z.json")
    for _ in range(5):
        write_json_atomic(p, {"k": "v"})
    leftovers = [n for n in os.listdir(tmp_path) if n != "z.json"]
    assert leftovers == [], f"atomic write leaked temp files: {leftovers}"


def _hammer(writer, reader, *, n_write=150, n_read=500):
    """Run writer (n_write times) and reader (n_read times) concurrently from a synchronized start;
    return the list of exceptions either raised."""
    errors: list[BaseException] = []
    start = threading.Barrier(2)

    def _w():
        start.wait()
        for _ in range(n_write):
            try:
                writer()
            except BaseException as e:    # noqa: BLE001 -- surface any writer error to the assertion
                errors.append(e)

    def _r():
        start.wait()
        for _ in range(n_read):
            try:
                reader()
            except BaseException as e:    # noqa: BLE001 -- the race manifests as a reader exception
                errors.append(e)

    tw, tr = threading.Thread(target=_w), threading.Thread(target=_r)
    tw.start(); tr.start(); tw.join(); tr.join()
    return errors


def test_concurrent_atomic_write_and_read_never_partial(tmp_path):
    p = str(tmp_path / "shared.json")
    big = {"rows": [{"i": i, "pad": "x" * 64} for i in range(400)]}   # large enough to span reads
    write_json_atomic(p, big)

    def reader():
        with open(p) as f:
            d = json.load(f)
        assert len(d["rows"]) == 400      # complete content every time, never empty/partial

    errors = _hammer(lambda: write_json_atomic(p, big), reader)
    assert not errors, f"concurrent read/write raced: {errors[:3]}"


def test_concurrent_bodies_regen_and_body_density(tmp_path):
    """Faithful end-to-end guard: body_density() reads stewie/server/bodies.json while it is rewritten
    atomically (exactly the regen+read overlap that failed under -n auto). The writer replays the real
    committed bytes, so the file is unchanged even if the test is interrupted."""
    assert os.path.isfile(_BODIES), "bodies.json missing -- run gen_bodies_json"
    with open(_BODIES, "rb") as f:
        committed = f.read()

    def reader():
        assert MP.body_density("moon") > 0.0   # never JSONDecodeError on an empty/partial file

    errors = _hammer(lambda: write_bytes_atomic(_BODIES, committed), reader, n_write=120, n_read=400)
    # the committed bytes are unchanged regardless, but assert it explicitly
    with open(_BODIES, "rb") as f:
        assert f.read() == committed
    assert not errors, f"body_density raced bodies.json regen: {errors[:3]}"
