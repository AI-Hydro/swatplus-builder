# Run Artifact Retention

This document defines how local SWAT+ run trees are retained without allowing
candidate outputs and superseded validations to exhaust workstation storage.
Compression changes storage form only; it does not promote, invalidate, or
alter scientific claims.

## Retention Classes

1. **Live authoritative run**: keep the complete directory extracted while it
   supports the current dashboard, release validation, objective report, or an
   active diagnosis.
2. **Exact cold archive**: use for superseded complete runs that may still be
   needed for historical verification. Preserve every entry in a checksummed
   `tar.zst` archive.
3. **Compact evidence package**: use only when the package explicitly exports
   a self-contained evidence bundle with its own manifest and hashes.
4. **Disposable scratch**: remove interrupted objective directories, release
   smoke environments, browser-review files, and tool caches after QA.

Do not call a run "cached" merely because it is old. A run can contain the
only retained copy of an input configuration, lock, or verification output.

## Live Run Boundary (2026-07-13)

The following groups remain extracted under `/Users/mgalib/swatplus_runs/`:

- `calibration_resume_validate_20260710`: current positive calibrated evidence
  and modeller dashboard.
- `calibration_contract_validate_20260710`: current negative-control release
  validation.
- `objective_refresh_v0710` and `objective_refresh_v079`: source runs for the
  current objective basin validation report.
- `e2e_hardening_20260626`: retained cross-basin hardening evidence referenced
  by the current report.
- `recovery_01031500_nldi_mask_20260625`: retained topology/outlet diagnostic
  evidence that has not yet been replaced by an equivalent compact package.

## Exact Archives Created 2026-07-13

Archives and SHA-256 sidecars are stored under
`/Users/mgalib/swatplus_run_archives/20260713/`.

| Original tree | Archive | Original | Compressed |
|---|---|---:|---:|
| repository `demo_runs/` | `repo_demo_runs_legacy_through_20260614.tar.zst` | 9.89 GiB | 1.03 GiB |
| repository `swatplus_runs/` | `repo_swatplus_runs_legacy_through_20260620.tar.zst` | 11.28 GiB | 0.89 GiB |
| `landuse_gate_validate_20260703` | `external_landuse_gate_validate_20260703.tar.zst` | 0.32 GiB | 0.04 GiB |
| `recovery_01547700_v2_20260625` | `external_recovery_01547700_v2_20260625.tar.zst` | 0.74 GiB | 0.04 GiB |
| `calibration_validate_20260703` | `external_calibration_validate_20260703.tar.zst` | 0.87 GiB | 0.05 GiB |
| `calibration_contract_validate_20260709` | `external_calibration_contract_validate_20260709.tar.zst` | 1.07 GiB | 0.07 GiB |
| `release_candidate_validate_20260703` | `external_release_candidate_validate_20260703.tar.zst` | 1.39 GiB | 0.18 GiB |

The source trees totaled 25.58 GiB; the verified archives total 2.30 GiB.
Entry counts were compared before source deletion, every archive passed
`zstd -t`, and every SHA-256 sidecar passed verification.

## Restore Procedure

Verify an archive before extraction:

```bash
shasum -a 256 -c /Users/mgalib/swatplus_run_archives/20260713/<archive>.sha256
```

Restore a repository-local archive to the repository parent:

```bash
zstd -dc /Users/mgalib/swatplus_run_archives/20260713/<archive>.tar.zst \
  | bsdtar -xf - -C /Users/mgalib/Documents/PyQSwatPlus/swatplus-builder
```

Restore an external run group to `/Users/mgalib/swatplus_runs/`:

```bash
zstd -dc /Users/mgalib/swatplus_run_archives/20260713/<archive>.tar.zst \
  | bsdtar -xf - -C /Users/mgalib/swatplus_runs
```

Refuse extraction if the target directory already exists. Inspect and rename
the existing target first so restoration cannot merge two evidence trees.

## Routine Hygiene

- Remove temporary browser QA and release-smoke environments after their tests
  pass.
- Clean `uv`, `pip`, pytest, Ruff, and mypy caches when disk pressure is real;
  do not repeatedly clear provider caches that make scientific reruns faster.
- Keep the current positive and negative release-validation pair extracted.
- Archive superseded full trees only after the replacement is documented and
  the archive passes integrity and entry-count checks.
- Treat Hugging Face models, Codex runtimes, and browser runtimes as shared
  machine dependencies, not project cache, unless their consumers are audited.
