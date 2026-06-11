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

```bash
# Downloads the per-platform engine (see the script header for details)
bash scripts/bootstrap_swatplus_binary.sh
```

Or supply your own and expose it:

```bash
export SWATPLUS_EXE=/path/to/swatplus_exe       # explicit path, or
export PATH="/path/to/swatplus_dir:$PATH"       # 'swatplus' on PATH
```

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
