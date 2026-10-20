"""历史回看：等权持有所选股票，对比股票池等权基准。条件用“当前”数据，存在前视偏差，不代表策略有效性。"""


def _mdd(curve):
    peak, d = curve[0], 0.0
    for x in curve:
        peak = max(peak, x); d = min(d, x / peak - 1)
    return d


def lookback(facts, codes, days=60):
    pick = [facts["stocks"][c] for c in codes if c in facts["stocks"] and facts["stocks"][c].get("series") and len(facts["stocks"][c]["series"]) > days]
    if not pick: return {"error": "所选股票缺少足够的价格序列"}
    allst = [s for s in facts["stocks"].values() if s.get("series") and len(s["series"]) > days]

    def curve(lst):
        out = []
        for i in range(days + 1):
            acc = 0.0
            for s in lst:
                arr = s["series"]; base = arr[-1 - days]["c"]; acc += arr[len(arr) - (days + 1) + i]["c"] / base
            out.append(acc / len(lst))
        return out
    pc, bc = curve(pick), curve(allst)
    r = lambda s: s["series"][-1]["c"] / s["series"][-1 - days]["c"] - 1
    return {"days": days, "n": len(pick), "baselineN": len(allst), "dates": [x["d"] for x in pick[0]["series"][-(days + 1):]],
            "portfolio": {"curve": pc, "totalReturnPct": round((pc[-1] - 1) * 100, 2), "maxDrawdownPct": round(_mdd(pc) * 100, 2)},
            "baseline": {"curve": bc, "totalReturnPct": round((bc[-1] - 1) * 100, 2), "maxDrawdownPct": round(_mdd(bc) * 100, 2)},
            "perStock": [{"code": s["code"], "name": s["name"], "returnPct": round(r(s) * 100, 2)} for s in pick],
            "caveats": ["等权、不含交易成本与分红再投资（价格为前复权）", "筛选条件基于当前最新数据，回看区间内并未按当时可得信息调仓（前视偏差）", "历史表现不代表未来，本结果不构成投资建议"]}
