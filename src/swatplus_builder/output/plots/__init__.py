"""Publication-ready plotting suite for swatplus-builder.

Requires: matplotlib (install with ``pip install 'swatplus-builder[viz]'``).

All figures are saved in both PNG (300 dpi) and PDF for manuscript submission.
Figure naming follows journal convention: fig_NN_<name>.{png,pdf}
"""

from .fdc import plot_fdc
from .forcing_context import plot_forcing_context
from .hydrograph import plot_hydrograph
from .landuse_composition import plot_landuse_composition, summarize_landuse_composition
from .residuals import plot_residuals
from .scatter import plot_scatter
from .seasonal import plot_seasonal
from .soil import plot_soil_sources
from .spatial import plot_basin_spatial_overview, plot_basin_summary, plot_spatial_map, read_masked_raster
from .style import COLORS, apply_style
from .utils import align_timeseries, build_figure_title, save_publication_figure
from .water_balance import plot_water_balance, summarize_water_balance
from .wrapper import generate_all_plots

__all__ = [
    "apply_style",
    "COLORS",
    "align_timeseries",
    "build_figure_title",
    "save_publication_figure",
    "plot_hydrograph",
    "plot_forcing_context",
    "plot_landuse_composition",
    "summarize_landuse_composition",
    "plot_fdc",
    "plot_residuals",
    "plot_scatter",
    "plot_seasonal",
    "plot_soil_sources",
    "plot_spatial_map",
    "plot_basin_summary",
    "plot_basin_spatial_overview",
    "read_masked_raster",
    "plot_water_balance",
    "summarize_water_balance",
    "generate_all_plots",
]
