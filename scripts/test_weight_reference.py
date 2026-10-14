"""Exposure-coordinate behavior, independently of production eligibility."""
import unittest
from weight_reference import WeightReference
from smooth_reference import DIMENSIONS


def query(w=20, n=9, h=100, evidence=20):
    return {"W": w, "N": n, "H": h, "sufficiency_reasons": [],
            "concentration": {d: .1 for d in DIMENSIONS},
            "evidence_ticks": {d: evidence for d in DIMENSIONS}}


class WeightReferenceTests(unittest.TestCase):
    def test_W_only_ignores_N_and_H(self):
        rows = [[w,w*10,1,*([w]*12)] for w in range(1,51)]
        engine = WeightReference(rows,(.2,1),minimum_effective=1)
        self.assertEqual(engine.positions(query()), engine.positions(query(n=100,h=999999)))

    def test_eligibility_still_uses_real_game_count(self):
        rows = [[w,100,1,*([w]*12)] for w in range(1,51)]
        engine = WeightReference(rows,(.2,1),minimum_effective=1)
        s = query(n=4); s["sufficiency_reasons"] = ["insufficient_games"]
        self.assertEqual(engine.positions(s)["P"]["reason"],"insufficient_games")

    def test_exposure_coordinate_is_continuous(self):
        rows = [[w,100,1,*([w]*12)] for w in range(1,51)]
        engine = WeightReference(rows,(.2,1),minimum_effective=1)
        before = engine.positions(query())["P"]["value"]
        after = engine.positions(query(w=20.0000001,n=10))["P"]["value"]
        self.assertLess(abs(before-after),.00001)

    def test_WH_uses_hours_but_not_game_count(self):
        rows = [[20,h,1,*([h]*12)] for h in range(50,201)]
        engine = WeightReference(rows,(.2,.65),mode="WH",minimum_effective=1)
        self.assertEqual(engine.positions(query()), engine.positions(query(n=100)))
        self.assertNotEqual(engine.positions(query(evidence=100))["P"]["value"],engine.positions(query(h=150,evidence=100))["P"]["value"])

    def test_tiny_nonzero_evidence_can_cross_zero_tie(self):
        rows = [[20,100,1,*([0 if i<60 else 100]*12)] for i in range(100)]
        engine = WeightReference(rows,(.2,1),minimum_effective=1)
        self.assertEqual(engine.positions(query(evidence=0))["P"]["value"],30)
        self.assertEqual(engine.positions(query(evidence=1))["P"]["value"],60)


if __name__ == "__main__":
    unittest.main()
