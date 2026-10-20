import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.pop("FUYAO_API_KEY", None); os.environ.pop("ANTHROPIC_API_KEY", None)
from app import datasource as ds
from app.parser import parse_intent, validate_conditions, detect_conflicts, check_compliance
from app.engine import evaluate, summarize, sensitivity
from app.backtest import lookback

def mk(metrics, missing=None, code="000001.SZ"):
    return {"code": code, "name": code, "metrics": {k: {"v": v, "asof": "2025-01-01", "src": "t", "field": "f"} for k, v in metrics.items()}, "missing": missing or {}, "series": None}

class MainChain(unittest.TestCase):
    def test_vague_phrase_to_conditions(self):
        r = parse_intent("经营改善、估值合理、走势相对稳定")
        self.assertEqual({c["term"] for c in r["conditions"]}, {"经营改善", "估值合理", "走势相对稳定"})
        self.assertEqual(len(r["clarifications"]), 3)           # 每个模糊词都要求口径确认
    def test_level_changes_threshold(self):
        s = parse_intent("估值合理", {"估值合理": "strict"})["conditions"][0]; l = parse_intent("估值合理", {"估值合理": "loose"})["conditions"][0]
        self.assertEqual((s["value"], l["value"]), ([0, 20], [0, 45]))
    def test_unmatched_reported(self):
        self.assertIn("护城河深", parse_intent("估值合理，护城河深")["unmatched"])
    def test_engine_pass_fail_missing_and_policy(self):
        f = {"stocks": {"A": mk({"pe_ttm": 10}, code="A"), "B": mk({"pe_ttm": 50}, code="B"), "C": mk({}, {"pe_ttm": "上游null"}, code="C")}}
        c = [{"id": "1", "metric": "pe_ttm", "op": "lte", "value": 30, "enabled": True, "label": "PE", "unit": "倍"}]
        v = {r["code"]: r["verdict"] for r in evaluate(c, f)}
        self.assertEqual(v, {"A": "selected", "B": "excluded", "C": "undetermined"})   # 缺失不得静默通过
        self.assertEqual({r["code"]: r["verdict"] for r in evaluate(c, f, "include")}["C"], "selected_incomplete")
    def test_explanation_traceable(self):
        f = {"stocks": {"B": mk({"pe_ttm": 50}, code="B")}}
        c = [{"id": "1", "metric": "pe_ttm", "op": "lte", "value": 30, "enabled": True, "label": "PE", "unit": "倍"}]
        k = evaluate(c, f)[0]["checks"][0]; self.assertEqual((k["value"], k["asof"], k["need"], k["gap"]), (50, "2025-01-01", 50, 20))
    def test_sensitivity_remove_condition_adds_stock(self):
        f = {"stocks": {"B": mk({"pe_ttm": 50, "vol": 10}, code="B")}}
        c = [{"id": "1", "metric": "pe_ttm", "op": "lte", "value": 30, "enabled": True, "label": "PE", "unit": ""}, {"id": "2", "metric": "vol", "op": "lte", "value": 20, "enabled": True, "label": "V", "unit": ""}]
        s = sensitivity(c, f, "exclude"); self.assertEqual(s["perCondition"][0]["ifRemoved"]["delta"], 1); self.assertEqual(len(s["nearMiss"]), 1)
    def test_demo_end_to_end(self):
        r = parse_intent("经营改善、估值合理、走势相对稳定"); f = ds.get_facts(ds.get_universe())
        rows = evaluate(r["conditions"], f)
        s = summarize(rows); self.assertEqual(s["selected"] + s["excluded"] + s["undetermined"], s["total"])
    def test_demo_deterministic(self):
        a = ds.get_facts(ds.get_universe()); b = ds.get_facts(ds.get_universe())
        self.assertEqual(a["stocks"]["600519.SH"]["metrics"]["pe_ttm"]["v"], b["stocks"]["600519.SH"]["metrics"]["pe_ttm"]["v"])
    def test_lookback(self):
        f = ds.get_facts(ds.get_universe()); r = lookback(f, list(f["stocks"])[:5], 60)
        self.assertEqual(len(r["portfolio"]["curve"]), 61); self.assertTrue(r["caveats"])

class Conflicts(unittest.TestCase):
    def test_hard_conflict_same_metric(self):
        c, _ = validate_conditions([{"id": "a", "metric": "pe_ttm", "op": "lte", "value": 10}, {"id": "b", "metric": "pe_ttm", "op": "gte", "value": 30}])
        self.assertEqual(detect_conflicts(c)[0]["severity"], "hard")
    def test_semantic_conflict(self):
        r = parse_intent("高弹性、走势稳定"); self.assertTrue(any(c["severity"] == "hard" for c in r["conflicts"]))
    def test_growth_vs_valuation_soft(self):
        self.assertTrue(any(c["severity"] == "soft" for c in parse_intent("高成长，估值合理")["conflicts"]))

class Failures(unittest.TestCase):
    def setUp(self): os.environ["FUYAO_API_KEY"] = "x"; ds._cache.clear()
    def tearDown(self): os.environ.pop("FUYAO_API_KEY", None)
    def test_all_api_down_marks_missing_not_normal(self):
        with mock.patch.object(ds, "fuyao", side_effect=ds.ApiError("code=2001 invalid key")):
            f = ds.get_facts([{"code": "600519.SH", "name": "x"}])
        self.assertTrue(f["errors"]); self.assertEqual(f["stocks"]["600519.SH"]["metrics"], {})
        c = [{"id": "1", "metric": "pe_ttm", "op": "lte", "value": 30, "enabled": True, "label": "PE", "unit": ""}]
        self.assertEqual(evaluate(c, f)[0]["verdict"], "undetermined")
    def test_null_and_nonpositive_base(self):
        def fake(path, p):
            if "valuations" in path: return {"timestamp": 1735689600000, "item": [{"thscode": "600519.SH", "name": "茅台", "pe_ttm": None, "pb_mrq": 8}]}
            if "income" in path: return {"item": [{"fiscal_year": 2025, "fiscal_period": "Q2", "period_end_ms": 1751212800000, "operating_income": 10, "parent_holder_net_profit": 5},
                                                  {"fiscal_year": 2024, "fiscal_period": "Q2", "period_end_ms": 1719676800000, "operating_income": 8, "parent_holder_net_profit": -1}]}
            raise ds.ApiError("boom")
        with mock.patch.object(ds, "fuyao", side_effect=fake):
            s = ds.get_facts([{"code": "600519.SH", "name": "x"}])["stocks"]["600519.SH"]
        self.assertIn("pe_ttm", s["missing"]); self.assertIn("≤0", s["missing"]["np_yoy"]); self.assertAlmostEqual(s["metrics"]["rev_yoy"]["v"], 25.0)
        self.assertIn("vol", s["missing"])
    def test_short_history(self):
        bars = [{"date_ms": i * 86400000, "close_price": 10 + i} for i in range(20)]
        def fake(path, p):
            if "historical" in path: return {"item": bars}
            raise ds.ApiError("x")
        with mock.patch.object(ds, "fuyao", side_effect=fake):
            s = ds.get_facts([{"code": "600519.SH", "name": "x"}])["stocks"]["600519.SH"]
        self.assertIn("样本不足", s["missing"]["vol"])

class Compliance(unittest.TestCase):
    def test_blocked(self):
        for t in ["稳赚不赔的股票", "明天涨停的股票", "我该不该买茅台", "保证收益", "推荐买入哪只"]:
            self.assertTrue(check_compliance(t)["blocked"], t); self.assertEqual(parse_intent(t)["conditions"], [])
    def test_normal_not_blocked(self):
        self.assertFalse(check_compliance("经营改善、估值合理、走势相对稳定")["blocked"])
    def test_invalid_conditions_rejected(self):
        _, e = validate_conditions([{"metric": "rm_rf", "op": "gte", "value": 1}, {"metric": "pe_ttm", "op": "eval", "value": 1}, {"metric": "pe_ttm", "op": "lte", "value": "abc"}, {"metric": "pe_ttm", "op": "between", "value": [9, 1]}])
        self.assertEqual(len(e), 4)

if __name__ == "__main__": unittest.main()
