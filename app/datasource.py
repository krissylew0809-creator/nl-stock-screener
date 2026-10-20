"""金融数据工具层：只负责取数与口径标注，不做任何筛选判断。无 FUYAO_API_KEY 时返回明确标注的示例数据。"""
import json, math, os, random, time, urllib.parse, urllib.request, datetime as dt
from concurrent.futures import ThreadPoolExecutor
from .universe import DEFAULT

BASE = os.environ.get("FUYAO_BASE", "https://fuyao.aicubes.cn")
_cache, TTL = {}, 30 * 60
SRC = {"val": "扶摇 valuations/snapshot", "inc": "扶摇 income-statements", "cf": "扶摇 cash-flow-statements",
       "bs": "扶摇 balance-sheets", "px": "扶摇 prices/historical"}
CST = dt.timezone(dt.timedelta(hours=8))


def fmt_date(ms): return dt.datetime.fromtimestamp(ms / 1000, CST).strftime("%Y-%m-%d")


class ApiError(Exception):
    pass


def fuyao(path, params, _try=0):
    qs = urllib.parse.urlencode(params); key = f"{path}?{qs}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL: return hit[1]
    try:
        req = urllib.request.Request(f"{BASE}{path}?{qs}", headers={"X-api-key": os.environ.get("FUYAO_API_KEY", "")})
        with urllib.request.urlopen(req, timeout=12) as r:
            j = json.load(r)
    except Exception as e:
        if _try < 1: return fuyao(path, params, _try + 1)
        raise ApiError(f"网络/超时：{e}")
    if j.get("code") != 0: raise ApiError(f"code={j.get('code')} {j.get('message', '')}")  # 业务错误不重试、不静默
    _cache[key] = (time.time(), j.get("data")); return j.get("data")


def price_metrics(bars, src=SRC["px"]):
    closes = [b["close_price"] for b in bars]
    r = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    mean = sum(r) / len(r); sd = math.sqrt(sum((x - mean) ** 2 for x in r) / (len(r) - 1))
    peak, dd = closes[0], 0.0
    for c in closes: peak = max(peak, c); dd = min(dd, c / peak - 1)
    asof = fmt_date(bars[-1]["date_ms"]); f = f"close_price(前复权) 近{len(bars)}根日线"
    return {"vol": {"v": round(sd * math.sqrt(252) * 100, 2), "asof": asof, "src": src, "field": f},
            "maxdd": {"v": round(dd * 100, 2), "asof": asof, "src": src, "field": f}}


def fuyao_facts(universe):
    errors, stocks = [], {u["code"]: {"code": u["code"], "name": u["name"], "metrics": {}, "missing": {}, "series": None} for u in universe}
    codes = list(stocks)

    def miss(code, keys, why):
        for k in keys: stocks[code]["missing"][k] = why

    for i in range(0, len(codes), 100):
        chunk = codes[i:i + 100]
        try:
            d = fuyao("/api/a-share/valuations/snapshot", {"thscodes": ",".join(chunk)}); got = set()
            asof = fmt_date(d["timestamp"]) if d.get("timestamp") else None
            for it in d.get("item") or []:
                s = stocks.get(it["thscode"])
                if not s: continue
                got.add(it["thscode"]); s["name"] = it.get("name") or s["name"]
                for k in ("pe_ttm", "pb_mrq"):
                    if it.get(k) is None: s["missing"][k] = "上游返回 null（可能亏损或未披露）"
                    else: s["metrics"][k] = {"v": it[k], "asof": asof, "src": SRC["val"], "field": k}
            for c in chunk:
                if c not in got: miss(c, ["pe_ttm", "pb_mrq"], "估值接口未返回该股票")
        except ApiError as e:
            errors.append({"scope": "valuations", "msg": str(e)})
            for c in chunk: miss(c, ["pe_ttm", "pb_mrq"], f"估值接口失败：{e}")

    end = int(time.time() * 1000); start = end - 230 * 86400000

    def one(code):
        s = stocks[code]
        try:
            items = (fuyao("/api/a-share/financials/income-statements", {"thscode": code, "period": "quarterly", "limit": 5}).get("item")) or []
            cur = items[0] if items else None
            prev = next((x for x in items if cur and x["fiscal_year"] == cur["fiscal_year"] - 1 and x["fiscal_period"] == cur["fiscal_period"]), None)
            if not cur: miss(code, ["rev_yoy", "np_yoy"], "无利润表数据")
            else:
                for k, f, nm in (("rev_yoy", "operating_income", "营业收入"), ("np_yoy", "parent_holder_net_profit", "归母净利润")):
                    a, b = cur.get(f), (prev or {}).get(f)
                    if not prev: miss(code, [k], "缺少去年同期报告，无法计算同比")
                    elif a is None or b is None: miss(code, [k], f"{f} 未披露(null)")
                    elif b <= 0: miss(code, [k], f"去年同期{nm}≤0，同比无意义")
                    else: s["metrics"][k] = {"v": round((a / b - 1) * 100, 2), "asof": fmt_date(cur["period_end_ms"]), "src": SRC["inc"],
                                             "field": f"{f} {cur['fiscal_year']}{cur['fiscal_period']} vs {prev['fiscal_year']}{prev['fiscal_period']}", "raw": {"cur": a, "prev": b}}
        except ApiError as e:
            errors.append({"scope": "income", "code": code, "msg": str(e)}); miss(code, ["rev_yoy", "np_yoy"], f"利润表接口失败：{e}")
        try:
            it = ((fuyao("/api/a-share/financials/cash-flow-statements", {"thscode": code, "period": "quarterly", "limit": 1}).get("item")) or [None])[0]
            if not it or it.get("act_cash_flow_net") is None: miss(code, ["ocf"], "现金流量表无经营现金流数据")
            else: s["metrics"]["ocf"] = {"v": round(it["act_cash_flow_net"] / 1e8, 3), "asof": fmt_date(it["period_end_ms"]), "src": SRC["cf"],
                                         "field": f"act_cash_flow_net {it['fiscal_year']}{it['fiscal_period']}", "raw": it["act_cash_flow_net"]}
        except ApiError as e:
            errors.append({"scope": "cashflow", "code": code, "msg": str(e)}); miss(code, ["ocf"], f"现金流接口失败：{e}")
        try:
            it = ((fuyao("/api/a-share/financials/balance-sheets", {"thscode": code, "period": "quarterly", "limit": 1}).get("item")) or [None])[0]
            if not it or it.get("total_debt") is None or not it.get("assets_total"): miss(code, ["debt_ratio"], "资产负债表缺少 total_debt/assets_total")
            else: s["metrics"]["debt_ratio"] = {"v": round(it["total_debt"] / it["assets_total"] * 100, 2), "asof": fmt_date(it["period_end_ms"]), "src": SRC["bs"],
                                                "field": f"total_debt/assets_total {it['fiscal_year']}{it['fiscal_period']}", "raw": {"total_debt": it["total_debt"], "assets_total": it["assets_total"]}}
        except ApiError as e:
            errors.append({"scope": "balance", "code": code, "msg": str(e)}); miss(code, ["debt_ratio"], f"资产负债表接口失败：{e}")
        try:
            d = fuyao("/api/a-share/prices/historical", {"thscode": code, "interval": "1d", "start": start, "end": end, "adjust": "forward"})
            bars = sorted([b for b in (d.get("item") or []) if (b.get("close_price") or 0) > 0], key=lambda b: b["date_ms"])[-121:]
            if len(bars) < 60: miss(code, ["vol", "maxdd"], f"日线样本不足（{len(bars)}根，至少60）")
            else:
                s["metrics"].update(price_metrics(bars)); s["series"] = [{"d": fmt_date(b["date_ms"]), "c": b["close_price"]} for b in bars]
        except ApiError as e:
            errors.append({"scope": "history", "code": code, "msg": str(e)}); miss(code, ["vol", "maxdd"], f"K线接口失败：{e}")

    with ThreadPoolExecutor(6) as ex: list(ex.map(one, codes))
    return {"mode": "live", "errors": errors, "stocks": stocks}


def demo_facts(universe):
    """确定性伪随机的合成数据，页面会标注“示例数据（非真实）”。"""
    SRCD = "示例数据（合成，非真实）"; today = dt.date.today().isoformat(); stocks = {}
    for u in universe:
        r = random.Random(u["code"]); s = {"code": u["code"], "name": u["name"], "metrics": {}, "missing": {}, "series": None}
        put = lambda k, v: s["metrics"].__setitem__(k, {"v": round(v, 2), "asof": today, "src": SRCD, "field": "synthetic", "demo": True})
        put("pe_ttm", 6 + r.random() * 50); put("pb_mrq", 0.6 + r.random() * 7); put("rev_yoy", -15 + r.random() * 55)
        put("np_yoy", -30 + r.random() * 100); put("ocf", -20 + r.random() * 150); put("debt_ratio", 15 + r.random() * 65)
        v0 = 0.012 + r.random() * 0.022; p = 50 + r.random() * 100; bars = []
        now = int(time.time() * 1000)
        for i in range(121):
            p *= 1 + (r.random() - 0.5) * 2 * v0 * 1.7; bars.append({"date_ms": now - (120 - i) * 86400000, "close_price": p})
        pm = price_metrics(bars, SRCD)
        for m in pm.values(): m["demo"] = True
        s["metrics"].update(pm); s["series"] = [{"d": fmt_date(b["date_ms"]), "c": round(b["close_price"], 3)} for b in bars]
        if r.random() < 0.07: del s["metrics"]["np_yoy"]; s["missing"]["np_yoy"] = "示例：模拟上游返回 null"
        if r.random() < 0.05: del s["metrics"]["pe_ttm"]; s["missing"]["pe_ttm"] = "示例：模拟亏损股 PE 为空"
        stocks[u["code"]] = s
    return {"mode": "demo", "errors": [], "stocks": stocks}


def get_universe():
    env = os.environ.get("UNIVERSE")
    return [{"code": c.strip().upper(), "name": c.strip().upper()} for c in env.split(",")] if env else DEFAULT


def get_facts(universe):
    if not os.environ.get("FUYAO_API_KEY"): return demo_facts(universe)
    try: return fuyao_facts(universe)
    except Exception as e: return {"mode": "live", "errors": [{"scope": "fatal", "msg": str(e)}], "stocks": {}}
