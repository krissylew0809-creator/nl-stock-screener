"""指标目录：确定性引擎只认这里登记的指标。AI 输出必须映射到这些 key，否则被丢弃。"""
import re

METRICS = {
    "pe_ttm": {"label": "市盈率 PE(TTM)", "unit": "倍", "source": "扶摇 /api/a-share/valuations/snapshot · pe_ttm", "note": "亏损股 PE 为空"},
    "pb_mrq": {"label": "市净率 PB(MRQ)", "unit": "倍", "source": "扶摇 /api/a-share/valuations/snapshot · pb_mrq"},
    "rev_yoy": {"label": "营业收入同比", "unit": "%", "source": "扶摇 income-statements(quarterly) · operating_income，最新报告期 vs 去年同期", "note": "同报告期同比，累计口径一致"},
    "np_yoy": {"label": "归母净利润同比", "unit": "%", "source": "扶摇 income-statements(quarterly) · parent_holder_net_profit，最新报告期 vs 去年同期", "note": "去年同期≤0时同比无意义，记为缺失"},
    "ocf": {"label": "经营现金流净额", "unit": "亿元", "source": "扶摇 cash-flow-statements(quarterly) · act_cash_flow_net", "note": "报告期累计值，元换算为亿元"},
    "debt_ratio": {"label": "负债/总资产", "unit": "%", "source": "扶摇 balance-sheets(quarterly) · total_debt / assets_total", "note": "total_debt 口径以官方文档为准，此处按字面计算"},
    "vol": {"label": "年化波动率(近120日)", "unit": "%", "source": "扶摇 prices/historical(前复权日线) · close_price 对数收益率标准差×√252"},
    "maxdd": {"label": "近120日最大回撤", "unit": "%", "source": "扶摇 prices/historical(前复权日线) · close_price", "note": "负数，越接近0越稳"},
}

# 模糊词典：每个词 → 一组条件模板，三档口径 strict/standard/loose
LEXICON = [
    {"term": "经营改善", "kw": ["经营改善", "业绩改善", "基本面改善", "业绩向好", "盈利改善"], "conds": [
        {"metric": "np_yoy", "op": "gte", "levels": {"strict": 20, "standard": 0, "loose": -10}},
        {"metric": "rev_yoy", "op": "gte", "levels": {"strict": 10, "standard": 0, "loose": -5}}]},
    {"term": "估值合理", "kw": ["估值合理", "估值适中", "估值不高", "估值便宜", "估值低", "低估值", "不贵"], "conds": [
        {"metric": "pe_ttm", "op": "between", "levels": {"strict": [0, 20], "standard": [0, 30], "loose": [0, 45]}},
        {"metric": "pb_mrq", "op": "lte", "levels": {"strict": 2.5, "standard": 4, "loose": 6}}]},
    {"term": "走势相对稳定", "kw": ["走势相对稳定", "走势稳定", "波动小", "波动低", "低波动", "走势平稳", "股价稳定", "稳健"], "conds": [
        {"metric": "vol", "op": "lte", "levels": {"strict": 25, "standard": 35, "loose": 45}},
        {"metric": "maxdd", "op": "gte", "levels": {"strict": -12, "standard": -20, "loose": -30}}]},
    {"term": "现金流健康", "kw": ["现金流健康", "现金流好", "现金流充裕", "现金流为正"], "conds": [
        {"metric": "ocf", "op": "gte", "levels": {"strict": 5, "standard": 0, "loose": -5}}]},
    {"term": "财务稳健", "kw": ["低负债", "负债低", "财务稳健", "财务健康", "资产负债率低"], "conds": [
        {"metric": "debt_ratio", "op": "lte", "levels": {"strict": 40, "standard": 60, "loose": 75}}]},
    {"term": "高成长", "kw": ["高成长", "高增长", "快速增长", "成长性好", "业绩高增"], "conds": [
        {"metric": "np_yoy", "op": "gte", "levels": {"strict": 50, "standard": 30, "loose": 15}},
        {"metric": "rev_yoy", "op": "gte", "levels": {"strict": 30, "standard": 20, "loose": 10}}]},
    {"term": "高弹性", "kw": ["高弹性", "弹性大", "高波动", "波动大"], "conds": [
        {"metric": "vol", "op": "gte", "levels": {"strict": 50, "standard": 40, "loose": 30}}]},
]

# 合规：命中则不生成选股，只给出说明
COMPLIANCE_PATTERNS = [
    (re.compile(r"(稳赚|保证(收益|盈利)|保本|包赚|必涨|一定(会)?涨|肯定(会)?涨|翻倍|十倍股|无风险)"), "涉及收益承诺/确定性涨跌表述"),
    (re.compile(r"(明天|下周|下个月|后天|本周).{0,6}(涨停|大涨|上涨|暴涨|会涨)"), "要求预测具体涨跌"),
    (re.compile(r"(该不该|要不要|应不应该|直接).{0,4}(买|卖|入手|清仓|满仓|加仓)|推荐.{0,4}(买入|卖出)|帮我(决定|选).{0,6}(买|卖)"), "要求直接买卖建议"),
]
