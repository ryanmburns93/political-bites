import httpx

from political_bites import legislators
from political_bites.legislators import fetch_dataset, parse_people

YAML = (
    "- id: {bioguide: X000002}\n"
    "  name: {first: Ūlu, last: Palakua, official_full: Ūlu Palakua}\n"
    "  terms:\n"
    "  - {type: rep, start: '2025-01-03', end: '2027-01-03', state: HI, party: Democrat}\n"
)


def test_fetch_dataset_caches_non_ascii_as_utf8(tmp_path, monkeypatch):
    resp = httpx.Response(
        200, content=YAML.encode("utf-8"), request=httpx.Request("GET", "http://x")
    )
    monkeypatch.setattr(legislators.httpx, "get", lambda *a, **k: resp)
    text = fetch_dataset("legislators-current", tmp_path)
    assert "Ūlu" in text
    assert (tmp_path / "legislators-current.yaml").read_bytes() == YAML.encode("utf-8")
    again = fetch_dataset("legislators-current", tmp_path)  # served from cache
    assert parse_people(again)["X000002"]["name"]["official_full"] == "Ūlu Palakua"
