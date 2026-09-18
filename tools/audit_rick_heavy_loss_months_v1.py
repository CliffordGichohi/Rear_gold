"""Fixed-ledger diagnostic. No execution changes, filtering or strategy reruns."""
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import json
import math
from pathlib import Path
import statistics as st

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import acquire_rick_jpy_history_v1 as h

ROOT=h.ROOT;BATCH=ROOT/'research_artifacts/rick_pair_native_2023_to_date_v1'
REGIME=ROOT/'research_artifacts/rick_pair_native_monthly_regime_audit_v1'
OUT=ROOT/'research_artifacts/rick_heavy_loss_months_audit_v1'
EAT=timezone(timedelta(hours=3))
NUMERIC=['fill_delay_minutes','h1_range_in_stop_r','h1_body_fraction','entry_h1_range_position',
 'atr20_m15_pips','stop_over_atr20_m15','spread_in_r','zone_width_in_r','w_depth_in_r','w_confirmation_extension_r']
BINARY=['h1_bearish','late_entry_15eat','stop_above_setup_floor','stop_above_w_second_low',
 'w_lower_second_low','w_confirm_below_neckline_wick','earlier_position_open','spatial_overlap_open_parent',
 'same_parent_previously_traded','gap_during_trade','ambiguous_trade','plus1_before_exit','plus2_before_exit',
 'sl_then_target_same_day','setup_floor_close_broken_before_exit']
PREENTRY=BINARY[:9]


def group(r):return 'HEAVY_LOSS' if r<-2 else 'PROFIT' if r>0 else 'SMALL_LOSS' if r<0 else 'ZERO'
def day(t):return datetime.fromtimestamp(t,EAT).date().isoformat()
def mon(t):return day(t)[:7]
def rounded(x):return round(float(x),6) if x is not None else None


def prices(symbol,tf):
    paths=sorted((h.OUT/'normalized').glob(f'{symbol}_{tf}_*.parquet'))
    cols=['open_epoch_utc','historical_available_at_epoch_utc','open','high','low','close']
    table=pa.concat_tables([pq.read_table(p,columns=cols) for p in paths])
    data={k:table[k].to_numpy() for k in cols}
    for k in ('open','high','low','close'):data[k]=np.rint(data[k]*1000).astype('int64')
    data['time']=data.pop('open_epoch_utc');data['known']=data.pop('historical_available_at_epoch_utc')
    if np.any(np.diff(data['time'])<=0):raise RuntimeError('Source ordering')
    return data


def path_diagnostics(t,event,m1,m15,reference=False):
    at=t['entry_time'];end=t['exit_time'];risk=t['planned_risk_points']
    # Exclude fill/exit candles: unknown intraminute ordering cannot establish capture.
    left=int(np.searchsorted(m1['time'],at,side='right'))
    right=int(np.searchsorted(m1['known'],end,side='right'))
    later_left=int(np.searchsorted(m1['time'],end,side='right'))
    dt=datetime.fromtimestamp(at,EAT);deadline=int(dt.replace(hour=23,minute=0,second=0).timestamp())
    later_right=int(np.searchsorted(m1['known'],deadline,side='right'))
    floor_left=int(np.searchsorted(m15['time'],event['time'],side='left'))
    floor_right=int(np.searchsorted(m15['known'],end,side='right'))
    last=int(np.searchsorted(m15['known'],at,side='right'))
    if reference:
        highs=[int(m1['high'][i]) for i in range(left,right)]
        hit=any(int(m1['high'][i])>=t['target'] for i in range(later_left,later_right))
        broken=any(int(m15['close'][i])<event['invalidation'] for i in range(floor_left,floor_right))
        tr=[max(int(m15['high'][i]-m15['low'][i]),abs(int(m15['high'][i]-m15['close'][i-1])),
                abs(int(m15['low'][i]-m15['close'][i-1]))) for i in range(last-20,last)] if last>=21 else []
        best=max(highs) if highs else None;atr=sum(tr)/20 if tr else None
    else:
        best=int(np.max(m1['high'][left:right])) if right>left else None
        hit=bool(np.any(m1['high'][later_left:later_right]>=t['target']))
        broken=bool(np.any(m15['close'][floor_left:floor_right]<event['invalidation']))
        if last>=21:
            hi=m15['high'][last-20:last];lo=m15['low'][last-20:last];prev=m15['close'][last-21:last-1]
            atr=float(np.maximum.reduce([hi-lo,np.abs(hi-prev),np.abs(lo-prev)]).sum())/20
        else:atr=None
    return dict(plus1_before_exit=best is not None and best>=t['entry']+risk,
        plus2_before_exit=best is not None and best>=t['entry']+2*risk,
        sl_then_target_same_day=hit if t['outcome']=='SL' else None,
        setup_floor_close_broken_before_exit=broken,
        atr20_m15_pips=rounded(atr/10) if atr is not None else None,
        stop_over_atr20_m15=rounded(risk/atr) if atr else None)


def summarize(rows):
    rs=[r['net_r'] for r in rows];gains=math.fsum(r for r in rs if r>0);loss=-math.fsum(r for r in rs if r<0)
    answer=dict(trades=len(rows),net_r=rounded(math.fsum(rs)),mean_r=rounded(st.mean(rs)) if rs else None,
        profit_factor=rounded(gains/loss) if loss else None,net_win_pct=rounded(100*sum(r>0 for r in rs)/len(rs)) if rs else None,
        price_r=rounded(math.fsum(r['price_r'] for r in rows)),outcomes=dict(Counter(r['outcome'] for r in rows)))
    answer['numeric']={k:dict(n=len(v),median=rounded(st.median(v)) if v else None)
        for k in NUMERIC for v in [[r[k] for r in rows if r[k] is not None]]}
    answer['binary']={k:dict(n=len(v),yes=sum(v),pct=rounded(100*sum(v)/len(v)) if v else None)
        for k in BINARY for v in [[r[k] for r in rows if r[k] is not None]]}
    return answer


def trade_row(t,event,previous,m1,m15,regime):
    risk=t['planned_risk_points'];hour=t['context_at_fill']['previous_h1']
    w=event['evidence'].get('w');zone=event['evidence'].get('zone') or event['evidence'].get('box')
    active=[p for p in previous if p['entry_time']<=t['entry_time']<=p['exit_time']]
    overlapping=[p for p in active if zone and p['zone_low'] is not None and
                 p['zone_low']<=zone['high'] and zone['low']<=p['zone_high']]
    for value in (hour,):
        if value and value['time']+value['seconds']>t['entry_time']:raise RuntimeError('Unfinished context')
    if w and w['confirmation_time']>t['entry_time']:raise RuntimeError('Future W')
    if zone and zone['known']>t['entry_time']:raise RuntimeError('Future parent')
    one=path_diagnostics(t,event,m1,m15);two=path_diagnostics(t,event,m1,m15,True)
    if one!=two:raise RuntimeError('Independent path diagnostic differs '+t['id'])
    hr=hour['high']-hour['low'] if hour else 0
    return dict(id=t['id'],entry_time=t['entry_time'],exit_time=t['exit_time'],entry_day=day(t['entry_time']),
        entry_month=mon(t['entry_time']),exit_month=mon(t['exit_time']),
        route=t['route'],mode=t['mode'],net_r=t['net_r'],price_r=t['price_r'],outcome=t['outcome'],
        entry_hour_eat=datetime.fromtimestamp(t['entry_time'],EAT).hour,
        weekday=datetime.fromtimestamp(t['entry_time'],EAT).strftime('%A'),
        h1_bearish=hour['close']<hour['open'] if hour else None,
        late_entry_15eat=datetime.fromtimestamp(t['entry_time'],EAT).hour>=15,
        fill_delay_minutes=rounded((t['entry_time']-t['signal_time'])/60),
        h1_range_in_stop_r=rounded(hr/risk) if hour else None,
        h1_body_fraction=rounded(abs(hour['close']-hour['open'])/hr) if hr else None,
        entry_h1_range_position=rounded((t['entry']-hour['low'])/hr) if hr else None,
        spread_in_r=rounded(t['spread_points']/risk),zone_width_in_r=rounded((zone['high']-zone['low'])/risk) if zone else None,
        w_depth_in_r=rounded((t['entry']-w['second_low_points'])/risk) if w else None,
        w_confirmation_extension_r=rounded((w['confirmation_close_points']-w['entry_points'])/risk) if w else None,
        stop_above_setup_floor=t['initial_stop']>event['invalidation'],
        stop_above_w_second_low=t['initial_stop']>w['second_low_points'] if w else None,
        w_lower_second_low=w['second_low_points']<w['first_low_points'] if w else None,
        w_confirm_below_neckline_wick=w['confirmation_close_points']<=w['neckline_wick_points'] if w else None,
        earlier_position_open=bool(active),spatial_overlap_open_parent=bool(overlapping) if zone else None,
        same_parent_previously_traded=any(p['parent_id']==zone['id'] for p in previous) if zone else None,
        parent_id=zone['id'] if zone else None,zone_low=zone['low'] if zone else None,zone_high=zone['high'] if zone else None,
        open_trade_ids=[p['id'] for p in active],overlap_trade_ids=[p['id'] for p in overlapping],
        gap_during_trade=t['gap_count']>0,ambiguous_trade=t['ambiguous_count']>0,
        prior20d_direction=regime['momentum20'],daily_structure=regime['structure'],**one)


def inspect_pair(symbol):
    m1=prices(symbol,'M1');m15=prices(symbol,'M15')
    contexts={r['trade_id']:r for r in h.read(REGIME/'trade_entry_context.json') if r['symbol']==symbol}
    monthly={p.parent.name[-7:]:h.read(p) for p in sorted(BATCH.glob(symbol+'_20??-??/summary.json'))}
    trades=[];events={}
    for p in sorted(BATCH.glob(symbol+'_20??-??/primary.json')):
        result=h.read(p);events.update({x['id']:x for x in result['events']});trades+=result['trades']
    trades.sort(key=lambda t:(t['entry_time'],t['signal_time'],t['id']))
    rows=[]
    for t in trades:
        r=trade_row(t,events[t['id']],rows,m1,m15,contexts[t['id']]);r['symbol']=symbol
        r['month_group']=group(monthly[r['exit_month']]['metrics']['net_r'])
        r['partial']=monthly[r['exit_month']]['partial'];rows.append(r)
    full=[r for r in rows if not r['partial']];months=[]
    for key,s in monthly.items():
        if s['partial']:continue
        rr=[r for r in rows if r['exit_month']==key];detail=summarize(rr)
        if abs(detail['net_r']-s['metrics']['net_r'])>0.0001:raise RuntimeError('Ledger total drift')
        perday=defaultdict(list)
        for r in rr:perday[r['entry_day']].append(r)
        days=[dict(day=k,trades=len(v),net_r=rounded(math.fsum(r['net_r'] for r in v)),
                   stopped=sum(r['outcome']=='SL' for r in v),overlapping=sum(r['earlier_position_open'] for r in v)) for k,v in perday.items()]
        detail.update(month=key,group=group(s['metrics']['net_r']),trading_days=len(perday),
            worst_days=sorted(days,key=lambda x:x['net_r'])[:3],
            routes={k:summarize([r for r in rr if r['route']==k]) for k in sorted({r['route'] for r in rr})})
        months.append(detail)
    result=dict(groups={g:summarize([r for r in full if r['month_group']==g]) for g in ('HEAVY_LOSS','PROFIT','SMALL_LOSS','ZERO')},
        months=months,breakdowns={})
    for field in ('route','h1_bearish','late_entry_15eat','stop_above_w_second_low','w_lower_second_low',
                  'w_confirm_below_neckline_wick','earlier_position_open','spatial_overlap_open_parent',
                  'same_parent_previously_traded','weekday','entry_hour_eat','prior20d_direction','daily_structure'):
        result['breakdowns'][field]={str(v):{g:summarize([r for r in full if r[field]==v and r['month_group']==g])
            for g in ('HEAVY_LOSS','PROFIT','SMALL_LOSS')} for v in sorted({r[field] for r in full},key=str)}
    heavy=[m for m in months if m['group']=='HEAVY_LOSS'];good=[m for m in months if m['group']=='PROFIT']
    contrasts={}
    for field in PREENTRY:
        good_values=[m['binary'][field]['pct'] for m in good if m['binary'][field]['pct'] is not None]
        bad_values=[m['binary'][field]['pct'] for m in heavy if m['binary'][field]['pct'] is not None]
        if good_values and bad_values:
            baseline=st.median(good_values)
            contrasts[field]=dict(profitable_month_median_pct=rounded(baseline),heavy_month_median_pct=rounded(st.median(bad_values)),
                heavy_months_above_profitable_median=sum(x>baseline for x in bad_values),heavy_months=len(bad_values))
    result['equal_month_contrasts']=contrasts
    return rows,result


def render(summary):
    lines=['# Rick pair-native heavy-loss month diagnostic','',
        'Scope: every full month Jan 2023-Aug 2026; HEAVY_LOSS strictly below -2R. Profitable and other months retained as controls.',
        'Descriptive, post-hoc comparison, not an optimized filter or new strategy. Original entries, stops, targets and ledgers unchanged.',
        'Net R and month group use exit month. Daily exposure clusters use entry day. Trades are correlated; trade counts are not independent samples.',
        'M15 ATR20 uses 20 observed completed bars. No inferred/fabricated missing minutes. Stop/range geometry is available at entry.',
        'Pre-exit +1/+2R touch excludes fill and exit M1 candles, avoiding unknown within-minute order. It is conservative path evidence, not realizable PnL.',
        'Stopped-then-target means a later observed M1 high reached the original target before 23 EAT on entry day. It does not prove a wider stop would win.',
        'Overlapping means another previously admitted trade remained open when this trade filled; same-minute stops retain conservative fill-before-exit ordering.',
        'Same-parent reuse includes earlier resolved trades, not a violation of the existing no-same-parent-open rule.','']
    for symbol,s in summary.items():
        lines+=['## '+symbol,'','### Aggregate groups','',
            '| Group | Trades | Net R | Before-cost price R | PF | Outcomes |','|---|---:|---:|---:|---:|---|']
        for k,v in s['groups'].items():lines.append(f"| {k} | {v['trades']} | {v['net_r']} | {v['price_r']} | {v['profit_factor']} | {v['outcomes']} |")
        lines+=['','### All defined characteristics: heavy-loss versus profitable months','',
            '| Characteristic | Heavy-loss months | Profitable months |','|---|---:|---:|']
        for field in BINARY:
            a=s['groups']['HEAVY_LOSS']['binary'][field];b=s['groups']['PROFIT']['binary'][field]
            lines.append(f"| {field} | {a['yes']}/{a['n']} ({a['pct']}%) | {b['yes']}/{b['n']} ({b['pct']}%) |")
        for field in NUMERIC:
            a=s['groups']['HEAVY_LOSS']['numeric'][field];b=s['groups']['PROFIT']['numeric'][field]
            lines.append(f"| {field} median | {a['median']} (n={a['n']}) | {b['median']} (n={b['n']}) |")
        lines+=['','### Consistency across months (each month equal weight)','',
                '```json',json.dumps(s['equal_month_contrasts'],indent=2),'```','',
                '### Every month below -2R','',
                '| Month | Net R | Trades | Outcomes | H1 bearish % | Stop above W low % | Already open % | SL then target | Worst entry day |',
                '|---|---:|---:|---|---:|---:|---:|---|---|']
        for m in s['months']:
            if m['group']!='HEAVY_LOSS':continue
            bins=m['binary'];later=bins['sl_then_target_same_day']
            lines.append(f"| {m['month']} | {m['net_r']} | {m['trades']} | {m['outcomes']} | {bins['h1_bearish']['pct']} | {bins['stop_above_w_second_low']['pct']} | {bins['earlier_position_open']['pct']} | {later['yes']}/{later['n']} | {m['worst_days'][0] if m['worst_days'] else None} |")
        lines+=['','### Complete categorical comparisons','', 'Stored in summary.json: route, H1 direction, time, stop/W geometry, confirmation, exposure, parent reuse, weekday, prior-20D direction and D1 structure.',
            'Every tested comparison retained, including those that do not distinguish the groups. No p-values, optimal thresholds, adjusted strategy returns or causal claims.','']
    with (OUT/'REPORT.md').open('x',encoding='utf8') as f:f.write('\n'.join(lines)+'\n')


def main():
    OUT.mkdir(exist_ok=True)
    if (OUT/'completion_seal.json').exists():h.verify(h.read(OUT/'completion_seal.json')['files']);print('ALREADY_COMPLETE');return
    if (OUT/'protocol.json').exists():raise RuntimeError('Incomplete attempt, preserve artifacts')
    seals=[BATCH/'completion_seal.json',REGIME/'completion_seal.json',h.OUT/'completion_seal.json']+sorted(BATCH.glob('*_20??-??/seal.json'))
    for p in seals:h.verify(h.read(p)['files'])
    code=[h.rec(Path(__file__)),h.rec(ROOT/'tests/test_rick_heavy_loss_months_v1.py')]
    h.save(OUT/'protocol.json',dict(purpose='EXPOSED_FIXED_LEDGER_DIAGNOSTIC',created_at=datetime.now(timezone.utc).isoformat(),
       month_threshold='STRICTLY_LESS_THAN_MINUS_2R',controls=['PROFIT','SMALL_LOSS','ZERO'],partial_months_excluded=True,
       numeric=NUMERIC,binary=BINARY,implementation=code,sources=[h.rec(p) for p in seals],
       path_policy='exclude fill and exit M1 from pre-exit excursion; post-stop target touch after exit bar until 23 EAT entry date',
       forbid=['strategy changes','counterfactual filtered performance','optimization','new data']))
    rows=[];summary={}
    for symbol in ('USDJPY','GBPJPY'):
        print('ANALYZE '+symbol,flush=True);r,s=inspect_pair(symbol);rows+=r;summary[symbol]=s
    h.save(OUT/'trade_diagnostics.json',rows);h.save(OUT/'summary.json',summary);render(summary)
    h.verify(code)
    for p in seals:h.verify(h.read(p)['files'])
    h.save(OUT/'completion_seal.json',dict(status='PASS_DIAGNOSTIC_REPRODUCTION',strategy_changed=False,
        path_primary_reference_equal=True,files=[h.rec(OUT/name) for name in ('protocol.json','trade_diagnostics.json','summary.json','REPORT.md')]))
    for symbol,s in summary.items():
        print(symbol,json.dumps(dict(groups=s['groups'],equal_month_contrasts=s['equal_month_contrasts']),indent=2))


if __name__=='__main__':main()
