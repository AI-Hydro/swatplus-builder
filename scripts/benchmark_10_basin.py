#!/usr/bin/env python3
"""Compatibility wrapper for the canonical agent-governed 10-basin workflow.

This script intentionally does not calibrate, classify claim tiers, or derive
blockers. Scientific policy lives in ``swatplus_builder.workflows.usgs_e2e``.
"""

from __future__ import annotations

from run_objective_10basin import main

if __name__ == "__main__":
    main()
