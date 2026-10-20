"""零依赖 HTTP 服务（Python 3.9+）。python3 server.py"""
import json, os, re, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).parent
envf = ROOT / ".env"
if envf.exists():
    for line in envf.read_text().splitlines():
        m = re.match(r"\s*([A-Z_]+)\s*=\s*(.*?)\s*$", line)
        if m and m.group(2) and m.group(1) not in os.environ: os.environ[m.group(1)] = m.group(2)

from app import datasource as ds
from app.parser import parse_intent, validate_conditions, detect_conflicts
from app.engine import evaluate, summarize, sensitivity
from app.backtest import lookback
from app.catalog import METRICS

DATA = ROOT / "data"; DATA.mkdir(exist_ok=True)
DISCLAIMER = "本工具仅做数据筛选与解释，结果为基于所选口径和数据时点的事实性筛选，不构成投资建议，不预测涨跌，不承诺收益。"


def load(f):
    try: return json.loads((DATA / f).read_text())
    except Exception: return []


def save(f, v): (DATA / f).write_text(json.dumps(v, ensure_ascii=False, indent=2))


def data_status(facts):
    live = facts["mode"] == "live"; w = []
    if not live: w.append("当前为【示例数据】模式：数值为合成数据，不代表真实行情/财务。配置 FUYAO_API_KEY 后切换为真实数据。")
    if facts["errors"]: w.append(f"数据接口出现 {len(facts['errors'])} 个错误（如 {facts['errors'][0]['scope']}: {facts['errors'][0]['msg']}），相关股票的条件已标记为“缺失”，未被当作正常处理。")
    if live and not facts["stocks"]: w.append("数据源完全不可用，无法产生任何结果。")
    asofs = sorted({m["asof"] for s in facts["stocks"].values() for m in s["metrics"].values() if m.get("asof")})
    return {"mode": facts["mode"], "warnings": w, "errorCount": len(facts["errors"]), "errors": facts["errors"][:10], "asofRange": [asofs[0], asofs[-1]] if asofs else None}


def run_screen(b):
    conds, errs = validate_conditions(b.get("conditions"))
    if errs: return 400, {"error": "条件不合法", "details": errs}
    if not any(c["enabled"] for c in conds): return 400, {"error": "没有启用的条件"}
    policy = "include" if b.get("missingPolicy") == "include" else "exclude"
    uni = ds.get_universe()
    if isinstance(b.get("universe"), list) and b["universe"]:
        uni = [{"code": c.upper(), "name": c.upper()} for c in b["universe"] if re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", str(c), re.I)]
    facts = ds.get_facts(uni); rows = evaluate(conds, facts, policy); summ = summarize(rows)
    return 200, {"conditions": conds, "conflicts": detect_conflicts(conds), "policy": policy, "summary": summ, "rows": rows,
                 "sensitivity": sensitivity(conds, facts, policy), "dataStatus": data_status(facts), "disclaimer": DISCLAIMER,
                 "zeroResultHint": "没有股票满足全部条件。可参考“条件变化影响”逐条放宽，或检查是否存在冲突条件。" if summ["selected"] == 0 else None}


def post_parse(b):
    t = str(b.get("text") or "").strip()
    if not t: return 400, {"error": "请输入选股描述"}
    return 200, {**parse_intent(t[:500], b.get("levels") or {}), "disclaimer": DISCLAIMER}


def post_backtest(b):
    codes = (b.get("codes") or [])[:50]
    if not codes: return 400, {"error": "请先选择股票"}
    try: days = min(max(int(b.get("days") or 60), 20), 100)
    except (ValueError, TypeError): days = 60
    facts = ds.get_facts(ds.get_universe()); r = lookback(facts, codes, days)
    return (422 if "error" in r else 200), {**r, "dataStatus": data_status(facts), "disclaimer": DISCLAIMER}


def post_saved(b):
    lst = load("saved.json"); item = {"id": format(int(time.time() * 1000), "x"), "name": str(b.get("name") or "未命名")[:60], "text": b.get("text", ""),
        "conditions": b.get("conditions", []), "codes": b.get("codes", []), "savedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
    lst.insert(0, item); save("saved.json", lst[:50]); return 200, item


def post_monitor(b):
    conds, errs = validate_conditions(b.get("conditions"))
    if errs or not conds: return 400, {"error": "条件不合法", "details": errs}
    facts = ds.get_facts(ds.get_universe()); rows = evaluate(conds, facts, "exclude")
    m = {"id": format(int(time.time() * 1000), "x"), "name": str(b.get("name") or "监控任务")[:60], "conditions": conds,
         "baseline": [r["code"] for r in rows if r["verdict"] == "selected"], "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "lastRun": None, "mode": facts["mode"]}
    lst = load("monitors.json"); lst.insert(0, m); save("monitors.json", lst); return 200, m


def run_monitor(mid):
    lst = load("monitors.json"); m = next((x for x in lst if x["id"] == mid), None)
    if not m: return 404, {"error": "任务不存在"}
    facts = ds.get_facts(ds.get_universe()); rows = evaluate(m["conditions"], facts, "exclude")
    now = [r["code"] for r in rows if r["verdict"] == "selected"]; nm = {r["code"]: r["name"] for r in rows}
    m["lastRun"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "count": len(now), "dataStatus": data_status(facts),
                    "entered": [{"code": c, "name": nm[c]} for c in now if c not in m["baseline"]],
                    "left": [{"code": c, "name": nm.get(c, c)} for c in m["baseline"] if c not in now]}
    save("monitors.json", lst); return 200, m


ROUTES = {
    ("GET", "/api/status"): lambda b: (200, {"mode": "live" if os.environ.get("FUYAO_API_KEY") else "demo", "llm": bool(os.environ.get("ANTHROPIC_API_KEY")),
                                           "universeSize": len(ds.get_universe()), "metrics": METRICS, "disclaimer": DISCLAIMER}),
    ("POST", "/api/parse"): post_parse, ("POST", "/api/screen"): run_screen, ("POST", "/api/backtest"): post_backtest,
    ("GET", "/api/saved"): lambda b: (200, load("saved.json")), ("POST", "/api/saved"): post_saved,
    ("GET", "/api/monitors"): lambda b: (200, load("monitors.json")), ("POST", "/api/monitors"): post_monitor,
}
MIME = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode(); self.send_response(code)
        self.send_header("content-type", "application/json; charset=utf-8"); self.send_header("content-length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def _handle(self, method):
        path = self.path.split("?")[0]
        try:
            n = int(self.headers.get("content-length") or 0); raw = self.rfile.read(n) if n else b""
            try: body = json.loads(raw) if raw else {}
            except ValueError: return self._send(400, {"error": "请求体不是合法 JSON"})
            if not isinstance(body, dict): return self._send(400, {"error": "请求体必须是 JSON 对象"})
            if method == "DELETE":
                m = re.fullmatch(r"/api/(saved|monitors)/(\w+)", path)
                if m: f = m.group(1) + ".json"; save(f, [x for x in load(f) if x["id"] != m.group(2)]); return self._send(200, {"ok": True})
            m = re.fullmatch(r"/api/monitors/(\w+)/run", path)
            if method == "POST" and m: return self._send(*run_monitor(m.group(1)))
            fn = ROUTES.get((method, path))
            if fn: return self._send(*fn(body))
            if method == "GET":
                p = (ROOT / "public" / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
                if str(p).startswith(str(ROOT / "public")) and p.is_file():
                    data = p.read_bytes(); self.send_response(200); self.send_header("content-type", MIME.get(p.suffix, "application/octet-stream") + "; charset=utf-8")
                    self.send_header("content-length", str(len(data))); self.end_headers(); return self.wfile.write(data)
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(500, {"error": f"服务内部错误：{e}"})

    do_GET = lambda s: s._handle("GET"); do_POST = lambda s: s._handle("POST"); do_DELETE = lambda s: s._handle("DELETE")

    def log_message(self, *a): pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    print(f"http://localhost:{port}  mode={'live' if os.environ.get('FUYAO_API_KEY') else 'demo'}")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
