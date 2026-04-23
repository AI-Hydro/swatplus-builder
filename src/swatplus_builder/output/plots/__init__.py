"""Publication-ready plotting suite for swatplus-builder.

Requires: matplotlib (install with ``pip install 'swatplus-builder[viz]'``).

All figures are saved in both PNG (300 dpi) and PDF for manuscript submission.
Figure naming follows journal convention: fig_NN_<name>.{png,pdf}
"""

from .style import apply_style, COLORS
from .utils import align_timeseries, build_figure_title, save_publication_figure
from .hydrograph import plot_hydrograph
from .fdc import plot_fdc
from .residuals import plot_residuals
from .scatter import plot_scatter
from .seasonal import plot_seasonal
from .soil import plot_soil_sources
from .spatial import plot_spatial_map, plot_basin_summary
from .wrapper import generate_all_plots

__all__ = [
    "apply_style",
    "COLORS",
    "align_timeseries",
    "build_figure_title",
    "save_publication_figure",
    "plot_hydrograph",
    "plot_fdc",
    "plot_residuals",
    "plot_scatter",
    "plot_seasonal",
    "plot_soil_sources",
    "plot_spatial_map",
    "plot_basin_summary",
    "generate_all_plots",
]
