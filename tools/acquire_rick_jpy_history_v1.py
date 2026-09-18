"""Checkpointed read-only MT5 history extension. No strategy or order imports."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'research_artifacts/rick_jpy_history_2023_to_date_v1'
UTC = timezone.utc
NY = ZoneInfo('America/New_York')
START = int(datetime(2022, 12, 1, tzinfo=UTC).timestamp())
RESEARCH_START = int(datetime(2023, 1, 1, tzinfo=UTC).timestamp())
DTYPE = np.dtype([('time', '<i8'), ('open', '<f8'), ('high', '<f8'),
                  ('low', '<f8'), ('close', '<f8'), ('tick_volume', '<i8'),
                  ('spread', '<i8'), ('real_volume', '<i8')])
TF_SECONDS = {'M1': 60, 'M15': 900, 'D1': 86400}


def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def read(p):
    return json.loads(Path(p).read_text(encoding='utf8'))


def save(p, value):
    with Path(p).open('x', encoding='utf8', newline='\n') as f:
        json.dump(value, f, sort_keys=True, indent=2)
        f.write('\n')


def rec(p):
    p = Path(p)
    return {'path': p.relative_to(ROOT).as_posix(), 'sha256': sha(p)}


def verify(items):
    for r in items:
        if sha(ROOT / r['path']) != r['sha256']:
            raise RuntimeError('Source/hash mismatch: ' + r['path'])


def iso(t):
    return datetime.fromtimestamp(int(t), UTC).isoformat()


def epoch(s):
    return int(datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp())


def log(stage, **kw):
    item = dict(utc=datetime.now(UTC).isoformat(), stage=stage, **kw)
    with (OUT / 'progress.jsonl').open('a', encoding='utf8') as f:
        f.write(json.dumps(item, sort_keys=True) + '\n')
    print(json.dumps(item), flush=True)


def primary_clock(t):
    approx = datetime.fromtimestamp(int(t) - 7200, UTC)
    return int(t - (7 * 3600 + approx.astimezone(NY).utcoffset().total_seconds()))


def reference_clock(t):
    wall = datetime.fromtimestamp(int(t), UTC).replace(tzinfo=None)
    return int((wall - timedelta(hours=7)).replace(tzinfo=NY).timestamp())


def clocks(stamps, reference=False):
    # Offset constant within an encoded hour. No price-dependent conversion.
    hours, indexes = np.unique(stamps // 3600, return_inverse=True)
    fn = reference_clock if reference else primary_clock
    offsets = np.array([fn(int(h) * 3600) - int(h) * 3600 for h in hours], dtype=np.int64)
    return stamps + offsets[indexes]


def subtract(lo, hi, covered):
    result = []
    at = lo
    for a, b in sorted(covered):
        if b <= at or a >= hi:
            continue
        if a > at:
            result.append((at, min(a, hi)))
        at = max(at, b)
        if at >= hi:
            break
    if at < hi:
        result.append((at, hi))
    return result


def monthly(lo, hi):
    while lo < hi:
        d = datetime.fromtimestamp(lo, UTC)
        nxt = datetime(d.year + (d.month == 12), d.month % 12 + 1, 1, tzinfo=UTC)
        end = min(hi, int(nxt.timestamp()))
        yield lo, end
        lo = end


def source(symbol, tf, lo, hi, path, fmt, refs):
    return dict(symbol=symbol, timeframe=tf, lo=lo, hi=hi, path=path,
                format=fmt, records=refs, reused=True,
                source_id=hashlib.sha256(path.encode()).hexdigest()[:20])


def inventory():
    found, metadata = [], []
    old = ROOT / 'research_artifacts/multi_asset_macro_session_portfolio_v1_m2/acquisition_manifest.json'
    metadata.append(rec(old))
    for symbol in read(old)['symbols']:
        if symbol['symbol'] != 'USDJPY':
            continue
        for r in symbol['files']:
            lo, hi = epoch(r['request_start']), epoch(r['request_end_exclusive'])
            if hi <= START:
                continue
            ref = {k: r[k] for k in ('path', 'sha256')}
            found.append(source('USDJPY', 'M1', lo, hi, r['path'], 'legacy_csv', [ref]))
    base = ROOT / 'research_artifacts/rick_usdjpy_video_replication_v1/source_manifest.json'
    metadata.append(rec(base))
    for s in read(base)['sources']:
        if s['schema'] not in TF_SECONDS:
            continue
        found.append(source('USDJPY', s['schema'], epoch(s['requested_start']),
                            epoch(s['requested_end_exclusive']), s['raw']['path'],
                            'npy', [s['raw'], s['normalized']]))
    base = ROOT / 'research_artifacts/rick_three_video_replication_v1/source_manifest.json'
    metadata.append(rec(base))
    ranges = {'B': ('2025-11-17', '2026-01-01'), 'C': ('2025-02-17', '2025-04-01')}
    for s in read(base)['sources']:
        lo, hi = [epoch(x+'T00:00:00Z') for x in ranges[s['version']]]
        found.append(source('GBPJPY', s['timeframe'], lo, hi, s['raw']['path'],
                            'npy', [s['raw'], s['normalized']]))
    base = ROOT / 'research_artifacts/rick_gbpjpy_d1_trend_source_v1/source_manifest.json'
    metadata.append(rec(base))
    d = read(base)
    raw = next(r for r in d['files'] if r['path'].endswith('.npy'))
    found.append(source('GBPJPY', 'D1', epoch(d['request_start']),
                        epoch(d['request_end_exclusive']), raw['path'], 'npy', d['files']))
    verify(metadata)
    for s in found:
        verify(s['records'])
    return found, metadata


def freeze():
    if (OUT / 'freeze.json').exists():
        verify(read(OUT / 'freeze.json')['implementation'])
        print('EXISTING_FREEZE_REUSED_NO_NEW_CUTOFF')
        return
    if OUT.exists():
        raise RuntimeError('Unsealed existing output directory')
    cutoff = int(datetime.now(UTC).timestamp()) // 60 * 60
    wall = datetime.fromtimestamp(cutoff, NY).replace(tzinfo=None) + timedelta(hours=7)
    end = int(wall.replace(tzinfo=UTC).timestamp())
    old, metadata = inventory()
    requests = []
    for symbol in ('USDJPY', 'GBPJPY'):
        for tf in TF_SECONDS:
            covered = [(s['lo'], s['hi']) for s in old if s['symbol'] == symbol and s['timeframe'] == tf]
            for lo, hi in subtract(START, end, covered):
                for a, b in monthly(lo, hi):
                    requests.append(dict(id=f'Q{len(requests)+1:03}', symbol=symbol,
                                         timeframe=tf, lo=a, hi=b))
    if shutil.disk_usage(ROOT).free < 5 * 1024**3:
        raise RuntimeError('Need at least 5 GiB usable storage')
    OUT.mkdir()
    for folder in ('raw', 'requests', 'normalized', 'months'):
        (OUT / folder).mkdir()
    save(OUT / 'freeze.json', dict(utc_cutoff=cutoff, encoded_end=end,
         research_start=RESEARCH_START, warmup_start=START, requests=requests,
         existing=old, source_metadata=metadata, maximum_charge=0,
         implementation=[rec(Path(__file__)), rec(ROOT/'RICK_JPY_HISTORY_2023_TO_DATE_V1.md'),
                         rec(ROOT/'tests/test_rick_jpy_history_v1.py')]))
    log('FROZEN', cutoff_utc=iso(cutoff), requests=len(requests), reused_sources=len(old))


def read_source(s):
    p = ROOT / s['path']
    if s['format'] == 'npy':
        a = np.load(p, allow_pickle=False)
        if a.dtype.names != DTYPE.names:
            raise RuntimeError('Unexpected native schema ' + str(p))
        return a.astype(DTYPE, copy=False)
    values = []
    with p.open(encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            values.append((epoch(r['open_time']), *[float(r[k]) for k in ('open','high','low','close')],
                           int(float(r['volume'])), int(r['spread_points']), int(r['real_volume'])))
    return np.array(values, dtype=DTYPE)


def validate(a, lo, hi, tf):
    if a.dtype.names != DTYPE.names:
        raise RuntimeError('Bad source schema')
    t = a['time']
    if not np.all((t >= lo) & (t < hi)) or np.any(np.diff(t) < 0):
        raise RuntimeError('Outside request or unordered source')
    if np.any(t % TF_SECONDS[tf]):
        raise RuntimeError('Unaligned timestamp')
    for k in ('open','high','low','close'):
        if not np.all(np.isfinite(a[k]) & (a[k] > 0)):
            raise RuntimeError('Invalid source price field')
    if not np.all((a['low'] <= np.minimum(a['open'],a['close'])) &
                  (a['high'] >= np.maximum(a['open'],a['close']))):
        raise RuntimeError('Invalid OHLC envelope')
    if any(np.any(a[k] < 0) for k in ('tick_volume','spread','real_volume')):
        raise RuntimeError('Negative metadata field')
    duplicates = np.flatnonzero(np.diff(t) == 0)
    for i in duplicates:
        if a[i].tobytes() != a[i+1].tobytes():
            raise RuntimeError('Conflicting duplicate source timestamp')


def connect():
    import MetaTrader5 as mt5
    if not mt5.initialize(path=r'C:\Program Files\MetaTrader 5\terminal64.exe', timeout=10000):
        raise RuntimeError('MT5 initialize failed: '+str(mt5.last_error()))
    t, a = mt5.terminal_info(), mt5.account_info()
    if not t or not t.connected or not a or 'IC Markets' not in a.company:
        mt5.shutdown()
        raise RuntimeError('Connected IC Markets terminal required')
    return mt5, a.company


def acquire(f):
    mt5, company = connect()
    try:
        if not (OUT / 'symbol_metadata.json').exists():
            catalog = {}
            for symbol in ('USDJPY','GBPJPY'):
                info = mt5.symbol_info(symbol)
                if not info or info.digits != 3 or info.point != 0.001:
                    raise RuntimeError('Unexpected symbol mapping')
                fields = ('name','digits','point','trade_contract_size','trade_tick_size',
                          'trade_tick_value','volume_min','volume_max','volume_step',
                          'currency_base','currency_profit','currency_margin','swap_mode',
                          'swap_long','swap_short','swap_rollover3days')
                catalog[symbol] = {k:getattr(info,k) for k in fields}
            save(OUT / 'symbol_metadata.json', dict(company=company, observed_at_utc=datetime.now(UTC).isoformat(),
                 symbols=catalog, historical_swap_history=False, orders_sent=False))
        for n, q in enumerate(f['requests'], 1):
            checkpoint = OUT / 'requests' / (q['id']+'.json')
            raw = OUT / 'raw' / (q['id']+'.npy')
            if checkpoint.exists():
                c = read(checkpoint)
                if c['request'] != q:
                    raise RuntimeError('Checkpoint request differs')
                verify([c['raw']])
                continue
            if raw.exists():
                raise RuntimeError('Unsealed raw file; inspect before retry: '+raw.name)
            if shutil.disk_usage(ROOT).free < 2 * 1024**3:
                raise RuntimeError('Storage below 2 GiB')
            log('REQUEST_START', request=q['id'], index=n, total=len(f['requests']),
                symbol=q['symbol'], timeframe=q['timeframe'], start_encoded=iso(q['lo']), end_encoded=iso(q['hi']))
            received = datetime.now(UTC).isoformat()
            a = mt5.copy_rates_range(q['symbol'], getattr(mt5,'TIMEFRAME_'+q['timeframe']),
                                    datetime.fromtimestamp(q['lo'],UTC),datetime.fromtimestamp(q['hi']-1,UTC))
            if a is None:
                raise RuntimeError('Provider failed '+q['id']+': '+str(mt5.last_error()))
            with raw.open('xb') as h:
                np.save(h, a, allow_pickle=False)
            validate(a, q['lo'], q['hi'], q['timeframe'])
            info = dict(request=q, raw=rec(raw), rows=len(a), received_at_utc=received,
                        first_encoded=int(a['time'][0]) if len(a) else None,
                        last_encoded=int(a['time'][-1]) if len(a) else None,
                        status='RECEIVED_VALID_ROWS' if len(a) else 'EMPTY_PROVIDER_RESPONSE')
            save(checkpoint, info)
            log('REQUEST_COMPLETE', request=q['id'], index=n, total=len(f['requests']), rows=len(a))
    finally:
        mt5.shutdown()


def all_sources(f):
    result = list(f['existing'])
    for q in f['requests']:
        r = read(OUT/'requests'/(q['id']+'.json'))
        s = source(q['symbol'],q['timeframe'],q['lo'],q['hi'],r['raw']['path'],'npy',[r['raw']])
        s.update(reused=False, received_at_utc=r['received_at_utc'])
        result.append(s)
    return result


def normalized(a, source_ids, source_rows, tf, cutoff, reference=False):
    opened = clocks(a['time'],reference)
    closed = clocks(a['time']+TF_SECONDS[tf],reference)
    mask = closed <= cutoff
    if np.any(closed <= opened):
        raise RuntimeError('Nonpositive normalized duration')
    columns = dict(encoded_epoch=a['time'][mask], open_epoch_utc=opened[mask],
                   close_epoch_utc=closed[mask], historical_available_at_epoch_utc=closed[mask])
    for k in DTYPE.names[1:]:
        columns[k] = a[k][mask]
    columns['source_id'] = source_ids[mask].tolist()
    columns['source_row'] = source_rows[mask]
    table = pa.table(columns)
    return table, int((~mask).sum())


def technical(table, tf, lo, hi):
    stamps = table['encoded_epoch'].to_numpy()
    unit = TF_SECONDS[tf]
    days = np.unique(stamps // 86400)
    expected = range(lo//86400, (hi+86399)//86400)
    missing = [iso(d*86400)[:10] for d in expected if datetime.fromtimestamp(d*86400,UTC).weekday()<5 and d not in days]
    gaps = np.diff(stamps)
    # Gap list is metadata; absence is not automatically called a closure.
    missing_intervals = [dict(after_encoded=int(stamps[i]), before_encoded=int(stamps[i+1]),
                              absent_grid_slots=int(gaps[i]//unit-1)) for i in np.flatnonzero(gaps>unit)]
    return dict(rows=len(table), first_encoded=int(stamps[0]) if len(stamps) else None,
                last_encoded=int(stamps[-1]) if len(stamps) else None,
                first_open_utc=iso(table['open_epoch_utc'][0].as_py()) if len(stamps) else None,
                last_close_utc=iso(table['close_epoch_utc'][-1].as_py()) if len(stamps) else None,
                observed_broker_dates=len(days), missing_weekdays=missing, gaps=missing_intervals,
                zero_spread_rows=int(np.sum(table['spread'].to_numpy()==0)),
                gap_classification='REPORTED_NOT_IMPUTED_CALENDAR_NOT_INFERRED')


def materialize(f):
    sources = all_sources(f)
    for s in sources:
        verify(s['records'])
    completed = []
    for symbol in ('USDJPY','GBPJPY'):
        for tf in TF_SECONDS:
            for lo, hi in monthly(START,f['encoded_end']):
                key = symbol+'_'+tf+'_'+iso(lo)[:7]
                checkpoint = OUT/'months'/(key+'.json')
                if checkpoint.exists():
                    r = read(checkpoint)
                    verify([r['payload']])
                    completed.append(r)
                    continue
                chunks, ids, rows = [], [], []
                for s in sources:
                    if s['symbol']!=symbol or s['timeframe']!=tf or s['hi']<=lo or s['lo']>=hi:
                        continue
                    a = read_source(s)
                    validate(a,s['lo'],s['hi'],tf)
                    indices = np.flatnonzero((a['time']>=lo)&(a['time']<hi))
                    chunks.append(a[indices])
                    ids.extend([s['source_id']]*len(indices))
                    rows.extend(indices.tolist())
                a = np.concatenate(chunks) if chunks else np.empty(0,dtype=DTYPE)
                source_ids, source_rows = np.array(ids,dtype='U20'),np.array(rows,dtype=np.int64)
                sort = np.argsort(a['time'],kind='stable')
                a,source_ids,source_rows = a[sort],source_ids[sort],source_rows[sort]
                validate(a,lo,hi,tf)
                keep = np.r_[True,np.diff(a['time'])!=0] if len(a) else np.array([],dtype=bool)
                duplicates = int((~keep).sum())
                a,source_ids,source_rows = a[keep],source_ids[keep],source_rows[keep]
                primary, excluded = normalized(a,source_ids,source_rows,tf,f['utc_cutoff'])
                # Second timestamp algorithm and independently enumerated row reconstruction.
                rebuilt = np.array([tuple(row[k].item() for k in DTYPE.names) for row in a],dtype=DTYPE)
                reference, ref_excluded = normalized(rebuilt,source_ids,source_rows,tf,f['utc_cutoff'],True)
                if not primary.equals(reference) or excluded!=ref_excluded:
                    raise RuntimeError('Primary/reference normalization mismatch '+key)
                p = OUT/'normalized'/(key+'.parquet')
                if p.exists():
                    raise RuntimeError('Unsealed payload; inspect before retry '+key)
                pq.write_table(primary,p,compression='zstd',version='2.6',row_group_size=50000)
                if not pq.read_table(p).equals(reference):
                    raise RuntimeError('Parquet roundtrip mismatch '+key)
                info = dict(key=key,symbol=symbol,timeframe=tf,lo=lo,hi=hi,payload=rec(p),
                            duplicates_preserved_in_raw=duplicates,incomplete_bars_excluded=excluded,
                            primary_reference_equal=True,technical=technical(primary,tf,lo,hi))
                save(checkpoint,info)
                completed.append(info)
                log('MONTH_CERTIFIED',key=key,rows=len(primary),months_done=len(completed),
                    missing_weekdays=len(info['technical']['missing_weekdays']))
    return completed,sources


def aggregate_audit(months):
    # Native M15 compared only against complete observed 15-minute child buckets.
    index = {r['key']:r for r in months}
    results=[]
    for key,r in sorted(index.items()):
        if r['timeframe']!='M1':
            continue
        other=index[key.replace('_M1_','_M15_')]
        one=pq.read_table(ROOT/r['payload']['path']).to_pydict()
        native=pq.read_table(ROOT/other['payload']['path']).to_pydict()
        groups={}
        for i,t in enumerate(one['encoded_epoch']):
            groups.setdefault(t//900*900,[]).append(i)
        counts=Counter(); failures=[]
        for j,t in enumerate(native['encoded_epoch']):
            ix=groups.get(t,[])
            if len(ix)!=15 or [one['encoded_epoch'][i] for i in ix]!=list(range(t,t+900,60)):
                counts['incomplete_child_buckets']+=1
                continue
            built=(one['open'][ix[0]],max(one['high'][i] for i in ix),
                   min(one['low'][i] for i in ix),one['close'][ix[-1]])
            wanted=tuple(native[k][j] for k in ('open','high','low','close'))
            counts['complete_buckets']+=1
            if built!=wanted:
                failures.append(t)
        results.append(dict(symbol=r['symbol'],month=key[-7:],counts=dict(counts),
                            mismatch_encoded_timestamps=failures,mismatch_count=len(failures)))
    return results


def calendar_inventory():
    # Read only time/name/ID metadata from the existing value-bearing US file.
    base=ROOT/'data/mt5/calendar/mt5_us_calendar_raw.csv'
    months=Counter()
    with base.open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            months[r['event_time_server'][:7].replace('.','-')]+=1
    status=ROOT/'data/mt5/calendar/mt5_us_calendar_status.csv'
    with status.open(encoding='utf-8-sig',newline='') as f:
        record=list(csv.DictReader(f))[0]
    return dict(us_source=rec(base),us_status=rec(status),us_declared_start=record['date_from_server'],
                us_declared_end=record['date_to_server'],us_month_rows=dict(sorted(months.items())),
                gb_jp_existing_certified_months=['2025-03','2025-12'],
                remaining_calendar_status='REQUIRES_TERMINAL_METADATA_EXPORT',
                historical_schedule_vintage_certified=False,actual_forecast_values_used=False)


def run():
    f=read(OUT/'freeze.json')
    verify(f['implementation']);verify(f['source_metadata'])
    if (OUT/'completion_seal.json').exists():
        verify(read(OUT/'completion_seal.json')['files'])
        print('VERIFIED_ALREADY_COMPLETED');return
    acquire(f)
    log('DOWNLOADS_COMPLETE',requests=len(f['requests']))
    months,sources=materialize(f)
    validation=aggregate_audit(months)
    mismatches=sum(x['mismatch_count'] for x in validation)
    by_symbol={}
    for symbol in ('USDJPY','GBPJPY'):
        by_symbol[symbol]={}
        for tf in TF_SECONDS:
            subset=[r for r in months if r['symbol']==symbol and r['timeframe']==tf]
            by_symbol[symbol][tf]=dict(rows=sum(x['technical']['rows'] for x in subset),
                first_open_utc=next((x['technical']['first_open_utc'] for x in subset if x['technical']['rows']),None),
                last_close_utc=next((x['technical']['last_close_utc'] for x in reversed(subset) if x['technical']['rows']),None),
                zero_row_months=[x['key'] for x in subset if not x['technical']['rows']],
                missing_weekdays=sum(len(x['technical']['missing_weekdays']) for x in subset),
                incomplete_bars_excluded=sum(x['incomplete_bars_excluded'] for x in subset))
    status='PASS_PRICE_SERIALIZATION_WITH_REPORTED_GAPS' if not mismatches else 'PARTIAL_NATIVE_M15_M1_DISAGREEMENTS_REVIEW_REQUIRED'
    summary=dict(status=status,as_of_utc=iso(f['utc_cutoff']),current_month_partial=True,
        research_start='2023-01-01',warmup_start='2022-12-01',by_symbol=by_symbol,
        downloaded_requests=len(f['requests']),reused_sources=len(f['existing']),
        native_m15_m1_mismatches=mismatches,calendar=calendar_inventory(),
        backtest_ready=False,backtests_run=False,paid_calls=False,orders_sent=False)
    for name,value in [('source_registry.json',sources),('native_aggregation_audit.json',validation),('summary.json',summary)]:
        p=OUT/name
        if p.exists():
            if read(p)!=value:raise RuntimeError('Existing unsealed result differs '+name)
        else:save(p,value)
    verify(f['implementation']);verify(f['source_metadata'])
    for s in sources:verify(s['records'])
    files=[OUT/'freeze.json',OUT/'source_registry.json',OUT/'native_aggregation_audit.json',OUT/'summary.json',OUT/'symbol_metadata.json']
    files+=sorted((OUT/'requests').glob('*.json'))+sorted((OUT/'months').glob('*.json'))
    files+=[ROOT/r['payload']['path'] for r in months]
    save(OUT/'completion_seal.json',dict(status=status,files=[rec(p) for p in files]))
    log('COMPLETE',status=status,by_symbol=by_symbol,native_m15_m1_mismatches=mismatches)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['freeze','run'])
    args=parser.parse_args()
    try:
        freeze() if args.command=='freeze' else run()
    except Exception as exc:
        if OUT.exists():log('FAILED',error=repr(exc))
        raise
