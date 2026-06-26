"""Evidence-gated crop-management profiles for controlled SWAT+ experiments."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..errors import SwatBuilderInputError

SOURCE_BACKED_CORN_SOY_PROFILE = "source_backed_corn_soy_rotation_v1"
_CORN_SOY_DECISION_TABLE = "pl_hv_summer2_corn_soyb"


def apply_source_backed_corn_soy_rotation(
    txtinout: str | Path,
    *,
    evidence: Mapping[str, Any],
    report_path: str | Path | None = None,
    minimum_corn_soy_share_of_cultivated: float = 0.80,
) -> dict[str, Any]:
    """Replace generic AGRL management with a two-year corn-soy rotation.

    This is intentionally opt-in. The profile is accepted only when a
    basin-clipped, crop-specific source shows that corn plus soybeans account
    for the required share of the independently measured cultivated footprint.
    The function changes only ``agrl_comm`` and ``agrl_rot``; it does not alter
    curve numbers, soils, weather, routing, or calibration parameters.
    """
    root = Path(txtinout).expanduser().resolve()
    paths = {
        "plant_ini": root / "plant.ini",
        "management_sch": root / "management.sch",
        "landuse_lum": root / "landuse.lum",
        "lum_dtl": root / "lum.dtl",
        "plants_plt": root / "plants.plt",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise SwatBuilderInputError(
            "Crop-management profile requires complete TxtInOut inputs.",
            missing_files=missing,
        )

    normalized_evidence = _validate_corn_soy_evidence(
        evidence,
        minimum_share=minimum_corn_soy_share_of_cultivated,
    )
    landuse_text = paths["landuse_lum"].read_text(encoding="utf-8")
    if not any(
        tokens[:4] == ["agrl_lum", "null", "agrl_comm", "agrl_rot"]
        for tokens in (line.lower().split() for line in landuse_text.splitlines())
        if len(tokens) >= 4
    ):
        raise SwatBuilderInputError(
            "AGRL land use does not reference the expected agrl_comm and agrl_rot inputs.",
            path=str(paths["landuse_lum"]),
        )

    lum_text = paths["lum_dtl"].read_text(encoding="utf-8")
    if _CORN_SOY_DECISION_TABLE not in lum_text:
        raise SwatBuilderInputError(
            "Required corn-soy decision table is absent from lum.dtl.",
            decision_table=_CORN_SOY_DECISION_TABLE,
            path=str(paths["lum_dtl"]),
        )
    plant_db_text = paths["plants_plt"].read_text(encoding="utf-8")
    plant_names = {
        tokens[0].lower()
        for tokens in (line.split() for line in plant_db_text.splitlines())
        if tokens
    }
    if not {"corn", "soyb"}.issubset(plant_names):
        raise SwatBuilderInputError(
            "Corn and soybean entries are required in plants.plt.",
            path=str(paths["plants_plt"]),
        )

    plant_before = paths["plant_ini"].read_text(encoding="utf-8")
    management_before = paths["management_sch"].read_text(encoding="utf-8")
    plant_after = _replace_agrl_plant_community(plant_before)
    management_after = _replace_agrl_management_schedule(management_before)

    before_hashes = {
        "plant.ini": _text_sha256(plant_before),
        "management.sch": _text_sha256(management_before),
    }
    after_hashes = {
        "plant.ini": _text_sha256(plant_after),
        "management.sch": _text_sha256(management_after),
    }
    _atomic_write(paths["plant_ini"], plant_after)
    _atomic_write(paths["management_sch"], management_after)

    report = {
        "status": "applied",
        "profile": SOURCE_BACKED_CORN_SOY_PROFILE,
        "scope": "all HRUs referencing agrl_lum",
        "changes": {
            "plant_community": "agrl -> corn + soyb",
            "management_schedule": f"pl_hv_summer1 agrl -> {_CORN_SOY_DECISION_TABLE} corn soyb",
            "unchanged_domains": [
                "curve_number",
                "soils",
                "weather",
                "routing",
                "calibration_parameters",
            ],
        },
        "evidence": normalized_evidence,
        "guardrails": [
            "opt_in_only",
            "crop_specific_source_required",
            "minimum_corn_soy_share_enforced",
            "fresh_engine_run_required",
            "physical_and_locked_verification_gates_unchanged",
        ],
        "file_sha256": {"before": before_hashes, "after": after_hashes},
    }
    if report_path is not None:
        destination = Path(report_path).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(destination, json.dumps(report, indent=2) + "\n")
        report["report_path"] = str(destination)
    return report


def _validate_corn_soy_evidence(
    evidence: Mapping[str, Any],
    *,
    minimum_share: float,
) -> dict[str, Any]:
    required = (
        "source",
        "source_url",
        "source_sha256",
        "year",
        "basin_id",
        "corn_fraction_of_basin",
        "soybean_fraction_of_basin",
        "cultivated_fraction_of_basin",
    )
    missing = [key for key in required if evidence.get(key) in (None, "")]
    if missing:
        raise SwatBuilderInputError(
            "Crop-management evidence is incomplete.",
            missing_fields=missing,
        )
    try:
        corn = float(evidence["corn_fraction_of_basin"])
        soy = float(evidence["soybean_fraction_of_basin"])
        cultivated = float(evidence["cultivated_fraction_of_basin"])
    except (TypeError, ValueError) as exc:
        raise SwatBuilderInputError("Crop fractions must be numeric.") from exc
    if not all(0.0 <= value <= 1.0 for value in (corn, soy, cultivated)):
        raise SwatBuilderInputError("Crop fractions must be within [0, 1].")
    if cultivated <= 0.0:
        raise SwatBuilderInputError("Cultivated fraction must be positive.")
    crop_share = (corn + soy) / cultivated
    if crop_share < minimum_share:
        raise SwatBuilderInputError(
            "Corn-soy evidence does not support applying the rotation profile.",
            corn_soy_share_of_cultivated=crop_share,
            required_share=minimum_share,
        )
    digest = str(evidence["source_sha256"]).lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise SwatBuilderInputError("source_sha256 must be a hexadecimal SHA-256 digest.")

    normalized = dict(evidence)
    normalized.update(
        {
            "year": int(evidence["year"]),
            "corn_fraction_of_basin": corn,
            "soybean_fraction_of_basin": soy,
            "cultivated_fraction_of_basin": cultivated,
            "corn_soy_share_of_cultivated": crop_share,
            "minimum_required_share": float(minimum_share),
        }
    )
    return normalized


def _replace_agrl_plant_community(text: str) -> str:
    lines = text.splitlines()
    index = next(
        (i for i, line in enumerate(lines) if line.split()[:1] == ["agrl_comm"]),
        None,
    )
    if index is None:
        raise SwatBuilderInputError("plant.ini does not contain agrl_comm.")
    header = lines[index].split()
    if len(header) < 3:
        raise SwatBuilderInputError("agrl_comm header is malformed in plant.ini.")
    try:
        plant_count = int(header[1])
    except ValueError as exc:
        raise SwatBuilderInputError("agrl_comm plant count is invalid.") from exc
    old_rows = lines[index + 1 : index + 1 + plant_count]
    if len(old_rows) != plant_count or [row.split()[0].lower() for row in old_rows] != ["agrl"]:
        raise SwatBuilderInputError(
            "Expected the generic agrl_comm community before applying crop profile."
        )
    replacement = [
        "agrl_comm                2         1",
        # Preserve the generic community's total 10,000 kg/ha initial residue
        # instead of accidentally assigning that amount to each crop.
        "                                        corn             n       0.00000       0.00000       0.00000       0.00000       0.00000    5000.00000",
        "                                        soyb             n       0.00000       0.00000       0.00000       0.00000       0.00000    5000.00000",
    ]
    return "\n".join(lines[:index] + replacement + lines[index + 1 + plant_count :]) + "\n"


def _replace_agrl_management_schedule(text: str) -> str:
    lines = text.splitlines()
    index = next(
        (i for i, line in enumerate(lines) if line.split()[:1] == ["agrl_rot"]),
        None,
    )
    if index is None:
        raise SwatBuilderInputError("management.sch does not contain agrl_rot.")
    header = lines[index].split()
    if len(header) < 3:
        raise SwatBuilderInputError("agrl_rot header is malformed in management.sch.")
    try:
        operation_count = int(header[1])
        automatic_count = int(header[2])
    except ValueError as exc:
        raise SwatBuilderInputError("agrl_rot counts are invalid.") from exc
    if automatic_count != 1:
        raise SwatBuilderInputError("The controlled profile requires one agrl_rot automatic schedule.")
    auto_index = index + 1 + operation_count
    if auto_index >= len(lines) or lines[auto_index].split() != ["pl_hv_summer1", "agrl"]:
        raise SwatBuilderInputError(
            "Expected generic pl_hv_summer1 agrl management before applying crop profile."
        )
    lines[auto_index] = f"                                                   {_CORN_SOY_DECISION_TABLE}   corn   soyb"
    return "\n".join(lines) + "\n"


def _text_sha256(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)
