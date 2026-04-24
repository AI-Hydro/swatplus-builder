"""Calibration modules."""

from .spotpy_adapter import CalibrationRequest, CalibrationIterationResult, run_calibration
from .report import write_calibration_reports
from .forward import (
    BasinSpec,
    ForwardRequest,
    ForwardVerification,
    ParameterVector,
    SimulatedTimeseries,
    SurrogateDataset,
    SurrogateDatasetRow,
    extract_surrogate_dataset,
    forward_simulate,
    verify_forward_artifact,
)
from .pyswatplus_runtime import PySwatPlusRuntimeStatus, ensure_pyswatplus_runtime
from .calibrator import (
    BackendRequest,
    BackendResult,
    CalibrationSummary,
    Calibrator,
    CalibratorRequest,
    EvaluationRecord,
    PySwatPlusBackend,
)

__all__ = [
    "CalibrationRequest",
    "CalibrationIterationResult",
    "run_calibration",
    "write_calibration_reports",
    "BasinSpec",
    "ForwardRequest",
    "ForwardVerification",
    "ParameterVector",
    "SimulatedTimeseries",
    "SurrogateDataset",
    "SurrogateDatasetRow",
    "extract_surrogate_dataset",
    "forward_simulate",
    "verify_forward_artifact",
    "PySwatPlusRuntimeStatus",
    "ensure_pyswatplus_runtime",
    "BackendRequest",
    "BackendResult",
    "CalibrationSummary",
    "Calibrator",
    "CalibratorRequest",
    "EvaluationRecord",
    "PySwatPlusBackend",
]
