"""Exposed fixed-ledger diagnostics, NOT a new strategy or management backtest."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math

import numpy as np
import pandas as pd

import acquire_rick_jpy_history_v1 as h
import audit_rick_heavy_loss_months_v1 as old

ROOT = h.ROOT
OUT = ROOT / 'research_artifacts/rick_reentry_management_audit_v1'
THRESHOLDS = (1, 2)
REENTRY_FIELDS = ('prior_result', 'signal_after_last_sl', 'formation_after_last_sl',
    'final_rebound_after_last_sl', 'failed_level_reclaimed', 'w_floor_change',
    'same_failed_parent', 'parent_known_after_last_sl')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def complete_m5(m1, reference=False):
    """UTC five-minute grid; absent minutes never filled. Full five rows required."""
    t = m1['time']; bucket = t // 300 * 300
    if reference:
        frame = pd.DataFrame({k: v for k, v in m1.items() if k != 'known'})
        frame['bucket'] = bucket
        groups = frame.groupby('bucket', sort=True)
        counts = groups.size(); first = groups['time'].first(); last = groups['time'].last()
        valid = (counts == 5) & (first == counts.index) & (last == counts.index + 240)
        out = {'time': counts.index.to_numpy()[valid], 'open': groups['open'].first().to_numpy()[valid],
            'high': groups['high'].max().to_numpy()[valid], 'low': groups['low'].min().to_numpy()[valid],
            'close': groups['close'].last().to_numpy()[valid]}
    else:
        starts = np.r_[0, np.flatnonzero(np.diff(bucket)) + 1]; ends = np.r_[starts[1:], len(t)]
        good = (ends-starts == 5) & (t[starts] == bucket[starts]) & (t[ends-1] == bucket[starts]+240)
        out = {'time': bucket[starts][good], 'open': m1['open'][starts][good],
            'high': np.maximum.reduceat(m1['high'], starts)[good],
            'low': np.minimum.reduceat(m1['low'], starts)[good], 'close': m1['close'][ends-1][good]}
    out = {k: np.asarray(v, dtype=np.int64) for k, v in out.items()}
    out['known'] = out['time'] + 300
    return out


def swing_lows(m5, reference=False):
    """Diagnostic only: strict 2-left/2-right wick low, known after right2 close."""
    lo = m5['low']; t = m5['time']
    if reference:
        indices = [i for i in range(2, len(t)-2)
            if all(t[j+1]-t[j] == 300 for j in range(i-2, i+2))
            and all(lo[i] < lo[j] for j in (i-2, i-1, i+1, i+2))]
    else:
        mid = lo[2:-2]
        good = ((mid < lo[:-4]) & (mid < lo[1:-3]) & (mid < lo[3:-1]) & (mid < lo[4:])
            & (t[4:]-t[:-4] == 1200))
        indices = np.flatnonzero(good) + 2
    ix = np.asarray(indices, dtype=int)
    return {'time': t[ix], 'known': m5['known'][ix+2], 'low': lo[ix]}


def reentry(t, event, history, events, m5, reference=False):
    # An exit stamped in this fill minute is NOT known before this fill.
    if reference:
        eligible = []
        for p in history:
            if old.day(p['entry_time']) == old.day(t['entry_time']) and p['exit_time'] < t['entry_time']:
                eligible.append(p)
        eligible.sort(key=lambda p: (p['exit_time'], p['id']))
    else:
        eligible = sorted((p for p in history if p['exit_time'] < t['entry_time']
            and old.day(p['entry_time']) == old.day(t['entry_time'])), key=lambda p: (p['exit_time'], p['id']))
    prior = eligible[-1] if eligible else None
    stopped = [p for p in eligible if p['outcome'] == 'SL']
    result = dict(prior_result='NONE' if prior is None else ('PROFIT' if prior['net_r'] > 0 else prior['outcome']),
        prior_resolved_id=prior['id'] if prior else None, prior_sl_count=len(stopped), last_sl_id=None)
    result.update({k: None for k in REENTRY_FIELDS if k != 'prior_result'})
    result.update(previous_failed_level=None, last_m5_known=None, failed_level_close=None)
    if not stopped:
        return result
    previous = stopped[-1]; pe = events[previous['id']]; at = previous['exit_time']
    w = event['evidence'].get('w'); pw = pe['evidence'].get('w')
    zone = event['evidence'].get('zone') or event['evidence'].get('box')
    pz = pe['evidence'].get('zone') or pe['evidence'].get('box')
    # Failed W neckline, or failed governing range's high: both known before prior entry.
    failed = pw['entry_points'] if pw else pz['high'] if pz else None
    if reference:
        end = int(np.searchsorted(m5['known'], t['entry_time'], side='right'))
        j = max((i for i in range(max(0, end-2), end) if m5['known'][i] <= t['entry_time']), default=-1)
    else:
        j = int(np.searchsorted(m5['known'], t['entry_time'], side='right')) - 1
    # Stale or pre-loss close gives UNKNOWN, not an automatic negative classification.
    usable = j >= 0 and at < m5['known'][j] <= t['entry_time'] and t['entry_time']-m5['known'][j] < 300
    result.update(last_sl_id=previous['id'], signal_after_last_sl=event['time'] > at,
        formation_after_last_sl=event['origin'] >= at,
        final_rebound_after_last_sl=w['leg_starts'][3] >= at if w else None,
        failed_level_reclaimed=bool(m5['close'][j] > failed) if usable and failed is not None else None,
        previous_failed_level=failed, last_m5_known=int(m5['known'][j]) if usable else None,
        failed_level_close=int(m5['close'][j]) if usable else None,
        w_floor_change=('HIGHER' if w['second_low_points'] > pw['second_low_points'] else
            'LOWER' if w['second_low_points'] < pw['second_low_points'] else 'SAME') if w and pw else None,
        same_failed_parent=zone['id'] == pz['id'] if zone and pz else None,
        parent_known_after_last_sl=zone['known'] > at if zone else None)
    return result


def management(t, m1, m5, pivots, reference=False):
    at = t['entry_time']; end = t['exit_time']; entry = t['entry']; risk = t['planned_risk_points']
    # Strict pre-exit chronology. Entry and exit M1 candles excluded from excursion.
    left = int(np.searchsorted(m1['time'], at, side='right'))
    right = int(np.searchsorted(m1['known'], end, side='right'))
    start5 = int(np.searchsorted(m5['known'], at, side='right'))
    end5 = int(np.searchsorted(m5['known'], end, side='left'))
    values = [int(m1['high'][i]) for i in range(left, right)] if reference else m1['high'][left:right]
    best = max(values) if len(values) else None
    answer = dict(conservative_mfe_r=old.rounded((best-entry)/risk) if best is not None else None,
        thresholds={})
    for multiple in THRESHOLDS:
        level = entry + multiple*risk
        if reference:
            hits = [i for i in range(start5, end5) if m5['close'][i] >= level]
            touch = any(v >= level for v in values)
        else:
            hits = np.flatnonzero(m5['close'][start5:end5] >= level) + start5
            touch = bool(np.any(values >= level))
        item = dict(m1_touch=touch, m5_close=bool(len(hits)), trigger_time=None,
            return_to_entry_after_close=None, return_to_entry_time=None,
            protected_low=None, protected_low_known=None, protected_low_below_entry=None,
            structure_warning_time=None, structure_warning_r=None)
        if len(hits):
            ix = int(hits[0]); activation = int(m5['known'][ix]); item['trigger_time'] = activation
            # Threshold M5 complete; next observed M1 can now show a retracement.
            a = int(np.searchsorted(m1['time'], activation, side='left'))
            b = int(np.searchsorted(m1['time'], end, side='right'))
            if reference:
                returns = [i for i in range(a, b) if m1['low'][i] <= entry]
            else:
                returns = np.flatnonzero(m1['low'][a:b] <= entry) + a
            # A TP-minute also below entry is unknown ordering; mark AMBIGUOUS.
            if len(returns):
                ri = int(returns[0]); rt = int(m1['time'][ri])
                ambiguous = rt == end and t['outcome'] in ('TP', 'TIME_EXIT')
                item['return_to_entry_after_close'] = 'AMBIGUOUS_EXIT_MINUTE' if ambiguous else 'YES'
                item['return_to_entry_time'] = rt
            else:
                item['return_to_entry_after_close'] = 'NO'
            pi = int(np.searchsorted(pivots['known'], activation, side='right'))-1
            if pi >= 0:
                floor = int(pivots['low'][pi]); known = int(pivots['known'][pi])
                item.update(protected_low=floor, protected_low_known=known, protected_low_below_entry=floor < entry)
                # Freeze the last known pivot at the threshold, not a future-selected pivot.
                if reference:
                    warnings = [j for j in range(ix+1, end5) if m5['close'][j] < floor]
                else:
                    warnings = np.flatnonzero(m5['close'][ix+1:end5] < floor) + ix+1
                if len(warnings):
                    wi = int(warnings[0])
                    item.update(structure_warning_time=int(m5['known'][wi]),
                        structure_warning_r=old.rounded((int(m5['close'][wi])-entry)/risk))
        answer['thresholds'][str(multiple)] = item
    return answer


def stats(rows):
    vals = [r['net_r'] for r in rows]
    return dict(n=len(rows), net_r=old.rounded(math.fsum(vals)),
        win_pct=old.rounded(100*sum(v > 0 for v in vals)/len(vals)) if vals else None,
        mean_r=old.rounded(math.fsum(vals)/len(vals)) if vals else None,
        outcomes=dict(Counter(r['outcome'] for r in rows)),
        entry_days=len(set(r['entry_day'] for r in rows)))


def management_stats(rows):
    result = stats(rows); result['thresholds'] = {}
    for key in map(str, THRESHOLDS):
        seen = [r for r in rows if r['management']['thresholds'][key]['m5_close']]
        warned = [r for r in seen if r['management']['thresholds'][key]['structure_warning_time'] is not None]
        result['thresholds'][key] = dict(
            m1_touch=sum(r['management']['thresholds'][key]['m1_touch'] for r in rows),
            m5_close=len(seen), returns=dict(Counter(r['management']['thresholds'][key]['return_to_entry_after_close'] for r in seen)),
            structure_warning=stats(warned),
            warning_while_bid_still_profitable=stats([r for r in warned if r['management']['thresholds'][key]['structure_warning_r'] > 0]),
            no_known_pivot=sum(r['management']['thresholds'][key]['protected_low'] is None for r in seen))
    return result


def summarize(rows):
    groups = {'ALL': rows, 'HEAVY_LOSS': [r for r in rows if r['month_group'] == 'HEAVY_LOSS'],
        'PROFIT': [r for r in rows if r['month_group'] == 'PROFIT'],
        'OTHER': [r for r in rows if r['month_group'] not in ('HEAVY_LOSS', 'PROFIT')]}
    result = {}
    for group, rr in groups.items():
        result[group] = dict(total=stats(rr), reentry={}, management={})
        for field in REENTRY_FIELDS:
            values = sorted({str(r['reentry'][field]) for r in rr})
            result[group]['reentry'][field] = {v: stats([r for r in rr if str(r['reentry'][field]) == v]) for v in values}
        for status, subset in {'SL': [r for r in rr if r['outcome'] == 'SL'],
            'TP': [r for r in rr if r['outcome'] == 'TP'],
            'BE': [r for r in rr if r['outcome'] == 'BE'],
            'TIME_EXIT': [r for r in rr if r['outcome'] == 'TIME_EXIT'],
            'NET_POSITIVE': [r for r in rr if r['net_r'] > 0],
            'NET_NONPOSITIVE': [r for r in rr if r['net_r'] <= 0]}.items():
            result[group]['management'][status] = management_stats(subset)
    result['months'] = {}
    for month in sorted({r['exit_month'] for r in rows}):
        rr = [r for r in rows if r['exit_month'] == month]
        result['months'][month] = dict(group=rr[0]['month_group'], total=stats(rr),
            after_sl=stats([r for r in rr if r['reentry']['prior_sl_count'] > 0]),
            fresh_formation=stats([r for r in rr if r['reentry']['formation_after_last_sl'] is True]),
            older_formation=stats([r for r in rr if r['reentry']['formation_after_last_sl'] is False]),
            management_sl=management_stats([r for r in rr if r['outcome'] == 'SL']))
    return result


def write_report(summary):
    lines = ['# Rick re-entry and management diagnostic', '',
        'All 44 complete months per pair, January 2023-August 2026. September partial excluded.',
        'Existing actual fills and outcomes only; original strategies, trade schedules and risk unchanged.',
        'All analysis is descriptive and post-hoc. Subgroup R is original booked R, NOT a filtered or managed backtest.',
        'A failed attempt means an actual SL already resolved before the later fill on the same EAT entry day.',
        'Formation freshness uses the existing detector origin, not a redesigned pattern. Reclaim uses the last completed M5 close versus the prior failed neckline/range high.',
        'M1 excursions exclude entry/exit candles. M5 thresholds require a completed close strictly before the actual exit; incomplete M5 buckets are unavailable.',
        'Entry retracement is measured only AFTER that completed close. Ambiguous exit-minute order is reported separately.',
        'Diagnostic control-loss warning: after the threshold, a completed M5 close below the latest 2-left/2-right confirmed wick low known at the threshold. No trailing, fill, or stop change is simulated.',
        'Zero-R price is not net break-even: costs remain. Swap omitted in the original batch. No recovered R is claimed.', '',]
    for pair, s in summary.items():
        lines += ['## '+pair, '', '### Re-entry comparisons', '',
            '| Group | Observation | State | Trades | Original net R | Win % |', '|---|---|---|---:|---:|---:|']
        for group in ('ALL', 'HEAVY_LOSS', 'PROFIT'):
            for field, split in s[group]['reentry'].items():
                for state, v in split.items():
                    lines.append(f"| {group} | {field} | {state} | {v['n']} | {v['net_r']} | {v['win_pct']} |")
        lines += ['', '### Profit-retention evidence', '',
            '| Group | Original outcome | N | Level | M1 touch | M5 close | Later entry returns | Structure warnings | Warnings above entry |',
            '|---|---|---:|---:|---:|---:|---|---:|---:|']
        for group in ('ALL', 'HEAVY_LOSS', 'PROFIT'):
            for outcome, v in s[group]['management'].items():
                for level, z in v['thresholds'].items():
                    lines.append(f"| {group} | {outcome} | {v['n']} | {level}R | {z['m1_touch']} | {z['m5_close']} | {z['returns']} | {z['structure_warning']['n']} | {z['warning_while_bid_still_profitable']['n']} |")
        lines += ['', '### Each heavy-loss month', '',
            '| Month | R | Trades after prior SL (R) | Fresh formation after SL (R) | Older formation (R) | SL M5-close +1R / +2R |',
            '|---|---:|---|---|---|---|']
        for mon, m in s['months'].items():
            if m['group'] != 'HEAVY_LOSS': continue
            a=m['after_sl']; f=m['fresh_formation']; o=m['older_formation']; z=m['management_sl']['thresholds']
            lines.append(f"| {mon} | {m['total']['net_r']} | {a['n']} ({a['net_r']}) | {f['n']} ({f['net_r']}) | {o['n']} ({o['net_r']}) | {z['1']['m5_close']} / {z['2']['m5_close']} |")
    lines += ['', '## Reproduction and limits', '',
        'Independent NumPy/Pandas M5 aggregations; independent vector/loop pivot and path calculations; independent selection implementations for prior losses. All agree exactly.',
        'Input reading and reporting share code. This is not two independent backtest engines. No optimized thresholds, p-values, causal proof, or out-of-sample credit.',
        'Same-day resolved-loss analysis does not include losses still open at a new fill, nor carry a prior-day loss forward. Overlapping GJ observations are correlated.',
        'A close-based warning is observable at candle completion, but its close price is not guaranteed executable. Warnings and retracements are diagnostics, not executions.', '']
    with (OUT/'REPORT.md').open('x', encoding='utf8') as f: f.write('\n'.join(lines))


def main():
    OUT.mkdir(exist_ok=True)
    if (OUT/'protocol.json').exists():
        raise RuntimeError('Preserve existing attempt; do not overwrite')
    seals = [old.BATCH/'completion_seal.json', old.OUT/'completion_seal.json', h.OUT/'completion_seal.json']
    seals += sorted(old.BATCH.glob('*_20??-??/seal.json'))
    print('VERIFY predecessor and normalized source hashes', flush=True)
    for p in seals: h.verify(h.read(p)['files'])
    source_records = [h.read(p)['payload'] for p in sorted((h.OUT/'months').glob('*_M1_*.json'))]
    h.verify(source_records)
    code = [h.rec(Path(__file__).resolve()), h.rec(ROOT/'tests/test_rick_reentry_management_v1.py'),
        h.rec(ROOT/'tools/audit_rick_heavy_loss_months_v1.py'), h.rec(ROOT/'tools/acquire_rick_jpy_history_v1.py')]
    protocol = dict(purpose='FIXED_LEDGER_EXPOSED_DIAGNOSTIC_ONLY', created_at=datetime.now(timezone.utc).isoformat(),
        full_months='2023-01 through 2026-08', direction='LONG_ONLY_UNCHANGED_BOTH_PAIRS',
        reentry_fields=REENTRY_FIELDS, thresholds_r=THRESHOLDS,
        chronological_rules='same EAT entry day; prior exit strictly before fill; only completed full M5; last close age <300s and after prior stop',
        formation_freshness='existing event origin >= previous SL; W final rebound leg start >= previous SL separately',
        failed_level='prior W entry_points (neckline) or prior box high; last completed M5 close strictly above',
        management='M1 touch excluding fill/exit M1; completed M5 close >=1R/2R strictly before original exit; subsequent entry return with ambiguous exit minute separate',
        structure='strict M5 wick low2-left2-right in five consecutive full buckets; freeze latest confirmed low at threshold; later completed M5 close below it',
        exclusions=['partial September', 'new data', 'rule changes', 'counterfactual PnL', 'optimization', 'new backtest'],
        implementation=code, predecessors=[h.rec(p) for p in seals], source_payloads=source_records)
    h.save(OUT/'protocol.json', protocol)
    h.save(OUT/'protocol_seal.json', dict(files=[h.rec(OUT/'protocol.json')]+code))
    diagnostics = {(r['symbol'], r['id']): r for r in h.read(old.OUT/'trade_diagnostics.json')}
    allrows=[]; summary={}; reproduction={}
    for symbol in ('USDJPY', 'GBPJPY'):
        print('ANALYZE '+symbol, flush=True)
        m1=old.prices(symbol, 'M1')
        if not np.all(m1['known'] == m1['time']+60): raise RuntimeError('Timestamp availability changed')
        m5=complete_m5(m1); m5r=complete_m5(m1, True)
        if not all(np.array_equal(m5[k], m5r[k]) for k in m5): raise RuntimeError('M5 reproduction')
        piv=swing_lows(m5); pivr=swing_lows(m5r, True)
        if not all(np.array_equal(piv[k], pivr[k]) for k in piv): raise RuntimeError('Pivot reproduction')
        trades=[]; events={}
        for p in sorted(old.BATCH.glob(symbol+'_20??-??/primary.json')):
            result=h.read(p); trades.extend(result['trades']); events.update({x['id']: x for x in result['events']})
        trades.sort(key=lambda t: (t['entry_time'], t['signal_time'], t['id']))
        history=[]; rows=[]; refrows=[]
        for t in trades:
            base=diagnostics[(symbol, t['id'])]
            if base['partial']: continue
            e=events[t['id']]
            if e['time']>t['entry_time']: raise RuntimeError('Future signal')
            row={k:base[k] for k in ('symbol','id','entry_time','exit_time','entry_day','exit_month','month_group','route','mode','net_r','outcome')}
            row['reentry']=reentry(t,e,history,events,m5)
            row['management']=management(t,m1,m5,piv)
            reference=dict(row, reentry=reentry(t,e,history,events,m5r,True), management=management(t,m1,m5r,pivr,True))
            if row != reference: raise RuntimeError('Row reproduction '+t['id'])
            for key in map(str,THRESHOLDS):
                if row['management']['thresholds'][key]['m1_touch'] != base['plus'+key+'_before_exit']:
                    raise RuntimeError('Prior path count mismatch '+t['id'])
            rows.append(row); refrows.append(reference); history.append(t)
        summary[symbol]=summarize(rows); allrows+=rows
        reproduction[symbol]=dict(trades=len(rows), m5_complete_buckets=len(m5['time']), confirmed_lows=len(piv['time']),
            primary_hash=digest(rows), reference_hash=digest(refrows))
        print(symbol+' complete '+str(len(rows))+' trades', flush=True)
    h.save(OUT/'trade_diagnostics.json', allrows); h.save(OUT/'summary.json', summary)
    h.save(OUT/'reproduction.json', reproduction); write_report(summary)
    h.verify(code); h.verify(source_records)
    for p in seals: h.verify(h.read(p)['files'])
    names=('protocol.json','protocol_seal.json','trade_diagnostics.json','summary.json','reproduction.json','REPORT.md')
    h.save(OUT/'completion_seal.json',dict(status='PASS_FIXED_LEDGER_DIAGNOSTIC_REPRODUCTION', strategy_changed=False,
        files=[h.rec(OUT/n) for n in names], independent_checks=reproduction))
    print('COMPLETE '+str(OUT), flush=True)


if __name__=='__main__': main()
