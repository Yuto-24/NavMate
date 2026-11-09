"""Offline, fixed-case research for #374; never imported by the application.

Uses private 0.6.0 decode/interpolation helpers only to avoid a second decoder.
WX arrays are experimental NPZ, NOT a valid library portable payload.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import numpy as np
import pygrib
from jma_gpv_weather import Bounds, MsmPreparedData, GsmPreparedData
from jma_gpv_weather.models import RunSelection
from jma_gpv_weather.grib import read_grib_records, _subset_message
from jma_gpv_weather.interpolation import _grid_bracket, bilinear, temporal
from jma_gpv_weather.msm import spec as msm
from jma_gpv_weather.gsm import spec as gsm

RUN = datetime(2026, 9, 12, tzinfo=timezone.utc)
BASE = 'https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original/2026/09/12/'
LEVELS = (1000, 975, 950, 925, 900, 850, 800, 700, 600, 500, 400, 300)
CLOUD = {1: 'total', 3: 'low', 4: 'middle', 5: 'high'}
# User-supplied KML LineString: lon,lat,0 converted to lat,lon in original order.
# KML zero altitudes are not a flight-height specification.
WAYPOINTS = (
    (31.87712037682015, 131.4484495960596),
    (32.11563297766774, 130.3376632947516),
    (32.89351014087774, 130.5367556500529),
    (32.85783487963734, 130.0867842334102),
    (32.91714519596533, 129.9132553497481),
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(records):
    h = hashlib.sha256()
    for key, record in sorted(records.items()):
        h.update(str(key).encode())
        for array in record:
            h.update(array.tobytes())
    return h.hexdigest()


def sample(records, variable, level, when, latitude, longitude, step):
    """Require the scheduled endpoints and all corners; never bridge missing data."""
    hour = (when - RUN).total_seconds() / 3600
    lower = math.floor(hour / step) * step
    upper = lower if hour == lower else lower + step
    times = [RUN + timedelta(hours=h) for h in (lower, upper)]
    values = []
    for time in times:
        record = records.get((time, level, variable))
        if record is None:
            return None
        field, lat, lon = record
        bracket = _grid_bracket(lat, lon, latitude, longitude)
        if bracket is None:
            return None
        yi, xi, ys, xs = bracket
        corners = field[np.ix_(yi, xi)]
        if not np.isfinite(corners).all():
            return None
        values.append(bilinear(longitude, latitude, *xs, *ys, corners))
    return temporal(*times, *values, when)


def route():
    distance = 0.0
    previous = None
    for leg, (start, end) in enumerate(zip(WAYPOINTS, WAYPOINTS[1:])):
        for i in range(13):
            if leg and i == 0:
                continue
            lat, lon = (a + (b-a)*i/12 for a, b in zip(start, end))
            if previous:
                p1, p2 = math.radians(previous[0]), math.radians(lat)
                a = math.sin((p2-p1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(math.radians(lon-previous[1])/2)**2
                distance += 6371000 * 2 * math.asin(math.sqrt(a)) / 1852
            previous = lat, lon
            yield distance, lat, lon


def write_npz(records, path):
    arrays, keys = {}, []
    for i, (key, record) in enumerate(sorted(records.items())):
        arrays[f'r{i}'] = record[0]  # same float64 storage as the current codec
        group = 'pressure' if key[1] else 'surface'
        arrays[f'{group}_latitude'] = record[1]
        arrays[f'{group}_longitude'] = record[2]
        keys.append([key[0].isoformat(), key[1], key[2]])
    arrays['metadata'] = np.frombuffer(json.dumps({'experimental': True, 'records': keys}).encode(), dtype=np.uint8)
    np.savez_compressed(path, **arrays)
    return sum(a.nbytes for a in arrays.values())


def measure(path):
    """Fresh Linux process: import baseline, then read and materialize every array."""
    code = '''import io,json,time,numpy as np,sys
from pathlib import Path
def memory():
    rows=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines())
    return {k:int(rows[k].split()[0]) for k in ('VmRSS','VmHWM')}
before=memory()
start=time.perf_counter()
payload=open(sys.argv[1],'rb').read()
with np.load(io.BytesIO(payload),allow_pickle=False) as z: arrays=[z[k] for k in z.files]
print(json.dumps(dict(seconds=time.perf_counter()-start,baseline_rss_kib=before['VmRSS'],peak_rss_kib=memory()['VmHWM'],expanded_array_bytes=sum(a.nbytes for a in arrays))))'''
    result = json.loads(subprocess.check_output([sys.executable, '-c', code, str(path)], text=True))
    result['compressed_bytes'] = path.stat().st_size
    result['sha256'] = sha(path.read_bytes())
    return result


def inspect_model(model, raw, output):
    spec, codec = (msm, MsmPreparedData) if model == 'MSM' else (gsm, GsmPreparedData)
    suffix = ('Rjp_{}_FH00-15' if model == 'MSM' else 'Rjp_Gll0p1deg_{}_FD0000-0100')
    paths = [raw / f'Z__C_RJTD_20260912000000_{model}_GPV_{suffix.format(kind)}_grib2.bin'
             for kind in ('L-pall', 'Lsurf')]
    files = tuple(spec.parse_listing(p.name, BASE)[0] for p in paths)
    hashes = {BASE+p.name: sha(p.read_bytes()) for p in paths}
    bounds = spec.interpolation_bounds(Bounds())
    times = tuple(RUN + timedelta(hours=h) for h in range(13))
    surface, pressure = read_grib_records(paths, None, bounds, times, pressure_levels=spec.LEVELS_HPA)
    baseline = codec(RunSelection(RUN, files), surface, pressure, hashes)
    before = [fingerprint(surface), fingerprint(pressure)]
    base_payload = baseline.to_bytes()
    base_path = output / f'{model.lower()}-baseline.npz'
    base_path.write_bytes(base_payload)
    wx, inventory = {}, defaultdict(lambda: {'levels': set(), 'hours': set(), 'grids': set()})
    for path in paths:
        with pygrib.open(str(path)) as grib:
            for message in grib:
                assert message.analDate.replace(tzinfo=timezone.utc) == RUN
                assert message.productionStatusOfProcessedData == 0
                valid = message.validDate.replace(tzinfo=timezone.utc)
                category, number, level = message.parameterCategory, message.parameterNumber, message.level
                kind = message.typeOfLevel
                identity = f'{kind}/{category}/{number}/{message.shortName}/{message.units}'
                inv = inventory[identity]
                inv['levels'].add(level)
                inv['hours'].add((valid-RUN).total_seconds()/3600)
                inv['grids'].add((message.Nj, message.Ni))
                variable = None
                if kind == 'isobaricInhPa' and level in LEVELS:
                    variable = {(1, 1): 'rh', (3, 5): 'hgt'}.get((category, number))
                if kind == 'surface':
                    variable = CLOUD.get(number) if category == 6 else {(3, 0): 'sp'}.get((category, number))
                if variable and valid in times:
                    key = valid, level, variable
                    assert key not in wx
                    wx[key] = _subset_message(message, bounds)
    # Verify baseline data stay bit-for-bit unchanged; round-trip current public codec.
    restored = codec.from_bytes(base_payload, expected_sha256=sha(base_payload))
    assert before == [fingerprint(surface), fingerprint(pressure)]
    assert before == [fingerprint(restored.surface), fingerprint(restored.pressure)]
    # The old codec must reject added pressure RH, not silently accept a new schema.
    foreign = codec(baseline.selection, surface, {**pressure, **{k: v for k, v in wx.items() if k[2] == 'rh'}}, hashes)
    try:
        foreign.to_bytes()
    except Exception as error:
        rejection = type(error).__name__
    else:
        raise AssertionError('0.6.0 unexpectedly accepted pressure RH')
    wx_path = output / f'{model.lower()}-wx-experimental.npz'
    write_npz(wx, wx_path)
    rows = []
    for departure in (3.5, 9.5):
        for index, (distance, lat, lon) in enumerate(route()):
            when = RUN + timedelta(hours=departure + distance/150)
            sp = sample(wx, 'sp', 0, when, lat, lon, 1)
            clouds = {f'{name}_pct': sample(wx, name, 0, when, lat, lon, 1) for name in CLOUD.values()}
            for level in LEVELS:
                rh = sample(wx, 'rh', level, when, lat, lon, 3)
                hgt = sample(wx, 'hgt', level, when, lat, lon, 3)
                state = ('missing' if None in (sp, rh, hgt) else
                         'below_model_surface' if level*100 > sp else 'available')
                rows.append(dict(model=model, departure_hour=departure, sample=index,
                                 distance_nm=distance, lat=lat, lon=lon, valid_utc=when.isoformat(),
                                 level_hpa=level, hgt_m=hgt, rh_pct=rh, sp_pa=sp, state=state, **clouds))
    metrics = {'baseline': measure(base_path), 'wx_experimental': measure(wx_path)}
    for name in ('rh', 'hgt', 'sp', 'total', 'low', 'middle', 'high'):
        selected = [v[0] for k, v in wx.items() if k[2] == name]
        metrics[name] = dict(records=len(selected), shape=list(selected[0].shape),
                             array_bytes=sum(a.nbytes for a in selected),
                             nonfinite_cells=sum(int((~np.isfinite(a)).sum()) for a in selected))
    summary = {}
    for departure in (3.5, 9.5):
        subset = [r for r in rows if r['departure_hour'] == departure and r['state'] == 'available']
        summary[str(departure)] = {'available_cells': len(subset),
            'rh_ge_counts': {str(t): sum(r['rh_pct'] >= t for r in subset) for t in (80, 90, 95)},
            'hgt_range_m': [min(r['hgt_m'] for r in subset), max(r['hgt_m'] for r in subset)],
            'layer_cloud_ranges_pct': {name: [min(r[f'{name}_pct'] for r in subset), max(r[f'{name}_pct'] for r in subset)] for name in CLOUD.values()}}
    return rows, dict(sources=[{'url': BASE+p.name, 'bytes': p.stat().st_size, 'sha256': hashes[BASE+p.name]} for p in paths],
        inventory={k: {field: sorted(value) for field, value in v.items()} for k,v in sorted(inventory.items())},
        bounds=bounds.__dict__, baseline_unchanged=before, old_codec_rh_rejection=rejection,
        measurements=metrics, sensitivity=summary,
        states={state: sum(r['state'] == state for r in rows) for state in ('available','missing','below_model_surface')})


def plot(rows, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(12, 7), sharex=True, sharey=True, layout='constrained')
    for j, departure in enumerate((3.5, 9.5)):
        for i, model in enumerate(('MSM', 'GSM')):
            ax = axes[j, i]
            subset = [r for r in rows if r['model'] == model and r['departure_hour'] == departure and r['state'] == 'available']
            scatter = ax.scatter([r['distance_nm'] for r in subset], [r['hgt_m']/0.3048 for r in subset],
                                c=[r['rh_pct'] for r in subset], vmin=0, vmax=100, cmap='viridis', marker='s', s=14)
            ax.set_title(f'{model} | departure {int(departure):02d}:30 UTC | GS 150 kt')
            ax.set_xlabel('Distance along research route (NM)')
            ax.set_ylabel('GPV geopotential height / 0.3048 (ft)')
    fig.colorbar(scatter, ax=axes, label='Forecast relative humidity (%)')
    fig.suptitle('Run 2026-09-12 00 UTC | User-supplied Kyushu KML route\nNative pressure-level samples; no cloud-base/top inference or gap filling')
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--plot', action='store_true', help='requires matplotlib')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows, results = [], {'run_utc': RUN.isoformat(), 'python': platform.python_version(),
        'numpy': np.__version__, 'pygrib': pygrib.__version__, 'platform': platform.platform(),
        'window_hours': [0, 12], 'waypoints': WAYPOINTS, 'gs_kt': 150,
        'scope': 'One historical case; no observational accuracy or Safari acceptance.'}
    for model in ('MSM', 'GSM'):
        new_rows, results[model] = inspect_model(model, args.raw, args.output)
        rows.extend(new_rows)
    with (args.output/'profile.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (args.output/'results.json').write_text(json.dumps(results, indent=2, allow_nan=False)+'\n')
    if args.plot:
        plot(rows, args.output/'profile.png')
    print(json.dumps({m: results[m]['sensitivity'] for m in ('MSM','GSM')}, indent=2))


if __name__ == '__main__':
    main()
