from __future__ import annotations

import json

import pytest
from shapely.geometry import box

from swatplus_builder.errors import SwatBuilderExternalError
from swatplus_builder.soil import sda


class _Response:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


def test_fetch_sda_mukeys_for_geometry_queries_spatial_function(monkeypatch, tmp_path):
    calls: list[dict] = []

    def fake_post(url, data, timeout):
        calls.append({"url": url, "data": data, "timeout": timeout})
        return _Response({"Table": [["100"], ["200"], ["100"], [None]]})

    monkeypatch.setattr(sda.requests, "post", fake_post)

    result = sda.fetch_sda_mukeys_for_geometry(
        box(-85.89, 39.91, -85.43, 40.10),
        cache_dir=tmp_path,
        timeout_s=12.0,
    )

    assert result == [100, 200]
    assert calls[0]["url"].endswith("/Tabular/post.rest")
    assert calls[0]["timeout"] == 12.0
    assert "SDA_Get_Mukey_from_intersection_with_WktWgs84" in calls[0]["data"]["query"]


def test_fetch_sda_mukeys_for_geometry_uses_cache(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_post(url, data, timeout):
        calls["n"] += 1
        return _Response({"Table": [["321"]]})

    monkeypatch.setattr(sda.requests, "post", fake_post)
    geom = box(-85.89, 39.91, -85.43, 40.10)

    assert sda.fetch_sda_mukeys_for_geometry(geom, cache_dir=tmp_path) == [321]
    assert sda.fetch_sda_mukeys_for_geometry(geom, cache_dir=tmp_path) == [321]

    assert calls["n"] == 1
    cache = json.loads((tmp_path / "sda_spatial_mukeys.json").read_text())
    assert cache["_version"] == sda.CACHE_VERSION


def test_fetch_sda_mukeys_for_geometry_wraps_provider_error(monkeypatch):
    def fake_post(url, data, timeout):
        raise TimeoutError("SDA unavailable")

    monkeypatch.setattr(sda.requests, "post", fake_post)

    with pytest.raises(SwatBuilderExternalError, match="SDA spatial mukey query failed"):
        sda.fetch_sda_mukeys_for_geometry(box(-85.89, 39.91, -85.43, 40.10))
