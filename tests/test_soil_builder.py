import pytest
from unittest.mock import patch
from swatplus_builder.soil.builder import fetch_soil_profiles_result, normalize_profile
from swatplus_builder.soil.models import SoilConfig, SoilProfile
from swatplus_builder.soil.params import horizon_from_chorizon

def dummy_layer(layer_num, dep):
    return horizon_from_chorizon(layer_num=layer_num, hzdepb_cm=dep, sandtotal_r=40.0, silttotal_r=40.0, claytotal_r=20.0, ksat_umps=5.0, dbthirdbar=1.4, wthirdbar_pct=30.0, wfifteenbar_pct=15.0, om_r=1.0)

@pytest.fixture
def dummy_settings():
    from swatplus_builder.config import Settings
    from pathlib import Path
    return Settings(reference_db_dir=Path("/tmp/ref_db"))

def test_every_mukey_gets_profile(dummy_settings):
    """Tier 1 Guarantee: Ensure mukeys never fail resolving."""
    with patch("swatplus_builder.soil.builder.fetch_aggregated_profiles") as mock_pc:
        mock_pc.return_value = {}
        
        mukeys = [111, 222]
        res = fetch_soil_profiles_result(mukeys, config=SoilConfig(use_sda=False), settings=dummy_settings)
        
        assert len(res.profiles) == 2
        for p in res.profiles:
            assert p.source == "synthetic_default"
        assert res.soil_report["coverage_pct"] == 1.0
        assert res.soil_report["aggregated"]["default_fallback"] == 2

def test_normalize_profile_drops_duplicate_depths_and_renumbers():
    profile = SoilProfile(
        name="gnatsgo_658396",
        hyd_grp="D",
        description="shallow aggregate with duplicate zero-thickness layer",
        source="pc_muaggatt",
        layers=[dummy_layer(1, 30.0), dummy_layer(2, 30.0), dummy_layer(3, 100.0)],
    )

    normalized = normalize_profile(profile)

    assert [layer.layer_num for layer in normalized.layers] == [1, 2]
    assert [layer.dp for layer in normalized.layers] == [300.0, 1000.0]

def test_fetch_soil_profiles_normalizes_duplicate_pc_layers_before_write(dummy_settings, tmp_path):
    """A duplicate aggregate bottom depth must not force synthetic fallback."""
    import sqlite3

    from swatplus_builder.soil.writer import write_soils

    with patch("swatplus_builder.soil.builder.fetch_aggregated_profiles") as mock_pc:
        mock_pc.return_value = {
            658396: SoilProfile(
                name="gnatsgo_658396",
                hyd_grp="D",
                description="pc aggregate shallow profile",
                source="pc_muaggatt",
                layers=[dummy_layer(1, 30.0), dummy_layer(2, 30.0)],
            )
        }

        res = fetch_soil_profiles_result(
            [658396],
            config=SoilConfig(use_sda=False),
            settings=dummy_settings,
        )

    db = tmp_path / "project.sqlite"
    sqlite3.connect(str(db)).close()
    write_res = write_soils(res.profiles, db)

    assert [layer.dp for layer in res.profiles[0].layers] == [300.0]
    assert write_res.profiles_written == 1

def test_sda_partial_enrichment(dummy_settings):
    """Test merging: SDA enriches some, Tier 1 left for the rest."""
    mukeys = [100, 200]
    
    with patch("swatplus_builder.soil.builder.fetch_aggregated_profiles") as mock_pc:
        mock_pc.return_value = {
            100: SoilProfile(name="gnatsgo_100", hyd_grp="A", description="agg", source="pc_muaggatt", layers=[dummy_layer(1, 30.0)]),
            200: SoilProfile(name="gnatsgo_200", hyd_grp="B", description="agg", source="pc_muaggatt", layers=[dummy_layer(1, 30.0)])
        }
        
        with patch("swatplus_builder.soil.builder.fetch_sda_horizons") as mock_sda:
            layers = [dummy_layer(1, 40.0), dummy_layer(2, 60.0)]
            mock_sda.return_value = {
                100: SoilProfile(name="sda_100", hyd_grp="A", description="sda hz", source="sda_horizon", layers=layers)
            }
            
            res = fetch_soil_profiles_result(mukeys, config=SoilConfig(use_sda=True), settings=dummy_settings)
            
            p100 = next(p for p in res.profiles if p.name == "sda_100")
            p200 = next(p for p in res.profiles if p.name == "gnatsgo_200")
            
            assert p100.source == "sda_horizon"
            assert p200.source == "pc_muaggatt"
            assert res.soil_report["horizon"]["used"] == 1
            assert res.soil_report["aggregated"]["muaggatt_based"] == 1

def test_all_default_fallback(dummy_settings):
    """Test offline behavior."""
    mukeys = [555]
    
    with patch("swatplus_builder.soil.builder.fetch_aggregated_profiles") as mock_pc:
        mock_pc.return_value = {
            555: SoilProfile(name="gnatsgo_555", hyd_grp="B", description="agg", source="pc_muaggatt", layers=[dummy_layer(1, 30.0)])
        }
        
        res = fetch_soil_profiles_result(mukeys, config=SoilConfig(use_sda=False), settings=dummy_settings)
        assert len(res.profiles) == 1
        assert res.profiles[0].source == "pc_muaggatt"
        assert res.soil_report["sources"]["sda"] is False

def test_invalid_horizon_rejected(dummy_settings):
    """Ensure invalid SDA rows (too shallow or < 2 layers) are rejected and Tier 1 is kept."""
    mukeys = [333]
    
    with patch("swatplus_builder.soil.builder.fetch_aggregated_profiles") as mock_pc:
        mock_pc.return_value = {
            333: SoilProfile(name="gnatsgo_333", hyd_grp="C", description="agg", source="pc_muaggatt", layers=[dummy_layer(1, 30.0)])
        }
        
        with patch("swatplus_builder.soil.builder.fetch_sda_horizons") as mock_sda:
            layers = [dummy_layer(1, 100.0)]
            mock_sda.return_value = {
                333: SoilProfile(name="sda_333", hyd_grp="C", description="sda hz", source="sda_horizon", layers=layers)
            }
            
            res = fetch_soil_profiles_result(mukeys, config=SoilConfig(use_sda=True), settings=dummy_settings)
            
            assert res.profiles[0].source == "pc_muaggatt"
            assert res.soil_report["horizon"]["rejected"] == 1
            assert res.soil_report["aggregated"]["muaggatt_based"] == 1

def test_sda_100_mukeys(dummy_settings):
    """Stress test large batches seamlessly merge into normalized outputs without KeyError."""
    mukeys = list(range(1000, 1100))
    
    with patch("swatplus_builder.soil.builder.fetch_aggregated_profiles") as mock_pc:
        # Mock that PC gives us 100 profiles natively
        mock_pc.return_value = {
            m: SoilProfile(name=f"gnatsgo_{m}", hyd_grp="C", description="agg", source="pc_muaggatt", layers=[dummy_layer(1, 30.0)])
            for m in mukeys
        }
        
        with patch("swatplus_builder.soil.builder.fetch_sda_horizons") as mock_sda:
            # Mock SDA succeeds on exactly 50 of them
            sda_res = {}
            for i, m in enumerate(mukeys):
                if i % 2 == 0:
                    sda_res[m] = SoilProfile(name=f"sda_{m}", hyd_grp="C", description="sda hz", source="sda_horizon", layers=[dummy_layer(1, 60.0), dummy_layer(2, 80.0)])
            mock_sda.return_value = sda_res
            
            res = fetch_soil_profiles_result(mukeys, config=SoilConfig(use_sda=True), settings=dummy_settings)
            
            assert len(res.profiles) == 100
            assert res.soil_report["horizon"]["used"] == 50
            assert res.soil_report["aggregated"]["muaggatt_based"] == 50
            assert res.soil_report["sda_attempted"] == 100
