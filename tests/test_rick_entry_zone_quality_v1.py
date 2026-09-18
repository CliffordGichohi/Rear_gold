import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import audit_rick_entry_zone_quality_v1 as a


def bars(n=50,seconds=900):
    t=np.arange(n,dtype=np.int64)*seconds;c=np.full(n,100,dtype=np.int64)
    return dict(time=t,known=t+seconds,open=c.copy(),close=c.copy(),low=c-2,high=c+2)


class Proof(unittest.TestCase):
    def test_exact_end_excludes_future(self):
        b=bars();w=a.exact_window(b,900,2700,900)
        self.assertEqual(w['time'].tolist(),[900,1800])
        b['known'][2]=2701;self.assertIsNone(a.exact_window(b,900,2700,900))

    def test_gaps_unknown(self):
        b={k:np.delete(v,2) for k,v in bars().items()}
        self.assertIsNone(a.exact_window(b,0,3600,900))
        self.assertIsNone(a.exact_window(b,0,3600,900,True))

    def test_formation_efficient_vs_chop(self):
        b=bars(4);b['close']=np.array([110,105,115,110])
        x=a.formation(b,0,3600);self.assertEqual(x,a.formation(b,0,3600,True))
        self.assertTrue(x['inefficient']);self.assertAlmostEqual(x['efficiency'],1/3,places=7)

    def test_departure_prior_atr_not_current(self):
        b=bars();b['open'][30]=100;b['close'][30]=108;b['low'][30]=99;b['high'][30]=109
        x=a.departure(b,31*900);self.assertFalse(x['weak']);self.assertEqual(x,a.departure(b,31*900,True))
        b['close'][31:]=10000;self.assertEqual(x,a.departure(b,31*900))

    def test_contacts_episode_not_candle_count(self):
        b=bars(6,300);b['low']=np.array([111,99,98,112,100,99]);b['high']=b['low']+5;b['close']=b['low']+2
        x=a.contacts(b,0,1800,95,110);self.assertEqual(x,a.contacts(b,0,1800,95,110,True));self.assertEqual(x['count'],2)

    def test_contacts_random_agreement(self):
        rng=np.random.default_rng(52)
        for _ in range(100):
            b=bars(30,300);b['low']=rng.integers(88,119,30);b['high']=b['low']+rng.integers(1,10,30);b['close']=(b['low']+b['high'])//2
            self.assertEqual(a.contacts(b,0,9000,95,110),a.contacts(b,0,9000,95,110,True))

    def test_contact_gap_not_fresh(self):
        b={k:np.delete(v,2) for k,v in bars(10,300).items()}
        self.assertIsNone(a.contacts(b,0,3000,95,110)['count'])

    def test_weaker_second_w(self):
        b=bars(8,300);b['close'][3]=110;b['close'][7]=106
        w=dict(leg_starts=[0,600,1200,1800],leg_ends=[600,1200,1800,2400])
        x=a.w_rebound(w,b,300);self.assertTrue(x['weaker']);self.assertEqual(x,a.w_rebound(w,b,300,True))

    def test_future_outcome_metadata_stripped(self):
        e=dict(id='x',time=900,route='RESPONSE_MARKET',mode='MARKET',evidence=dict(box=dict(id='p',kind='BOX',known=900,origin=0,
            low=90,high=110,break_time=None,invalidated_at=100000,closed_at=200000,end_reason='LOSER')))
        x=a.clean_event(e);self.assertNotIn('invalidated_at',x['parent']);self.assertNotIn('end_reason',x['parent'])
        e['evidence']['box']['invalidated_at']=123456;self.assertEqual(x,a.clean_event(e))

    def test_no_parent_not_fabricated_for_uj(self):
        b=bars(8,900);w=dict(id='w',confirmation_time=7200,leg_starts=[0,1800,3600,5400],leg_ends=[1800,3600,5400,7200])
        e=dict(time=7200,parent=None,w=w)
        d=dict(entry_time=7200,entry=100,risk=150,stop=-50,symbol='USDJPY')
        x=a.features(d,e,bars(24,300),b)
        self.assertEqual(x['parent_kind'],'W_STRUCTURE_NOT_PARENT_ZONE');self.assertIsNone(x['weak_zone_departure'])
        self.assertEqual(x['fill_location'],'NO_PARENT_ZONE')

    def test_completed_pullback_and_distance_boundaries(self):
        m15=bars(40);m5=bars(120,300)
        p=dict(id='p',kind='BOX',known=18000,origin=17100,low=90,high=110,break_time=18900,pullback_close=20700)
        e=dict(time=21600,parent=p,w=None)
        d=dict(entry_time=21600,entry=130,risk=20,stop=110,symbol='GBPJPY')
        x=a.features(d,e,m5,m15);self.assertFalse(x['fill_over_1r_above_zone']);self.assertEqual(x['fill_location'],'ABOVE_LE_1R')
        for k in ('open','close','high','low'):m5[k][m5['known']>21600]=9999
        self.assertEqual(x,a.features(d,e,m5,m15))
        self.assertEqual(x,a.features(d,e,m5,m15,True))


if __name__=='__main__':unittest.main()
