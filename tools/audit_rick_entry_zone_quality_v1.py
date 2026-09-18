"""Fixed-ledger entry/zone attribution. Never changes or executes a strategy."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import math
import unittest

import numpy as np

import acquire_rick_jpy_history_v1 as h
import audit_rick_preentry_streak_state_v1 as prior
import audit_rick_preentry_response_quality_v1 as quality
import audit_rick_reentry_management_v1 as management
import audit_rick_heavy_loss_months_v1 as old

ROOT=h.ROOT
OUT=ROOT/'research_artifacts/rick_entry_zone_quality_v1'
FIELDS={
 'weak_zone_departure':'GJ recorded M15 break candle fails bullish body>=50% range, close in upper25%, AND true range>=preceding ATR20.',
 'inefficient_formation':'GJ absolute net close-path movement / total close-path movement <0.5. SUPPORT origin through break; BOX origin through known-at birth. These are different formation types, never pooled.',
 'zone_age_ge_24h':'At least24 clock hours since parent became known, including closed-market elapsed time.',
 'repeated_completed_revisits':'At least two completed M5 contact episodes after known-at, separated by an entirely-above-zone M5 bar. Initial departure must be observed. Incomplete observation window -> UNKNOWN.',
 'deep_current_pullback':'Lowest completed M5 low in current attempt is below parent midpoint. GJ W starts at third-leg start; RESPONSE starts at recorded last bearish M15 pullback candle open.',
 'fill_over_1r_above_zone':'Actual original fill more than one original planned stop distance above parent high.',
 'weaker_second_w_rebound':'W second upward leg has lower net body-close advance per observed candle than the first upward leg; GJ M5 and UJ M15 respectively.'}
REGISTRY={('USDJPY','W'):('weaker_second_w_rebound',),
 ('GBPJPY','DEMAND_W'):tuple(FIELDS),
 ('GBPJPY','RESPONSE_MARKET'):tuple(f for f in FIELDS if f!='weaker_second_w_rebound')}


def exact_window(data,start,end,seconds,reference=False):
    # Exact [start,end) opens; every bar must already be available by end.
    if start is None or end is None or end<=start or (end-start)%seconds:return None
    i=int(np.searchsorted(data['time'],start));j=int(np.searchsorted(data['time'],end))
    expected=(end-start)//seconds
    if j-i!=expected:return None
    if reference:
        if any(int(data['time'][i+k])!=start+k*seconds or int(data['known'][i+k])>end for k in range(expected)):return None
    elif not (np.array_equal(data['time'][i:j],np.arange(start,end,seconds)) and np.all(data['known'][i:j]<=end)):return None
    return {k:v[i:j] for k,v in data.items()}


def formation(data,start,end,reference=False):
    w=exact_window(data,start,end,900,reference)
    if w is None:return dict(inefficient=None,efficiency=None,bars=None)
    if reference:
        previous_close=int(w['open'][0]);distance=0
        for v in w['close']:
            distance+=abs(int(v)-previous_close);previous_close=int(v)
    else:distance=int(np.abs(np.diff(np.r_[w['open'][0],w['close']])).sum())
    net=abs(int(w['close'][-1])-int(w['open'][0]))
    return dict(inefficient=2*net<distance if distance else None,
        efficiency=round(net/distance,8) if distance else None,bars=len(w['time']))


def departure(data,end,reference=False):
    if end is None:return dict(weak=None,body_fraction=None,close_location=None,tr_atr=None)
    i=int(np.searchsorted(data['known'],end))
    out=dict(weak=None,body_fraction=None,close_location=None,tr_atr=None)
    if i>=len(data['known']) or int(data['known'][i])!=end:return out
    o,c,hi,lo=(int(data[k][i]) for k in ('open','close','high','low'));span=hi-lo
    if span>0:out.update(body_fraction=round((c-o)/span,8),close_location=round((c-lo)/span,8))
    if i<21:return out
    w=exact_window(data,int(data['time'][i])-21*900,int(data['time'][i])+900,900,reference)
    if w is None:return out
    if reference:
        total=sum(max(int(data['high'][k]-data['low'][k]),abs(int(data['high'][k]-data['close'][k-1])),
            abs(int(data['low'][k]-data['close'][k-1]))) for k in range(i-20,i))
    else:
        high=data['high'][i-20:i];low=data['low'][i-20:i];prev=data['close'][i-21:i-1]
        total=int(np.maximum.reduce([high-low,np.abs(high-prev),np.abs(low-prev)]).sum())
    tr=max(span,abs(hi-int(data['close'][i-1])),abs(lo-int(data['close'][i-1])))
    if total<=0 or span<=0:return out
    out.update(weak=not (2*(c-o)>=span and 4*(c-lo)>=3*span and 20*tr>=total),tr_atr=round(20*tr/total,8))
    return out


def contacts(data,known,at,low,high,reference=False):
    end=at//300*300
    w=exact_window(data,known,end,300,reference)
    if w is None:return dict(count=None,closes_below_floor=None,status='INCOMPLETE_OR_NO_COMPLETED_WINDOW')
    if reference:
        departed=False;in_contact=False;count=0;breaches=0
        for lo,hi,close in zip(w['low'],w['high'],w['close']):
            touching=int(lo)<=high and int(hi)>=low
            if touching and departed and not in_contact:count+=1;in_contact=True
            if int(lo)>high:in_contact=False;departed=True
            if not departed and int(close)>high:departed=True
            breaches+=int(int(close)<low)
    else:
        touch=(w['low']<=high)&(w['high']>=low)
        above=w['low']>high;close_above=w['close']>high
        # A completed entirely-above bar separates touch episodes. Vector reference
        # segment starts allow the birth departure close to arm the first episode.
        separators=np.flatnonzero(above);count=0;last=0;armed=False
        for stop in list(separators)+[len(touch)]:
            if stop>last:
                start=last
                if not armed:
                    dep=np.flatnonzero(close_above[last:stop])
                    start=last+int(dep[0])+1 if len(dep) else stop
                if np.any(touch[start:stop]):count+=1
            armed=True;last=int(stop)+1
        breaches=int(np.sum(w['close']<low))
    return dict(count=count,closes_below_floor=breaches,status='COMPLETE',last_known=int(w['known'][-1]))


def w_rebound(w,native,seconds,reference=False):
    if w is None:return dict(weaker=None,first_speed=None,second_speed=None)
    speeds=[];numbers=[]
    for leg in (1,3):
        q=exact_window(native,w['leg_starts'][leg],w['leg_ends'][leg],seconds,reference)
        if q is None:return dict(weaker=None,first_speed=None,second_speed=None)
        advance=int(q['close'][-1])-int(q['open'][0]);n=len(q['time']);numbers.append((advance,n));speeds.append(round(advance/n,8))
    a,b=numbers
    return dict(weaker=b[0]*a[1]<a[0]*b[1],first_speed=speeds[0],second_speed=speeds[1])


def clean_event(event):
    # Exclude invalidated_at, closed_at, future status, trade outcomes and all paths.
    w=event['evidence'].get('w');p=event['evidence'].get('zone') or event['evidence'].get('box')
    parent={k:p[k] for k in ('id','kind','known','origin','low','high','break_time','base_known','origin_candles',
        'small_origin_extended','reaction_ids','pullback_close') if k in p} if p else None
    ww={k:w[k] for k in ('id','confirmation_time','leg_starts','leg_ends','first_low_points','second_low_points','entry_points')} if w else None
    return dict(id=event['id'],time=event['time'],route=event['route'],mode=event['mode'],parent=parent,w=ww)


def features(decision,event,m5,m15,reference=False):
    at=decision['entry_time'];risk=decision['risk'];entry=decision['entry'];p=event['parent'];w=event['w']
    assert event['time']<=at
    result={f:None for f in FIELDS}
    native=m5 if decision['symbol']=='GBPJPY' and w else m15
    rebound=w_rebound(w,native,300 if native is m5 else 900,reference)
    result['weaker_second_w_rebound']=rebound['weaker']
    result.update(parent_id=p['id'] if p else w['id'],parent_kind=p['kind'] if p else 'W_STRUCTURE_NOT_PARENT_ZONE',
        fill_location='NO_PARENT_ZONE',stop_location='NO_PARENT_ZONE',parent_age_seconds=None,
        evidence=dict(w_rebound=rebound,signal_time=event['time'],entry_time=at))
    if not p:return result
    assert p['known']<=at and (p.get('break_time') is None or p['break_time']<=at)
    low,high=p['low'],p['high'];assert low<high
    end=p['known'] if p['kind']=='BOX' else p['break_time']
    frm=formation(m15,p['origin'],end,reference);dep=departure(m15,p['break_time'],reference)
    touch=contacts(m5,p['known'],at,low,high,reference)
    start=w['leg_starts'][2] if w else p.get('pullback_close')
    if not w and start is not None:start-=900
    current=exact_window(m5,start,at//300*300,300,reference) if start is not None else None
    lowest=(min(int(v) for v in current['low']) if reference else int(np.min(current['low']))) if current is not None else None
    result.update(weak_zone_departure=dep['weak'],inefficient_formation=frm['inefficient'],
        zone_age_ge_24h=at-p['known']>=86400,repeated_completed_revisits=touch['count']>=2 if touch['count'] is not None else None,
        deep_current_pullback=2*lowest<low+high if lowest is not None else None,
        fill_over_1r_above_zone=entry-high>risk,parent_age_seconds=at-p['known'])
    result['fill_location']=('BELOW_ZONE' if entry<low else 'INSIDE_ZONE' if entry<=high else 'ABOVE_GT_1R' if entry-high>risk else 'ABOVE_LE_1R')
    stop=decision['stop']
    result['stop_location']=('BELOW_OR_AT_FLOOR' if stop<=low else 'INSIDE_ZONE' if stop<high else 'AT_OR_ABOVE_TOP')
    result['evidence'].update(formation=frm,departure=dep,revisits=touch,
        parent_low=low,parent_high=high,parent_known=p['known'],parent_origin=p['origin'],break_time=p['break_time'],
        current_attempt_start=start,deepest_completed_current_low=lowest,
        current_depth_fraction=round((high-lowest)/(high-low),8) if lowest is not None else None,
        fill_above_top_r=round((entry-high)/risk,8),zone_width_r=round((high-low)/risk,8),
        origin_candle_count=len(p.get('origin_candles',[])) if p['kind']!='BOX' else None,
        range_reaction_count=len(p.get('reaction_ids',[])) if p['kind']=='BOX' else None)
    return result


def response_label(r):
    if r['outcome']=='TP':return 'TARGET_REACHED'
    if r['outcome']=='SL':return 'HALF_R_CLOSE_THEN_STOP' if r['half_r_response'] else 'STOP_WITHOUT_OBSERVED_HALF_R_CLOSE'
    if r['outcome']=='BE':return 'BE_EXIT'
    return 'OTHER_PROFIT_EXIT' if r['net_r']>0 else 'OTHER_LOSS_OR_FLAT_EXIT'


def stats(rows):
    rs=[r['net_r'] for r in rows];gain=math.fsum(r for r in rs if r>0);loss=-math.fsum(r for r in rs if r<0)
    result=quality.stats(rows)
    result.update(profit_factor=round(gain/loss,6) if loss else None,winners=sum(r>0 for r in rs),winner_r=round(gain,6),loser_r=round(-loss,6),
        parents=len({r['parent_id'] for r in rows}),response_classes=dict(Counter(response_label(r) for r in rows)),
        path_gap_rows=sum(r['path_has_gaps'] for r in rows),streak_members=sum(r['in_sl_streak'] for r in rows),
        recovery_winner_members=sum(r['recovery_winner'] for r in rows),
        entry_locations=dict(Counter(r['fill_location'] for r in rows)),stop_locations=dict(Counter(r['stop_location'] for r in rows)))
    return result


def cohorts(rows,episodes):
    answer={}
    for pair,route in prior.ROUTES:
        q=[r for r in rows if (r['symbol'],r['route'])==(pair,route)]
        groups={'all':q,'streak_losses':[r for r in q if r['in_sl_streak']],
            'winners':[r for r in q if r['net_r']>0],'recovery_winners':[r for r in q if r['recovery_winner']]}
        for i,e in enumerate(episodes):
            groups[f'decline_{i+1}']=[r for r in q if e['peak_time']<r['entry_time']<=e['trough_time']]
            groups[f'recovery_{i+1}']=[r for r in q if e['recovery_time'] and e['trough_time']<r['entry_time']<=e['recovery_time']]
        answer[pair+'/'+route]={name:dict(summary=stats(group),features={f:{str(v):stats([r for r in group if r[f] is v]) for v in (True,False,None)} for f in REGISTRY[(pair,route)]}) for name,group in groups.items()}
    return answer


def matrix(rows):
    answer=[]
    for pair,route in prior.ROUTES:
        q=[r for r in rows if (r['symbol'],r['route'])==(pair,route)]
        formation_field='weaker_second_w_rebound' if pair=='USDJPY' else 'weak_zone_departure'
        locations=('NO_PARENT_ZONE',) if pair=='USDJPY' else ('BELOW_ZONE','INSIDE_ZONE','ABOVE_LE_1R','ABOVE_GT_1R')
        for formation_state in (True,False,None):
            for trigger_state in (True,False,None):
                for location in locations:
                    cell=[r for r in q if r[formation_field] is formation_state and r['weak_confirmation'] is trigger_state and r['fill_location']==location]
                    answer.append(dict(symbol=pair,route=route,formation_field=formation_field,formation_state=formation_state,
                        weak_trigger=trigger_state,location=location,stats=stats(cell),
                        years={y:stats([r for r in cell if r['entry_year']==y]) for y in ('2023','2024','2025','2026')}))
    return answer


def main():
    OUT.mkdir(exist_ok=True)
    if (OUT/'completion_seal.json').exists():h.verify(h.read(OUT/'completion_seal.json')['files']);print('ALREADY_COMPLETE');return
    if (OUT/'protocol.json').exists():raise RuntimeError('Preserve incomplete attempt')
    proof=unittest.TextTestRunner().run(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_rick_entry_zone_quality_v1.py'))
    if not proof.wasSuccessful():raise RuntimeError('Synthetic proof failed')
    for d in (prior.OUT,prior.ZONE,quality.OUT,prior.DD):h.verify(h.read(d/'completion_seal.json')['files'])
    predecessor=h.read(prior.OUT/'protocol.json');sources=predecessor['sources'];assert len(sources)==180;h.verify(sources)
    event_sources=[]
    for pair in ('USDJPY','GBPJPY'):
        for p in sorted(old.BATCH.glob(pair+'_20??-??/primary.json')):
            if not '2023-01'<=p.parent.name[-7:]<='2026-08':continue
            sealed=[r for r in h.read(p.parent/'seal.json')['files'] if r['path']==p.relative_to(ROOT).as_posix()]
            assert len(sealed)==1;h.verify(sealed);event_sources+=sealed
    assert len(event_sources)==88
    artifacts=[h.rec(p) for p in (prior.ZONE/'primary.json',prior.ZONE/'reference.json',quality.OUT/'primary.json',
        prior.OUT/'sequences.json',prior.DD/'episode_details.json')]
    implementation=[h.rec(Path(__file__).resolve()),h.rec(ROOT/'tests/test_rick_entry_zone_quality_v1.py')]+[
        h.rec(ROOT/'tools'/n) for n in ('audit_rick_preentry_streak_state_v1.py','audit_rick_preentry_response_quality_v1.py','audit_rick_reentry_management_v1.py')]
    protocol=dict(created_utc=datetime.now(timezone.utc).isoformat(),purpose='EXPOSED_ENTRY_MODEL_ZONE_FORMATION_ATTRIBUTION',
        baseline='All1512 original long-only closed trades Jan2023-Aug2026, same selectors, directions, entries, stops, targets, execution, risk, costs and management. No refitting or filtering.',
        exposure='Previously exposed history, not independent validation.',fields=FIELDS,
        registry=[dict(symbol=k[0],route=k[1],fields=list(v)) for k,v in REGISTRY.items()],
        source_semantics='GJ SUPPORT parent: original M15 base origin and later structural break; BOX: original governing range birth and later break. UJ has no GJ-style parent; only its original M15 W rebound comparison is applicable. GJ W confirmation M5, not parent-envelope900seconds.',
        strength='Break signed bullish body>=50% range, close in top25%, true range>=arithmetic ATR20 of PRIOR completed M15 bars. Current break excluded from ATR. No parameter sweep.',
        formation='Exact completed M15 window origin to break close for SUPPORT, origin to known birth for BOX. Absolute net open-to-last-close divided by absolute first body plus absolute successive close changes. Zero path UNKNOWN.',
        contacts='Exact completed M5 bars from known timestamp to floor(entry/300)*300. Initial close above arms contact; intersection of high-low with zone starts episode; entirely-above bar ends/rearms. Below-floor excursion does not manufacture another episode. Missing expected bar => UNKNOWN, never fresh by default.',
        current_attempt='GJ W third-leg start through latest completed M5 before fill. GJ range recorded last bearish pullback M15 candle open through latest completed M5. These are different known trigger-defined windows, no outcome selection.',
        geometry='Parent fill BELOW_ZONE/INSIDE_ZONE inclusive bounds/ABOVE_LE_1R/ABOVE_GT_1R; stop BELOW_OR_AT_FLOOR/INSIDE_ZONE/AT_OR_ABOVE_TOP. UJ NO_PARENT_ZONE. Native prices in .001 JPY points.',
        reuse='Original weak-confirmation classification and post-entry M5 response/floor-failure evidence reused from sealed audit, not recalculated or retuned. No generic bullish/bearish regime tests repeated.',
        matrix='81 exhaustive descriptive cells:9UJ and36perGJ route, formation state x existing trigger quality x fill-location. Every zero/sparse cell retained. No ranking, cell selection, new joint hypothesis or candidate validation.',
        outcomes='Original TP/SL/BE/TIME and netR. SL with prior completed+.5R M5 close = HALF_R_CLOSE_THEN_STOP; otherwise STOP_WITHOUT_OBSERVED_HALF_R_CLOSE, not proof of immediate loss. Gaps flagged, no new outcome path opened.',
        comparisons='14 preregistered univariate comparisons separately per route. Reuse2000 entry-month cluster bootstrap seed20260918, descriptive95 interval and approximate two-sided sign-tail, Holm across14. Support20eachstate total/5eachyear; all4year directional consistency. No new candidate/filter from this exposed audit.',
        chronology='All feature inputs whitelist event/parent timestamps, geometry and completed bars known<=fill. Future invalidated/closed/end_reason/status fields removed before extraction.',
        controls='All123 sealed SL runs, profitable and recovery controls, five previous DD/recovery intervals, each year/month. Preserve all unknowns and losses.',
        reproduction='Scalar/vector formation, break, contact, W and geometry extraction; independent scalar/vector statistics; exact JSON hash agreement. Synthetic source-boundary and leakage checks first.',
        sources=sources,event_sources=event_sources,predecessor_artifacts=artifacts,implementation=implementation)
    h.save(OUT/'protocol.json',protocol);h.save(OUT/'protocol_seal.json',dict(files=[h.rec(OUT/'protocol.json')]+implementation))
    print('PROTOCOL_SEALED',flush=True)
    original=h.read(prior.ZONE/'primary.json');assert original==h.read(prior.ZONE/'reference.json') and len(original)==1512
    base={(r['symbol'],r['id']):r for r in h.read(quality.OUT/'primary.json')}
    primary=[];reference=[]
    for pair in ('USDJPY','GBPJPY'):
        print('MATERIALIZE '+pair,flush=True)
        events={};wanted={r['id'] for r in original if r['symbol']==pair}
        for record in event_sources:
            if not Path(record['path']).parent.name.startswith(pair+'_'):continue
            for event in h.read(ROOT/record['path'])['events']:
                if event['id'] not in wanted:continue
                e=clean_event(event)
                if e['id'] in events:assert e==events[e['id']],('event identity changed',e['id'])
                events[e['id']]=e
        paths=lambda tf:[ROOT/r['path'] for r in sources if Path(r['path']).name.startswith(pair+'_'+tf+'_')]
        m1=prior.load(paths('M1'));m15=prior.load(paths('M15'))
        assert np.all(m1['known']==m1['time']+60)
        m5=management.complete_m5(m1);m5ref=management.complete_m5(m1,True)
        assert all(np.array_equal(m5[k],m5ref[k]) for k in m5);del m1
        for r in original:
            if r['symbol']!=pair:continue
            d=dict(id=r['id'],symbol=pair,entry_time=r['entry_time'],entry=r['entry'],stop=r['initial_stop'],risk=r['planned_risk_points'])
            e=events[r['id']]
            a=features(d,e,m5,m15);b=features(d,e,m5ref,m15,True);assert a==b,('feature reproduction',r['id'])
            for f,out in ((a,primary),(b,reference)):out.append(dict(f,id=r['id'],symbol=pair,route=r['route'],entry_time=r['entry_time']))
        del m5,m5ref,m15,events
    assert primary==reference
    # Sealed outcome evidence joined only after both point-in-time passes agree.
    runs=h.read(prior.OUT/'sequences.json');episodes=h.read(prior.DD/'episode_details.json')
    members={(s['symbol'],i) for s in runs for i in s['ids']};recovery={(s['symbol'],s['recovery_id']) for s in runs}
    ledger={(r['symbol'],r['id']):r for r in original}
    for rows in (primary,reference):
        for r in rows:
            key=(r['symbol'],r['id']);b=base[key];oldr=ledger[key]
            for k in ('entry_day','entry_month','entry_year','net_r','outcome','half_r_response','structure_failed_by_horizon','weak_confirmation'):r[k]=b[k]
            r.update(in_sl_streak=key in members,recovery_winner=key in recovery,
                path_has_gaps=oldr['entry_to_exit_coverage']['missing_minutes_within_observed_span']>0)
    comparisons=[];refs=[]
    for (pair,route),fields in REGISTRY.items():
        print('COMPARE '+pair+' '+route,flush=True)
        q=[r for r in primary if (r['symbol'],r['route'])==(pair,route)]
        for field in fields:
            a=quality.compare(q,field);b=quality.compare(q,field,True);assert a==b
            comparisons.append(dict(a,symbol=pair,route=route));refs.append(dict(b,symbol=pair,route=route))
    for cs in (comparisons,refs):
        quality.holm(cs)
        for x in cs:
            x['stronger_years']=sum(v['yes']['mean_r'] is not None and v['no']['mean_r'] is not None and v['yes']['mean_r']>v['no']['mean_r'] for v in x['years'].values())
            ci=x['month_cluster_95_interval']
            x['association']=('SUPPORT_FAIL' if not x['support'] else 'ADVERSE_DESCRIPTIVE_ASSOCIATION' if x['disposition']=='CONSISTENT_DESCRIPTIVE_WARNING' else
                'FAVOURABLE_DESCRIPTIVE_ASSOCIATION' if x['stronger_years']==4 and ci and ci[0]>0 and x['holm_adjusted_sign_tail']<.05 else 'NOT_ESTABLISHED_AS_STABLE_ASSOCIATION')
    assert comparisons==refs and len(comparisons)==14
    groups=cohorts(primary,episodes);gref=cohorts(reference,episodes);assert groups==gref
    cells=matrix(primary);cref=matrix(reference);assert cells==cref and len(cells)==81 and sum(c['stats']['n'] for c in cells)==1512
    for name,a,b in (('features',primary,reference),('comparisons',comparisons,refs),('cohorts',groups,gref),('matrix',cells,cref)):
        h.save(OUT/(name+'.json'),a);h.save(OUT/('reference_'+name+'.json'),b)
        assert h.sha(OUT/(name+'.json'))==h.sha(OUT/('reference_'+name+'.json'))
    render(primary,comparisons,groups,cells)
    h.verify(sources+event_sources+artifacts+implementation)
    h.save(OUT/'completion_seal.json',dict(status='PASS_ENTRY_ZONE_ATTRIBUTION_REPRODUCTION',trades=1512,tests=proof.testsRun,
        comparisons=14,matrix_cells=81,strategy_changed=False,files=[h.rec(p) for p in sorted(OUT.iterdir()) if p.is_file()]))
    print('COMPLETE '+str(OUT/'REPORT.md'),flush=True)


def render(rows,cs,groups,cells):
    lines=['# Entry models, zone formation and pre-fill condition','',
        '1512 original trades, January2023-August2026. Original R=$50 planned risk. No trading rules, risk or execution changed. No filtered strategy, hypothetical savings or changed equity curve.',
        'SUPPORT and BOX are different GJ zone models. UJ has a W structure, not a GJ parent zone. All history exposed; association is not causal or independent validation.','',
        '| Original route | Trades | Win % net | Mean R | Original R | PF | SL no observed +.5R close | SL after +.5R close |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for key,v in groups.items():
        s=v['all']['summary'];beh=s['response_classes']
        lines.append(f"|{key}|{s['n']}|{s['net_win_pct']}|{s['mean_r']}|{s['original_net_r']}|{s['profit_factor']}|{beh.get('STOP_WITHOUT_OBSERVED_HALF_R_CLOSE',0)}|{beh.get('HALF_R_CLOSE_THEN_STOP',0)}|")
    lines+=['','## New predefined comparisons','',
        '| Route | Condition | True n / mean R / total R | False n / mean R / total R | Difference95 interval | Weaker years | Holm tail | Association |',
        '|---|---|---:|---:|---|---:|---:|---|']
    for x in cs:
        a,b=x['yes'],x['no'];lines.append(f"|{x['symbol']}/{x['route']}|{x['field']}|{a['n']} / {a['mean_r']} / {a['original_net_r']}|{b['n']} / {b['mean_r']} / {b['original_net_r']}|{x['month_cluster_95_interval']}|{x['weaker_years']}|{x['holm_adjusted_sign_tail']}|{x['association']}|")
    for key,v in groups.items():
        lines+=['',f'## {key}: winning and losing-sequence controls','',
            '| Condition | Streak SL true/known | Winners true/known | Recovery winners true/known |','|---|---:|---:|---:|']
        for f in v['all']['features']:
            parts=[]
            for c in ('streak_losses','winners','recovery_winners'):
                s=v[c]['features'][f];parts.append(f"{s['True']['n']}/{s['True']['n']+s['False']['n']} ({s['None']['n']} unknown)")
            lines.append('|'+f+'|'+'|'.join(parts)+'|')
        q=[r for r in rows if r['symbol']+'/'+r['route']==key]
        lines+=['','| Fill / stop geometry | n | Original R | Winners |','|---|---:|---:|---:|']
        for field in ('fill_location','stop_location'):
            for value in sorted({r[field] for r in q}):
                s=stats([r for r in q if r[field]==value]);lines.append(f"|{field}: {value}|{s['n']}|{s['original_net_r']}|{s['winners']}|")
    lines+=['','## Complete descriptive formation x trigger x location matrix','',
        'Every cell retained, including zero and sparse cells. True means weaker formation/trigger under the recorded definition, not a proven bad setup. No matrix cell is a candidate.','',
        '| Route | Formation flag | Weak trigger | Fill location | n | Original R | Win % | Mean R |','|---|---|---|---|---:|---:|---:|---:|']
    for c in cells:
        s=c['stats'];lines.append(f"|{c['symbol']}/{c['route']}|{c['formation_state']}|{c['weak_trigger']}|{c['location']}|{s['n']}|{s['original_net_r']}|{s['net_win_pct']}|{s['mean_r']}|")
    for x in cs:
        lines+=['',f"## Annual detail {x['symbol']}/{x['route']} / {x['field']}",'',FIELDS[x['field']],f"Unknown: {x['unknown']['n']}.",'',
            '| Year | True n / R / mean R | False n / R / mean R |','|---|---:|---:|']
        for y,v in x['years'].items():
            a,b=v['yes'],v['no'];lines.append(f"|{y}|{a['n']} / {a['original_net_r']} / {a['mean_r']}|{b['n']} / {b['original_net_r']} / {b['mean_r']}|")
    lines+=['','## Limitations','',
        'No new entry model was executed. Differences between UJ/GJ or GJ routes are confounded by instrument, opportunity selection and original management; they are not randomized causal effects.',
        'No confirmed +.5R M5 close before SL is not proof that price immediately failed or never touched +.5R intrabar. Missing path observations are explicitly flagged.',
        'Strict pre-entry M5 completeness can leave repeat-touch/depth UNKNOWN, particularly for older zones across closures. They remain in every ledger and no prices were fabricated.',
        'All five DD and recovery intervals, all original entry-months and years and every negative/support-failed result are recorded. Broad repeated research makes nominal within-audit statistics exploratory only.','']
    with (OUT/'REPORT.md').open('x',encoding='utf8') as f:f.write('\n'.join(lines))


if __name__=='__main__':main()
