"""Weather ingestion & SWAT+ weather-file emission.

Public API:

* :func:`write_observed` — serialize a
  :class:`~swatplus_builder.types.WeatherBundle` to the
  ``.pcp/.tmp/.hmd/.wnd/.slr`` + ``<var>.cli`` file set the engine expects.
* :func:`station_name` — editor-compatible station id from (lat, lon).
* :func:`synthesize` — deterministic stand-in dataset for tests /
  first-run smoke. Not real climate — do not use in production.
* :class:`WeatherWriteResult` — enumerates every file written.
"""

from .daymet import DAYMET_VARIABLE_MAP, fetch_daymet
from .gridmet import GRIDMET_VARIABLE_MAP, fetch_gridmet
from .synthetic import synthesize, synthesize_station
from .writer import WeatherWriteResult, station_name, write_observed

__all__ = [
    "DAYMET_VARIABLE_MAP",
    "GRIDMET_VARIABLE_MAP",
    "WeatherWriteResult",
    "fetch_daymet",
    "fetch_gridmet",
    "station_name",
    "synthesize",
    "synthesize_station",
    "write_observed",
]
