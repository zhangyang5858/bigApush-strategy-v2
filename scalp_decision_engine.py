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

from strategy_four_pillars import (
    detect_s1_auction_first_board,
    detect_s2_mainline_leader,
    detect_s3_limitup_pullback,
    detect_s4_breakout_retest,
    load_observation_pools_from_json,
    is_st_or_delisted
)


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


def calc_line67_auction_score(amount, auction_change, vol_ratio, sector_score=50, sector_breadth=0.5, float_cap=50.0, min_cap=15.0, max_cap=160.0, regime="中性"):
    """
    Line 67 竞价评分模型（满分 100）
    AuctionScore = clamp(S_amount + S_price + S_vr + S_sector + S_cap + S_market, 0, 100)
    """
    amt_wan = max(float(amount) / 1e4, 1.0)
    s_amt = clamp(math.log10(amt_wan) * 7.0 - 8.0, 0.0, 24.0)
    chg = float(auction_change)
    if 1.5 <= chg <= 6.5:
        s_price = 18.0
    elif (0.0 < chg < 1.5) or (6.5 < chg <= 9.0):
        s_price = 10.0
    else:
        s_price = 2.0
    vr = float(vol_ratio)
    s_vr = clamp((vr - 1.0) * 6.0 + 5.0, 0.0, 15.0)
    s_sec = clamp(float(sector_score) * 0.12 + float(sector_breadth) * 10.0, 0.0, 20.0)
    cap = float(float_cap)
    s_cap = 10.0 if (20.0 <= cap <= 100.0) else 6.0 if (min_cap <= cap <= max_cap) else 2.0
    s_mkt = 8.0 if regime == "进攻" else -8.0 if regime == "防守" else 2.0
    return clamp(s_amt + s_price + s_vr + s_sec + s_cap + s_mkt, 0.0, 100.0)


def calc_line67_confirm_score(hold_diff, trend_diff, amount, sector_score=50, regime="中性"):
    """
    Line 67 开盘承接确认评分模型（满分 100）
    ConfirmScore = clamp(S_hold + S_trend + S_liq + S_sector + S_market, 0, 100)
    """
    hd = float(hold_diff)
    if hd >= 0:
        s_hold = 22.0
    elif -0.015 <= hd < 0:
        s_hold = 12.0
    else:
        s_hold = 0.0
    td = float(trend_diff)
    if td >= 0.3:
        s_trend = 20.0
    elif td >= -0.5:
        s_trend = 12.0
    else:
        s_trend = 2.0
    amt_wan = max(float(amount) / 1e4, 1.0)
    s_liq = clamp(math.log10(amt_wan) * 8.0 - 12.0, 0.0, 18.0)
    s_sec = clamp(float(sector_score) * 0.2, 0.0, 20.0)
    s_mkt = 8.0 if regime == "进攻" else -8.0 if regime == "防守" else 2.0
    return clamp(s_hold + s_trend + s_liq + s_sec + s_mkt, 0.0, 100.0)


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
    短线决策台 V2 全市场量化多因子评分引擎（Line 67 打分与四策略独立判定）
    stage: 'auction' (09:26) | 'instant' (09:31) | 'confirm' (09:38) | 'settle' (10:00) | 'afternoon' (14:30)
    """
    is_confirm_stage = (stage in ["confirm", "settle", "afternoon"])

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

    # 加载 S3/S4 观察池
    obs_pools = load_observation_pools_from_json()
    if is_demo and not obs_pools.get("s3_pullback_pool"):
        s3_demo = [{
            "code": str(raw_stocks[i].get("f12")),
            "first_board_date": "2026-09-12",
            "support_low": round(float(raw_stocks[i].get("f2")) * 0.95, 2),
            "midpoint": round(float(raw_stocks[i].get("f2")) * 0.98, 2),
            "first_vol": 100000,
            "adjust_days": 3
        } for i in range(4, 8) if i < len(raw_stocks)]
        s4_demo = [{
            "code": str(raw_stocks[i].get("f12")),
            "breakout_date": "2026-09-15",
            "ceiling": round(float(raw_stocks[i].get("f2")) * 0.96, 2),
            "avg_vol": 50000,
            "breakout_vol": 95000,
            "breakout_vol_ratio": 1.9
        } for i in range(8, 12) if i < len(raw_stocks)]
        obs_pools = {"s3_pullback_pool": s3_demo, "s4_breakout_pool": s4_demo}

    s3_dict = {str(item.get("code")): item for item in obs_pools.get("s3_pullback_pool", [])}
    s4_dict = {str(item.get("code")): item for item in obs_pools.get("s4_breakout_pool", [])}

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
    elif up_ratio < 0.38 or total_net_flow < -1.5e10:
        regime = "防守"
    else:
        regime = "中性"

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

        # ── 1. Line 67 打分模型（仅作同策略内部排序字段） ──
        auction_score = calc_line67_auction_score(
            amount=auction_amt,
            auction_change=auction_chg,
            vol_ratio=vol_ratio,
            sector_score=sec_info.get("score", 50),
            sector_breadth=sec_info.get("breadth", 0.5),
            float_cap=float_cap,
            min_cap=min_cap,
            max_cap=max_cap,
            regime=regime
        )

        hold_diff = (cur_price / open_price - 1) if open_price > 0 else 0
        trend_diff = cur_chg - auction_chg
        vwap_est = (open_price + cur_price) / 2.0
        vwap_diff = (cur_price / vwap_est - 1) * 100 if vwap_est > 0 else 0

        confirm_score = calc_line67_confirm_score(
            hold_diff=hold_diff,
            trend_diff=trend_diff,
            amount=amt,
            sector_score=sec_info.get("score", 50),
            regime=regime
        )

        final_score = (auction_score * 0.4 + confirm_score * 0.6) if is_confirm_stage else auction_score

        # 涨停判定与连板数
        is_zt = (code in zt_dict) or (cur_chg >= 9.85 and (cur_price == n(x.get("f2"))))
        zt_info = zt_dict.get(code, {})
        lbc = zt_info.get("lbc") or zt_info.get("lb") or 1
        seal_fund = zt_info.get("fund") or (amt * 0.15 if is_zt else 0)

        if is_zt:
            final_score = clamp(final_score + 10, 0, 100)

        final_score = clamp(final_score, 0, 100)
        grade = "S" if final_score >= 80 else "A" if final_score >= 70 else "B" if final_score >= 60 else "C"

        # ── 2. 四策略独立判定引擎（独立信号条件，不以分数替代战法） ──
        stock_obj = {
            "code": code,
            "name": name,
            "price": cur_price,
            "open_price": open_price,
            "pre_close": pre_close,
            "change": cur_chg,
            "auction_change": auction_chg,
            "amount": amt,
            "auction_amount": auction_amt,
            "net_flow": net_flow,
            "flow_ratio": flow_ratio,
            "float_cap": float_cap,
            "vr": vol_ratio,
            "vol_ratio": vol_ratio,
            "vwap_diff": vwap_diff,
            "low": n(x.get("f16")) or open_price,
            "high": n(x.get("f15")) or cur_price
        }

        # S1: 竞价首板
        s1_sig = detect_s1_auction_first_board(
            stock=stock_obj,
            confirm_stock=stock_obj if is_confirm_stage else None,
            yesterday={"is_limit_up": False},
            sector_info=sec_info,
            min_amount=min_amt
        )

        # S2: 主线龙头
        s2_sig = detect_s2_mainline_leader(
            stock=stock_obj,
            sector_rank_info=sec_info,
            stage=stage
        )

        # S3: 涨停回调低吸
        s3_sig = None
        if code in s3_dict:
            s3_sig = detect_s3_limitup_pullback(stock_obj, s3_item=s3_dict[code], stage=stage)

        # S4: 量价突破回踩
        s4_sig = None
        if code in s4_dict:
            s4_sig = detect_s4_breakout_retest(stock_obj, s4_item=s4_dict[code], stage=stage)

        # 判定主策略归属（若同属多策略，依据时段与确认优先级分配）
        primary_sig = None
        if stage == "afternoon":
            if s3_sig and s3_sig["status"] in ["CONFIRMED", "WATCHING"]: primary_sig = s3_sig
            elif s4_sig and s4_sig["status"] in ["CONFIRMED", "WATCHING"]: primary_sig = s4_sig
            elif s2_sig and s2_sig["status"] == "CONFIRMED": primary_sig = s2_sig
            elif s1_sig and s1_sig["status"] == "CONFIRMED": primary_sig = s1_sig
        elif stage == "settle":
            if s2_sig and s2_sig["status"] in ["CONFIRMED", "WATCHING"]: primary_sig = s2_sig
            elif s1_sig and s1_sig["status"] in ["CONFIRMED", "WATCHING"]: primary_sig = s1_sig
            elif s3_sig and s3_sig["status"] == "CONFIRMED": primary_sig = s3_sig
            elif s4_sig and s4_sig["status"] == "CONFIRMED": primary_sig = s4_sig
        else:
            if s1_sig and s1_sig["status"] in ["CONFIRMED", "WATCHING"]: primary_sig = s1_sig
            elif s2_sig and s2_sig["status"] in ["CONFIRMED", "WATCHING"]: primary_sig = s2_sig
            elif s3_sig and s3_sig["status"] == "CONFIRMED": primary_sig = s3_sig
            elif s4_sig and s4_sig["status"] == "CONFIRMED": primary_sig = s4_sig

        if primary_sig:
            strategy_id = primary_sig["strategy_id"]
            strategy_tag = f"{primary_sig['strategy_name']} ({primary_sig['stage_desc']})"
            strategy_variant = primary_sig.get("strategy_variant", primary_sig["stage_desc"])
            support_price = primary_sig.get("support_price", open_price)
            signal_stage = primary_sig["status"]
            strat_invalid_reason = primary_sig.get("invalid_reason")
            if primary_sig.get("reasons"):
                reasons.extend(primary_sig["reasons"][:3])
        else:
            strategy_id = "GENERIC"
            strategy_tag = "🎯 综合短线先锋"
            strategy_variant = "综合选股"
            support_price = round(open_price * 0.98, 2)
            signal_stage = "WATCHING"
            strat_invalid_reason = None

        # 经典通用亮点补充
        if net_flow >= 1.5e7 and not any("主力抢筹" in r for r in reasons):
            reasons.append(f"主力抢筹{fmt_amount(net_flow)}(占{flow_ratio * 100:+.1f}%)")
        if sec_info.get("flow_rank", 999) <= 5 and sec_info.get("net_flow", 0) > 0 and not any("主力流入" in r for r in reasons):
            reasons.append(f"{sector_name}主力流入TOP{sec_info['flow_rank']}({sec_info['flow_str']})")

        # ── 3. 风险排查与硬性否决 (Hard Veto) ──
        if is_st_or_delisted(name):
            risks.append("新股/ST/退市风险")
        if float_cap < min_cap or float_cap > max_cap:
            risks.append(f"流通值{float_cap:.1f}亿超出设定")
        if auction_amt < min_amt:
            risks.append(f"成交{fmt_amount(auction_amt)}不足")
        if hold_diff < -0.02 and not is_zt:
            risks.append(f"开盘跌破竞价价2%({hold_diff * 100:.1f}%)")
        if trend_diff < -2.0 and not is_zt:
            risks.append(f"冲高回落走弱超2%({trend_diff:+.1f}%)")
        if strat_invalid_reason:
            risks.append(strat_invalid_reason)

        is_hard_veto = len(risks) > 0
        if is_hard_veto and signal_stage != "INVALIDATED":
            signal_stage = "INVALIDATED"
            strat_invalid_reason = risks[0]

        is_qualified = (not is_hard_veto) and (final_score >= min_score)

        if not code or pre_close <= 0 or code.startswith(("688", "8", "4")):
            continue

        is_leader = (sec_info["leader"] == name)
        stop_loss_price = round(support_price * 0.98, 2) if support_price > 0 else round(open_price * 0.98, 2)
        push_price = cur_price

        analyzed_stocks.append({
            "code": code,
            "name": name,
            "price": cur_price,
            "open_price": open_price,
            "pre_close": pre_close,
            "push_price": push_price,
            "stop_loss": stop_loss_price,
            "support_price": support_price,
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
            "strategy_id": strategy_id,
            "strategy_tag": strategy_tag,
            "strategy_variant": strategy_variant,
            "signal_stage": signal_stage,
            "invalid_reason": strat_invalid_reason,
            "s1_signal": s1_sig,
            "s2_signal": s2_sig,
            "s3_signal": s3_sig,
            "s4_signal": s4_sig,
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
    """
    获取指定时段真正推荐上榜的个股列表（按 S1~S4 策略独立规则筛选 + 内部按 Line 67 得分倒序）
    【实战原则】：严格排除当时已封死涨停的标的，不打板、不排板，只推荐有明确买入/低吸空间的未封死标的
    """
    stocks = analysis_res.get("stocks", [])

    def is_buyable_unsealed(s):
        """判断标的是否为未封死、可即时买入/挂单的个股"""
        if s.get("is_zt"):
            return False
        code = str(s.get("code") or "")
        chg = float(s.get("change") or s.get("auction_change") or 0.0)
        if code.startswith(("30", "688")):
            return chg < 19.5
        else:
            return chg < 9.7

    buyable_qualified = [s for s in stocks if s.get("qualified") and is_buyable_unsealed(s)]
    buyable_all = [s for s in stocks if is_buyable_unsealed(s)]

    # 四大策略池按策略独立提取（不混淆策略条件）
    s1_candidates = [
        s for s in buyable_qualified
        if s.get("s1_signal") and s["s1_signal"].get("status") in (["CONFIRMED", "WATCHING"] if stage == "auction" else ["CONFIRMED"])
    ]
    s2_candidates = [
        s for s in buyable_qualified
        if s.get("s2_signal") and s["s2_signal"].get("status") in (["CONFIRMED", "WATCHING"] if stage in ["auction", "instant"] else ["CONFIRMED"])
    ]
    s3_candidates = [
        s for s in buyable_qualified
        if s.get("s3_signal") and s["s3_signal"].get("status") == "CONFIRMED"
    ]
    s4_candidates = [
        s for s in buyable_qualified
        if s.get("s4_signal") and s["s4_signal"].get("status") == "CONFIRMED"
    ]

    # 策略内部严格按 Line 67 score 排序（评分仅作为排序字段，不替代策略定义）
    s1_candidates.sort(key=lambda s: (s.get("score", 0) + (5 if s.get("net_flow", 0) > 1e7 else 0)), reverse=True)
    s2_candidates.sort(key=lambda s: (s.get("score", 0) + (5 if s.get("net_flow", 0) > 1e7 else 0)), reverse=True)
    s3_candidates.sort(key=lambda s: s.get("score", 0), reverse=True)
    s4_candidates.sort(key=lambda s: s.get("score", 0), reverse=True)

    strategy_groups = {
        "S1": s1_candidates[:2],
        "S2": s2_candidates[:2],
        "S3": s3_candidates[:2],
        "S4": s4_candidates[:2],
    }
    analysis_res["strategy_groups"] = strategy_groups

    pushed_list = []
    if stage == "auction":
        # 09:26 竞价初筛：S1 竞价入选 TOP2 + S2 龙头候选 TOP2
        pushed_list.extend(strategy_groups["S1"][:2])
        pushed_list.extend(strategy_groups["S2"][:2])
    elif stage == "instant":
        # 09:31:30 极速秒板：S1 开盘确认优先
        pushed_list.extend(strategy_groups["S1"][:2])
        pushed_list.extend(strategy_groups["S2"][:1])
    elif stage == "confirm":
        # 09:38 开盘承接：S1 开盘确认 TOP2 + S2 领涨跟踪 TOP2
        pushed_list.extend(strategy_groups["S1"][:2])
        pushed_list.extend(strategy_groups["S2"][:2])
        if strategy_groups["S3"]: pushed_list.extend(strategy_groups["S3"][:1])
        if strategy_groups["S4"]: pushed_list.extend(strategy_groups["S4"][:1])
    elif stage == "settle":
        # 10:00 早盘定势：S2 主线龙头确认 TOP2 + S1 确认 TOP1
        pushed_list.extend(strategy_groups["S2"][:2])
        pushed_list.extend(strategy_groups["S1"][:1])
        if strategy_groups["S3"]: pushed_list.extend(strategy_groups["S3"][:1])
        if strategy_groups["S4"]: pushed_list.extend(strategy_groups["S4"][:1])
    elif stage == "afternoon":
        # 14:30 尾盘决胜：S3 涨停回调低吸确认 TOP2 + S4 量价突破回踩确认 TOP2
        pushed_list.extend(strategy_groups["S3"][:2])
        pushed_list.extend(strategy_groups["S4"][:2])
        if not pushed_list:
            pushed_list.extend(strategy_groups["S2"][:2])

    # 去重处理
    seen = set()
    final_pushed = []
    for s in pushed_list:
        if s["code"] not in seen:
            seen.add(s["code"])
            final_pushed.append(s)

    if not final_pushed:
        # 兜底避免空榜
        final_pushed = buyable_qualified[:3] or buyable_all[:2]

    return final_pushed


    return buyable_qualified[:4] or buyable_all[:3]


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

    if stage == "afternoon":
        title_text = f"🌙 缅A尾盘低吸与突破回踩决胜榜 ({now_str[11:16]})"
        header_color = "indigo"
    elif stage == "settle":
        title_text = f"🏆 缅A早盘定势主线龙头榜 ({now_str[11:16]})"
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

    extra_stat = f" | 封板家数: **{zt_cnt}家**" if stage in ["settle", "afternoon"] else ""
    market_md = (
        f"{regime_emoji} **大盘姿态**: 【**{regime}模式**】 (上涨: {summary.get('ups', 0)} / 下跌: {summary.get('downs', 0)} | 占比 {summary.get('up_ratio', '0%')})\n"
        f"📊 全市场成交: **{summary.get('total_amount', '--')}** | 主力资金: {flow_desc}{extra_stat}\n"
        f"🔥 领涨主线资金: **{lead_sec_str}**"
    )
    card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": market_md}})

    # 2. 模拟账户当前资金小看板 (实时动态资产与盘中盈亏)
    if account_data:
        total_assets = account_data.get("total_assets", 100000.0)
        cash = account_data.get("cash", 100000.0)
        pos_val = account_data.get("position_market_value", 0.0)
        pos_cnt = len(account_data.get("positions", []))
        daily_profit = account_data.get("daily_profit", 0.0)
        daily_ret = account_data.get("daily_return_pct", 0.0)
        total_profit = account_data.get("total_profit", 0.0)
        total_ret = account_data.get("total_return_pct", 0.0)
        profit_emoji = "🟢" if daily_profit >= 0 else "🔴"

        regime = analysis_res.get("regime", "中性")
        if regime == "进攻":
            regime_tag = " [🔥进攻·满仓4只]"
        elif regime == "防守":
            regime_tag = " [🛡️防守·上限2只/50%避险]"
        else:
            regime_tag = " [⚖️中性·上限3只/75%]"

        account_md = (
            f"💼 **10万模拟账户**{regime_tag}: 总资产 **￥{total_assets:,.2f}** | 可用现金: **￥{cash:,.2f}** | 持仓市值: **￥{pos_val:,.2f}** ({pos_cnt}只)\n"
            f"{profit_emoji} **今日盘中实时盈亏**: **{daily_profit:+,.2f}元 ({daily_ret:+.2f}%)** | 累计总收益: **{total_profit:+,.2f}元 ({total_ret:+.2f}%)**"
        )
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

    # 5. 今日推荐标的列表（按 S1~S4 策略分栏呈现）
    strat_sections = [
        ("S1", "🎯 **【S1 竞价首板 · 优选标的】**"),
        ("S2", "👑 **【S2 主线龙头 · 优选标的】**"),
        ("S3", "🛡️ **【S3 涨停回调 · 优选标的】**"),
        ("S4", "⚡ **【S4 量价突破 · 优选标的】**"),
        ("GENERIC", "🎯 **【短线综合先锋 · 优选标的】**"),
    ]

    grouped_stocks = {}
    for s in (pushed_stocks or []):
        sid = s.get("strategy_id") or "GENERIC"
        if sid not in grouped_stocks:
            grouped_stocks[sid] = []
        grouped_stocks[sid].append(s)

    has_any = False
    for sid, sec_title in strat_sections:
        s_list = grouped_stocks.get(sid, [])
        if not s_list:
            continue
        has_any = True
        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": sec_title}})

        stock_md_list = []
        for s in s_list:
            grade_badge = f"【{s['grade']}级 {s['score']}分】"
            leader_tag = " 👑板块龙头" if s.get("is_leader") else ""
            reasons_str = "、".join(s.get("reasons", [])[:3]) if s.get("reasons") else "符合战法量化模型"
            flow_tag = f"净买 **{fmt_amount(s.get('net_flow', 0))}** (占{s.get('flow_ratio', 0) * 100:+.1f}%)" if s.get('net_flow') else f"成交 {fmt_amount(s['amount'])}"
            sec_tag = f"`{s['sector']}` ({s.get('sector_flow_str', '--')})"

            buy_info_str = ""
            if s["code"] in buy_map:
                b = buy_map[s["code"]]
                buy_info_str = f"\n> 💼 **【10万实盘模拟买入】**: 买入 **{b['shares']}股** | 占用现金: **￥{b['cost_amount']:,.2f}** (仓位 {b['pos_ratio']:.1f}%)"

            # 风控失效判定
            sup_p = float(s.get("support_price") or s.get("open_price") or 0.0)
            if sid == "S1":
                veto_tips = f"开盘跌破竞价价 `￥{sup_p:.2f}` (2%) 或冲高回落走弱超2% 即失效"
            elif sid == "S2":
                veto_tips = f"跌破开盘价 `￥{sup_p:.2f}` 或板块资金断崖净流出即失效"
            elif sid == "S3":
                veto_tips = f"有效跌破首板最低价支撑 `￥{sup_p:.2f}` 即失效"
            elif sid == "S4":
                veto_tips = f"跌回突破前高平台顶 `￥{sup_p:.2f}` 超过2% 即失效"
            else:
                veto_tips = f"跌破防守止损线 `￥{s.get('stop_loss', 0.0):.2f}` 即失效"

            stock_md_list.append(
                f"🟢 **{s['code']} {s['name']}** (现价: **￥{s['price']:.2f}** | {s['change']:+.2f}%){leader_tag}\n"
                f"> 战法: **`{s.get('strategy_tag')}`** | 评级: **{grade_badge}**\n"
                f"> 行业: {sec_tag} | {flow_tag}\n"
                f"> 核心依据: {reasons_str}{buy_info_str}\n"
                f"> 🚨 **风控失效线**: {veto_tips}"
            )

        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "\n\n".join(stock_md_list)}})
        card["elements"].append({"tag": "hr"})

    if not has_any:
        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "⚠️ 今日当前时段无达到合格门槛的标的，建议保持耐心，防守观望。"}})
        card["elements"].append({"tag": "hr"})

    # 6. 底部短线纪律提示
    if stage == "afternoon":
        tips_md = "🌙 **尾盘决胜提醒**: 14:30 尾盘确定性最高，优先低吸 S3 涨停回调到位与 S4 回踩守稳标的，防范次日诱多！"
    elif stage == "settle":
        tips_md = "💡 **早盘定势提醒**: 开盘半小时已过，主要主线已明朗，切忌追高无主力资金承接的后排杂毛股！"
    elif stage == "confirm":
        tips_md = "⚠️ **短线实战铁律**: A股严格执行 T+1 制度，买入当日锁定不可卖出，次日若破防守线且无法收回坚决止损！"
    else:
        tips_md = "💡 **竞价操作提醒**: 9:25-9:30 为锁单期不可撤单，请在 9:30 开盘后根据分时主力承接决定是否买入。"

    card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": tips_md}})

    return card
