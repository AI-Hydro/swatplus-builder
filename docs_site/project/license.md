# License & attribution

## License

swatplus-builder is released under the **MIT License**. See
[`LICENSE`](https://github.com/AI-Hydro/swatplus-builder/blob/main/LICENSE) in
the repository.

## Vendored and optional components

| Component | License | Posture |
|---|---|---|
| [`swat-model/swatplus-editor`](https://github.com/swat-model/swatplus-editor) | Apache-2.0 | **Vendored** under `src/swatplus_builder/editor/vendored/` |
| [pySWATPlus](https://github.com/swat-model/pySWATPlus) | GPL-3.0 | **Optional** dependency — non-authoritative calibration bridge |

!!! note "GPL posture"
    pySWATPlus is GPL-3.0 and is an *optional* dependency, used only for the
    non-authoritative bridge path. The core build and the authoritative
    real-engine calibration path do not require it. See `DECISIONS.md` in the
    repository for the full licensing rationale.

## Reference data

SWAT+ reference databases are downloaded at install/bootstrap time from the
`ai-hydro/swatplus-reference-data` mirror. The SWAT+ engine binary is **not**
distributed with this package — you supply your own.

## Attribution

If swatplus-builder is useful in your work, please cite it and link the
repository — see [Citing & references](citing.md).
