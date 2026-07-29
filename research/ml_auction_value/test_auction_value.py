from __future__ import annotations

import unittest
import numpy as np
import pandas as pd

from build_outcomes import FirstCrossIndex, StateView
from build_profiles import profile_one
from variant_models import acct


class AuctionValueUnitTests(unittest.TestCase):
    def test_nan_safe_first_cross_matches_bruteforce(self) -> None:
        values=np.array([np.nan,3.0,5.0,np.nan,2.0,7.0,1.0])
        index=FirstCrossIndex(values)
        for left in range(len(values)):
            for right in range(left+1,len(values)+1):
                for threshold in (0.0,1.5,4.0,8.0):
                    finite=np.flatnonzero(np.isfinite(values[left:right]))+left
                    le=next((int(i) for i in finite if values[i]<=threshold),len(values))
                    ge=next((int(i) for i in finite if values[i]>=threshold),len(values))
                    self.assertEqual(index.first_le(left,right,threshold),le)
                    self.assertEqual(index.first_ge(left,right,threshold),ge)

    def test_profile_is_bounded_by_source_day(self) -> None:
        day=pd.DataFrame({'open':[100.0,101.0,100.5],'high':[102.0,103.0,101.5],'low':[99.0,100.0,99.5],'close':[101.0,100.5,101.0],'volume':[10.0,15.0,12.0],'turnover':[1005.0,1515.0,1206.0]})
        profile=profile_one(day,log_step=0.001,value_fraction=0.70)
        self.assertLessEqual(profile['profile_low'],day.low.min())
        self.assertGreaterEqual(profile['profile_high'],day.high.max())
        self.assertLessEqual(profile['val'],profile['poc'])
        self.assertLessEqual(profile['poc'],profile['vah'])
        self.assertGreaterEqual(profile['value_fraction_observed'],0.70)

    def test_state_exit_is_structural_not_elapsed(self) -> None:
        g=pd.DataFrame({'decision_ms':np.arange(6,dtype=np.int64)*300_000,'close':[101.0,102.0,101.5,99.5,100.5,98.0],'trail_lo_12':[np.nan,95.0,95.0,95.0,101.0,101.0],'trail_hi_12':[np.nan,105.0,105.0,105.0,100.0,100.0],'trail_lo_24':[np.nan,94.0,94.0,94.0,94.0,94.0],'trail_hi_24':[np.nan,106.0,106.0,106.0,106.0,106.0]})
        state=StateView(g)
        self.assertEqual(state.continuation_exit(0,len(g),1,100.0,12),3)
        self.assertEqual(state.excursion_exit(0,len(g),1,102.5),len(g))
        self.assertEqual(state.excursion_exit(0,len(g),-1,99.0),5)

    def test_global_slot_prefers_higher_action_value(self) -> None:
        rows=pd.DataFrame({'year':[2022,2022],'symbol':['BTCUSDT','ETHUSDT'],'decision_ms':[1000,1000],'entry_ts_ms':[2000,2000],'cont_mean':[0.01,0.02],'cont_q35':[0.01,0.02],'rev_mean':[-0.01,-0.01],'rev_q35':[-0.01,-0.01],'cont_unit_return':[-0.10,0.10],'cont_exit_ts_ms':[5000,5000],'rev_unit_return':[-0.10,-0.10],'rev_exit_ts_ms':[5000,5000]})
        result=acct(rows,2022,'mean')
        self.assertEqual(result['trades'],1)
        self.assertAlmostEqual(result['return'],0.10,places=12)


if __name__=='__main__':
    unittest.main()
