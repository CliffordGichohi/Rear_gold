"""Verify narrative and source timestamp bounds; no new features or execution."""
from pathlib import Path
import math
import acquire_rick_jpy_history_v1 as h

OUT=h.ROOT/'research_artifacts/rick_entry_zone_quality_v1'


def main():
    h.verify(h.read(OUT/'completion_seal.json')['files'])
    p=h.read(OUT/'protocol.json');h.verify(p['implementation']+p['predecessor_artifacts']+p['event_sources'])
    rows=h.read(OUT/'features.json');assert rows==h.read(OUT/'reference_features.json') and len(rows)==1512
    cs=h.read(OUT/'comparisons.json');assert cs==h.read(OUT/'reference_comparisons.json') and len(cs)==14
    assert not any(c['association'].endswith('DESCRIPTIVE_ASSOCIATION') for c in cs)
    cells=h.read(OUT/'matrix.json');assert cells==h.read(OUT/'reference_matrix.json') and len(cells)==81
    assert sum(c['stats']['n'] for c in cells)==1512
    q=[r for r in rows if r['symbol']=='GBPJPY' and r['route']=='RESPONSE_MARKET' and r['fill_location']=='INSIDE_ZONE']
    assert len(q)==32 and round(math.fsum(r['net_r'] for r in q),6)==-2.877273
    assert sum(r['net_r']>0 for r in q)==13 and round(math.fsum(r['net_r'] for r in q if r['net_r']>0),6)==15.5
    old=h.read(h.ROOT/'research_artifacts/rick_preentry_response_quality_v1/primary.json')
    ix={(r['symbol'],r['id']):r for r in old}
    assert all(ix[(r['symbol'],r['id'])]['trigger_not_held'] is True for r in q)
    groups=h.read(OUT/'cohorts.json');assert groups==h.read(OUT/'reference_cohorts.json')
    for key,n,total in (('USDJPY/W',393,58.62),('GBPJPY/DEMAND_W',897,150.659091),('GBPJPY/RESPONSE_MARKET',222,83.172727)):
        s=groups[key]['all']['summary'];assert s['n']==n and abs(s['original_net_r']-total)<1e-6
    dw=groups['GBPJPY/DEMAND_W']
    for phase,n,total in (('decline',311,-82.872727),('recovery',178,93.313636)):
        s=[dw[f'{phase}_{i}']['summary'] for i in range(1,5)]
        assert sum(x['n'] for x in s)==n and abs(math.fsum(x['original_net_r'] for x in s)-total)<2e-6
    wanted={(r['symbol'],r['id']):r['entry_time'] for r in rows};checked=set()
    # Additional read-only lineage check of the source W windows actually used.
    for record in p['event_sources']:
        symbol=Path(record['path']).parent.name.split('_')[0]
        for e in h.read(h.ROOT/record['path'])['events']:
            key=(symbol,e['id'])
            if key not in wanted:continue
            at=wanted[key];assert e['time']<=at
            w=e['evidence'].get('w')
            if w:assert max(w['leg_ends'])<=w['confirmation_time']<=at
            parent=e['evidence'].get('zone') or e['evidence'].get('box')
            if parent:
                assert parent['known']<=at and parent['origin']<parent['known']
                assert parent.get('break_time') is None or parent['break_time']<=at
                assert parent.get('pullback_close') is None or parent['pullback_close']<=at
            checked.add(key)
    assert len(checked)==1512
    files=[h.rec(OUT/'FINDINGS.md'),h.rec(OUT/'completion_seal.json'),h.rec(Path(__file__).resolve())]
    if (OUT/'findings_seal.json').exists():h.verify(h.read(OUT/'findings_seal.json')['files'])
    else:h.save(OUT/'findings_seal.json',dict(status='PASS_NARRATIVE_AND_TIMESTAMP_VERIFICATION',timestamp_checked=1512,files=files))
    print('PASS: findings, duplicate-lead check, 1512 source timestamp bounds and all paired artifact hashes verified')


if __name__=='__main__':main()
