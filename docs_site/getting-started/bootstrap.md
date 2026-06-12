# Bootstrap the engine & reference data

A real build needs two things that are *not* shipped with the Python package:
the **SWAT+ engine binary** and the **SWAT+ reference databases**. Helper
scripts fetch both.

## Reference databases

```bash
# Reference DBs → ~/.swatplus-builder/reference_dbs (tag v60.5.7)
bash scripts/bootstrap_reference_dbs.sh
```

This downloads `swatplus_datasets.sqlite`, `swatplus_soils.sqlite`, and
`swatplus_wgn.sqlite` from the `ai-hydro/swatplus-reference-data` mirror.

You can also point the toolchain at an existing copy:

```bash
swat init --ref-dir /path/to/reference_dbs --datasets-version 3.2.0
```

## SWAT+ engine binary

The SWAT+ engine binary is **not distributed with this package** — you acquire
it separately from the SWAT+ team and point the toolchain at it.

### Supported version

swatplus-builder targets the **SWAT+ v2023** input/output layout and has been
validated across:

```
SWAT+ v2023  —  rev 60.5.7  through  rev 61.0.2.61
```

The full-mode topology converter and routing fixes were first developed against
**rev 60.5.7** (the `rte_cha=1` / `chandeg.con` connect-block layout), and the
pipeline was subsequently confirmed working on the native **rev 61.0.2.61**
engine. The binary shipped/used in the current builds is **rev 61.0.2.61**.

!!! note "Engine version is recorded, not assumed"
    Every run parses the engine's startup banner and records the verified
    revision in its evidence bundle. If you assert a version that disagrees
    with the binary, the workflow records the banner value and flags the
    mismatch — so provenance always reflects the engine that actually ran.
    (Note: the historical 11-basin objective suite predates this capture, so
    its exact engine revision is not recorded in the report.)

Earlier revisions than 60.5.7 may produce different output file layouts and are
not supported.

### Where to get it

| Platform | Source |
|---|---|
| **Official download page** | [swat.tamu.edu/software/plus](https://swat.tamu.edu/software/plus/) |
| **SWAT+ GitBook docs** | [swatplus.gitbook.io/docs](https://swatplus.gitbook.io/docs) |
| **Source / releases** | [github.com/swat-model](https://github.com/swat-model) |

Download the Linux or macOS binary for a supported revision (rev 60.5.7 –
61.0.2.61; the latest v2023 release is recommended), mark it executable, and
place it on `PATH` as `swatplus`:

```bash
chmod +x swatplus_exe
sudo mv swatplus_exe /usr/local/bin/swatplus
```

Or leave it anywhere and set the env var:

```bash
export SWATPLUS_EXE=/path/to/swatplus_exe
```

> **Windows:** place `swatplus.exe` on `PATH` or set `SWATPLUS_EXE` to the
> full path including the `.exe` extension.

## Confirm everything is wired up

```bash
swat health --json
```

A healthy result reports the engine path, version, and reference-DB
availability. If `swat health` reports **degraded**, the most common causes
are: no engine on `PATH`/`SWATPLUS_EXE`, or missing reference DBs.

```bash
# the workflow surface should now resolve
swat workflow run --help
```

## Containers

A Docker baseline is provided. Mount the engine read-only and persist
artifacts:

```bash
docker compose build

# health with no binary mounted — expect 'degraded'
docker compose run --rm swat health --json

# with the engine mounted
SWATPLUS_BIN_DIR=/path/to/swatplus_dir docker compose run --rm swat health
```

Volume mounts (see `docker-compose.yml`):

| Host | Container | Purpose |
|---|---|---|
| `./artifacts` | `/data/artifacts` | persisted run / calibration artifacts |
| `$SWATPLUS_BIN_DIR` | `/opt/swatplus` | engine binary (read-only) |
| `$SWATPLUS_DATASETS_DIR` | `/data` | reference datasets SQLite |

Next: [Run your first basin →](quickstart.md)
