"""Independent regressions for package, verification, and rebuild boundaries.

These tests encode the acceptance behavior identified by the package/integration
review of commit 8f38832b. They intentionally exercise public interfaces rather
than implementation helpers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tomllib
import venv

import pytest

from stewie.ultrabuild.benchmark import run_benchmarks
from stewie.ultrabuild.canonical import canonical_bytes, record_content_hash
from stewie.ultrabuild.cli import main as cli_main
from stewie.ultrabuild.golden import build_golden_world
from stewie.ultrabuild.records import branch_record, submission
from stewie.ultrabuild.store import AuthoritativeStore, StoreContractError


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _normalized_requirement_name(requirement: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    assert match is not None, f"cannot parse requirement name from {requirement!r}"
    return re.sub(r"[-_.]+", "-", match.group(1)).lower()


def test_root_metadata_declares_unconditional_stewie_bodies_dependency() -> None:
    """The root wheel must declare the package imported by ``import stewie``."""

    project = tomllib.loads((_REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependency_names = {_normalized_requirement_name(requirement) for requirement in project["dependencies"]}
    assert "stewie-bodies" in dependency_names, (
        "stewie.specs.bodies imports stewie_bodies during root-package import, "
        "but the root distribution does not declare stewie-bodies"
    )


@pytest.mark.skipif(
    os.environ.get("STEWIE_WHEEL_SMOKE") != "1",
    reason=("clean wheel installation is an opt-in release test; set STEWIE_WHEEL_SMOKE=1"),
)
def test_root_wheel_metadata_resolves_ultrabuild_entrypoint_dependencies(
    tmp_path: Path,
) -> None:
    """Install only the root requirement and let its metadata resolve local wheels.

    The workspace dependency wheel is placed in the wheelhouse, but it is not
    passed to ``pip install`` explicitly. This prevents the release smoke from
    masking incomplete root metadata.
    """

    distribution_directory = tmp_path / "dist"
    distribution_directory.mkdir()
    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(distribution_directory),
            str(_REPOSITORY_ROOT),
            str(_REPOSITORY_ROOT / "packages" / "stewie-bodies"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, f"wheel build failed:\nSTDOUT:\n{build.stdout}\nSTDERR:\n{build.stderr}"
    root_wheels = sorted(distribution_directory.glob("stewie-*.whl"))
    assert len(root_wheels) == 1, root_wheels

    environment_directory = tmp_path / "venv"
    venv.create(environment_directory, with_pip=True)
    binary_directory = environment_directory / ("Scripts" if os.name == "nt" else "bin")
    python = binary_directory / ("python.exe" if os.name == "nt" else "python")
    clean_environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "PYTHONHOME",
            "PYTHONNOUSERSITE",
            "PYTHONPATH",
            "VIRTUAL_ENV",
        }
    }
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--quiet",
            "--find-links",
            str(distribution_directory),
            f"{root_wheels[0]}[ultrabuild]",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=clean_environment,
    )

    executable = binary_directory / ("stewie-ultrabuild.exe" if os.name == "nt" else "stewie-ultrabuild")
    completed = subprocess.run(
        [str(executable), "--help"],
        cwd=tmp_path,
        env=clean_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, (
        "the root wheel's declared metadata did not produce an importable "
        f"UltraBuild entry point:\nSTDOUT:\n{completed.stdout}\n"
        f"STDERR:\n{completed.stderr}"
    )


def test_verify_requires_payload_path_or_reports_payloads_unchecked(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Record-only verification must never look like complete verification."""

    database = tmp_path / "authority.sqlite3"
    store, ids = build_golden_world(database)
    observation = store.get(ids["observation_id"])
    assert observation is not None
    payload_store = store.payload_store
    assert payload_store is not None
    payload_store.path(observation["payload"]["content_hash"]).write_bytes(b"deliberately-corrupt")
    store.close()

    try:
        return_code = cli_main(["verify", "--database", str(database)])
    except SystemExit as error:
        captured = capsys.readouterr()
        assert error.code not in {None, 0}
        assert "--payloads" in captured.err
        return

    captured = capsys.readouterr()
    combined_output = f"{captured.out}\n{captured.err}".lower()
    if return_code != 0:
        assert "payload" in combined_output
        assert any(phrase in combined_output for phrase in ("required", "not checked", "not_checked", "unchecked"))
        return

    report = json.loads(captured.out)
    encoded_report = json.dumps(report, sort_keys=True).lower()
    assert "payload" in encoded_report, "successful record-only verification omitted its payload-verification scope"
    assert any(phrase in encoded_report for phrase in ("not checked", "not_checked", "unchecked")), report


def test_projection_rebuild_refuses_invalid_immutable_history(
    tmp_path: Path,
) -> None:
    """Projection repair must validate history before replacing a valid head."""

    database = tmp_path / "authority.sqlite3"
    store = AuthoritativeStore(database)
    store.append(
        submission(
            "branch.schema.json",
            branch_record(
                branch_id="branch.accepted",
                branch_kind="accepted",
                policy_id="policy.test",
                permitted_state_kinds=["reconciled"],
            ),
            token="branch.accepted",
        )
    )
    expected_head = store.branch_head("branch.accepted")
    branch = store.get("branch.accepted")
    assert expected_head is not None and branch is not None
    store.close()

    branch["head_revision_id"] = "revision.nonexistent"
    branch["head_sequence"] = 9
    branch["content_hash"] = record_content_hash(branch)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            UPDATE records
            SET content_hash=?, record_json=?
            WHERE record_id=?
            """,
            (
                branch["content_hash"],
                canonical_bytes(branch),
                branch["branch_id"],
            ),
        )

    with AuthoritativeStore(database) as reopened:
        assert reopened.verify_integrity()["ok"] is False
        with pytest.raises(
            StoreContractError,
            match=r"(?i)(graph|hash|integrity|invalid)",
        ):
            reopened.rebuild_projections()

        assert reopened.branch_head("branch.accepted") == expected_head


def test_benchmark_refuses_reusing_an_existing_output_directory(
    tmp_path: Path,
) -> None:
    """A second run must not time idempotent receipt lookup as durable append."""

    report = run_benchmarks(tmp_path, measured_runs=20)
    assert report["integrity"]["append_store"]["ok"] is True
    with sqlite3.connect(tmp_path / "append-benchmark.sqlite3") as connection:
        record_count = connection.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    assert record_count == 25

    with pytest.raises(
        (FileExistsError, RuntimeError, ValueError),
        match=r"(?i)(exist|fresh|non.?empty|output|reuse)",
    ):
        run_benchmarks(tmp_path, measured_runs=20)

    with sqlite3.connect(tmp_path / "append-benchmark.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == record_count


def test_benchmark_cli_rejects_too_few_measured_runs_as_usage_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The public CLI validates its lower bound before entering the runner."""

    with pytest.raises(SystemExit) as error:
        cli_main(
            [
                "benchmark",
                "--output",
                str(tmp_path),
                "--measured-runs",
                "5",
            ]
        )
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "measured-runs" in captured.err
    assert "20" in captured.err
    assert not any(tmp_path.iterdir())


def test_benchmark_cli_reports_output_reuse_as_usage_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        cli_main(
            [
                "benchmark",
                "--output",
                str(tmp_path),
                "--measured-runs",
                "20",
            ]
        )
        == 0
    )
    capsys.readouterr()
    with pytest.raises(SystemExit) as error:
        cli_main(
            [
                "benchmark",
                "--output",
                str(tmp_path),
                "--measured-runs",
                "20",
            ]
        )
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "existing artifacts" in captured.err
    assert "fresh" in captured.err
    assert "Traceback" not in captured.err
