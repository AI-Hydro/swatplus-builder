#!/usr/bin/env python3
"""5-basin CN2 calibration benchmark."""
import sys, shutil, subprocess, os, tempfile, json, time
from pathlib import Path
import pandas as pd

sys.path.insert(0, 'src')
from swatplus_builder.output.eval import evaluate_run
from swatplus_builder.full_mode.water_balance_gate import check_water_balance

SWAT_EXE = str((Path('bin/swatplus_exe')).resolve())
CN2 = {'wood_f','wood_p','pastg_g','pastg_f','pastg_p','pasth','urban','agrl_rot','rc_strow_g','rc_strow_p','fal_bare'}
env = {'DYLD_LIBRARY_PATH': str(Path(SWAT_EXE).parent), 'OMP_NUM_THREADS': '1'}

basins = {
    '02129000': 'multibasin_test/02129000_full',
    '01547700': 'multibasin_test/01547700_final',
    '03349000': 'multibasin_test/03349000_full',
    '01654000': 'multibasin_test/01654000_full',
    '01491000': 'multibasin_test/01491000_full',
}

results = []
print(f"{'Gauge':>10} {'CN2':>5} {'BaseKGE':>8} {'BestKGE':>8} {'BestNSE':>8} {'Tier':>12}")
print('-' * 65)

for gid, path in basins.items():
    t0 = time.time()
    tio = Path(path) / 'project' / 'Scenarios' / 'Default' / 'TxtInOut'
    obs_path = Path(path) / 'outputs' / 'obs_q.csv'
    q_obs = pd.read_csv(obs_path, index_col=0, parse_dates=True)['obs']
    
    for s in tio.glob('simulation.out'): s.unlink()
    for s in tio.glob('channel_sd_day.txt'): s.unlink()
    rc = subprocess.run([SWAT_EXE], capture_output=True, text=True, cwd=str(tio), env=env, timeout=600).returncode
    if rc != 0:
        print(f'{gid:>10} ENGINE CRASH')
        results.append({'gauge': gid, 'status': 'CRASH'})
        continue
    
    _, bm, _ = evaluate_run(tio/'channel_sd_day.txt', q_obs, outlet_gis_id=1, outlet_policy='auto', return_diagnostics=True)
    bk = bm.get('kge', -999)
    
    best = {'nse': -999, 'kge': -999, 'offset': 0}
    for off in range(-30, 40, 5):
        w = Path(tempfile.mkdtemp(prefix='cb_'))
        shutil.copytree(tio, w, dirs_exist_ok=True)
        
        f = w / 'cntable.lum'
        lines = f.read_text().split('\n')
        out = []
        for ln in lines:
            parts = ln.split()
            if len(parts) >= 5 and parts[0] in CN2:
                for i in range(1, 5):
                    try:
                        v = float(parts[i])
                        parts[i] = '{:.5f}'.format(max(30, min(98, v + off)))
                    except: pass
            out.append(' '.join(parts))
        f.write_text('\n'.join(out))
        
        for s in w.glob('simulation.out'): s.unlink()
        if subprocess.run([SWAT_EXE], capture_output=True, text=True, cwd=str(w), env=env, timeout=600).returncode != 0:
            shutil.rmtree(w, ignore_errors=True); continue
        
        _, m, _ = evaluate_run(w/'channel_sd_day.txt', q_obs, outlet_gis_id=1, outlet_policy='auto', return_diagnostics=True)
        n, k = m.get('nse',-999), m.get('kge',-999)
        if k > best['kge']: best = {'nse': n, 'kge': k, 'offset': off}
        shutil.rmtree(w, ignore_errors=True)
    
    gate = check_water_balance(tio, nse=best['nse'], kge=best['kge'])
    tiers = gate['allowed_tiers']
    tier = 'research' if 'research_grade' in tiers else 'diag' if 'diagnostic' in tiers else 'explor'
    
    elapsed = time.time() - t0
    print(f'{gid:>10} {best["offset"]:>+5d} {bk:>8.3f} {best["kge"]:>8.3f} {best["nse"]:>8.3f} {tier:>12} {elapsed:.0f}s')
    results.append({'gauge': gid, 'best_kge': best['kge'], 'best_nse': best['nse'], 'cn2': best['offset'], 'tier': tier, 'base_kge': bk})

n_research = sum(1 for r in results if r.get('best_kge',0) >= 0.40)
print(f'\nKGE>=0.40: {n_research}/{len(results)}')
Path('multibasin_test/calibration_results.json').write_text(json.dumps(results, indent=2))
