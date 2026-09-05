"""
短线决策台 V2 量化计算引擎 (Scalp Decision Engine V2)
深度融合主力资金与板块流向的多因子早盘量化推送体系：
1. 09:26 竞价初筛 (`stage="auction"`): 聚焦【🔥 主力大单抢筹弱转强】与【🎯 综合短线先锋】
2. 09:35 开盘确认 (`stage="confirm"`): 聚焦【💥 强攻打板先锋】与【🛡️ 资金共振VWAP低吸】
3. 09:55 早盘定势 (`stage="settle"`): 聚焦【🏆 主线封板龙头确认/排板】与【🌊 主线二波蓄势低吸】
"""
import math
import time
import requests
from datetime import datetime

EM_HOSTS = [
    "https://push2dycalc.eastmoney.com",
    "https://push2.eastmoney.com",
    "https://82.push2.eastmoney.com"
]
EM_POOL_URL = "https://push2ex.eastmoney.com"
FIELDS = "f2,f3,f5,f6,f8,f10,f12,f14,f15,f16,f17,f18,f20,f21,f31,f32,f33,f34,f35,f36,f37,f38,f39,f40,f62,f100"


def n(v):
    """安全转换为浮点数"""
    try:
        val = float(v)
        return val if math.isfinite(val) else 0.0
    except (ValueError, TypeError):
        return 0.0


def clamp(v, min_v, max_v):
    return max(min_v, min(max_v, v))


def fmt_amount(v):
    """格式化金额 (元 -> 亿/万)"""
    v = n(v)
    if abs(v) >= 1e8:
        return f"{v / 1e8:.2f}亿"
    if abs(v) >= 1e4:
        return f"{v / 1e4:.0f}万"
    return f"{v:.0f}"


def load_market_pages(max_pages=12, timeout=9):
    """拉取东财全市场行情数据（支持多域名容灾与 f62 主力净流入）"""
    all_stocks = []
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    for host in EM_HOSTS:
        try:
            for p in range(1, max_pages + 1):
                url = f"{host}/api/qt/clist/get"
                params = {
                    "fs": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",
                    "fltt": "2",
                    "invt": "2",
                    "fields": FIELDS,
                    "fid": "f3",
                    "po": "1",
                    "pn": str(p),
                    "pz": "500",
                    "np": "1",
                    "ut": "c92c50e6b0fab2c17cd5e276e9a79c42",
                    "_": str(int(time.time() * 1000)),
                }
                resp = requests.get(url, params=params, headers=headers, timeout=timeout)
                data = resp.json().get("data", {}).get("diff", [])
                if not data:
                    break
                all_stocks.extend(data)
                if len(data) < 500:
                    break
            if all_stocks:
                return all_stocks
        except Exception:
            continue
    return all_stocks


def load_limit_pools():
    """获取涨跌停池详情（包含连板数、封单金额）"""
    today_str = datetime.now().strftime("%Y%m%d")
    url_zt = f"{EM_POOL_URL}/getTopicZTPool"
    params = {
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "dpt": "wz.ztzt",
        "Pageindex": "0",
        "Pagesize": "500",
        "sort": "fbt:asc",
        "date": today_str,
        "_": str(int(time.time() * 1000)),
    }
    zt_list = []
    try:
        resp = requests.get(url_zt, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
        zt_list = resp.json().get("data", {}).get("pool", []) or []
    except Exception:
        pass
    return zt_list


def load_sector_fund_flows(timeout=6):
    """
    拉取东财板块主力资金净流入与涨跌榜单（行业+概念）
    返回: {板块名: {"net_flow": float, "change": float, "amount": float}}
    """
    sector_flows = {}
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    base_url = "https://push2.eastmoney.com/api/qt/clist/get"
    for po in ["1", "0"]:  # 1: 净流入降序, 0: 净流出升序
        try:
            params = {
                "np": "1",
                "fltt": "2",
                "invt": "2",
                "fid": "f62",
                "fs": "m:90+t:3",
                "fields": "f2,f3,f6,f12,f14,f62",
                "pn": "1",
                "pz": "100",
                "po": po,
                "ut": "b2884a393a59ad64002292a3e90d46a5",
                "_": str(int(time.time() * 1000))
            }
            resp = requests.get(base_url, params=params, headers=headers, timeout=timeout)
            diff = resp.json().get("data", {}).get("diff", [])
            for item in diff:
                name = item.get("f14")
                if name and name not in sector_flows:
                    sector_flows[name] = {
                        "code": item.get("f12"),
                        "name": name,
                        "change": n(item.get("f3")),
                        "amount": n(item.get("f6")),
                        "net_flow": n(item.get("f62"))  # 元
                    }
        except Exception:
            continue
    return sector_flows


def build_sector_map(raw_stocks, sector_flows=None):
    """行业板块涨幅、主力资金净流入、强势股与龙头聚合"""
    if sector_flows is None:
        sector_flows = {}

    sector_map = {}
    for x in raw_stocks:
        s_name = x.get("f100") or "其他"
        if s_name not in sector_map:
            sector_map[s_name] = {
                "name": s_name, "count": 0, "up": 0, "strong": 0,
                "sum_pct": 0.0, "amount": 0.0, "net_flow": 0.0,
                "leader": "", "max_chg": -99.0
            }
        sec = sector_map[s_name]
        chg = n(x.get("f3"))
        sec["count"] += 1
        sec["sum_pct"] += chg
        sec["amount"] += n(x.get("f6"))
        sec["net_flow"] += n(x.get("f62"))
        if chg > 0:
            sec["up"] += 1
        if chg >= 3.5:
            sec["strong"] += 1
        if chg > sec["max_chg"]:
            sec["max_chg"] = chg
            sec["leader"] = x.get("f14") or ""

    # 如果有官方板块资金流数据，对齐更精准的主力净流入
    for s_name, sec in sector_map.items():
        if s_name in sector_flows:
            official_flow = sector_flows[s_name].get("net_flow", 0.0)
            if official_flow != 0:
                sec["net_flow"] = official_flow

    # 对板块按照净流入排序计算资金排名
    flow_sorted = sorted(sector_map.values(), key=lambda s: s["net_flow"], reverse=True)
    for rank, sec in enumerate(flow_sorted, 1):
        sec["flow_rank"] = rank

    sectors = []
    for sec in sector_map.values():
        cnt = sec["count"] or 1
        avg_pct = sec["sum_pct"] / cnt
        breadth = sec["up"] / cnt
        flow_yi = sec["net_flow"] / 1e8

        # 资金流加分/扣分
        if flow_yi >= 10.0: flow_score = 100
        elif flow_yi >= 5.0: flow_score = 90
        elif flow_yi >= 2.0: flow_score = 80
        elif flow_yi >= 0.5: flow_score = 70
        elif flow_yi >= 0: flow_score = 55
        elif flow_yi >= -2.0: flow_score = 40
        elif flow_yi >= -5.0: flow_score = 25
        else: flow_score = 10

        # 板块综合评分 = 涨幅权重 + 上涨广度 + 强势股 + 资金流强度
        score = clamp(avg_pct * 8 + breadth * 30 + sec["strong"] * 3 + flow_score * 0.45 + 10, 10, 100)

        flow_str = f"+{flow_yi:.2f}亿" if flow_yi >= 0 else f"{flow_yi:.2f}亿"
        sectors.append({
            "name": sec["name"],
            "count": cnt,
            "avg_pct": avg_pct,
            "strong": sec["strong"],
            "amount": sec["amount"],
            "net_flow": sec["net_flow"],
            "flow_str": flow_str,
            "flow_rank": sec.get("flow_rank", 999),
            "score": score,
            "leader": sec["leader"]
        })
    sectors.sort(key=lambda s: s["score"], reverse=True)
    return {s["name"]: s for s in sectors}, sectors


def get_demo_stocks():
    """生成 V2 高保真模拟数据（包含真实的主力资金与板块数据）"""
    sectors = ["人形机器人", "低空经济", "半导体芯片", "算力硬件", "消费电子", "固态电池", "创新药"]
    prefix = ["华", "中", "新", "科", "恒", "奥", "智", "拓", "蓝", "天"]
    suffix = ["科技", "股份", "智能", "动力", "微电", "精密", "重工", "新材"]
    demo = []
    for i in range(80):
        is_strong = i < 24
        is_zt = (i < 4)
        chg = 9.98 if is_zt else (2.5 + (i % 8) * 0.95 if is_strong else -3.0 + (i % 15) * 0.55)
        pre = round(7.0 + (i % 38) * 1.85, 2)
        open_p = round(pre * (1 + (0.035 if is_zt else chg / 100)), 2)
        now_p = round(pre * (1 + chg / 100), 2)
        amt = (4500 if is_strong else 400) * (1 + (i % 9) * 0.6) * 10000
        cap = (18 + (i % 70) * 1.6) * 1e8
        # 强股主力资金大幅流入，弱股主力资金净流出
        flow = amt * (0.28 if is_zt else (0.18 + (i % 5) * 0.03 if is_strong else -0.12 - (i % 4) * 0.02))
        demo.append({
            "f12": f"{'60' if i % 2 == 0 else '00'}{1000 + i:04d}"[-6:],
            "f14": prefix[i % len(prefix)] + prefix[(i + 3) % len(prefix)] + suffix[i % len(suffix)] + (str(i) if i > 8 else ""),
            "f2": now_p,
            "f3": chg,
            "f5": amt / now_p / 100,
            "f6": amt,
            "f8": 2.5 + (i % 12) * 0.7,
            "f10": 1.5 + (i % 8) * 0.8,
            "f15": max(now_p, open_p * 1.02),
            "f16": min(now_p, open_p * 0.99),
            "f17": open_p,
            "f18": pre,
            "f20": cap * 1.3,
            "f21": cap,
            "f62": flow,
            "f100": sectors[i % len(sectors)]
        })
    return demo


def score_auction_amount(amt):
    if amt >= 5e7: return 96
    if amt >= 2.5e7: return 88
    if amt >= 1.2e7: return 78
    if amt >= 6e6: return 66
    if amt >= 2e6: return 50
    return 30


def score_auction_change(chg):
    if 2.0 <= chg <= 5.5: return 95
    if 1.0 <= chg < 2.0: return 82
    if 5.5 < chg <= 7.5: return 78
    if 0 <= chg < 1.0: return 62
    if -1.5 <= chg < 0: return 45
    return 25


def score_volume_ratio(vr, turnover):
    v_score = 95 if vr >= 3.0 else 85 if vr >= 2.0 else 75 if vr >= 1.4 else 60 if vr >= 0.9 else 35
    t_bonus = 5 if turnover >= 3.0 else 3 if turnover >= 1.5 else 0
    return clamp(v_score + t_bonus, 20, 100)


def score_market_cap(cap, min_cap, max_cap):
    if 25 <= cap <= 85: return 95
    if min_cap <= cap <= max_cap: return 80
    return 45


def score_price_hold(hold_diff):
    if hold_diff >= 0.015: return 95
    if hold_diff >= 0: return 85
    if hold_diff >= -0.01: return 65
    if hold_diff >= -0.02: return 45
    return 15


def score_vwap_diff(vwap_diff):
    if vwap_diff >= 0.005: return 95
    if vwap_diff >= 0: return 85
    if vwap_diff >= -0.01: return 65
    return 30


def score_trend(trend_diff):
    if trend_diff >= 1.5: return 95
    if trend_diff >= 0.3: return 85
    if trend_diff >= -0.5: return 68
    if trend_diff >= -1.5: return 45
    return 20


def score_liquidity(amt):
    if amt >= 2e8: return 95
    if amt >= 8e7: return 85
    if amt >= 3e7: return 75
    if amt >= 1e7: return 60
    return 35


def score_stock_fund_flow(net_flow, flow_ratio):
    """
    个股主力资金净流入及占比打分 (0-100)
    结合主力净买额度与总成交占比
    """
    if net_flow >= 5e7: base = 96
    elif net_flow >= 2.5e7: base = 88
    elif net_flow >= 1e7: base = 78
    elif net_flow >= 3e6: base = 68
    elif net_flow >= 0: base = 55
    elif net_flow >= -1e7: base = 38
    elif net_flow >= -3e7: base = 25
    else: base = 10

    ratio_bonus = 0
    if flow_ratio >= 0.25: ratio_bonus = 10
    elif flow_ratio >= 0.15: ratio_bonus = 6
    elif flow_ratio >= 0.05: ratio_bonus = 2
    elif flow_ratio <= -0.15: ratio_bonus = -12
    elif flow_ratio <= -0.25: ratio_bonus = -20

    return clamp(base + ratio_bonus, 10, 100)


def analyze_scalp_market_v2(raw_stocks=None, stage="auction", is_demo=False, min_score=60, min_cap=15, max_cap=160, min_amount_wan=500):
    """
    短线决策台 V2 全市场量化多因子评分引擎（主力资金与板块流向增强版）
    stage: 'auction' (09:26 竞价初筛) | 'confirm' (09:35 开盘确认) | 'settle' (09:55 早盘定势)
    """
    is_confirm_stage = (stage in ["confirm", "settle"])

    if not raw_stocks:
        if is_demo:
            raw_stocks = get_demo_stocks()
        else:
            raw_stocks = load_market_pages()

    if not raw_stocks:
        return {"stocks": [], "sectors": [], "regime": "等待", "summary": {}, "zt_count": 0}

    zt_pool = load_limit_pools() if not is_demo else []
    zt_dict = {str(item.get("c") or item.get("f12") or ""): item for item in zt_pool}
    if is_demo:
        for idx in range(min(4, len(raw_stocks))):
            c = str(raw_stocks[idx].get("f12"))
            zt_dict[c] = {"c": c, "lbc": 1 if idx > 1 else 2, "fund": 58000000}

    # 拉取板块主力资金流向
    sector_flows = load_sector_fund_flows() if not is_demo else {}
    sec_dict, sec_list = build_sector_map(raw_stocks, sector_flows=sector_flows)

    ups = sum(1 for x in raw_stocks if n(x.get("f3")) > 0)
    downs = sum(1 for x in raw_stocks if n(x.get("f3")) < 0)
    total_amt = sum(n(x.get("f6")) for x in raw_stocks)
    total_net_flow = sum(n(x.get("f62")) for x in raw_stocks)
    up_ratio = ups / len(raw_stocks) if raw_stocks else 0

    # 大盘状态机（上涨家数 + 全市场主力资金流向共振）
    if up_ratio > 0.58 and total_net_flow > 0:
        regime = "进攻"
        market_bonus = 4
    elif up_ratio < 0.38 or total_net_flow < -1.5e10:
        regime = "防守"
        market_bonus = -4
    else:
        regime = "中性"
        market_bonus = 0

    min_amt = min_amount_wan * 1e4
    analyzed_stocks = []

    for x in raw_stocks:
        code = str(x.get("f12") or "")
        name = str(x.get("f14") or "")
        pre_close = n(x.get("f18"))
        open_price = n(x.get("f17")) or n(x.get("f2"))
        cur_price = n(x.get("f2"))
        cur_chg = n(x.get("f3"))
        total_vol = n(x.get("f5"))
        amt = n(x.get("f6"))
        net_flow = n(x.get("f62"))
        flow_ratio = (net_flow / amt) if amt > 0 else 0.0
        float_cap = n(x.get("f21")) / 1e8
        vol_ratio = n(x.get("f10"))
        turnover = n(x.get("f8"))
        sector_name = x.get("f100") or "其他"
        sec_info = sec_dict.get(sector_name, {"score": 50, "avg_pct": 0, "strong": 0, "leader": "", "net_flow": 0, "flow_str": "0.00亿", "flow_rank": 999})

        auction_chg = (open_price / pre_close - 1) * 100 if pre_close > 0 else cur_chg
        auction_amt = amt

        reasons = []
        risks = []

        # ── 1. 竞价阶段 6 大因子加权打分（新增主力大单抢筹因子 f_flow） ──
        f_amt = score_auction_amount(auction_amt)
        f_chg = score_auction_change(auction_chg)
        f_vol = score_volume_ratio(vol_ratio, turnover)
        f_flow = score_stock_fund_flow(net_flow, flow_ratio)
        f_sec = clamp(sec_info["score"], 0, 100)
        f_cap = score_market_cap(float_cap, min_cap, max_cap)

        auction_score_raw = (f_amt * 20 + f_chg * 15 + f_vol * 15 + f_flow * 20 + f_sec * 15 + f_cap * 15) / 100.0
        auction_score = clamp(auction_score_raw + market_bonus, 0, 100)

        # ── 2. 开盘承接确认各因子（新增主力资金流入占比 f_flow） ──
        hold_diff = (cur_price / open_price - 1) if open_price > 0 else 0
        f_hold = score_price_hold(hold_diff)
        trend_diff = cur_chg - auction_chg
        f_trend = score_trend(trend_diff)
        f_liq = score_liquidity(amt)
        vwap_est = (open_price + cur_price) / 2.0
        vwap_diff = (cur_price / vwap_est - 1) * 100 if vwap_est > 0 else 0
        f_vwap = score_vwap_diff(vwap_diff / 100.0)

        confirm_score_raw = (f_hold * 25 + f_trend * 20 + f_flow * 25 + f_liq * 10 + f_vwap * 20) / 100.0
        confirm_score = clamp(confirm_score_raw + market_bonus, 0, 100)

        # 综合总分：35% 竞价分 + 65% 开盘承接分
        final_score = (auction_score * 0.35 + confirm_score * 0.65) if is_confirm_stage else auction_score

        # 涨停判定与连板数
        is_zt = (code in zt_dict) or (cur_chg >= 9.85 and (cur_price == n(x.get("f2"))))
        zt_info = zt_dict.get(code, {})
        lbc = zt_info.get("lbc") or zt_info.get("lb") or 1
        seal_fund = zt_info.get("fund") or (amt * 0.15 if is_zt else 0)

        if is_zt:
            final_score = clamp(final_score + 10, 0, 100)

        final_score = clamp(final_score, 0, 100)

        # ── 战法形态识别（结合主力资金共振） ──
        is_breakthrough = (vol_ratio >= 1.8 and 1.5 <= auction_chg <= 6.5 and f_amt >= 75)
        is_wave2_absorb = (vwap_diff >= 0 and hold_diff >= 0 and 2.5 <= cur_chg <= 7.5 and not is_zt and f_vwap >= 75)
        is_low_absorb = (vwap_diff >= 0 and hold_diff >= 0 and auction_chg <= 3.5 and f_hold >= 75)

        is_flow_inflow = (net_flow > 0 and flow_ratio >= 0.08)
        is_sector_strong = (sec_info.get("flow_rank", 999) <= 6 or sec_info.get("net_flow", 0) > 2e8)

        if is_zt:
            if lbc > 1 and is_sector_strong:
                strategy_tag = f"👑 主线领涨封板 ({lbc}连板)"
            elif lbc > 1:
                strategy_tag = f"🏆 主线封板 ({lbc}连板)"
            else:
                strategy_tag = "🏆 主线首板突破"
        elif is_breakthrough and is_flow_inflow:
            strategy_tag = "🔥 主力大单爆量抢筹"
        elif is_wave2_absorb and is_flow_inflow:
            strategy_tag = "🌊 主线二波蓄势低吸"
        elif is_low_absorb and is_flow_inflow and is_sector_strong:
            strategy_tag = "🛡️ 资金共振VWAP低吸"
        elif is_low_absorb:
            strategy_tag = "🛡️ VWAP低吸承接"
        elif is_breakthrough:
            strategy_tag = "🔥 竞价爆量弱转强"
        else:
            strategy_tag = "🎯 综合短线先锋"

        # 依据与亮点
        if net_flow >= 1.5e7:
            reasons.append(f"主力抢筹{fmt_amount(net_flow)}(占{flow_ratio * 100:+.1f}%)")
        if sec_info.get("flow_rank", 999) <= 5 and sec_info.get("net_flow", 0) > 0:
            reasons.append(f"{sector_name}主力流入TOP{sec_info['flow_rank']}({sec_info['flow_str']})")
        elif f_sec >= 70:
            reasons.append(f"{sector_name}主线领涨(+{sec_info['avg_pct']:.1f}%)")

        if f_amt >= 75:
            reasons.append(f"成交{fmt_amount(auction_amt)}(分{f_amt})")
        if f_chg >= 75:
            reasons.append(f"黄金高开{auction_chg:+.2f}%")
        if f_vol >= 75:
            reasons.append(f"量比{vol_ratio:.1f}/换手{turnover:.1f}%")

        if is_confirm_stage:
            if is_zt:
                reasons.append(f"坚决封涨停(封单约{fmt_amount(seal_fund)})")
            elif f_hold >= 75:
                reasons.append(f"站稳开盘价(偏离{hold_diff * 100:+.1f}%)")
            if f_vwap >= 75:
                reasons.append(f"稳居VWAP均线上方({vwap_diff:+.1f}%)")

        # ── 风险排查与硬性否决 ──
        if name.startswith(("N", "C", "ST", "*ST")) or "ST" in name.upper() or "退" in name:
            risks.append("新股/ST/退市风险")
        if float_cap < min_cap or float_cap > max_cap:
            risks.append(f"流通值{float_cap:.1f}亿超出设定")
        if auction_amt < min_amt:
            risks.append(f"成交{fmt_amount(auction_amt)}不足")
        if hold_diff < -0.02 and not is_zt:
            risks.append(f"开盘跌破竞价价2%({hold_diff * 100:.1f}%)")
        if trend_diff < -3.5 and not is_zt:
            risks.append("冲高回落走弱超3.5%")
        # 主力资金大单出货与板块逆势流出风险
        if cur_chg >= 2.5 and net_flow <= -1.5e7 and flow_ratio <= -0.10 and not is_zt:
            risks.append(f"主力净流出{fmt_amount(abs(net_flow))}(冲高出货背离)")
        if sec_info.get("net_flow", 0) <= -5e8:
            risks.append(f"所属板块主力大额流出{sec_info.get('flow_str', '')}")

        is_hard_veto = len(risks) > 0
        grade = "S" if final_score >= 82 else "A" if final_score >= 70 else "B" if final_score >= 58 else "C"
        is_qualified = (not is_hard_veto) and (final_score >= min_score)

        if not code or pre_close <= 0 or code.startswith(("688", "8", "4")):
            continue

        stop_loss_price = open_price * 0.98
        is_leader = (sec_info["leader"] == name)

        if stage == "auction":
            push_price = open_price
        else:
            push_price = cur_price

        analyzed_stocks.append({
            "code": code,
            "name": name,
            "price": cur_price,
            "open_price": open_price,
            "pre_close": pre_close,
            "push_price": push_price,
            "stop_loss": stop_loss_price,
            "change": cur_chg,
            "auction_change": auction_chg,
            "amount": amt,
            "net_flow": net_flow,
            "flow_ratio": round(flow_ratio, 3),
            "float_cap": float_cap,
            "sector": sector_name,
            "sector_flow_str": sec_info.get("flow_str", "--"),
            "sector_flow_rank": sec_info.get("flow_rank", 999),
            "score": round(final_score, 1),
            "auction_score": round(auction_score, 1),
            "confirm_score": round(confirm_score, 1) if is_confirm_stage else None,
            "vwap_diff": round(vwap_diff, 2),
            "grade": grade,
            "qualified": is_qualified,
            "hard_veto": is_hard_veto,
            "strategy_tag": strategy_tag,
            "is_breakthrough": is_breakthrough,
            "is_wave2_absorb": is_wave2_absorb,
            "is_low_absorb": is_low_absorb,
            "is_leader": is_leader,
            "is_zt": is_zt,
            "lbc": lbc,
            "seal_fund": seal_fund,
            "reasons": reasons,
            "risks": risks,
        })

    analyzed_stocks.sort(key=lambda s: s["score"], reverse=True)

    return {
        "stocks": analyzed_stocks,
        "raw_price_map": {str(x.get("f12")): x for x in (raw_stocks or [])},
        "zt_set": set(zt_dict.keys()),
        "sectors": sec_list[:8],
        "regime": regime,
        "zt_count": len(zt_dict),
        "total_net_flow": total_net_flow,
        "summary": {
            "ups": ups,
            "downs": downs,
            "up_ratio": f"{up_ratio * 100:.0f}%",
            "total_amount": fmt_amount(total_amt),
            "total_net_flow": fmt_amount(total_net_flow),
            "total_count": len(raw_stocks),
            "qualified_count": sum(1 for s in analyzed_stocks if s["qualified"]),
        }
    }


def get_stage_pushed_stocks(analysis_res, stage="auction"):
    """获取指定时段真正推荐上榜的个股列表（供卡片展示与每日复盘统一读取）"""
    stocks = analysis_res.get("stocks", [])
    qualified_stocks = [s for s in stocks if s.get("qualified")]

    if stage == "instant":
        # 09:31:30 极速秒板与主力闪电冲板
        instant_zt = [s for s in qualified_stocks if s.get("is_zt") and s.get("net_flow", 0) > 0]
        instant_surge = [s for s in qualified_stocks if (s.get("change", 0) >= 5.0 and s.get("net_flow", 0) > 1e7 and s.get("flow_ratio", 0) >= 0.15) and not s.get("is_zt")]
        picks = instant_zt[:2] + instant_surge[:2]
        if not picks:
            picks = [s for s in qualified_stocks if s.get("is_breakthrough")][:3] or qualified_stocks[:3]
        return picks[:3]

    elif stage == "auction":
        sorted_qualified = sorted(qualified_stocks, key=lambda s: (s.get("score", 0) + (10 if s.get("net_flow", 0) > 1e7 else 0)), reverse=True)
        picks = [s for s in sorted_qualified if s.get("is_breakthrough") or s.get("net_flow", 0) > 1e7][:2]
        if not picks:
            picks = sorted_qualified[:2] or stocks[:2]
        return picks

    elif stage == "confirm":
        break_picks = [s for s in qualified_stocks if s.get("is_breakthrough") or s.get("score", 0) >= 82][:2]
        absorb_picks = [s for s in qualified_stocks if s.get("is_low_absorb") and s not in break_picks][:2]
        if not break_picks and not absorb_picks:
            break_picks = qualified_stocks[:2]
            absorb_picks = qualified_stocks[2:4]
        return break_picks + absorb_picks

    elif stage == "settle":
        zt_picks = [s for s in qualified_stocks if s.get("is_zt")][:2]
        wave2_picks = [s for s in qualified_stocks if s.get("is_wave2_absorb") and not s.get("is_zt")][:2]
        if not zt_picks and not wave2_picks:
            zt_picks = [s for s in stocks if s.get("is_zt")][:2]
            wave2_picks = qualified_stocks[:2]
        return zt_picks + wave2_picks

    return qualified_stocks[:4] or stocks[:3]


def build_scalp_feishu_card_v2(analysis_res, stage="auction", pushed_stocks=None, sell_actions=None, buy_records=None, account_data=None):
    """
    短线决策台 V2 专属分时段智能飞书卡片（融合主力资金与板块资金动向）
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary = analysis_res.get("summary", {})
    regime = analysis_res.get("regime", "中性")
    sectors = analysis_res.get("sectors", [])
    zt_cnt = analysis_res.get("zt_count", 0)
    total_flow_val = analysis_res.get("total_net_flow", 0.0)

    if pushed_stocks is None:
        pushed_stocks = get_stage_pushed_stocks(analysis_res, stage=stage)

    if stage == "settle":
        title_text = f"🏆 缅A早盘定势封板榜 ({now_str[11:16]})"
        header_color = "purple"
    elif stage == "confirm":
        title_text = f"🚀 缅A开盘承接强攻榜 ({now_str[11:16]})"
        header_color = "red"
    elif stage == "instant":
        title_text = f"⚡ 缅A极速秒板突击榜 ({now_str[11:16]})"
        header_color = "turquoise"
    else:
        title_text = f"☀️ 缅A早盘竞价初筛榜 ({now_str[11:16]})"
        header_color = "orange"

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title_text},
            "template": header_color
        },
        "elements": []
    }

    # 1. 市场大盘姿态与全市场资金流向
    regime_emoji = "🔥" if regime == "进攻" else "🛡️" if regime == "防守" else "⚖️"
    lead_sec_str = " | ".join([f"{s['name']}(+{s['avg_pct']:.1f}%/{s['flow_str']})" for s in sectors[:3]]) if sectors else "暂无"
    flow_emoji = "🟢 净流入" if total_flow_val >= 0 else "🔴 净流出"
    flow_desc = f"{flow_emoji} **{fmt_amount(abs(total_flow_val))}**"

    extra_stat = f" | 封板家数: **{zt_cnt}家**" if stage == "settle" else ""
    market_md = (
        f"{regime_emoji} **大盘姿态**: 【**{regime}模式**】 (上涨: {summary.get('ups', 0)} / 下跌: {summary.get('downs', 0)} | 占比 {summary.get('up_ratio', '0%')})\n"
        f"📊 全市场成交: **{summary.get('total_amount', '--')}** | 主力资金: {flow_desc}{extra_stat}\n"
        f"🔥 领涨主线资金: **{lead_sec_str}**"
    )
    card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": market_md}})

    # 2. 模拟账户当前资金小看板 (如果提供了账户信息)
    if account_data:
        total_assets = account_data.get("total_assets", 100000.0)
        cash = account_data.get("cash", 100000.0)
        pos_cnt = len(account_data.get("positions", []))
        total_ret = ((total_assets - 100000.0) / 100000.0) * 100
        account_md = f"💼 **10万模拟账户**: 总资产 **￥{total_assets:,.2f}** (累计: `{total_ret:+.2f}%`) | 可用现金: **￥{cash:,.2f}** | 当前持仓: **{pos_cnt}只**"
        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": account_md}})

    card["elements"].append({"tag": "hr"})

    # 3. 【📦 昨日持仓监控与 T+1 卖出操作指引】
    if sell_actions:
        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "📦 **【昨日持仓监控与 T+1 处置指令】**"}})
        sell_lines = []
        for sa in sell_actions:
            code = sa["code"]
            name = sa["name"]
            action = sa["action"]
            reason = sa["reason"]
            shares = sa["shares"]
            cur_p = sa["cur_price"]
            buy_p = sa["buy_price"]
            profit_pct = sa["profit_pct"]
            profit_amt = sa.get("profit_amount", 0.0)

            exec_tag = " (✅ 已模拟市价卖出回收现金)" if sa.get("is_executed") else ""
            t_tag = "" if sa.get("is_t_plus_1", True) else " [T日锁定]"

            sell_lines.append(
                f"• **{code} {name}**{t_tag} ({shares}股 | 买入 `￥{buy_p:.2f}` ➔ 现价 `￥{cur_p:.2f}` | 浮动: **{profit_pct:+.2f}% / {profit_amt:+.0f}元**)\n"
                f"  > 指令: **`{action}`**{exec_tag}\n"
                f"  > 依据: {reason}"
            )
        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(sell_lines)}})
        card["elements"].append({"tag": "hr"})

    # 4. 构建买入匹配映射
    buy_map = {b["code"]: b for b in (buy_records or [])}

    # 5. 今日推荐标的列表
    if stage == "auction":
        # ── 09:26 竞价初筛阶段 ──
        section_title = "🎯 **【竞价高分先锋 · 锁定今日观察池】**"
        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": section_title}})

        stock_md_list = []
        for s in pushed_stocks:
            grade_badge = f"【{s['grade']}级 {s['score']}分】"
            leader_tag = " 👑板块龙头" if s.get("is_leader") else ""
            zt_tag = " [涨停板]" if s.get("is_zt") else ""
            reasons_str = "、".join(s.get("reasons", [])[:3]) if s.get("reasons") else "符合竞价资金动能模型"

            flow_tag = f"净买 **{fmt_amount(s.get('net_flow', 0))}** (占{s.get('flow_ratio', 0) * 100:+.1f}%)" if s.get('net_flow') else f"成交 {fmt_amount(s['amount'])}"
            sec_tag = f"`{s['sector']}` ({s.get('sector_flow_str', '--')})"

            buy_info_str = ""
            if s["code"] in buy_map:
                b = buy_map[s["code"]]
                buy_info_str = f"\n> 💼 **【10万实盘模拟买入】**: 买入 **{b['shares']}股** | 占用现金: **￥{b['cost_amount']:,.2f}** (仓位 {b['pos_ratio']:.1f}%)"

            stock_md_list.append(
                f"🟢 **{s['code']} {s['name']}** (竞价开盘: **￥{s['open_price']:.2f}** | {s['auction_change']:+.2f}%){leader_tag}{zt_tag}\n"
                f"> 战法: **`{s['strategy_tag']}`** | 评级: **{grade_badge}**\n"
                f"> 行业: {sec_tag} | 主力: {flow_tag}\n"
                f"> 特征: {reasons_str}{buy_info_str}\n"
                f"> 🎯 **盯盘策略**: 9:30开盘观察分时承接，不破 ￥{s['open_price']:.2f} 即可择机买入"
            )

        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "\n\n".join(stock_md_list) if stock_md_list else "⚠️ 今日早盘竞价无达到合格门槛的标的，建议防守观望。"}})

    elif stage == "instant":
        # ── 09:31:30 极速秒板阶段 ──
        section_title = "⚡ **【开盘极速秒板 · 主力闪电抢筹先锋 (09:31:30)】**"
        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": section_title}})

        stock_md_list = []
        for s in pushed_stocks:
            grade_badge = f"【{s['grade']}级 {s['score']}分】"
            leader_tag = " 👑板块龙头" if s.get("is_leader") else ""
            zt_tag = f" | {s['change']:+.2f}% [涨停板]" if s.get("is_zt") else f" | {s['change']:+.2f}%"
            reasons_str = "、".join(s.get("reasons", [])[:3]) if s.get("reasons") else "开盘极速爆量拉升"

            flow_tag = f"净买 **{fmt_amount(s.get('net_flow', 0))}** (占{s.get('flow_ratio', 0) * 100:+.1f}%)"
            sec_tag = f"`{s['sector']}` ({s.get('sector_flow_str', '--')})"

            buy_info_str = ""
            if s["code"] in buy_map:
                b = buy_map[s["code"]]
                buy_info_str = f"\n> 💼 **【10万实盘模拟买入】**: 买入 **{b['shares']}股** | 占用现金: **￥{b['cost_amount']:,.2f}** (仓位 {b['pos_ratio']:.1f}%)"

            action_tips = "主力直线封板，可第一时间挂单打板或排队抢筹！" if s.get("is_zt") else "开盘极速大单拉升，可挂分时均线上方抢筹！"
            stock_md_list.append(
                f"🟢 **{s['code']} {s['name']}** (现价: **￥{s['price']:.2f}**{zt_tag}){leader_tag}\n"
                f"> 战法: **`{s['strategy_tag']}`** | 评级: **{grade_badge}**\n"
                f"> 行业: {sec_tag} | 主力: {flow_tag}\n"
                f"> 依据: {reasons_str}{buy_info_str}\n"
                f"> ⚡ **极速战术**: {action_tips}\n"
                f"> 🚨 **防守止损线**: `￥{s['stop_loss']:.2f}`"
            )

        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "\n\n".join(stock_md_list) if stock_md_list else "开盘 90 秒内暂无主力极速秒板标的。"}})

    elif stage == "confirm":
        # ── 09:35 开盘确认阶段 ──
        break_picks = [s for s in pushed_stocks if s.get("is_breakthrough") or s.get("score", 0) >= 82]
        absorb_picks = [s for s in pushed_stocks if s not in break_picks]

        # 1. 强攻打板先锋
        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "💥 **【强攻打板 / 主力抢筹先锋】**"}})
        if break_picks:
            break_md = []
            for s in break_picks:
                leader_tag = " 👑板块龙头" if s.get("is_leader") else ""
                reasons_str = "、".join(s.get("reasons", [])[:3]) if s.get("reasons") else "开盘主力资金持续抢筹"

                flow_tag = f"净买 **{fmt_amount(s.get('net_flow', 0))}** (占{s.get('flow_ratio', 0) * 100:+.1f}%)"
                sec_tag = f"`{s['sector']}` ({s.get('sector_flow_str', '--')})"

                buy_info_str = ""
                if s["code"] in buy_map:
                    b = buy_map[s["code"]]
                    buy_info_str = f"\n> 💼 **【10万实盘模拟买入】**: 买入 **{b['shares']}股** | 占用现金: **￥{b['cost_amount']:,.2f}** (仓位 {b['pos_ratio']:.1f}%)"

                break_md.append(
                    f"🟢 **{s['code']} {s['name']}** (现价: **￥{s['price']:.2f}** | {s['change']:+.2f}%){leader_tag}\n"
                    f"> 战法: **`{s['strategy_tag']}`** | 评级: **【{s['grade']}级 {s['score']}分】**\n"
                    f"> 行业: {sec_tag} | 主力: {flow_tag}\n"
                    f"> 依据: {reasons_str}{buy_info_str}\n"
                    f"> 💡 **强攻买入**: 现价或分时均线上方挂单抢筹\n"
                    f"> 🚨 **防守止损线**: `￥{s['stop_loss']:.2f}` (次日T+1跌破开盘2%坚决止损)"
                )
            card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "\n\n".join(break_md)}})
        else:
            card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "暂无明显强攻突破标的"}})

        card["elements"].append({"tag": "hr"})

        # 2. 稳健回踩低吸
        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "🛡️ **【稳健回踩 / 资金共振VWAP低吸】**"}})
        if absorb_picks:
            absorb_md = []
            for s in absorb_picks:
                leader_tag = " 👑板块龙头" if s.get("is_leader") else ""
                reasons_str = "、".join(s.get("reasons", [])[:3]) if s.get("reasons") else "稳稳站上分时均线且资金承接良好"

                flow_tag = f"净买 **{fmt_amount(s.get('net_flow', 0))}** (占{s.get('flow_ratio', 0) * 100:+.1f}%)"
                sec_tag = f"`{s['sector']}` ({s.get('sector_flow_str', '--')})"

                buy_info_str = ""
                if s["code"] in buy_map:
                    b = buy_map[s["code"]]
                    buy_info_str = f"\n> 💼 **【10万实盘模拟买入】**: 买入 **{b['shares']}股** | 占用现金: **￥{b['cost_amount']:,.2f}** (仓位 {b['pos_ratio']:.1f}%)"

                absorb_md.append(
                    f"🟢 **{s['code']} {s['name']}** (现价: **￥{s['price']:.2f}** | {s['change']:+.2f}%){leader_tag}\n"
                    f"> 战法: **`{s['strategy_tag']}`** | 评级: **【{s['grade']}级 {s['score']}分】**\n"
                    f"> 行业: {sec_tag} | 主力: {flow_tag}\n"
                    f"> 依据: {reasons_str}{buy_info_str}\n"
                    f"> 💡 **低吸区间**: `￥{s['open_price']:.2f} ~ ￥{s['price']:.2f}` (回踩均线买入)\n"
                    f"> 🚨 **防守止损线**: `￥{s['stop_loss']:.2f}`"
                )
            card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "\n\n".join(absorb_md)}})
        else:
            card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "暂无明显均线低吸标的"}})

    else:
        # ── 09:55 早盘定势阶段 ──
        zt_picks = [s for s in pushed_stocks if s.get("is_zt")]
        wave2_picks = [s for s in pushed_stocks if not s.get("is_zt")]

        # 1. 封板龙头打板确认
        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "🏆 **【主线封板先锋 · 封板/排板确认】**"}})
        if zt_picks:
            zt_md = []
            for s in zt_picks:
                leader_tag = " 👑板块龙头" if s.get("is_leader") else ""
                seal_str = f"封单约 {fmt_amount(s['seal_fund'])}" if s.get("seal_fund") else "封单坚挺"
                flow_tag = f"主力净买 **{fmt_amount(s.get('net_flow', 0))}**"
                sec_tag = f"`{s['sector']}` ({s.get('sector_flow_str', '--')})"

                buy_info_str = ""
                if s["code"] in buy_map:
                    b = buy_map[s["code"]]
                    buy_info_str = f"\n> 💼 **【10万实盘模拟买入】**: 买入 **{b['shares']}股** | 占用现金: **￥{b['cost_amount']:,.2f}** (仓位 {b['pos_ratio']:.1f}%)"

                zt_md.append(
                    f"🟢 **{s['code']} {s['name']}** (现价: **￥{s['price']:.2f}** | {s['change']:+.2f}% 涨停板){leader_tag}\n"
                    f"> 梯队: **`{s['strategy_tag']}`** | 评级: **【{s['grade']}级 {s['score']}分】**\n"
                    f"> 行业: {sec_tag} | {flow_tag} | {seal_str}{buy_info_str}\n"
                    f"> 💡 **排单操作**: 主线最强龙头，若有炸板回封机会可直接排单打板"
                )
            card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "\n\n".join(zt_md)}})
        else:
            card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "早盘暂无核心涨停标的"}})

        card["elements"].append({"tag": "hr"})

        # 2. 二波回踩蓄势低吸
        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "🌊 **【二波回踩蓄势 · 主力承接低吸】**"}})
        if wave2_picks:
            wave2_md = []
            for s in wave2_picks:
                leader_tag = " 👑板块龙头" if s.get("is_leader") else ""
                reasons_str = "、".join(s.get("reasons", [])[:3]) if s.get("reasons") else "冲高后缩量横盘蓄势，主力资金未离场"
                flow_tag = f"净买 **{fmt_amount(s.get('net_flow', 0))}** (占{s.get('flow_ratio', 0) * 100:+.1f}%)"
                sec_tag = f"`{s['sector']}` ({s.get('sector_flow_str', '--')})"

                buy_info_str = ""
                if s["code"] in buy_map:
                    b = buy_map[s["code"]]
                    buy_info_str = f"\n> 💼 **【10万实盘模拟买入】**: 买入 **{b['shares']}股** | 占用现金: **￥{b['cost_amount']:,.2f}** (仓位 {b['pos_ratio']:.1f}%)"

                wave2_md.append(
                    f"🟢 **{s['code']} {s['name']}** (现价: **￥{s['price']:.2f}** | {s['change']:+.2f}%){leader_tag}\n"
                    f"> 战法: **`{s['strategy_tag']}`** | 评级: **【{s['grade']}级 {s['score']}分】**\n"
                    f"> 行业: {sec_tag} | 主力: {flow_tag}\n"
                    f"> 依据: {reasons_str}{buy_info_str}\n"
                    f"> 💡 **二波低吸点**: `￥{s['open_price']:.2f} ~ ￥{s['price']:.2f}` (回踩黄线吸筹博弈二波拉升)\n"
                    f"> 🚨 **防守止损线**: `￥{s['stop_loss']:.2f}`"
                )
            card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "\n\n".join(wave2_md)}})
        else:
            card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "暂无明显二波回踩标的"}})

    card["elements"].append({"tag": "hr"})

    # 6. 底部短线纪律提示
    if stage == "settle":
        tips_md = "💡 **早盘定势提醒**: 开盘半小时已过，主要主线已明朗，切忌追高无主力资金承接的后排杂毛股！"
    elif stage == "confirm":
        tips_md = "⚠️ **短线实战铁律**: A股严格执行 T+1 制度，买入当日锁定不可卖出，次日若破防守线且无法收回坚决止损！"
    else:
        tips_md = "💡 **竞价操作提醒**: 9:25-9:30 为锁单期不可撤单，请在 9:30 开盘后根据分时主力承接决定是否买入。"

    card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": tips_md}})

    return card
