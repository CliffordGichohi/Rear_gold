import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import audit_rick_preentry_streak_state_v1 as a


def bars(closes, seconds, start=0):
    c=np.array(closes,dtype=np.int64);t=np.arange(len(c),dtype=np.int64)*seconds+start
    return dict(time=t,known=t+seconds,open=c-1,high=c+2,low=c-2,close=c)


class Proof(unittest.TestCase):
    def test_flat_and_unfinished_legs(self):
        c=[100,102,104,104,103,102,105,107,107,106,101,103,104,102]
        p=a.completed_legs(c);self.assertEqual(p,a.completed_legs(c,True))
        self.assertEqual([r['direction'] for r in p],[-1,1,-1,1])
        self.assertEqual([r['amplitude'] for r in p],[2,5,6,3])
        self.assertTrue(all(r['confirmed_index'] is not None for r in p))

    def test_random_legs_reproduce(self):
        rng=np.random.default_rng(823)
        for _ in range(250):
            c=1000+np.cumsum(rng.integers(-3,4,36))
            self.assertEqual(a.completed_legs(c),a.completed_legs(c,True))

    def test_swing_requires_right2_close(self):
        m=bars([10,11,15,12,11],900)
        self.assertEqual(a.pivots({k:v[:-1] for k,v in m.items()})['HIGH'],[])
        p=a.pivots(m);self.assertEqual(p,a.pivots(m,True))
        self.assertEqual(p['HIGH'][0]['known'],4500)

    def test_swing_gap_unknown(self):
        m=bars([10,11,15,12,11],900);m['time'][3:]+=900;m['known'][3:]+=900
        self.assertEqual(a.pivots(m)['HIGH'],[])
        self.assertEqual(a.pivots(m),a.pivots(m,True))

    def test_no_future_candles_or_pivots(self):
        c=1000+np.cumsum(np.tile([3,2,-1,-4,1,2],20))
        m5=bars(c,300);m15=bars(c,900);at=18000
        p=a.state_at(at,1000,22,m5,m15)
        self.assertEqual(p,a.state_at(at,1000,22,m5,m15,True))
        for data in (m5,m15):
            for k in ('open','high','low','close'):data[k][data['known']>at]+=100000
        self.assertEqual(p,a.state_at(at,1000,22,m5,m15))

    def test_exact_close_boundary(self):
        m5=bars(np.tile([10,12,11,13],30),300);m15=bars(np.tile([10,12,11,13],40),900)
        for at in (17999,18000,18001):
            p=a.state_at(at,11,2,m5,m15)
            self.assertEqual(p,a.state_at(at,11,2,m5,m15,True))
            self.assertLessEqual(p['evidence']['m5_known'],at)
            self.assertLessEqual(p['evidence']['m15_known'],at)
        self.assertEqual(a.state_at(18000,11,2,m5,m15)['evidence']['m15_known'],18000)
        self.assertEqual(a.state_at(17999,11,2,m5,m15)['evidence']['m15_known'],17100)

    def test_m5_gap_not_imputed(self):
        m5=bars(np.tile([10,12,11,13],30),300);m15=bars(np.tile([10,12,11,13],40),900)
        m5={k:np.delete(v,50) for k,v in m5.items()}
        p=a.state_at(18000,11,2,m5,m15)
        self.assertIsNone(p['weaker_rallies']);self.assertIsNone(p['stronger_selloffs'])

    def test_unknown_conjunction(self):
        self.assertIsNone(a.conjunction(None,False));self.assertIsNone(a.conjunction(True,None))
        self.assertFalse(a.conjunction(False,True));self.assertTrue(a.conjunction(True,True))

    def test_streak_ties_no_arbitrary_order(self):
        rows=[dict(symbol='GBPJPY',id=str(i),entry_time=i*10,exit_time=t,outcome=o,net_r=-1 if o=='SL' else 2)
              for i,(t,o) in enumerate([(100,'SL'),(100,'SL'),(200,'SL'),(300,'SL'),(300,'TP'),(400,'SL'),(500,'SL'),(600,'SL'),(700,'TP')])]
        p=a.streaks(rows);self.assertEqual(p,a.streaks(rows,True))
        self.assertEqual([r['count'] for r in p],[3,3])
        self.assertEqual(p[0]['initial_ids'],['0','1'])
        self.assertIsNone(p[0]['recovery_id']) # every trade already entered before last SL

    def test_atr_exact_boundary_and_gap(self):
        m5=bars(np.tile([100,102,101,103],50),300);m15=bars([100]*50,900)
        p=a.state_at(27000,100,4,m5,m15);self.assertFalse(p['stop_smaller_than_m15_atr'])
        self.assertTrue(a.state_at(27000,100,3,m5,m15)['stop_smaller_than_m15_atr'])
        m15={k:np.delete(v,25) for k,v in m15.items()}
        self.assertIsNone(a.state_at(27000,100,3,m5,m15)['stop_smaller_than_m15_atr'])


if __name__=='__main__':unittest.main()
