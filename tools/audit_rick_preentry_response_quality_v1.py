"""Bounded exposed attribution; never executes, filters or changes a strategy."""
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timezone
import math
from pathlib import Path
import unittest

import numpy as np

import acquire_rick_jpy_history_v1 as h
import audit_rick_heavy_loss_months_v1 as old
import audit_rick_reentry_management_v1 as management

ROOT=h.ROOT
PREV=ROOT/'research_artifacts/rick_zone_response_audit_v1'
OUT=ROOT/'research_artifacts/rick_preentry_response_quality_v1'
FIELDS={
 'prior_parent_damage':'Existing parent had a completed M15 close below its floor, then reclaimed before entry; unavailable for UJ.',
 'body_only_w_break':'Original W confirmation close did not exceed the neckline wick; not applicable to response-market.',
 'weak_confirmation':'Original confirmation candle fails bullish body >=50% of range AND close in upper 25%; source M15 for UJ/range and M5 for GJ W.',
 'selling_into_fill':'Four latest contiguous, fresh, completed M5 closes: latest below first (15-minute close-to-close decline).',
 'trigger_not_held':'Latest fresh completed M5 close at/below original W neckline or range top at entry.',
 'delayed_fill':'At least 900 seconds between original signal confirmation and actual fill.'}
SEED=20260918
REPS=2000


def right(times,at,reference):
    return bisect_right(times,at) if reference else int(np.searchsorted(times,at,side='right'))


def extract(entry_time,signal_time,trigger,w,native,m5,reference=False):
    """Only completed quotes available by entry; never consumes exit/outcome fields."""
    if signal_time>entry_time:raise ValueError('Future signal')
    i=right(native['known'],signal_time,reference)-1
    quality=None;body=None;location=None;confirm_known=None
    if i>=0 and native['known'][i]==signal_time:
        o,c,hi,lo=(int(native[k][i]) for k in ('open','close','high','low'))
        span=hi-lo;confirm_known=int(native['known'][i])
        if span>0:
            if reference:strong=(2*(c-o)>=span and 4*(c-lo)>=3*span)
            else:strong=(c-o>=.5*span and c-lo>=.75*span)
            quality=not strong;body=round((c-o)/span,8);location=round((c-lo)/span,8)
        else:quality=True
    j=right(m5['known'],entry_time,reference)-1
    fresh=j>=0 and 0<=entry_time-int(m5['known'][j])<300
    held=bool(m5['close'][j]<=trigger) if fresh else None
    selling=None;change=None
    if fresh and j>=3 and int(m5['known'][j])-int(m5['known'][j-3])==900:
        change=int(m5['close'][j])-int(m5['close'][j-3]);selling=change<0
    return dict(weak_confirmation=quality,selling_into_fill=selling,trigger_not_held=held,
        delayed_fill=entry_time-signal_time>=900,
        body_only_w_break=(w['confirmation_close_points']<=w['neckline_wick_points']) if w else None,
        evidence=dict(signal_time=signal_time,entry_time=entry_time,confirmation_known=confirm_known,
            confirmation_signed_body_fraction=body,confirmation_close_location=location,
            latest_m5_known=int(m5['known'][j]) if fresh else None,
            prefill_15minute_close_change_points=change,fill_delay_seconds=entry_time-signal_time,
            trigger_level=trigger))


def stats(rows):
    r=[x['net_r'] for x in rows];positive=sum(v>0 for v in r)
    return dict(n=len(rows),entry_dates=len({x['entry_day'] for x in rows}),
        original_net_r=round(math.fsum(r),6),mean_r=round(math.fsum(r)/len(r),6) if r else None,
        net_win_pct=round(100*positive/len(r),4) if r else None,
        outcomes=dict(Counter(x['outcome'] for x in rows)),
        observed_half_r_response=sum(x['half_r_response'] for x in rows),
        structure_failed_by_horizon=sum(x['structure_failed_by_horizon'] for x in rows))


def compare(rows,field,reference=False):
    yes=[r for r in rows if r[field] is True];no=[r for r in rows if r[field] is False]
    months=sorted({r['entry_month'] for r in rows})
    sums=np.zeros((len(months),2));counts=np.zeros_like(sums)
    for k,m in enumerate(months):
        for j,q in enumerate((yes,no)):
            vals=[r['net_r'] for r in q if r['entry_month']==m]
            sums[k,j]=math.fsum(vals);counts[k,j]=len(vals)
    boot=[];rng=np.random.default_rng(SEED)
    weights=rng.multinomial(len(months),np.full(len(months),1/len(months)),size=REPS)
    if reference:
        for w in weights:
            n=[sum(int(w[k])*int(counts[k,j]) for k in range(len(months))) for j in (0,1)]
            if all(n):
                s=[math.fsum(int(w[k])*sums[k,j] for k in range(len(months))) for j in (0,1)]
                boot.append(s[0]/n[0]-s[1]/n[1])
    else:
        n=weights@counts;s=weights@sums;valid=np.all(n>0,axis=1)
        boot=(s[valid,0]/n[valid,0]-s[valid,1]/n[valid,1]).tolist()
    years={y:{'yes':stats([r for r in yes if r['entry_year']==y]),'no':stats([r for r in no if r['entry_year']==y])}
           for y in ('2023','2024','2025','2026')}
    diff=round(math.fsum(r['net_r'] for r in yes)/len(yes)-math.fsum(r['net_r'] for r in no)/len(no),6) if yes and no else None
    ci=[round(float(v),6) for v in np.quantile(boot,[.025,.975])] if boot else None
    count_small=sum(v>=0 for v in boot) if boot else 0
    p=min(1.,2*(min(count_small,len(boot)-count_small)+1)/(len(boot)+1)) if boot else None
    yearly_support=all(min(v['yes']['n'],v['no']['n'])>=5 for v in years.values())
    support=min(len(yes),len(no))>=20 and yearly_support
    worse_years=sum(v['yes']['mean_r'] is not None and v['no']['mean_r'] is not None and v['yes']['mean_r']<v['no']['mean_r'] for v in years.values())
    return dict(field=field,yes=stats(yes),no=stats(no),unknown=stats([r for r in rows if r[field] is None]),
        difference_r=diff,month_cluster_95_interval=ci,bootstrap_two_sided_sign_tail=round(p,6) if p is not None else None,
        valid_bootstrap_samples=len(boot),support=support,yearly_support=yearly_support,weaker_years=worse_years,years=years,
        months={m:{'yes':stats([r for r in yes if r['entry_month']==m]),'no':stats([r for r in no if r['entry_month']==m])} for m in months})


def holm(comparisons):
    ordered=sorted([x for x in comparisons if x['bootstrap_two_sided_sign_tail'] is not None],key=lambda x:x['bootstrap_two_sided_sign_tail'])
    previous=0.
    for i,x in enumerate(ordered):
        previous=max(previous,min(1.,(len(ordered)-i)*x['bootstrap_two_sided_sign_tail']))
        x['holm_adjusted_sign_tail']=round(previous,6)
    for x in comparisons:
        x.setdefault('holm_adjusted_sign_tail',None)
        ci=x['month_cluster_95_interval']
        x['disposition']=('SUPPORT_FAIL' if not x['support'] else
            'CONSISTENT_DESCRIPTIVE_WARNING' if x['weaker_years']==4 and ci and ci[1]<0 and x['holm_adjusted_sign_tail']<.05 else
            'NOT_ESTABLISHED_AS_STABLE_WARNING')


def main():
    OUT.mkdir(exist_ok=True)
    if (OUT/'completion_seal.json').exists():h.verify(h.read(OUT/'completion_seal.json')['files']);print('ALREADY_COMPLETE');return
    if (OUT/'protocol.json').exists():raise RuntimeError('Preserve incomplete attempt')
    for name in ('completion_seal.json','findings_seal.json','protocol_seal.json'):h.verify(h.read(PREV/name)['files'])
    predecessor=h.read(PREV/'protocol.json');h.verify(predecessor['sources'])
    test_result=unittest.TextTestRunner().run(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_rick_preentry_response_quality_v1.py'))
    if not test_result.wasSuccessful():raise RuntimeError('Synthetic proof failed')
    implementation=[h.rec(Path(__file__).resolve()),h.rec(ROOT/'tests/test_rick_preentry_response_quality_v1.py'),
        h.rec(ROOT/'tools/audit_rick_heavy_loss_months_v1.py'),h.rec(ROOT/'tools/audit_rick_reentry_management_v1.py')]
    protocol=dict(purpose='EXPOSED_FIXED_LEDGER_PRE_ENTRY_ATTRIBUTION',created_utc=datetime.now(timezone.utc).isoformat(),
        population='Same 1512 original exits Jan2023-Aug2026; reporting years/months use entry timestamps for chronology',
        strategy='Frozen long-only pair-native selectors, costs, management, entries, stops and targets unchanged. No refit, filter or simulation.',
        exposure='All historical results already exposed; audit freeze is not independent preregistration or validation.',
        fields=FIELDS,unknown='Incomplete/stale M5, absent exact confirmation or not applicable remains UNKNOWN; no imputation.',
        analysis='Univariate only, separately UJ W / GJ DEMAND_W / GJ RESPONSE_MARKET. Every comparison and year recorded. No interactions or threshold search.',
        support='At least 20 trades each state overall and 5 each state in each of 2023/2024/2025/2026 (2026 partial).',
        uncertainty='2000 resamples of entry-calendar-month clusters, all rows retained. 95% percentile difference CI; approximate two-sided bootstrap sign-tail, Holm over all applicable comparisons in THIS audit only.',
        warning='Predefined adverse state worse in all four years, support passes, upper95CI<0, Holm sign-tail<.05. Warning is not an entry rule or edge.',
        seed=SEED,reps=REPS,prior_seal=h.rec(PREV/'completion_seal.json'),sources=predecessor['sources'],implementation=implementation)
    h.save(OUT/'protocol.json',protocol);h.save(OUT/'protocol_seal.json',dict(files=[h.rec(OUT/'protocol.json')]+implementation))
    old_rows=h.read(PREV/'primary.json');old_ref=h.read(PREV/'reference.json');assert old_rows==old_ref
    primary=[];reference=[]
    for pair in ('USDJPY','GBPJPY'):
        print('MATERIALIZE '+pair,flush=True)
        m1=old.prices(pair,'M1');m15=old.prices(pair,'M15')
        m5=management.complete_m5(m1);m5ref=management.complete_m5(m1,True)
        assert all(np.array_equal(m5[k],m5ref[k]) for k in m5)
        events={}
        for p in sorted(old.BATCH.glob(pair+'_20??-??/primary.json')):
            if p.parent.name.endswith('2026-09'):continue
            h.verify([x for x in h.read(p.parent/'seal.json')['files'] if x['path'].endswith('/primary.json')])
            events.update({e['id']:e for e in h.read(p)['events']})
        for r in old_rows:
            if r['symbol']!=pair:continue
            e=events[r['id']];w=e['evidence'].get('w');parent=e['evidence'].get('zone') or e['evidence'].get('box')
            at=e['time'];trigger=w['entry_points'] if w else parent['high']
            native=m5 if pair=='GBPJPY' and w else m15
            nref=m5ref if pair=='GBPJPY' and w else m15
            if w:assert w['confirmation_time']==at
            a=extract(r['entry_time'],at,trigger,w,native,m5)
            b=extract(r['entry_time'],at,trigger,w,nref,m5ref,True)
            assert a==b,('pre-entry reproduction',r['id'])
            if a['evidence']['confirmation_known'] is not None and w:
                ix=right(native['known'],at,False)-1
                assert native['close'][ix]==w['confirmation_close_points'],('source confirmation mismatch',r['id'])
            pstate=r['levels'].get('PARENT')
            prior=pstate['pre_entry_state']=='PAST_CLOSE_BREACH_RECLAIMED' if pstate else None
            level=pstate or r['levels']['W_FLOOR']
            extras=dict(id=r['id'],symbol=pair,route=r['route'],entry_day=r['entry_day'],entry_month=r['entry_day'][:7],entry_year=r['entry_day'][:4],
                net_r=r['net_r'],outcome=r['outcome'],parent_id=level['id'],prior_parent_damage=prior,
                half_r_response=r['m5_response_closes']['0.5'] is not None,
                structure_failed_by_horizon=level['native_first_close_failure'] is not None)
            primary.append(dict(a,**extras));reference.append(dict(b,**extras))
        del m1,m15,m5,m5ref
    assert len(primary)==1512 and primary==reference
    h.save(OUT/'primary.json',primary);h.save(OUT/'reference.json',reference)
    assert h.sha(OUT/'primary.json')==h.sha(OUT/'reference.json')
    results=[];ref_results=[]
    for pair,route in (('USDJPY','W'),('GBPJPY','DEMAND_W'),('GBPJPY','RESPONSE_MARKET')):
        print('COMPARE '+pair+' '+route,flush=True)
        for f in FIELDS:
            q=[r for r in primary if r['symbol']==pair and r['route']==route]
            a=compare(q,f);b=compare(q,f,True)
            assert a==b,('summary reproduction',pair,route,f)
            results.append(dict(a,symbol=pair,route=route));ref_results.append(dict(b,symbol=pair,route=route))
    holm(results);holm(ref_results);assert results==ref_results
    h.save(OUT/'comparisons.json',results);h.save(OUT/'reference_comparisons.json',ref_results)
    render(results)
    h.verify(implementation);h.verify(predecessor['sources'])
    files=[h.rec(OUT/n) for n in ('protocol.json','protocol_seal.json','primary.json','reference.json','comparisons.json','reference_comparisons.json','REPORT.md')]
    h.save(OUT/'completion_seal.json',dict(status='PASS_PREENTRY_ATTRIBUTION_REPRODUCTION',cases=len(primary),comparisons=len(results),tests=test_result.testsRun,files=files))
    print('COMPLETE '+str(OUT/'REPORT.md'),flush=True)


def render(results):
    lines=['# Pre-entry reaction quality: unchanged-ledger diagnostic','',
      'Exposed 2023-August 2026 history, 1512 original trades. No filter or strategy was executed. Totals below are original-ledger partitions, not counterfactual returns.',
      'True means the predefined potential warning is present. Unknowns are retained. Years use entry date. Positive/negative expectancy contrasts do not establish causality.',
      'Uncertainty resamples entry months, not individual trades. Multiple checks and extensive prior research make these exploratory diagnostics, not independent validation.','',
      '| Pair / route | Pre-entry warning | True n / mean R | False n / mean R | Difference 95% interval | Worse years /4 | Holm tail | Disposition |',
      '|---|---|---:|---:|---|---:|---:|---|']
    for x in results:
        lines.append(f"| {x['symbol']}/{x['route']} | {x['field']} | {x['yes']['n']} / {x['yes']['mean_r']} | {x['no']['n']} / {x['no']['mean_r']} | {x['month_cluster_95_interval']} | {x['weaker_years']} | {x['holm_adjusted_sign_tail']} | {x['disposition']} |")
    for x in results:
        lines+=['',f"## {x['symbol']} / {x['route']} / {x['field']}",'',FIELDS[x['field']],
            f"Unknown: {x['unknown']['n']}; True original R {x['yes']['original_net_r']}; False original R {x['no']['original_net_r']}.",'',
            '| Year | True n / mean R | False n / mean R |','|---|---:|---:|']
        for y,v in x['years'].items():lines.append(f"| {y} | {v['yes']['n']} / {v['yes']['mean_r']} | {v['no']['n']} / {v['no']['mean_r']} |")
    lines+=['','## Preserved limitations','',
        'The supplied bullish direction is unchanged; no autonomous higher-timeframe regime rule was fitted. Repeated trades/zones and common JPY exposure are correlated.',
        'The GJ event envelope uses seconds=900 for its parent invalidation. Its W confirmation is actually M5. This audit uses M5 for that confirmation only; prior sealed M15 floor diagnostics and every execution remain untouched.',
        'A failed support gate or unstable warning is not a rejection of the original profitable strategy. No combination of individually favorable partitions was selected. All observations remain exposed.','']
    with (OUT/'REPORT.md').open('x',encoding='utf8') as f:f.write('\n'.join(lines))


if __name__=='__main__':main()
