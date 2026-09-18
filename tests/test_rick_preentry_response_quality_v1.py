from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import audit_rick_preentry_response_quality_v1 as a


def bars(known,close,opens=None,hi=None,lo=None):
    return {k:np.array(v,dtype=np.int64) for k,v in dict(known=known,close=close,open=opens or close,high=hi or close,low=lo or close).items()}


class Tests(unittest.TestCase):
    def test_future_candle_never_used(self):
        m=bars([300,600,900,1200,1500],[100,99,98,97,150],opens=[99]*5,hi=[105]*4+[200],lo=[90]*5)
        x=a.extract(1200,900,100,None,m,m)
        self.assertTrue(x['selling_into_fill']);self.assertTrue(x['trigger_not_held'])
        self.assertEqual(x,a.extract(1200,900,100,None,{k:v[:-1] for k,v in m.items()},{k:v[:-1] for k,v in m.items()}))
        self.assertEqual(x,a.extract(1200,900,100,None,m,m,True))

    def test_strong_confirmation_exact_boundary(self):
        m=bars([300],[106],opens=[102],hi=[108],lo=[100])
        self.assertFalse(a.extract(300,300,100,None,m,m)['weak_confirmation'])

    def test_stale_quote_is_unknown(self):
        m=bars([300],[106],hi=[108],lo=[100])
        x=a.extract(600,300,100,None,m,m)
        self.assertIsNone(x['trigger_not_held']);self.assertIsNone(x['selling_into_fill'])

    def test_gap_cannot_be_three_bar_momentum(self):
        m=bars([300,600,1200,1500],[100,99,98,97])
        self.assertIsNone(a.extract(1500,1500,100,None,m,m)['selling_into_fill'])

    def test_absent_confirmation_stays_unknown(self):
        m=bars([300,900],[100,110])
        self.assertIsNone(a.extract(900,600,100,None,m,m)['weak_confirmation'])

    def test_future_signal_rejected(self):
        m=bars([300],[100])
        with self.assertRaises(ValueError):a.extract(300,600,100,None,m,m)

    def test_zero_range_weak(self):
        m=bars([300],[100])
        self.assertTrue(a.extract(300,300,100,None,m,m)['weak_confirmation'])

    def test_delay_and_body_break_equality(self):
        m=bars([300,1200],[100,99]);w=dict(confirmation_close_points=100,neckline_wick_points=100)
        x=a.extract(1200,300,100,w,m,m)
        self.assertTrue(x['delayed_fill']);self.assertTrue(x['body_only_w_break'])

    def test_summary_reproduction(self):
        rows=[]
        for y in ('2023','2024','2025','2026'):
            for j in range(12):
                rows.append(dict(net_r=-1 if j%2 else 2,entry_year=y,entry_month=y+'-'+str(j+1).zfill(2),entry_day=y+'-'+str(j+1).zfill(2)+'-01',
                    flag=j%2==1,outcome='SL' if j%2 else 'TP',half_r_response=j%2==0,structure_failed_by_horizon=j%2==1))
        self.assertEqual(a.compare(rows,'flag'),a.compare(rows,'flag',True))


if __name__=='__main__':unittest.main()
