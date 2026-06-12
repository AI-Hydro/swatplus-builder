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
swat init --ref-dir /path/to/reference_dbs --datasets-version v60.5.7
```

## SWAT+ engine binary

The SWAT+ engine binary is **not distributed with this package** — you acquire
it separately from the SWAT+ team and point the toolchain at it.

### Tested version

The entire swatplus-builder pipeline has been validated against:

```
SWAT+ v2023  —  rev 60.5.7
```

The topology converter and routing fixes in swatplus-builder target the
`rte_cha=1` / `chandeg.con` layout required by rev 60.5.7 specifically.
Other rev 60.x releases are likely compatible; earlier revisions may produce
different output file layouts.

### Where to get it

| Platform | Source |
|---|---|
| **Official download page** | [swat.tamu.edu/software/plus](https://swat.tamu.edu/software/plus/) |
| **SWAT+ GitBook docs** | [swatplus.gitbook.io/docs](https://swatplus.gitbook.io/docs) |
| **Source / releases** | [github.com/swat-model](https://github.com/swat-model) |

Download the Linux or macOS binary for rev 60.5.7 (or the latest rev 60.x),
mark it executable, and place it on `PATH` as `swatplus`:

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
