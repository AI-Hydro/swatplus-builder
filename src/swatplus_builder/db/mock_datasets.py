"""Build a minimal but valid ``swatplus_datasets.sqlite`` for testing.

The vendored SWAT+ Editor's ``setup_project`` action requires a datasets DB
that passes a version check (``>= 3.0``) and contains enough rows for
``import_gis`` to succeed.  Obtaining the *real* ``swatplus_datasets.sqlite``
requires a separate download (hosted at https://plus.swat.tamu.edu/) and is
not suitable for automated CI.

This module creates a **synthetic** datasets DB — minimum viable content for
the LTE pipeline (``is_lte=True``) — using the vendored editor's own peewee
models so the column order is guaranteed to match what ``lib.copy_table``
expects.

Usage::

    from swatplus_builder.db.mock_datasets import create_mock_datasets_db
    from pathlib import Path

    db = create_mock_datasets_db(Path("/tmp/mock_datasets.sqlite"),
                                 landuses=["frst", "agrr"])

Public API
----------
.. autofunction:: create_mock_datasets_db
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Sequence

__all__ = ["create_mock_datasets_db"]

# ---------------------------------------------------------------------------
# The creation script runs in a child interpreter so it can safely import the
# vendored peewee models without polluting our own namespace.
# ---------------------------------------------------------------------------

_SCRIPT = textwrap.dedent("""\
import sys, json
from pathlib import Path

db_path  = sys.argv[1]
landuses = json.loads(sys.argv[2])   # list[str] of lower-case plant names

from database.datasets.setup import SetupDatasetsDatabase
from database.datasets import (
    definitions, hru_parm_db, soils as ds_soils,
    decision_table, lum as ds_lum, basin, init as ds_init,
)

# ── 1. Initialise DB and create all table schemas ─────────────────────────
SetupDatasetsDatabase.init(db_path)
SetupDatasetsDatabase.create_tables()

# ── 2. Version ─────────────────────────────────────────────────────────────
definitions.Version.create(value='3.0.0')

# ── 3. Tropical bounds (required by insert_hru_ltes) ──────────────────────
definitions.Tropical_bounds.create(north=18, south=-18)

# ── 4. plants_plt – one perennial row per landuse ─────────────────────────
# All numeric parameters default to 0; the editor only looks up name,
# plnt_typ, and a handful of double fields that are safe at 0.
for lu in landuses:
    hru_parm_db.Plants_plt.create(
        name=lu,
        plnt_typ='perennial',
        gro_trig='gro',
        nfix_co=0, days_mat=0, bm_e=0, harv_idx=0, lai_pot=3.0,
        frac_hu1=0, lai_max1=0, frac_hu2=0, lai_max2=0,
        hu_lai_decl=0, dlai_rate=0, can_ht_max=5.0, rt_dp_max=2000.0,
        tmp_opt=25.0, tmp_base=0, frac_n_yld=0, frac_p_yld=0,
        frac_n_em=0, frac_n_50=0, frac_n_mat=0,
        frac_p_em=0, frac_p_50=0, frac_p_mat=0,
        harv_idx_ws=0, usle_c_min=0.003, stcon_max=0, vpd=0,
        frac_stcon=0, ru_vpd=0, co2_hi=0, bm_e_hi=0,
        plnt_decomp=0, lai_min=0, bm_tree_acc=0, yrs_mat=0,
        bm_tree_max=0, ext_co=0, leaf_tov_mn=0, leaf_tov_mx=0,
        bm_dieoff=0, rt_st_beg=0, rt_st_end=0,
        plnt_pop1=0, frac_lai1=0, plnt_pop2=0, frac_lai2=0,
        frac_sw_gro=0, aeration=0, rsd_pctcov=0, rsd_covfac=0,
        description=lu,
    )

# ── 5. soils_lte_sol – all 12 texture classes ─────────────────────────────
# get_soil_lte() maps sand/silt/clay percentages to texture names.
# We provide all 12 so the project is texture-agnostic.
textures = [
    ('sand',            0.06, 0.42, 50.0),
    ('loamy_sand',      0.09, 0.43, 25.0),
    ('sandy_loam',      0.14, 0.45, 10.0),
    ('loam',            0.22, 0.46,  5.0),
    ('silt_loam',       0.27, 0.47,  3.0),
    ('silt',            0.25, 0.46,  2.0),
    ('sandy_clay_loam', 0.17, 0.44,  2.5),
    ('clay_loam',       0.20, 0.47,  1.5),
    ('silty_clay_loam', 0.21, 0.47,  1.0),
    ('sandy_clay',      0.14, 0.43,  1.5),
    ('silty_clay',      0.18, 0.47,  0.8),
    ('clay',            0.16, 0.48,  0.5),
]
for name, awc, por, scon in textures:
    ds_soils.Soils_lte_sol.create(name=name, awc=awc, por=por, scon=scon)

# ── 6. Decision tables required by insert_hru_ltes ────────────────────────
# The editor copies these to the project and uses their IDs as FKs in
# hru_lte_hru (grow_start / grow_end).  write_files also serialises these
# tables, so each must have ≥1 condition (with ≥1 alternative) and ≥1 action
# (with ≥1 outcome) — otherwise the decision_table writer raises AttributeError.
for dt_name in ('pl_grow_sum', 'pl_end_sum', 'pl_grow_win', 'pl_end_win'):
    dt = decision_table.D_table_dtl.create(name=dt_name, file_name='lum.dtl',
                                            description=dt_name)
    cond = decision_table.D_table_dtl_cond.create(
        d_table=dt, var='hru', obj='hru', obj_num=0,
        lim_var='phu', lim_op='>', lim_const=0.9,
    )
    decision_table.D_table_dtl_cond_alt.create(cond=cond, alt='y')
    act = decision_table.D_table_dtl_act.create(
        d_table=dt, act_typ='plant', obj='hru', obj_num=0,
        name='null', option='default', const=0.0, const2=0.0, fp='null',
    )
    decision_table.D_table_dtl_act_out.create(act=act, outcome=True)

# ── 7. CN / LUM helpers (used by get_cn2 in the datasets DB) ──────────────
cn_row  = ds_lum.Cntable_lum.create(
    name='generic_cn', cn_a=77.0, cn_b=86.0, cn_c=91.0, cn_d=94.0)
cp_row  = ds_lum.Cons_prac_lum.create(
    name='none', usle_p=1.0, slp_len_max=120.0)
ovn_row = ds_lum.Ovn_table_lum.create(
    name='generic_ovn', ovn_mean=0.14, ovn_min=0.10, ovn_max=0.16)

for lu in landuses:
    ds_lum.Landuse_lum.create(
        name=f'{lu}_lum',
        cn2=cn_row.id,
        cons_prac=cp_row.id,
        ov_mann=ovn_row.id,
    )

# ── 8. Basin codes and parameters ─────────────────────────────────────────
basin.Codes_bsn.create(
    pet=1, event=0, crack=0, swift_out=0, sed_det=0,
    rte_cha=1, deg_cha=0, wq_cha=0, nostress=0, cn=0,
    c_fact=0, carbon=1, lapse=0, uhyd=0, sed_cha=1,
    tiledrain=0, wtable=0, soil_p=0, gampt=0,
    atmo_dep='no', stor_max=0, i_fpwet=0, gwflow=0,
)
basin.Parameters_bsn.create(
    lai_noevap=3.0, sw_init=0.0, surq_lag=4.0,
    adj_pkrt=1.0, adj_pkrt_sed=1.0, lin_sed=0.2, exp_sed=1.5,
    orgn_min=0.0003, n_uptake=0.0, p_uptake=0.0,
    n_perc=0.0, p_perc=0.0, p_soil=0.0, p_avail=0.4,
    rsd_decomp=0.05, pest_perc=0.0, msk_co1=0.2, msk_co2=0.5,
    msk_x=0.2, nperco_lchtile=0.0, evap_adj=0.5, scoef=1.0,
    denit_exp=1.4, denit_frac=0.1, man_bact=0.0, adj_uhyd=0.5,
    cn_froz=0.0, dorm_hr=-1.0, plaps=0.0, tlaps=6.0,
    n_fix_max=0.0, rsd_decay=0.05, rsd_cover=0.5,
    urb_init_abst=0.0, petco_pmpt=1.0, uhyd_alpha=0.5,
    splash=0.0, rill=0.0, surq_exp=1.0, cov_mgt=0.0,
    cha_d50=0.5, co2=0.0, day_lag_max=5.0, igen=0,
)

# ── 9. File CIO classification + file list ────────────────────────────────
# Required by write_files — editor reads these from the project DB after
# they are copied in initialize_data().
classifications = [
    (1,'simulation'),(2,'basin'),(3,'climate'),(4,'connect'),
    (5,'channel'),(6,'reservoir'),(7,'routing_unit'),(8,'hru'),
    (9,'exco'),(10,'recall'),(11,'dr'),(12,'aquifer'),(13,'herd'),
    (14,'water_rights'),(15,'link'),(16,'hydrology'),(17,'structural'),
    (18,'hru_parm_db'),(19,'ops'),(20,'lum'),(21,'chg'),(22,'init'),
    (23,'soils'),(24,'decision_table'),(25,'regions'),(26,'pcp_path'),
    (27,'tmp_path'),(28,'slr_path'),(29,'hmd_path'),(30,'wnd_path'),
    (31,'out_path'),
]
for cid, cname in classifications:
    definitions.File_cio_classification.create(name=cname)

file_cio_rows = [
    # simulation (4 required)
    (1,1,'time.sim','time_sim',True),
    (1,2,'print.prt','print_prt',True),
    (1,3,'object.prt','object_prt',False),
    (1,4,'object.cnt','object_cnt',True),
    (1,5,'constituents.cs','constituents_cs',False),
    # basin (2 required)
    (2,1,'codes.bsn','codes_bsn',True),
    (2,2,'parameters.bsn','parameters_bsn',True),
    # climate (9 required)
    (3,1,'weather-sta.cli','weather_sta_cli',True),
    (3,2,'weather-wgn.cli','weather_wgn_cli',True),
    (3,3,'wind-dir.cli','wind_dir_cli',False),
    (3,4,'pcp.cli','weather_file',True),
    (3,5,'tmp.cli','weather_file',True),
    (3,6,'slr.cli','weather_file',True),
    (3,7,'hmd.cli','weather_file',True),
    (3,8,'wnd.cli','weather_file',True),
    (3,9,'atmodep.cli','atmodep_cli',False),
    # connect (13 required)
    (4,1,'hru.con','hru_con',True),
    (4,2,'hru-lte.con','hru_lte_con',False),
    (4,3,'rout_unit.con','rout_unit_con',True),
    (4,4,'modflow.con','modflow_con',False),
    (4,5,'aquifer.con','aquifer_con',True),
    (4,6,'aquifer2d.con','aquifer2d_con',False),
    (4,7,'channel.con','channel_con',True),
    (4,8,'reservoir.con','reservoir_con',True),
    (4,9,'recall.con','recall_con',True),
    (4,10,'exco.con','exco_con',False),
    (4,11,'delratio.con','delratio_con',False),
    (4,12,'outlet.con','outlet_con',True),
    (4,13,'chandeg.con','chandeg_con',False),
    # channel (7 required; 8 entries OK)
    (5,1,'initial.cha','initial_cha',True),
    (5,2,'channel.cha','channel_cha',True),
    (5,3,'hydrology.cha','hydrology_cha',True),
    (5,4,'sediment.cha','sediment_cha',True),
    (5,5,'nutrients.cha','nutrients_cha',True),
    (5,6,'channel-lte.cha','channel_lte_cha',False),
    (5,7,'hyd-sed-lte.cha','hyd_sed_lte_cha',False),
    (5,8,'temperature.cha','temperature_cha',False),
    # reservoir (8 required)
    (6,1,'initial.res','initial_res',True),
    (6,2,'reservoir.res','reservoir_res',True),
    (6,3,'hydrology.res','hydrology_res',True),
    (6,4,'sediment.res','sediment_res',True),
    (6,5,'nutrients.res','nutrients_res',True),
    (6,6,'weir.res','weir_res',False),
    (6,7,'wetland.wet','wetland_wet',False),
    (6,8,'hydrology.wet','hydrology_wet',False),
    # routing_unit (4 required)
    (7,1,'rout_unit.def','',True),
    (7,2,'rout_unit.ele','rout_unit_ele',True),
    (7,3,'rout_unit.rtu','rout_unit_rtu',True),
    (7,4,'rout_unit.dr','rout_unit_dr',False),
    # hru (2 required)
    (8,1,'hru-data.hru','hru_data_hru',True),
    (8,2,'hru-lte.hru','hru_lte_hru',False),
    # exco (6 required)
    (9,1,'exco.exc','exco_exc',False),
    (9,2,'exco_om.exc','exco_om_exc',False),
    (9,3,'exco_pest.exc','exco_pest_exc',False),
    (9,4,'exco_path.exc','exco_path_exc',False),
    (9,5,'exco_hmet.exc','exco_hmet_exc',False),
    (9,6,'exco_salt.exc','exco_salt_exc',False),
    # recall (1 required)
    (10,1,'recall.rec','recall_rec',True),
    # dr (6 required)
    (11,1,'delratio.del','delratio_del',False),
    (11,2,'dr_om.del','dr_om_exc',False),
    (11,3,'dr_pest.del','dr_pest_del',False),
    (11,4,'dr_path.del','dr_path_del',False),
    (11,5,'dr_hmet.del','dr_hmet_del',False),
    (11,6,'dr_salt.del','dr_salt_del',False),
    # aquifer (2 required)
    (12,1,'initial.aqu','initial_aqu',True),
    (12,2,'aquifer.aqu','aquifer_aqu',True),
    # water_rights (1 required)
    (14,1,'define.wro','define_wro',False),
    (14,2,'element.wro','element_wro',False),
    (14,3,'water_rights.wro','water_rights_wro',False),
    # hydrology (3 required)
    (16,1,'hydrology.hyd','hydrology_hyd',True),
    (16,2,'topography.hyd','topography_hyd',True),
    (16,3,'field.fld','field_fld',True),
    # structural (5 required)
    (17,1,'tiledrain.str','tiledrain_str',True),
    (17,2,'septic.str','septic_str',False),
    (17,3,'filterstrip.str','filterstrip_str',True),
    (17,4,'grassedww.str','grassedww_str',True),
    (17,5,'bmpuser.str','bmpuser_str',False),
    # hru_parm_db (10 required)
    (18,1,'plants.plt','plants_plt',True),
    (18,2,'fertilizer.frt','fertilizer_frt',True),
    (18,3,'tillage.til','tillage_til',True),
    (18,4,'pesticide.pes','pesticide_pst',False),
    (18,5,'pathogens.pth','pathogens_pth',False),
    (18,6,'metals.mtl','metals_mtl',False),
    (18,7,'salts.slt','salts_slt',False),
    (18,8,'urban.urb','urban_urb',True),
    (18,9,'septic.sep','septic_sep',False),
    (18,10,'snow.sno','snow_sno',True),
    # ops (6 required)
    (19,1,'harv.ops','harv_ops',True),
    (19,2,'graze.ops','graze_ops',True),
    (19,3,'irr.ops','irr_ops',True),
    (19,4,'chem_app.ops','chem_app_ops',False),
    (19,5,'fire.ops','fire_ops',True),
    (19,6,'sweep.ops','sweep_ops',False),
    # lum (5 required)
    (20,1,'landuse.lum','landuse_lum',True),
    (20,2,'management.sch','management_sch',True),
    (20,3,'cntable.lum','cntable_lum',True),
    (20,4,'cons_practice.lum','cons_practice_lum',True),
    (20,5,'ovn_table.lum','ovn_table_lum',True),
    # chg (9 required)
    (21,1,'cal_parms.cal','cal_parms_cal',False),
    (21,2,'calibration.cal','calibration_cal',False),
    (21,3,'codes.sft','codes_sft',False),
    (21,4,'wb_parms.sft','wb_parms_sft',False),
    (21,5,'water_balance.sft','water_balance_sft',False),
    (21,6,'ch_sed_budget.sft','ch_sed_budget_sft',False),
    (21,7,'ch_sed_parms.sft','ch_sed_parms_sft',False),
    (21,8,'plant_parms.sft','plant_parms_sft',False),
    (21,9,'plant_gro.sft','plant_gro_sft',False),
    # init (2 required; 11 entries OK)
    (22,1,'plant.ini','plant_ini',False),
    (22,2,'soil_plant.ini','soil_plant_ini',True),
    (22,3,'om_water.ini','om_water_ini',True),
    (22,4,'pest_hru.ini','pest_hru_ini',True),
    (22,5,'pest_water.ini','pest_water_ini',True),
    (22,6,'path_hru.ini','path_hru_ini',True),
    (22,7,'path_water.ini','path_water_ini',True),
    (22,8,'hmet_hru.ini','hmet_hru_ini',True),
    (22,9,'hmet_water.ini','hmet_water_ini',True),
    (22,10,'salt_hru.ini','salt_hru_ini',True),
    (22,11,'salt_water.ini','salt_water_ini',True),
    # soils (3 required)
    (23,1,'soils.sol','soils_sol',True),
    (23,2,'nutrients.sol','nutrients_sol',True),
    (23,3,'soils_lte.sol','soils_lte_sol',True),
    # decision_table (4 required)
    (24,1,'lum.dtl','lum_dtl',True),
    (24,2,'res_rel.dtl','res_rel_dtl',True),
    (24,3,'scen_lu.dtl','scen_lu_dtl',True),
    (24,4,'flo_con.dtl','flo_con_dtl',True),
    # regions (17 required)
    (25,1,'ls_unit.ele','ls_unit_ele',True),
    (25,2,'ls_unit.def','ls_unit_def',True),
    (25,3,'ls_reg.ele','ls_reg_ele',False),
    (25,4,'ls_reg.def','ls_reg_def',False),
    (25,5,'ls_cal.reg','ls_cal_reg',False),
    (25,6,'ch_catunit.ele','ch_catunit_ele',False),
    (25,7,'ch_catunit.def','ch_catunit_def',False),
    (25,8,'ch_reg.def','ch_reg_def',False),
    (25,9,'aqu_catunit.ele','aqu_catunit_ele',False),
    (25,10,'aqu_catunit.def','aqu_catunit_def',False),
    (25,11,'aqu_reg.def','aqu_reg_def',False),
    (25,12,'res_catunit.ele','res_catunit_ele',False),
    (25,13,'res_catunit.def','res_catunit_def',False),
    (25,14,'res_reg.def','res_reg_def',False),
    (25,15,'rec_catunit.ele','rec_catunit_ele',False),
    (25,16,'rec_catunit.def','rec_catunit_def',False),
    (25,17,'rec_reg.def','rec_reg_def',False),
]
for cls_id, order, fname, dbtable, is_core in file_cio_rows:
    # look up classification by position (id == cls_id since we inserted them
    # in order and SQLite auto-increments)
    cls_obj = definitions.File_cio_classification.get(
        definitions.File_cio_classification.id == cls_id)
    definitions.File_cio.create(
        classification=cls_obj,
        order_in_class=order,
        default_file_name=fname,
        database_table=dbtable,
        is_core_file=is_core,
    )

# ── 10. Print prt ─────────────────────────────────────────────────────────
definitions.Print_prt.create(
    nyskip=1, day_start=0, yrc_start=0, day_end=0, yrc_end=0,
    interval=1, csvout=False, dbout=False, cdfout=False,
    crop_yld='b', mgtout=False, hydcon=False, fdcout=False,
)
from database.datasets import definitions as _defs  # already imported
# Print_prt_object is in definitions module
print_prt_objects = [
    'basin_wb','basin_nb','basin_ls','basin_pw','basin_aqu','basin_res',
    'basin_cha','basin_sd_cha','basin_psc',
    'region_wb','region_nb','region_ls','region_pw','region_aqu',
    'region_res','region_cha','region_sd_cha','region_psc',
    'lsunit_wb','lsunit_nb','lsunit_ls','lsunit_pw',
    'hru_wb','hru_nb','hru_ls','hru_pw',
    'hru-lte_wb','hru-lte_nb','hru-lte_ls','hru-lte_pw',
    'channel','channel_sd','aquifer','reservoir','recall','hyd','ru','pest',
]
for pname in print_prt_objects:
    definitions.Print_prt_object.create(
        name=pname, daily=False, monthly=False, yearly=True, avann=True)

print('ok')
""")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_mock_datasets_db(
    path: Path | str,
    *,
    landuses: Sequence[str] | None = None,
    timeout: float = 60.0,
) -> Path:
    """Create a minimal ``swatplus_datasets.sqlite`` suitable for LTE testing.

    Uses the vendored editor's own peewee models (via subprocess) so that
    column order, FK constraints, and table names are guaranteed correct.

    Args:
        path: Where to write the SQLite file.  Parent must exist.
        landuses: Lower-case SWAT+ plant names to seed into ``plants_plt``
            and ``landuse_lum``.  Defaults to ``["frst", "agrr"]``.
        timeout: Subprocess timeout in seconds.

    Returns:
        Resolved ``Path`` to the created file.

    Raises:
        RuntimeError: if the creation subprocess fails.
    """
    import json

    path = Path(path).resolve()
    if path.exists():
        path.unlink()

    lus = list(landuses or ["frst", "agrr"])

    vendored_dir = Path(__file__).parent.parent / "editor" / "vendored"
    env = dict(os.environ)
    existing_pypath = env.get("PYTHONPATH", "")
    parts = [str(vendored_dir)]
    if existing_pypath:
        parts.append(existing_pypath)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env["PYTHONUNBUFFERED"] = "1"

    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(_SCRIPT)
        tmp_path = tmp.name

    try:
        proc = subprocess.run(
            [sys.executable, tmp_path, str(path), json.dumps(lus)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(vendored_dir),
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if proc.returncode != 0:
        raise RuntimeError(
            f"create_mock_datasets_db failed (exit {proc.returncode}).\n"
            f"stderr:\n{proc.stderr[-2000:]}\n"
            f"stdout:\n{proc.stdout[-1000:]}"
        )

    if not path.exists():
        raise RuntimeError(
            f"create_mock_datasets_db reported success but {path} was not created."
        )

    return path
