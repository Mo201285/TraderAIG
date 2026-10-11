"""The Developer Home verification signal (row 764, UX-10).

Spec section 8 asks Developer Home to show Build PASS + the measured test count
**from the live run, never a hard-coded number**. `GET /system/verification`
serves the artifact `scripts/verify_all.ps1` writes; these tests pin the whole
seam:

- the pytest summary parser reads the counts the run printed;
- `record` -> `latest` round-trips through the artifact file;
- an absent artifact is an absent state (`present: False`), never a green;
- the live route reflects whatever was recorded -- change the number and the
  response changes, which is what makes "not hard-coded" a measured fact.
"""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations import verification  # noqa: E402
from operations.api import app  # noqa: E402


@pytest.fixture()
def client():
    return TestClient(app)


def test_pytest_summary_parser_reads_the_measured_counts():
    """The parser is the only place a number is derived, so pin it.

    Real `pytest -q` tails: a clean run, a run with a failure, and a run whose
    single non-pass is an error (the documented infra marker).
    """
    clean = verification.parse_pytest_summary(
        ".................................................... [100%]\n"
        "1969 passed in 5000.00s"
    )
    assert clean["passed"] == 1969
    assert clean["failed"] == 0
    assert clean["total"] == 1969
    assert clean["seconds"] == 5000.0

    with_fail = verification.parse_pytest_summary(
        "1890 passed, 2 failed, 1 error in 4855.64s")
    assert with_fail["passed"] == 1890
    assert with_fail["failed"] == 2
    assert with_fail["errors"] == 1
    assert with_fail["total"] == 1893

    assert verification.parse_pytest_summary("")["total"] == 0


def test_record_then_latest_round_trips_the_artifact(tmp_path):
    """A recorded run comes back whole, gates in canonical order."""
    target = tmp_path / "verification.json"
    verification.record(
        {
            "generated_at": "2026-10-09T00:00:00Z",
            "selected": ["lint", "compile", "pytest", "dash"],
            "gates": {
                "vite": {"ok": True},
                "pytest": {"ok": True, "detail": "1969 passed in 42.00s"},
                "ruff": {"ok": True},
                "smoke": {"ok": True, "detail": "7/7"},
            },
        },
        path=target,
    )
    view = verification.latest(path=target)
    assert view["present"] is True
    assert view["generated_at"] == "2026-10-09T00:00:00Z"
    assert list(view["gates"]) == ["ruff", "pytest", "vite", "smoke"]
    assert view["gates"]["pytest"]["passed"] == 1969
    assert view["summary"] == {"gates_total": 4, "passed": 4, "failed": 0}


def test_absent_artifact_is_an_absent_state_not_a_green(tmp_path):
    """No recorded run => present:False and no gate rows at all."""
    view = verification.latest(path=tmp_path / "missing.json")
    assert view["ok"] is True
    assert view["present"] is False
    assert view["gates"] == {}
    assert view["summary"]["gates_total"] == 0
    assert view["generated_at"] is None


def test_the_route_serves_whatever_was_measured_not_a_hard_coded_number(
    client, tmp_path, monkeypatch
):
    """The response tracks the artifact, so the surface cannot fake a PASS.

    Point the route at an empty location first (absent), then record two
    *different* runs and confirm the numbers move with them -- the exact proof
    that Developer Home reports a measured run, not a constant.
    """
    target = tmp_path / "verification.json"
    monkeypatch.setenv("TRADERAIG_VERIFICATION_PATH", str(target))

    absent = client.get("/system/verification")
    assert absent.status_code == 200, absent.text
    assert absent.json()["present"] is False

    verification.record(
        {"gates": {"pytest": {"ok": True, "detail": "1969 passed in 42.00s"}}},
        path=target,
    )
    first = client.get("/system/verification").json()
    assert first["present"] is True
    assert first["gates"]["pytest"]["passed"] == 1969

    verification.record(
        {"gates": {"pytest": {"ok": True, "detail": "7 passed in 1.00s"}}},
        path=target,
    )
    second = client.get("/system/verification").json()
    assert second["gates"]["pytest"]["passed"] == 7, (
        "the route returned a fixed count; the artifact is not the source")


def test_the_route_is_a_read_only_registered_get():
    """Verification is read-only, and the catalogue documents it as such."""
    paths = app.openapi()["paths"]
    assert "/system/verification" in paths
    assert "get" in paths["/system/verification"]
