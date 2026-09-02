"""
短线决策台 V2 量化计算引擎 (Scalp Decision Engine V2)
三阶段早盘超短线量化推送体系：
1. 09:26 竞价初筛 (`stage="auction"`): 聚焦【🔥 竞价爆量弱转强】与【🎯 综合短线先锋】
2. 09:35 开盘确认 (`stage="confirm"`): 聚焦【💥 强攻打板先锋】与【🛡️ 稳健回踩VWAP低吸】
3. 09:55 早盘定势 (`stage="settle"`): 聚焦【🏆 主线封板龙头确认/排板】与【🌊 二波回踩蓄势低吸】
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
    """拉取东财全市场行情数据（支持多域名容灾）"""
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


def build_sector_map(raw_stocks):
    """行业板块涨幅、强势股与龙头聚合"""
    sector_map = {}
    for x in raw_stocks:
        s_name = x.get("f100") or "其他"
        if s_name not in sector_map:
            sector_map[s_name] = {
                "name": s_name, "count": 0, "up": 0, "strong": 0,
                "sum_pct": 0.0, "amount": 0.0, "leader": "", "max_chg": -99.0
            }
        sec = sector_map[s_name]
        chg = n(x.get("f3"))
        sec["count"] += 1
        sec["sum_pct"] += chg
        sec["amount"] += n(x.get("f6"))
        if chg > 0:
            sec["up"] += 1
        if chg >= 3.5:
            sec["strong"] += 1
        if chg > sec["max_chg"]:
            sec["max_chg"] = chg
            sec["leader"] = x.get("f14") or ""

    sectors = []
    for sec in sector_map.values():
        cnt = sec["count"] or 1
        avg_pct = sec["sum_pct"] / cnt
        breadth = sec["up"] / cnt
        score = clamp(avg_pct * 12 + breadth * 45 + sec["strong"] * 4 + 30, 10, 100)
        sectors.append({
            "name": sec["name"],
            "count": cnt,
            "avg_pct": avg_pct,
            "strong": sec["strong"],
            "amount": sec["amount"],
            "score": score,
            "leader": sec["leader"]
        })
    sectors.sort(key=lambda s: s["score"], reverse=True)
    return {s["name"]: s for s in sectors}, sectors


def get_demo_stocks():
    """生成 V2 高保真模拟数据"""
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
            "f62": amt * 0.22 if is_strong else -amt * 0.1,
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


def analyze_scalp_market_v2(raw_stocks=None, stage="auction", is_demo=False, min_score=60, min_cap=15, max_cap=160, min_amount_wan=500):
    """
    短线决策台 V2 全市场量化多因子评分引擎
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

    sec_dict, sec_list = build_sector_map(raw_stocks)

    ups = sum(1 for x in raw_stocks if n(x.get("f3")) > 0)
    downs = sum(1 for x in raw_stocks if n(x.get("f3")) < 0)
    total_amt = sum(n(x.get("f6")) for x in raw_stocks)
    up_ratio = ups / len(raw_stocks) if raw_stocks else 0

    if up_ratio > 0.58:
        regime = "进攻"
        market_bonus = 4
    elif up_ratio < 0.38:
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
        float_cap = n(x.get("f21")) / 1e8
        vol_ratio = n(x.get("f10"))
        turnover = n(x.get("f8"))
        sector_name = x.get("f100") or "其他"
        sec_info = sec_dict.get(sector_name, {"score": 50, "avg_pct": 0, "strong": 0, "leader": ""})

        auction_chg = (open_price / pre_close - 1) * 100 if pre_close > 0 else cur_chg
        auction_amt = amt

        reasons = []
        risks = []

        # ── 1. 竞价阶段 5 大因子加权打分 ──
        f_amt = score_auction_amount(auction_amt)
        f_chg = score_auction_change(auction_chg)
        f_vol = score_volume_ratio(vol_ratio, turnover)
        f_sec = clamp(sec_info["score"], 0, 100)
        f_cap = score_market_cap(float_cap, min_cap, max_cap)

        auction_score_raw = (f_amt * 25 + f_chg * 20 + f_vol * 20 + f_sec * 20 + f_cap * 15) / 100.0
        auction_score = clamp(auction_score_raw + market_bonus, 0, 100)

        # ── 2. 开盘承接确认各因子 ──
        hold_diff = (cur_price / open_price - 1) if open_price > 0 else 0
        f_hold = score_price_hold(hold_diff)
        trend_diff = cur_chg - auction_chg
        f_trend = score_trend(trend_diff)
        f_liq = score_liquidity(amt)
        vwap_est = (open_price + cur_price) / 2.0
        vwap_diff = (cur_price / vwap_est - 1) * 100 if vwap_est > 0 else 0
        f_vwap = score_vwap_diff(vwap_diff / 100.0)

        confirm_score_raw = (f_hold * 30 + f_trend * 25 + f_liq * 15 + f_vwap * 30) / 100.0
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

        # ── 战法形态识别 ──
        is_breakthrough = (vol_ratio >= 1.8 and 1.5 <= auction_chg <= 6.5 and f_amt >= 75)
        is_wave2_absorb = (vwap_diff >= 0 and hold_diff >= 0 and 2.5 <= cur_chg <= 7.5 and not is_zt and f_vwap >= 75)
        is_low_absorb = (vwap_diff >= 0 and hold_diff >= 0 and auction_chg <= 3.5 and f_hold >= 75)

        if is_zt:
            strategy_tag = f"🏆 主线封板 ({lbc}连板)" if lbc > 1 else "🏆 主线首板"
        elif is_breakthrough:
            strategy_tag = "🔥 竞价爆量弱转强"
        elif is_wave2_absorb:
            strategy_tag = "🌊 二波回踩蓄势低吸"
        elif is_low_absorb:
            strategy_tag = "🛡️ VWAP低吸承接"
        else:
            strategy_tag = "🎯 综合短线先锋"

        # 依据与风险
        if f_amt >= 75:
            reasons.append(f"竞价抢筹{fmt_amount(auction_amt)}(分{f_amt})")
        if f_chg >= 75:
            reasons.append(f"黄金高开{auction_chg:+.2f}%")
        if f_vol >= 75:
            reasons.append(f"量比{vol_ratio:.1f}/换手{turnover:.1f}%")
        if f_sec >= 70:
            reasons.append(f"{sector_name}主线领涨(+{sec_info['avg_pct']:.1f}%)")
        if is_confirm_stage:
            if is_zt:
                reasons.append(f"早盘坚决封涨停(封单约{fmt_amount(seal_fund)})")
            elif f_hold >= 75:
                reasons.append(f"站稳开盘价(偏离{hold_diff * 100:+.1f}%)")
            if f_vwap >= 75:
                reasons.append(f"稳居VWAP均线上方({vwap_diff:+.1f}%)")

        # 硬性否决：排除新股(N/C前缀)、ST、退市股
        if name.startswith(("N", "C", "ST", "*ST")) or "ST" in name.upper() or "退" in name:
            risks.append("新股/ST/退市风险")
        if float_cap < min_cap or float_cap > max_cap:
            risks.append(f"流通值{float_cap:.1f}亿超出设定")
        if auction_amt < min_amt:
            risks.append(f"竞价成交{fmt_amount(auction_amt)}不足")
        if hold_diff < -0.02 and not is_zt:
            risks.append(f"开盘跌破竞价价2%({hold_diff * 100:.1f}%)")
        if trend_diff < -3.5 and not is_zt:
            risks.append("冲高回落走弱超3.5%")

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
            "float_cap": float_cap,
            "sector": sector_name,
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
        "sectors": sec_list[:8],
        "regime": regime,
        "zt_count": len(zt_dict),
        "summary": {
            "ups": ups,
            "downs": downs,
            "up_ratio": f"{up_ratio * 100:.0f}%",
            "total_amount": fmt_amount(total_amt),
            "total_count": len(raw_stocks),
            "qualified_count": sum(1 for s in analyzed_stocks if s["qualified"]),
        }
    }


def get_stage_pushed_stocks(analysis_res, stage="auction"):
    """获取指定时段真正推荐上榜的个股列表（供卡片展示与每日复盘统一读取）"""
    stocks = analysis_res.get("stocks", [])
    qualified_stocks = [s for s in stocks if s.get("qualified")]

    if stage == "auction":
        picks = [s for s in qualified_stocks if s.get("is_breakthrough")][:3]
        if not picks:
            picks = qualified_stocks[:4] or stocks[:3]
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
    短线决策台 V2 专属分时段智能飞书卡片（支持 10万模拟盘买卖指令融合）
    - 09:26 竞价阶段 (`stage="auction"`): 聚焦【🔥 竞价爆量弱转强】+【昨日持仓竞价预警】
    - 09:35 确认阶段 (`stage="confirm"`): 分组呈现【💥 强攻打板先锋】+【🛡️ VWAP低吸】+【持仓止盈止损执行】
    - 09:55 定势阶段 (`stage="settle"`): 分组呈现【🏆 主线封板龙头】+【🌊 二波低吸】+【调仓处置】
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary = analysis_res.get("summary", {})
    regime = analysis_res.get("regime", "中性")
    sectors = analysis_res.get("sectors", [])
    zt_cnt = analysis_res.get("zt_count", 0)

    if pushed_stocks is None:
        pushed_stocks = get_stage_pushed_stocks(analysis_res, stage=stage)

    if stage == "settle":
        title_text = f"🏆 缅A早盘定势封板榜 ({now_str[11:16]})"
        header_color = "purple"
    elif stage == "confirm":
        title_text = f"🚀 缅A开盘承接强攻榜 ({now_str[11:16]})"
        header_color = "red"
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

    # 1. 市场大盘姿态
    regime_emoji = "🔥" if regime == "进攻" else "🛡️" if regime == "防守" else "⚖️"
    lead_sec_str = " | ".join([f"{s['name']}(+{s['avg_pct']:.1f}%{(' 👑' + s['leader']) if s.get('leader') else ''})" for s in sectors[:3]]) if sectors else "暂无"
    
    extra_stat = f" | 封板家数: **{zt_cnt}家**" if stage == "settle" else ""
    market_md = (
        f"{regime_emoji} **大盘姿态**: 【**{regime}模式**】 (上涨: {summary.get('ups', 0)} / 下跌: {summary.get('downs', 0)} | 占比 {summary.get('up_ratio', '0%')})\n"
        f"📊 全市场成交: **{summary.get('total_amount', '--')}**{extra_stat} | 领涨主线: **{lead_sec_str}**"
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

    # 3. 【📦 昨日持仓监控与 T+1 卖出操作指引】(如果有持仓或卖出动作)
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

    # 4. 构建买入匹配映射 (方便将 10 万模拟买入信息与标的绑定)
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
            reasons_str = "、".join(s.get("reasons", [])[:3]) if s.get("reasons") else "符合竞价动能模型"

            buy_info_str = ""
            if s["code"] in buy_map:
                b = buy_map[s["code"]]
                buy_info_str = f"\n> 💼 **【10万实盘模拟买入】**: 买入 **{b['shares']}股** | 占用现金: **￥{b['cost_amount']:,.2f}** (仓位 {b['pos_ratio']:.1f}%)"

            stock_md_list.append(
                f"🟢 **{s['code']} {s['name']}** (竞价开盘: **￥{s['open_price']:.2f}** | {s['auction_change']:+.2f}%){leader_tag}{zt_tag}\n"
                f"> 战法: **`{s['strategy_tag']}`** | 评级: **{grade_badge}**\n"
                f"> 行业: `{s['sector']}` | 竞价成交: `{fmt_amount(s['amount'])}` | 流通: `{s['float_cap']:.1f}亿`\n"
                f"> 特征: {reasons_str}{buy_info_str}\n"
                f"> 🎯 **盯盘策略**: 9:30开盘观察分时承接，不破 ￥{s['open_price']:.2f} 即可择机买入"
            )

        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "\n\n".join(stock_md_list) if stock_md_list else "⚠️ 今日早盘竞价无达到合格门槛的标的，建议防守观望。"}})

    elif stage == "confirm":
        # ── 09:35 开盘确认阶段 ──
        break_picks = [s for s in pushed_stocks if s.get("is_breakthrough") or s.get("score", 0) >= 82]
        absorb_picks = [s for s in pushed_stocks if s not in break_picks]

        # 1. 强攻打板先锋
        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "💥 **【强攻打板 / 弱转强先锋】**"}})
        if break_picks:
            break_md = []
            for s in break_picks:
                leader_tag = " 👑板块龙头" if s.get("is_leader") else ""
                reasons_str = "、".join(s.get("reasons", [])[:3]) if s.get("reasons") else "开盘资金持续抢筹"

                buy_info_str = ""
                if s["code"] in buy_map:
                    b = buy_map[s["code"]]
                    buy_info_str = f"\n> 💼 **【10万实盘模拟买入】**: 买入 **{b['shares']}股** | 占用现金: **￥{b['cost_amount']:,.2f}** (仓位 {b['pos_ratio']:.1f}%)"

                break_md.append(
                    f"🟢 **{s['code']} {s['name']}** (现价: **￥{s['price']:.2f}** | {s['change']:+.2f}%){leader_tag}\n"
                    f"> 战法: **`{s['strategy_tag']}`** | 评级: **【{s['grade']}级 {s['score']}分】**\n"
                    f"> 行业: `{s['sector']}` | 均线偏离: `VWAP {s['vwap_diff']:+.1f}%`\n"
                    f"> 依据: {reasons_str}{buy_info_str}\n"
                    f"> 💡 **强攻买入**: 现价或开盘价上方挂单抢筹\n"
                    f"> 🚨 **防守止损线**: `￥{s['stop_loss']:.2f}` (次日T+1跌破开盘2%坚决止损)"
                )
            card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "\n\n".join(break_md)}})
        else:
            card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "暂无明显强攻突破标的"}})

        card["elements"].append({"tag": "hr"})

        # 2. 稳健回踩低吸
        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "🛡️ **【稳健回踩 / VWAP均线低吸】**"}})
        if absorb_picks:
            absorb_md = []
            for s in absorb_picks:
                leader_tag = " 👑板块龙头" if s.get("is_leader") else ""
                reasons_str = "、".join(s.get("reasons", [])[:3]) if s.get("reasons") else "稳稳站上分时均线"

                buy_info_str = ""
                if s["code"] in buy_map:
                    b = buy_map[s["code"]]
                    buy_info_str = f"\n> 💼 **【10万实盘模拟买入】**: 买入 **{b['shares']}股** | 占用现金: **￥{b['cost_amount']:,.2f}** (仓位 {b['pos_ratio']:.1f}%)"

                absorb_md.append(
                    f"🟢 **{s['code']} {s['name']}** (现价: **￥{s['price']:.2f}** | {s['change']:+.2f}%){leader_tag}\n"
                    f"> 战法: **`{s['strategy_tag']}`** | 评级: **【{s['grade']}级 {s['score']}分】**\n"
                    f"> 行业: `{s['sector']}` | 均线偏离: `VWAP {s['vwap_diff']:+.1f}%`\n"
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

                buy_info_str = ""
                if s["code"] in buy_map:
                    b = buy_map[s["code"]]
                    buy_info_str = f"\n> 💼 **【10万实盘模拟买入】**: 买入 **{b['shares']}股** | 占用现金: **￥{b['cost_amount']:,.2f}** (仓位 {b['pos_ratio']:.1f}%)"

                zt_md.append(
                    f"🟢 **{s['code']} {s['name']}** (现价: **￥{s['price']:.2f}** | {s['change']:+.2f}% 涨停板){leader_tag}\n"
                    f"> 梯队: **`{s['strategy_tag']}`** | 评级: **【{s['grade']}级 {s['score']}分】**\n"
                    f"> 行业: `{s['sector']}` | 成交额: `{fmt_amount(s['amount'])}` | {seal_str}{buy_info_str}\n"
                    f"> 💡 **排单操作**: 主线最强龙头，若有炸板回封机会可直接排单打板"
                )
            card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "\n\n".join(zt_md)}})
        else:
            card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "早盘暂无核心涨停标的"}})

        card["elements"].append({"tag": "hr"})

        # 2. 二波回踩蓄势低吸
        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "🌊 **【二波回踩蓄势 · VWAP企稳低吸】**"}})
        if wave2_picks:
            wave2_md = []
            for s in wave2_picks:
                leader_tag = " 👑板块龙头" if s.get("is_leader") else ""
                reasons_str = "、".join(s.get("reasons", [])[:3]) if s.get("reasons") else "冲高后缩量横盘蓄势"

                buy_info_str = ""
                if s["code"] in buy_map:
                    b = buy_map[s["code"]]
                    buy_info_str = f"\n> 💼 **【10万实盘模拟买入】**: 买入 **{b['shares']}股** | 占用现金: **￥{b['cost_amount']:,.2f}** (仓位 {b['pos_ratio']:.1f}%)"

                wave2_md.append(
                    f"🟢 **{s['code']} {s['name']}** (现价: **￥{s['price']:.2f}** | {s['change']:+.2f}%){leader_tag}\n"
                    f"> 战法: **`{s['strategy_tag']}`** | 评级: **【{s['grade']}级 {s['score']}分】**\n"
                    f"> 行业: `{s['sector']}` | 均线偏离: `VWAP {s['vwap_diff']:+.1f}%`\n"
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
        tips_md = "💡 **早盘定势提醒**: 开盘半小时已过，主要主线已明朗，切忌追高无资金承接的后排杂毛股！"
    elif stage == "confirm":
        tips_md = "⚠️ **短线实战铁律**: A股严格执行 T+1 制度，买入当日锁定不可卖出，次日若破防守线且无法收回坚决止损！"
    else:
        tips_md = "💡 **竞价操作提醒**: 9:25-9:30 为锁单期不可撤单，请在 9:30 开盘后根据分时承接决定是否买入。"

    card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": tips_md}})

    return card
