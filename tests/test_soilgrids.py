from __future__ import annotations

from swatplus_builder.soil import soilgrids


def test_soilgrids_live_fetch_is_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("SWATPLUS_ENABLE_SOILGRIDS_LIVE", raising=False)

    assert soilgrids.fetch_soilgrids_profile(-86.0, 40.0, mukey=12345) is None


def test_extract_soilgrids_means() -> None:
    payload = {
        "properties": {
            "layers": [
                {
                    "name": "clay",
                    "depths": [
                        {"values": {"mean": 20}},
                        {"values": {"mean": 40}},
                    ],
                },
                {
                    "name": "sand",
                    "depths": [
                        {"values": {"mean": 60}},
                        {"values": {}},
                    ],
                },
            ]
        }
    }

    assert soilgrids._extract_means(payload) == {"clay": 30.0, "sand": 60.0}


def test_soilgrids_profile_from_mocked_payload(monkeypatch) -> None:
    monkeypatch.setenv("SWATPLUS_ENABLE_SOILGRIDS_LIVE", "1")
    monkeypatch.setattr(
        soilgrids,
        "_query_soilgrids",
        lambda lon, lat: {
            "properties": {
                "layers": [
                    {"name": "clay", "depths": [{"values": {"mean": 24.0}}]},
                    {"name": "sand", "depths": [{"values": {"mean": 42.0}}]},
                    {"name": "silt", "depths": [{"values": {"mean": 34.0}}]},
                    {"name": "bdod", "depths": [{"values": {"mean": 135.0}}]},
                    {"name": "soc", "depths": [{"values": {"mean": 12.0}}]},
                    {"name": "wv0033", "depths": [{"values": {"mean": 300.0}}]},
                    {"name": "wv1500", "depths": [{"values": {"mean": 120.0}}]},
                ]
            }
        },
    )

    profile = soilgrids.fetch_soilgrids_profile(-86.0, 40.0, mukey=12345)

    assert profile is not None
    assert profile.name == "gnatsgo_12345"
    assert profile.source == "soilgrids_v2_coarse"
    assert profile.layers[0].dp == 2000.0
