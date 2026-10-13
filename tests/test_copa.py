import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import copa

CFG = {"season": 2026, "seed_week": 5, "teams_per_series": 12, "leagues": {s: s for s in copa.SERIES}}

def build(week, state):
    return copa.run(CFG, copa.MockSleeper(week), week, Path(state), Path(state) / "cup.json")

class CopaTests(unittest.TestCase):
    def test_before_seeds_frozen(self):
        with tempfile.TemporaryDirectory() as d:
            data = build(5, d)
            self.assertFalse(data["seeds_frozen"])
            self.assertFalse((Path(d) / "seeds.json").exists())

    def test_phase1_covers_56_teams_once(self):
        with tempfile.TemporaryDirectory() as d:
            data = build(6, d)
            self.assertTrue(data["seeds_frozen"])
            f1 = data["rounds"][0]["matches"]
            self.assertEqual(len(f1), 28)
            ids = [m[s]["id"] for m in f1 for s in "ab"]
            self.assertEqual(len(set(ids)), 56)
            self.assertNotIn("A1", ids); self.assertNotIn("A4", ids)
            self.assertEqual((f1[0]["a"]["id"], f1[0]["b"]["id"]), ("A5", "E12"))
            # mesmo desenho do ano passado: C5 x C12 ... e C1 x D4
            pares = {(m["a"]["id"], m["b"]["id"]) for m in f1}
            self.assertIn(("C5", "C12"), pares); self.assertIn(("C1", "D4"), pares)

    def test_phase2_draw_is_stable_and_valid(self):
        with tempfile.TemporaryDirectory() as d:
            data = build(8, d)
            f2 = data["rounds"][1]["matches"]
            ids = [m[s]["id"] for m in f2 for s in "ab"]
            self.assertEqual(len(f2), 16); self.assertEqual(len(set(ids)), 32)
            for a in ("A1", "A2", "A3", "A4"):
                self.assertIn(a, ids)
            top = {"A1", "A2", "A3", "A4"}
            pos = {m[s]["id"]: i for i, m in enumerate(f2) for s in "ab" if m[s]["id"] in top}
            self.assertEqual(sorted(p // 4 for p in pos.values()), [0, 1, 2, 3])  # um A por quarto
            again = build(8, d)  # nova execução não pode mudar o sorteio
            self.assertEqual(data["draw"], again["draw"])

    def test_full_season(self):
        with tempfile.TemporaryDirectory() as d:
            data = build(18, d)
            sizes = [len(r["matches"]) for r in data["rounds"]]
            self.assertEqual(sizes, [28, 16, 8, 4, 2, 1])
            self.assertIsNotNone(data["champion"])
            self.assertEqual(len(data["eliminated"]), 59)
            self.assertNotIn(data["champion"], data["eliminated"])
            for s in copa.SERIES:
                self.assertIsNotNone(data["toilet"]["series"][s]["loser"])

    def test_midway_has_placeholders(self):
        with tempfile.TemporaryDirectory() as d:
            data = build(11, d)
            qf = data["rounds"][3]["matches"]
            self.assertTrue(all(m["a"] is None for m in qf))
            self.assertTrue(qf[0]["tbd_a"].startswith("Venc."))

if __name__ == "__main__":
    unittest.main()
