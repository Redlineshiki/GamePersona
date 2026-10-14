"""Standalone NumPy tests; no production dependency or settings changes."""
import unittest
import numpy as np
from smooth_reference import SmoothReference, DIMENSIONS


def query(n=10, h=100, evidence=10):
    return {"N": n, "H": h, "sufficiency_reasons": [],
            "concentration": {d: .1 for d in DIMENSIONS},
            "evidence_ticks": {d: evidence for d in DIMENSIONS}}


class SmoothReferenceTests(unittest.TestCase):
    def test_weighted_midrank_and_sampling_correction(self):
        rows = [[10, 100, weight, *([e]*12)] for weight, e in [(1,0),(2,10),(3,10),(4,20)]]
        engine = SmoothReference(rows, (.4,.6), minimum_effective=1)
        p = engine.positions(query())["P"]
        self.assertAlmostEqual(p["value"], 35)
        self.assertAlmostEqual(p["cdf_lower"], .1)
        self.assertAlmostEqual(p["cdf_tie"], .5)
        self.assertAlmostEqual(p["effective_reference"], 100/30)
        expanded = [[10,100,1,*([e]*12)] for weight,e in [(1,0),(2,10),(3,10),(4,20)] for _ in range(weight)]
        self.assertAlmostEqual(SmoothReference(expanded,(.4,.6),1).positions(query())["P"]["value"], p["value"])

    def test_effective_count_not_raw_count(self):
        rows = [[10,100,1000 if i==0 else 1,*([i]*12)] for i in range(500)]
        p = SmoothReference(rows,(.4,.6)).positions(query())["P"]
        self.assertEqual(p["nearby_observations"], 500)
        self.assertLess(p["effective_reference"], 3)
        self.assertEqual(p["reason"], "insufficient_effective_reference")

    def test_continuity_at_old_group_and_kernel_boundaries(self):
        rows = [[n,100,1,*([n]*12)] for n in range(50,151)]
        engine = SmoothReference(rows,(.4,.6),1)
        a = engine.positions(query(99.999999, evidence=100))["P"]["value"]
        b = engine.positions(query(100.000001, evidence=100))["P"]["value"]
        self.assertLess(abs(a-b), .0001)
        # The first observation enters/leaves support with zero boundary weight.
        edge = np.expm1(np.log1p(50)+.4)
        a = engine.positions(query(edge-1e-7,evidence=100))["P"]["value"]
        b = engine.positions(query(edge+1e-7,evidence=100))["P"]["value"]
        self.assertLess(abs(a-b), .0001)

    def test_unknown_concentration_and_no_extrapolation(self):
        rows = [[n,100,1,*([n]*12)] for n in range(5,21)]
        engine = SmoothReference(rows,(.4,.6),1)
        s = query(); s["sufficiency_reasons"] = ["source_timeout"]
        self.assertEqual(engine.positions(s)["P"]["reason"], "source_timeout")
        s = query(); s["concentration"]["P"] = .9
        self.assertEqual(engine.positions(s)["P"]["reason"], "concentrated_evidence")
        self.assertIsNotNone(engine.positions(s,False)["P"]["value"])
        self.assertEqual(engine.positions(query(30))["P"]["reason"], "outside_reference_range")

    def test_degenerate_zero_reference(self):
        rows = [[n,100,1,*([0]*12)] for n in range(5,21)]
        self.assertEqual(SmoothReference(rows,(.4,.6),1).positions(query())["P"]["reason"], "degenerate_reference")

    def test_monotonic_evidence_and_reproducibility(self):
        rows = [[n,100,1,*([n]*12)] for n in range(5,21)]
        engine = SmoothReference(rows,(.4,.6),1)
        p = [engine.positions(query(evidence=e))["P"]["value"] for e in range(21)]
        self.assertEqual(p, sorted(p))
        self.assertEqual(engine.positions(query()), engine.positions(query()))

    def test_invalid_parameters_and_integer_precision(self):
        with self.assertRaises(ValueError):
            SmoothReference([[10,100,1,*([10]*12)]],(0,.6))
        with self.assertRaises(ValueError):
            SmoothReference([[10,100,1,*([2**54]*12)]],(.4,.6))
        with self.assertRaises(ValueError):
            SmoothReference([[10,100,1,*([10]*12)]],(.4,.6),0)


if __name__ == "__main__":
    unittest.main()
