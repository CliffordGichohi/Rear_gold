"""Exposed market-state attribution on unchanged trades. No trading-policy simulation."""
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timezone
from itertools import groupby
from pathlib import Path
import math
import unittest

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

import acquire_rick_jpy_history_v1 as h
import audit_rick_reentry_management_v1 as management
import audit_rick_preentry_response_quality_v1 as quality

ROOT = h.ROOT
OUT = ROOT / 'research_artifacts/rick_preentry_streak_state_v1'
REGIME = ROOT / 'research_artifacts/rick_shared_jpy_regime_audit_v1'
ZONE = ROOT / 'research_artifacts/rick_zone_response_audit_v1'
DD = ROOT / 'research_artifacts/rick_drawdown_episode_audit_v1'
ROUTES = (('USDJPY', 'W'), ('GBPJPY', 'DEMAND_W'), ('GBPJPY', 'RESPONSE_MARKET'))
FIELDS = {
    'weaker_rallies': 'Latest two completed M5 close-to-close up legs: newer amplitude AND ending close strictly lower.',
    'stronger_selloffs': 'Latest two completed M5 down legs: newer amplitude strictly larger AND ending close strictly lower.',
    'm15_bearish_structure': 'Last two confirmed M15 wick highs AND last two confirmed wick lows both lower.',
    'near_unbroken_high': 'An already confirmed M15 high at/above entry within one original stop distance, without an intervening M15 close above it.',
    'stop_smaller_than_m15_atr': 'Original fixed stop strictly smaller than 20-bar M15 arithmetic ATR available at entry.',
    'deteriorating_auction': 'weaker_rallies AND stronger_selloffs; both inputs must be known.',
    'bearish_h1_and_m15': 'Existing sealed H1 structure is BEARISH AND m15_bearish_structure; both must be known.',
}


def completed_legs(closes, reference=False):
    """Exclude truncated first and unfinished last run. Flats extend, never confirm."""
    c = [int(v) for v in closes]
    if reference:
        runs = []; active = None
        for i in range(1, len(c)):
            direction = (c[i] > c[i-1]) - (c[i] < c[i-1])
            if not direction:
                continue
            if active is None or active['direction'] != direction:
                if active is not None:
                    active['confirmed_index'] = i
                    runs.append(active)
                active = dict(direction=direction, start=i-1, end=i, confirmed_index=None)
            else:
                active['end'] = i
        if active is not None:
            runs.append(active)
    else:
        delta = np.diff(np.asarray(c, dtype=np.int64)); nz = np.flatnonzero(delta)
        if not len(nz):
            return []
        signs = np.sign(delta[nz]); starts = np.r_[0, np.flatnonzero(np.diff(signs)) + 1]
        ends = np.r_[starts[1:], len(nz)]
        runs = [dict(direction=int(signs[a]), start=int(nz[a]), end=int(nz[b-1])+1,
                     confirmed_index=int(nz[b])+1 if b < len(nz) else None)
                for a, b in zip(starts, ends)]
    return [dict(r, amplitude=abs(c[r['end']]-c[r['start']]), end_close=c[r['end']])
            for r in runs[1:-1]]


def pivots(window, reference=False):
    t = window['time']; result = {'HIGH': [], 'LOW': []}
    for name, column, sign in (('HIGH', 'high', 1), ('LOW', 'low', -1)):
        v = window[column]
        if reference:
            ix = [i for i in range(2, len(t)-2)
                  if all(int(t[j+1])-int(t[j]) == 900 for j in range(i-2, i+2))
                  and all(sign*int(v[i]) > sign*int(v[j]) for j in (i-2, i-1, i+1, i+2))]
        elif len(t) >= 5:
            mid = sign*v[2:-2]
            mask = ((mid > sign*v[:-4]) & (mid > sign*v[1:-3]) &
                    (mid > sign*v[3:-1]) & (mid > sign*v[4:]) & (t[4:]-t[:-4] == 3600))
            ix = (np.flatnonzero(mask)+2).tolist()
        else:
            ix = []
        result[name] = [dict(index=i, time=int(t[i]), known=int(window['known'][i+2]), price=int(v[i])) for i in ix]
    return result


def state_at(at, entry, risk, m5, m15, reference=False):
    """Outcome-free interface. Every slice ends at the actual decision timestamp."""
    right = (lambda arr, value: bisect_right(arr, value)) if reference else (
        lambda arr, value: int(np.searchsorted(arr, value, side='right')))
    result = {k: None for k in list(FIELDS)[:5]}
    evidence = dict(decision_time=at, m5_status='UNAVAILABLE', m15_status='UNAVAILABLE')
    j = right(m5['known'], at)
    if j >= 36 and 0 <= at-int(m5['known'][j-1]) < 300:
        w = {k: v[j-36:j] for k, v in m5.items()}
        if int(w['time'][-1])-int(w['time'][0]) == 35*300:
            legs = completed_legs(w['close'], reference)
            evidence.update(m5_status='AVAILABLE', m5_start=int(w['time'][0]), m5_known=int(w['known'][-1]), legs=legs)
            for direction, field in ((1, 'weaker_rallies'), (-1, 'stronger_selloffs')):
                two = [r for r in legs if r['direction'] == direction][-2:]
                if len(two) == 2:
                    a, b = two
                    amplitude_condition = b['amplitude'] < a['amplitude'] if direction == 1 else b['amplitude'] > a['amplitude']
                    result[field] = bool(amplitude_condition and b['end_close'] < a['end_close'])
    j = right(m15['known'], at)
    if j and 0 <= at-int(m15['known'][j-1]) < 900:
        left = int(np.searchsorted(m15['time'], at-86400, side='left')) if not reference else bisect_right(m15['time'], at-86400-1)
        w = {k: v[left:j] for k, v in m15.items()}
        ps = pivots(w, reference)
        evidence.update(m15_status='AVAILABLE', m15_known=int(m15['known'][j-1]),
                        high_pivots=ps['HIGH'], low_pivots=ps['LOW'])
        if len(ps['HIGH']) >= 2 and len(ps['LOW']) >= 2:
            result['m15_bearish_structure'] = all(ps[k][-1]['price'] < ps[k][-2]['price'] for k in ('HIGH', 'LOW'))
        unbroken = []
        for p in ps['HIGH']:
            # Closes after the pivot, including confirmation bars, already known now.
            later = w['close'][p['index']+1:]
            broken = any(int(v) > p['price'] for v in later) if reference else bool(np.any(later > p['price']))
            if not broken and p['price'] >= entry:
                unbroken.append(p)
        # No confirmed high in the window is missing location support, not clear space.
        if ps['HIGH']:
            distance = min((p['price']-entry for p in unbroken), default=None)
            result['near_unbroken_high'] = distance is not None and distance <= risk
            evidence['nearest_unbroken_high_distance_points'] = distance
        if j >= 21 and int(m15['time'][j-1])-int(m15['time'][j-21]) == 20*900:
            if reference:
                total = sum(max(int(m15['high'][i]-m15['low'][i]), abs(int(m15['high'][i]-m15['close'][i-1])),
                                abs(int(m15['low'][i]-m15['close'][i-1]))) for i in range(j-20, j))
            else:
                hi=m15['high'][j-20:j]; lo=m15['low'][j-20:j]; prev=m15['close'][j-21:j-1]
                total=int(np.maximum.reduce([hi-lo, np.abs(hi-prev), np.abs(lo-prev)]).sum())
            result['stop_smaller_than_m15_atr'] = risk*20 < total
            evidence['atr20_sum_points'] = total
    for p in evidence.get('high_pivots', []) + evidence.get('low_pivots', []):
        assert p['known'] <= at
    return dict(result, evidence=evidence)


def conjunction(a, b):
    return a and b if a is not None and b is not None else None


def streaks(rows, reference=False):
    """Retrospective labels, NOT decision features. Same-minute exits indivisible."""
    records = []
    for symbol in ('USDJPY', 'GBPJPY'):
        selected = sorted((r for r in rows if r['symbol'] == symbol), key=lambda r: (r['exit_time'], r['id']))
        if reference:
            by_time = {}
            for r in selected: by_time.setdefault(r['exit_time'], []).append(r)
            groups = sorted(by_time.items())
        else:
            groups = [(k, list(v)) for k, v in groupby(selected, key=lambda r: r['exit_time'])]
        run = []
        for at, group in groups + [(None, [])]:
            if group and all(r['outcome'] == 'SL' for r in group):
                run.extend(group)
                continue
            if len(run) >= 3:
                first = min(r['exit_time'] for r in run); last = max(r['exit_time'] for r in run)
                recovery = sorted((r for r in selected if r['entry_time'] > last and r['net_r'] > 0),
                                  key=lambda r: (r['entry_time'], r['id']))
                records.append(dict(symbol=symbol, first_sl_exit=first, last_sl_exit=last,
                    ids=[r['id'] for r in run], count=len(run), original_net_r=round(math.fsum(r['net_r'] for r in run), 6),
                    initial_ids=[r['id'] for r in run if r['exit_time'] == first],
                    entered_before_first_sl=sum(r['entry_time'] <= first for r in run),
                    entered_after_two_known_sl=sum(sum(p['exit_time'] < r['entry_time'] for p in run) >= 2 for r in run),
                    recovery_id=recovery[0]['id'] if recovery else None))
            run = []
    return records


def prevalence(rows):
    return dict(n=len(rows), original_net_r=round(math.fsum(r['net_r'] for r in rows), 6),
        warnings={f:dict(yes=sum(r[f] is True for r in rows), no=sum(r[f] is False for r in rows),
                        unknown=sum(r[f] is None for r in rows)) for f in FIELDS})


def attribution(rows, runs, episodes):
    output = {}
    for symbol, route in ROUTES:
        q = [r for r in rows if (r['symbol'], r['route']) == (symbol, route)]
        rs = [s for s in runs if s['symbol'] == symbol]
        members = {i for s in rs for i in s['ids']}; initial = {i for s in rs for i in s['initial_ids']}
        recoveries = {s['recovery_id'] for s in rs}
        result = dict(all_trades=prevalence(q), streak_members=prevalence([r for r in q if r['id'] in members]),
            initial_streak_losses=prevalence([r for r in q if r['id'] in initial]),
            other_full_stops=prevalence([r for r in q if r['outcome']=='SL' and r['id'] not in members]),
            all_profitable_controls=prevalence([r for r in q if r['net_r']>0]),
            recovery_profitable_controls=prevalence([r for r in q if r['id'] in recoveries]), episodes=[])
        for e in episodes:
            result['episodes'].append(dict(peak=e['peak_time'], trough=e['trough_time'], recovery=e['recovery_time'],
                decline_entries=prevalence([r for r in q if e['peak_time'] < r['entry_time'] <= e['trough_time']]),
                recovery_entries=prevalence([r for r in q if e['recovery_time'] is not None and e['trough_time'] < r['entry_time'] <= e['recovery_time']])))
        output[symbol+'/'+route] = result
    return output


def load(paths):
    columns=['open_epoch_utc','historical_available_at_epoch_utc','open','high','low','close']
    t=pa.concat_tables([pq.read_table(p,columns=columns) for p in paths])
    data={k:t[k].to_numpy() for k in columns}
    data['time']=data.pop('open_epoch_utc');data['known']=data.pop('historical_available_at_epoch_utc')
    for k in ('open','high','low','close'):data[k]=np.rint(data[k]*1000).astype(np.int64)
    assert np.all(np.diff(data['time'])>0) and np.all(np.diff(data['known'])>0)
    return data


def main():
    OUT.mkdir(exist_ok=True)
    if (OUT/'completion_seal.json').exists():
        h.verify(h.read(OUT/'completion_seal.json')['files']);print('ALREADY_COMPLETE');return
    if (OUT/'protocol.json').exists():raise RuntimeError('Preserve incomplete attempt')
    test=unittest.TextTestRunner().run(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_rick_preentry_streak_state_v1.py'))
    if not test.wasSuccessful():raise RuntimeError('Synthetic proof failed')
    for directory in (REGIME, ZONE, DD, quality.OUT):
        h.verify(h.read(directory/'completion_seal.json')['files'])
    paths={}; sources=[]
    for pair in ('USDJPY','GBPJPY'):
        for tf in ('M1','M15'):
            key=pair+'_'+tf
            paths[key]=[p for p in sorted((h.OUT/'normalized').glob(key+'_*.parquet')) if '2022-12'<=p.stem[-7:]<='2026-08']
            assert len(paths[key])==45,(key,len(paths[key]))
            for p in paths[key]:
                meta=h.read(h.OUT/'months'/f'{p.stem}.json');record=meta['payload']
                assert record['path']==h.rec(p)['path'];h.verify([record]);sources.append(record)
    predecessor_files=[h.rec(d/n) for d,n in ((REGIME,'entry_contexts.json'),(ZONE,'primary.json'),
        (ZONE,'reference.json'),(DD,'episode_details.json'),(quality.OUT,'primary.json'))]
    implementation=[h.rec(Path(__file__).resolve()),h.rec(ROOT/'tests/test_rick_preentry_streak_state_v1.py'),
        h.rec(ROOT/'tools/audit_rick_preentry_response_quality_v1.py'),h.rec(ROOT/'tools/audit_rick_reentry_management_v1.py')]
    protocol=dict(created_utc=datetime.now(timezone.utc).isoformat(),purpose='EXPOSED_MARKET_STATE_STREAK_ATTRIBUTION_ONLY',
        population='1512 unchanged UJ/GJ original closed trades Jan2023-Aug2026. Same selectors, long-only support, entries, exits, costs, risk and management. No fitting or simulated avoidance.',
        exposure='Previously exposed historical diagnostics, not independent validation; no claim that any condition causes losses.',
        fields=FIELDS,m5='36 contiguous completed UTC M5 bars, latest less than 300s old. Runs of signed nonzero close changes; flats do not confirm. Discard first window-truncated and last unfinished runs. Need two completed legs per sign.',
        m15='Trailing 24 clock hours, latest completed bar less than 900s old. Strict wick pivots two-left/two-right, all five bars contiguous. Known at right2 close. Need two highs/two lows for structure; at least one high for overhead test. ATR uses last21 contiguous bars, prior close true ranges, simple mean20.',
        point_in_time='All candles historical_available_at <= original entry; future fields never provided to feature function. Certified M1 must have known=time+60 before M5 aggregation.',
        missing='Unknown retained, no imputation. Conjunction unknown if either input unknown. No confirmed high is UNKNOWN, not free space.',
        sequences='Per pair maximal runs of >=3 full SL exits, across days; all exits at same timestamp grouped. Any mixed or non-SL group terminates run, including BE. Descriptive eventual sequence labels never predictors. Recovery control is first net-profitable trade ENTERED after last run exit, possibly shared by runs; deduplicate in cohorts.',
        comparisons='Seven frozen checks separately UJ W, GJ DEMAND_W, GJ RESPONSE_MARKET. All years/months/streak/control cohorts retained; no threshold search.',
        uncertainty='Existing 2000-entry-month cluster bootstrap, seed20260918; difference percentile95 interval and approximate two-sided sign-tail, Holm across all 21 checks. Descriptive not confirmatory; extensive prior testing not included in Holm.',
        warning='20 per state overall AND5 per state per2023/24/25/26, worse all4years, difference interval entirely negative, Holm sign-tail<0.05. No filter applied even if passes.',
        frozen_dd_intervals='Five previously sealed largest peak/trough/recovery episodes; phase labels retrospective only.',
        reproduction='Independent scalar/vector feature, pivot, leg and sequence calculations; independent scalar/vector bootstrap; exact serialized artifact hashes.',
        sources=sources,predecessor_files=predecessor_files,implementation=implementation)
    h.save(OUT/'protocol.json',protocol);h.save(OUT/'protocol_seal.json',dict(files=[h.rec(OUT/'protocol.json')]+implementation))
    print('PROTOCOL_SEALED',flush=True)
    regimes={(r['symbol'],r['id']):r for r in h.read(REGIME/'entry_contexts.json')}
    original=h.read(ZONE/'primary.json');assert original==h.read(ZONE/'reference.json') and len(original)==1512
    base={(r['symbol'],r['id']):r for r in h.read(quality.OUT/'primary.json')}
    primary=[];reference=[]
    for pair in ('USDJPY','GBPJPY'):
        print('MATERIALIZE '+pair,flush=True)
        m1=load(paths[pair+'_M1']);m15=load(paths[pair+'_M15'])
        assert np.all(m1['known']==m1['time']+60)
        m5=management.complete_m5(m1);m5ref=management.complete_m5(m1,True)
        assert all(np.array_equal(m5[k],m5ref[k]) for k in m5);del m1
        for r in original:
            if r['symbol']!=pair:continue
            reg=regimes[(pair,r['id'])];b=base[(pair,r['id'])]
            assert reg['entry_time']==r['entry_time'] and reg['net_r']==r['net_r']==b['net_r']
            a=state_at(r['entry_time'],r['entry'],r['planned_risk_points'],m5,m15)
            z=state_at(r['entry_time'],r['entry'],r['planned_risk_points'],m5ref,m15,True)
            assert a==z,('features',r['id'])
            for feature,output in ((a,primary),(z,reference)):
                h1=reg['h1_structure'];known_h1=h1 not in ('UNKNOWN','UNAVAILABLE')
                feature['deteriorating_auction']=conjunction(feature['weaker_rallies'],feature['stronger_selloffs'])
                feature['bearish_h1_and_m15']=conjunction(h1=='BEARISH' if known_h1 else None,feature['m15_bearish_structure'])
                output.append(dict(feature,id=r['id'],symbol=pair,route=r['route'],entry_time=r['entry_time'],exit_time=r['exit_time'],
                    entry_day=r['entry_day'],entry_month=r['entry_day'][:7],entry_year=r['entry_day'][:4],net_r=r['net_r'],outcome=r['outcome'],
                    half_r_response=b['half_r_response'],structure_failed_by_horizon=b['structure_failed_by_horizon'],h1_structure=h1))
        del m15,m5,m5ref
    assert primary==reference and len(primary)==1512
    for name,rows in (('primary.json',primary),('reference.json',reference)):h.save(OUT/name,rows)
    assert h.sha(OUT/'primary.json')==h.sha(OUT/'reference.json')
    runs=streaks(primary);ref_runs=streaks(reference,True);assert runs==ref_runs
    episodes=h.read(DD/'episode_details.json')
    att=attribution(primary,runs,episodes);ref_att=attribution(reference,ref_runs,episodes);assert att==ref_att
    results=[];ref_results=[]
    for pair,route in ROUTES:
        print('COMPARE '+pair+' '+route,flush=True)
        q=[r for r in primary if (r['symbol'],r['route'])==(pair,route)]
        for field in FIELDS:
            a=quality.compare(q,field);b=quality.compare(q,field,True)
            assert a==b,('comparison',pair,route,field)
            results.append(dict(a,symbol=pair,route=route));ref_results.append(dict(b,symbol=pair,route=route))
    quality.holm(results);quality.holm(ref_results);assert results==ref_results
    for name,value in [('sequences.json',runs),('reference_sequences.json',ref_runs),('attribution.json',att),('reference_attribution.json',ref_att),
                       ('comparisons.json',results),('reference_comparisons.json',ref_results)]:h.save(OUT/name,value)
    for name in ('sequences','attribution','comparisons'):assert h.sha(OUT/(name+'.json'))==h.sha(OUT/('reference_'+name+'.json'))
    render(results,att,runs)
    h.verify(sources+predecessor_files+implementation)
    files=[h.rec(p) for p in sorted(OUT.iterdir()) if p.is_file()]
    h.save(OUT/'completion_seal.json',dict(status='PASS_FIXED_LEDGER_STREAK_STATE_REPRODUCTION',trades=1512,tests=test.testsRun,
        comparisons=len(results),streaks=len(runs),sources=len(sources),strategy_changed=False,files=files))
    print('COMPLETE '+str(OUT/'REPORT.md'),flush=True)


def render(results, att, runs):
    lines=['# Pre-entry market conditions and losing sequences','',
        'Original 1512 trades, January2023-August2026. No execution, risk, position sizing, BE or entry filter changed.',
        'R is the original $50 planned-risk trade unit. These are original-ledger partitions, not a rerun with avoided trades.',
        'All history already exposed. A warning associated with losses is not proof of causality or of reduced future drawdown.','',
        '| Pair / route | Warning | Present: n / original R / mean R | Absent: n / mean R | Difference95 interval | Weaker years | Holm descriptive tail | Disposition |',
        '|---|---|---:|---:|---|---:|---:|---|']
    for x in results:
        lines.append(f"|{x['symbol']}/{x['route']}|{x['field']}|{x['yes']['n']} / {x['yes']['original_net_r']} / {x['yes']['mean_r']}|{x['no']['n']} / {x['no']['mean_r']}|{x['month_cluster_95_interval']}|{x['weaker_years']}|{x['holm_adjusted_sign_tail']}|{x['disposition']}|")
    lines+=['','## Sequence definition and false alarms','',
        'A streak is >=3 full-stop exits on a pair, consecutive in exit order, with equal exit timestamps grouped. Any mixed or non-SL group breaks it. Streak and recovery membership use outcomes ONLY for retrospective attribution, never the pre-entry features.']
    for pair in ('USDJPY','GBPJPY'):
        q=[r for r in runs if r['symbol']==pair]
        lines += [f"- {pair}: {len(q)} streaks, {sum(r['count'] for r in q)} SL trades, longest {max((r['count'] for r in q),default=0)}; {sum(r['entered_before_first_sl'] for r in q)} entries already placed by the first SL; {sum(r['entered_after_two_known_sl'] for r in q)} entered after at least two run SL exits were already known."]
    for key,v in att.items():
        lines+=['',f'## {key}: pre-entry warning prevalence','',
            '| Warning | First streak losses yes/known | All streak SL yes/known | Profitable controls yes/known | Recovery winner controls yes/known |',
            '|---|---:|---:|---:|---:|']
        for field in FIELDS:
            cells=[]
            for cohort in ('initial_streak_losses','streak_members','all_profitable_controls','recovery_profitable_controls'):
                s=v[cohort]['warnings'][field];cells.append(f"{s['yes']}/{s['yes']+s['no']} ({s['unknown']} unknown)")
            lines.append('|'+field+'|'+'|'.join(cells)+'|')
    for x in results:
        lines+=['',f"## Annual detail: {x['symbol']}/{x['route']} / {x['field']}",'',FIELDS[x['field']],
            f"Unknown: {x['unknown']['n']}; present winners {x['yes']['net_win_pct']}%; absent winners {x['no']['net_win_pct']}%.",
            '| Year | Present n / original R / mean R | Absent n / original R / mean R |','|---|---:|---:|']
        for year,v in x['years'].items():
            a,b=v['yes'],v['no'];lines.append(f"|{year}|{a['n']} / {a['original_net_r']} / {a['mean_r']}|{b['n']} / {b['original_net_r']} / {b['mean_r']}|")
    lines+=['','## Boundaries','',
        'No hidden per-case rule, fitting, threshold search or proposed risk overlay. No hypothetical savings or modified drawdown was calculated.',
        'The seven checks are limited operational definitions, not an exhaustive explanation of market behavior. Warning-absent does not establish a sound entry.',
        'Month clusters address some dependence, not all zone, regime or cross-pair dependence. Sign-tail and Holm outputs are descriptive; prior repeated investigations make new independent confirmation necessary.',
        'Wick pivots are confirmed price geometry, not proof of resting orders. Complete-bar requirements can yield UNKNOWN near gaps; those trades remain in the audit.',
        'All original-month, year, route, episode and losing/winning controls are retained in the linked JSON artifacts. Source and predecessor hashes are verified before and after.','']
    with (OUT/'REPORT.md').open('x',encoding='utf8') as f:f.write('\n'.join(lines))


if __name__=='__main__':main()
