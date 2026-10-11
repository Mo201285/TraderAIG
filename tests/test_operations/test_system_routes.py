"""The Developer Hub route catalogue against the real app (row 756).

`GET /system/routes` is the contract surface behind PROJECT_MAP M11.3: route
catalogue + contract docs *generated from the registered API* (Unified
Interface System, section 8). The source guards in
`test_dashboard_honesty.py` pin how it is built; these tests pin what it
actually serves, because "generated, not hand-written" is only true if the
output is set-equal to the live OpenAPI schema:

- the catalogue lists itself and `/system/health`, because both are mounted;
- every (path, method) it publishes is in `app.openapi()`, and every schema
  operation is published -- nothing invented, nothing omitted;
- counts match the rows, a path parameter arrives as `required`, a body-carrying
  route documents its content type, and every operation documents a 2xx.
"""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operations.api import app  # noqa: E402

HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")


@pytest.fixture()
def client():
    return TestClient(app)


def _catalogue(client) -> dict:
    res = client.get("/system/routes")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ok"] is True
    return data


def test_the_catalogue_lists_the_routes_that_are_actually_mounted(client):
    """Self-inclusion is the cheap proof of generation.

    A hand-written list tends to forget the route it lives behind; the
    generator cannot, because it reads the same table the server dispatches
    on. The registered health route is the second witness.
    """
    data = _catalogue(client)
    pairs = {(r["path"], r["method"]) for r in data["routes"]}
    assert ("/system/routes", "GET") in pairs, (
        "the catalogue does not list the route that serves it")
    assert ("/system/health", "GET") in pairs, (
        "the registered health route is missing from the catalogue")


def test_every_published_operation_is_registered_and_vice_versa(client):
    """No fabricated rows, no omissions: the catalogue IS the schema.

    Both directions matter. Subset-only would let the handler pad the list
    with routes nobody registered; superset-only would let it quietly drop
    routes from the docs. The counts block must agree with the rows it
    summarises for the same reason.
    """
    data = _catalogue(client)
    published = {(r["path"], r["method"]) for r in data["routes"]}
    schema = {
        (path, method.upper())
        for path, item in app.openapi()["paths"].items()
        for method in item
        if method.upper() in HTTP_METHODS
    }
    assert published == schema, (
        "catalogue drifted from the registered app; only in catalogue: "
        f"{sorted(published - schema)[:5]}; only in schema: "
        f"{sorted(schema - published)[:5]}")
    assert data["counts"]["operations"] == len(published)
    assert data["counts"]["paths"] == len({p for p, _ in published})
    per_method: dict = {}
    for _, method in published:
        per_method[method] = per_method.get(method, 0) + 1
    assert data["counts"]["methods"] == per_method


def test_the_contract_documents_parameters_bodies_and_responses(client):
    """The docs half of M11.3: what each operation takes and returns.

    Derived from the response rather than pinned to one known route (except
    where the assertion is structural): a path parameter must arrive
    `required`, a body-carrying route must name its content type, and every
    operation must document at least one 2xx -- an undocumented success path
    would make the contract docs ornamental.
    """
    data = _catalogue(client)

    with_path_param = next(
        (r for r in data["routes"]
         if any(p["location"] == "path" for p in r["parameters"])),
        None)
    assert with_path_param is not None, (
        "no route documents a path parameter; contract docs are empty")
    path_params = [p for p in with_path_param["parameters"]
                   if p["location"] == "path"]
    assert path_params, f"{with_path_param['path']}: no path parameter rows"
    for p in path_params:
        assert p["required"] is True, (
            f"{with_path_param['path']}: path parameter {p['name']} is "
            "documented as optional")
        assert p["name"], "a parameter row without a name is not a contract"

    with_body = next((r for r in data["routes"] if r["request_body"]), None)
    assert with_body is not None, "no route documents a request body"
    assert with_body["request_body"]["content_type"].startswith(
        "application/"), "the request body names no content type"

    for r in data["routes"]:
        codes = r["responses"]
        assert codes, f"no responses documented for {r['method']} {r['path']}"
        assert any(str(c).startswith("2") for c in codes), (
            f"{r['method']} {r['path']} documents no 2xx response")
