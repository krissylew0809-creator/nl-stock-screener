"""意图解析：规则解析为确定性兜底；LLM 可选，输出必须通过 validate_conditions。"""
import json, os, re, urllib.request
from .catalog import METRICS, LEXICON, COMPLIANCE_PATTERNS

LEVELS = ["strict", "standard", "loose"]
OPS = ["gte", "lte", "gt", "lt", "between"]
OPSYM = {"gte": "≥", "lte": "≤", "gt": ">", "lt": "<", "between": "介于"}


def check_compliance(text):
    for rx, reason in COMPLIANCE_PATTERNS:
        if rx.search(text):
            return {"blocked": True, "reason": reason}
    return {"blocked": False}


def _fmt(v):
    return f"{v[0]}~{v[1]}" if isinstance(v, list) else v


def _build(entry, level):
    return [{"id": f"{entry['term']}_{i}", "term": entry["term"], "metric": c["metric"], "op": c["op"], "value": c["levels"][level],
             "level": level, "enabled": True, "label": METRICS[c["metric"]]["label"], "unit": METRICS[c["metric"]]["unit"]}
            for i, c in enumerate(entry["conds"])]


def _describe_level(entry, lv):
    return "；".join(f"{METRICS[c['metric']]['label']} {OPSYM[c['op']]} {_fmt(c['levels'][lv])}{METRICS[c['metric']]['unit']}" for c in entry["conds"])


def parse_rules(text, level_by_term=None):
    level_by_term = level_by_term or {}
    conds, clar, rest = [], [], text
    for entry in LEXICON:
        hit = next((k for k in entry["kw"] if k in text), None)
        if not hit:
            continue
        rest = rest.replace(hit, " ")
        lv = level_by_term.get(entry["term"]) if level_by_term.get(entry["term"]) in LEVELS else "standard"
        conds += _build(entry, lv)
        clar.append({"term": entry["term"], "matchedText": hit, "level": lv,
                     "question": f"“{hit}”没有统一量化标准，请确认口径（默认「标准」，可随时调整）：",
                     "options": [{"level": l, "desc": _describe_level(entry, l)} for l in LEVELS]})
    unmatched = [s for s in re.split(r"[，。、；,.;\s和且并与及]+", rest) if len(s.strip()) >= 2]
    return conds, clar, unmatched


def validate_conditions(items):
    errors, out = [], []
    for i, c in enumerate(items if isinstance(items, list) else []):
        n = i + 1
        if not isinstance(c, dict) or c.get("metric") not in METRICS:
            errors.append(f"第{n}条：未知指标 {c.get('metric') if isinstance(c, dict) else c}"); continue
        if c.get("op") not in OPS:
            errors.append(f"第{n}条：未知算子 {c.get('op')}"); continue
        v = c.get("value")
        try:
            if c["op"] == "between":
                if not (isinstance(v, list) and len(v) == 2):
                    raise ValueError
                v = [float(v[0]), float(v[1])]
                if v[0] > v[1]:
                    errors.append(f"第{n}条：区间下限大于上限"); continue
            else:
                if isinstance(v, (list, bool)) or v is None:
                    raise ValueError
                v = float(v)
        except (ValueError, TypeError):
            errors.append(f"第{n}条：阈值不合法"); continue
        out.append({"id": c.get("id") or f"c{i}", "term": c.get("term") or "自定义", "metric": c["metric"], "op": c["op"], "value": v,
                    "level": c.get("level") or "custom", "enabled": c.get("enabled") is not False,
                    "label": METRICS[c["metric"]]["label"], "unit": METRICS[c["metric"]]["unit"]})
    return out, errors


def _range(c):
    if c["op"] in ("gte", "gt"): return (c["value"], float("inf"))
    if c["op"] in ("lte", "lt"): return (float("-inf"), c["value"])
    return tuple(c["value"])


def detect_conflicts(conditions):
    active = [c for c in conditions if c.get("enabled", True)]
    out = []
    by = {}
    for c in active: by.setdefault(c["metric"], []).append(c)
    for m, cs in by.items():
        if len(cs) < 2: continue
        lo = max(_range(c)[0] for c in cs); hi = min(_range(c)[1] for c in cs)
        if lo > hi:
            out.append({"severity": "hard", "metric": m, "conditionIds": [c["id"] for c in cs],
                        "message": f"「{METRICS[m]['label']}」的多个条件互相矛盾（要求同时 ≥{lo} 且 ≤{hi}），不可能有股票同时满足。"})
    terms = {c["term"] for c in active}

    def tension(a, b, msg, sev="soft"):
        if a in terms and b in terms:
            out.append({"severity": sev, "terms": [a, b], "conditionIds": [c["id"] for c in active if c["term"] in (a, b)], "message": msg})
    tension("高成长", "估值合理", "「高成长」与「估值合理」存在张力：高增速股票往往估值偏高，组合下候选可能很少，可放宽其中一项口径。")
    tension("高成长", "走势相对稳定", "「高成长」与「走势相对稳定」存在张力：成长股通常波动更大。")
    tension("高弹性", "走势相对稳定", "「高弹性」与「走势相对稳定」直接冲突：前者要求波动大，后者要求波动小。", "hard")
    tension("高成长", "财务稳健", "「高成长」与「财务稳健」可能存在张力：扩张常伴随更高负债。")
    return out


def parse_llm(text):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key: return None
    cat = "\n".join(f"{k}: {m['label']}({m['unit']})" for k, m in METRICS.items())
    prompt = (f"把投资者的选股描述转成筛选条件 JSON。只能使用以下指标 key：\n{cat}\n算子：gte,lte,gt,lt,between(value 为[下限,上限])。\n"
              '只输出 JSON：{"conditions":[{"term":"原话片段","metric":"","op":"","value":0}],"unmatched":["无法量化的片段"]}。不要输出买卖建议或预测。\n'
              f"描述：{text}")
    try:
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", method="POST",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            data=json.dumps({"model": os.environ.get("LLM_MODEL", "claude-sonnet-5-5"), "max_tokens": 800, "messages": [{"role": "user", "content": prompt}]}).encode())
        with urllib.request.urlopen(req, timeout=15) as r:
            j = json.load(r)
        t = "".join(b.get("text", "") for b in j.get("content", []))
        m = re.search(r"\{[\s\S]*\}", t)
        if not m: return {"error": "LLM 未返回 JSON"}
        p = json.loads(m.group(0))
        conds, rej = validate_conditions([{**c, "id": f"llm_{i}", "level": "llm"} for i, c in enumerate(p.get("conditions", []))])
        return {"conditions": conds, "rejected": rej, "unmatched": p.get("unmatched", [])}
    except Exception as e:
        return {"error": str(e)}


def parse_intent(text, level_by_term=None):
    comp = check_compliance(text)
    if comp["blocked"]:
        return {"compliance": comp, "conditions": [], "clarifications": [], "conflicts": [], "unmatched": [], "parser": "blocked"}
    conds, clar, unmatched = parse_rules(text, level_by_term)
    parser, note = "rules", None
    llm = parse_llm(text)
    if llm and llm.get("error"):
        note = f"LLM 解析失败，已回退到规则解析：{llm['error']}"
    elif llm and llm["conditions"] and not conds:
        conds, unmatched, parser = llm["conditions"], llm["unmatched"], "llm"
        if llm["rejected"]: note = f"LLM 输出中 {len(llm['rejected'])} 条不合法条件已被丢弃：" + "；".join(llm["rejected"])
    elif llm:
        parser = "rules(LLM 结果未采纳)"
    return {"compliance": comp, "conditions": conds, "clarifications": clar, "conflicts": detect_conflicts(conds),
            "unmatched": unmatched, "parser": parser, "llmNote": note}
