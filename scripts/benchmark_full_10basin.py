#!/usr/bin/env python3
"""Compatibility wrapper for the canonical full-mode 10-basin workflow.

Do not add calibration or claim-tier logic here. The package workflow owns
science policy; this script only invokes the canonical evidence-producing
suite.
"""

from __future__ import annotations

from run_objective_10basin import main

if __name__ == "__main__":
    main()
