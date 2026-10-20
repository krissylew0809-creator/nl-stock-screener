"""确定性筛选引擎：同样的条件+同样的数据 → 同样的结果。不含任何 AI 判断。"""


def _test(c, v):
    op = c["op"]
    if op == "gte": return v >= c["value"]
    if op == "gt": return v > c["value"]
    if op == "lte": return v <= c["value"]
    if op == "lt": return v < c["value"]
    return c["value"][0] <= v <= c["value"][1]


def describe(c):
    u = c.get("unit", "")
    if c["op"] == "between": return f"{c['value'][0]} ~ {c['value'][1]}{u}"
    return f"{ {'gte': '≥', 'lte': '≤', 'gt': '>', 'lt': '<'}[c['op']] } {c['value']}{u}"


def _gap(c, v):
    if c["op"] == "between": return c["value"][0] - v if v < c["value"][0] else v - c["value"][1]
    return abs(v - c["value"])


def _need(c, v):
    v = round(v, 2)
    if c["op"] == "between": return [v, c["value"][1]] if v < c["value"][0] else [c["value"][0], v]
    return v


def evaluate(conditions, facts, policy="exclude"):
    active = [c for c in conditions if c.get("enabled", True)]
    rows = []
    for s in facts["stocks"].values():
        checks = []
        for c in active:
            m = s["metrics"].get(c["metric"])
            base = {"condId": c["id"], "metric": c["metric"], "label": c["label"], "rule": describe(c)}
            if m is None:
                checks.append({**base, "status": "missing", "reason": s["missing"].get(c["metric"], "数据缺失")})
            else:
                ok = _test(c, m["v"])
                checks.append({**base, "status": "pass" if ok else "fail", "value": m["v"], "unit": c.get("unit"), "asof": m.get("asof"),
                               "src": m.get("src"), "field": m.get("field"), "gap": 0 if ok else round(_gap(c, m["v"]), 2), "need": None if ok else _need(c, m["v"])})
        fails = [k for k in checks if k["status"] == "fail"]; miss = [k for k in checks if k["status"] == "missing"]
        verdict = "excluded" if fails else ("selected" if not miss else ("selected_incomplete" if policy == "include" else "undetermined"))
        rows.append({"code": s["code"], "name": s["name"], "verdict": verdict, "checks": checks, "failCount": len(fails), "missingCount": len(miss)})
    return rows


def summarize(rows):
    n = lambda v: sum(1 for r in rows if r["verdict"] == v)
    return {"total": len(rows), "selected": n("selected") + n("selected_incomplete"), "excluded": n("excluded"), "undetermined": n("undetermined")}


def sensitivity(conditions, facts, policy):
    base = evaluate(conditions, facts, policy)
    base_sel = {r["code"] for r in base if r["verdict"].startswith("selected")}
    per = []
    for c in [c for c in conditions if c.get("enabled", True)]:
        rows = evaluate([{**x, "enabled": False} if x["id"] == c["id"] else x for x in conditions], facts, policy)
        sel = [r for r in rows if r["verdict"].startswith("selected")]
        per.append({"condId": c["id"], "label": c["label"], "rule": describe(c),
                    "ifRemoved": {"selected": len(sel), "delta": len(sel) - len(base_sel),
                                  "added": [{"code": r["code"], "name": r["name"]} for r in sel if r["code"] not in base_sel]}})
    near = []
    for r in base:
        if r["verdict"] == "excluded" and r["failCount"] == 1:
            f = next(k for k in r["checks"] if k["status"] == "fail")
            near.append({"code": r["code"], "name": r["name"], "condId": f["condId"], "label": f["label"], "value": f["value"],
                         "rule": f["rule"], "need": f["need"], "gap": f["gap"], "unit": f.get("unit")})
    near.sort(key=lambda x: x["gap"])
    return {"baseSelected": len(base_sel), "perCondition": per, "nearMiss": near}
