#!/usr/bin/env python3
"""Deprecated compatibility wrapper for canonical workflow evidence.

Historical versions of this script performed ad hoc CN2 calibration and local
tier classification. That violates the agent-governed workflow contract. Use
``scripts/run_objective_10basin.py`` or ``swat workflow run``; both delegate
claim policy to the package.
"""

from __future__ import annotations

from run_objective_10basin import main


if __name__ == "__main__":
    main()
