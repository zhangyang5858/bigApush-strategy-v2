"""
短线决策台 V2 量化计算引擎 (Scalp Decision Engine V2)
集成多战法分型：
- 09:26 竞价初筛: 聚焦【🔥 竞价爆量弱转强】与【🎯 综合短线先锋】
- 09:35 开盘确认: 输出【💥 强攻打板突破】与【🛡️ 稳健回踩VWAP低吸】分类买点
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
FIELDS = "f2,f3,f5,f6,f8,f10,f12,f14,f17,f18,f20,f21,f31,f32,f33,f34,f35,f36,f37,f38,f39,f40,f62,f100"


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
    """获取涨跌停池与连板天梯"""
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
        # 行业热度得分 (0-100)
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
        chg = 2.5 + (i % 8) * 0.95 if is_strong else -3.0 + (i % 15) * 0.55
        pre = round(7.0 + (i % 38) * 1.85, 2)
        open_p = round(pre * (1 + chg / 100), 2)
        # 现价与均线偏离
        now_p = round(open_p * (1 + (0.015 if is_strong else -0.015) + (i % 5 - 2) * 0.004), 2)
        now_chg = round((now_p / pre - 1) * 100, 2)
        amt = (3200 if is_strong else 400) * (1 + (i % 9) * 0.6) * 10000
        cap = (18 + (i % 70) * 1.6) * 1e8
        demo.append({
            "f12": f"{'60' if i % 2 == 0 else '00'}{1000 + i:04d}"[-6:],
            "f14": prefix[i % len(prefix)] + prefix[(i + 3) % len(prefix)] + suffix[i % len(suffix)] + (str(i) if i > 8 else ""),
            "f2": now_p,
            "f3": now_chg,
            "f5": amt / now_p / 100,
            "f6": amt,
            "f8": 1.5 + (i % 12) * 0.7,
            "f10": 1.2 + (i % 8) * 0.8,
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
    if 2.0 <= chg <= 5.5: return 95  # 黄金高开区间
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


def analyze_scalp_market_v2(raw_stocks=None, is_confirm_stage=False, is_demo=False, min_score=60, min_cap=15, max_cap=160, min_amount_wan=500):
    """
    短线决策台 V2 全市场量化多因子评分引擎
    """
    if not raw_stocks:
        if is_demo:
            raw_stocks = get_demo_stocks()
        else:
            raw_stocks = load_market_pages()

    if not raw_stocks:
        return {"stocks": [], "sectors": [], "regime": "等待", "summary": {}, "ladder": {}}

    zt_pool = load_limit_pools() if not is_demo else []
    zt_codes = {str(item.get("c") or item.get("f12") or "") for item in zt_pool}

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

        # ── 1. 竞价阶段 5 大因子加权打分 (权重: 25%, 20%, 20%, 20%, 15%) ──
        f_amt = score_auction_amount(auction_amt)
        f_chg = score_auction_change(auction_chg)
        f_vol = score_volume_ratio(vol_ratio, turnover)
        f_sec = clamp(sec_info["score"], 0, 100)
        f_cap = score_market_cap(float_cap, min_cap, max_cap)

        auction_score_raw = (f_amt * 25 + f_chg * 20 + f_vol * 20 + f_sec * 20 + f_cap * 15) / 100.0
        auction_score = clamp(auction_score_raw + market_bonus, 0, 100)

        # ── 2. 开盘确认阶段 4 大因子打分 (权重: 30%, 30%, 25%, 15%) ──
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
        final_score = clamp(final_score, 0, 100)

        # ── 战法形态识别 ──
        # 1. 爆量弱转强
        is_breakthrough = (vol_ratio >= 1.8 and 1.5 <= auction_chg <= 6.5 and f_amt >= 75)
        # 2. 开盘VWAP低吸
        is_low_absorb = (vwap_diff >= 0 and hold_diff >= 0 and auction_chg <= 3.5 and f_hold >= 75)

        if is_breakthrough:
            strategy_tag = "🔥 竞价爆量弱转强"
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
            if f_hold >= 75:
                reasons.append(f"站稳开盘价(偏离{hold_diff * 100:+.1f}%)")
            if f_vwap >= 75:
                reasons.append(f"稳居VWAP均线上方({vwap_diff:+.1f}%)")

        # 硬性否决
        if "ST" in name.upper() or "退" in name:
            risks.append("ST/退市风险")
        if float_cap < min_cap or float_cap > max_cap:
            risks.append(f"流通值{float_cap:.1f}亿超出设定")
        if auction_amt < min_amt:
            risks.append(f"竞价成交{fmt_amount(auction_amt)}不足")
        if hold_diff < -0.02:
            risks.append(f"开盘跌破竞价价2%({hold_diff * 100:.1f}%)")
        if trend_diff < -3.0:
            risks.append("冲高回落走弱超3%")

        is_hard_veto = len(risks) > 0
        grade = "S" if final_score >= 82 else "A" if final_score >= 70 else "B" if final_score >= 58 else "C"
        is_qualified = (not is_hard_veto) and (final_score >= min_score)

        if not code or pre_close <= 0 or code.startswith(("688", "8", "4")):
            continue

        stop_loss_price = open_price * 0.98
        is_leader = (sec_info["leader"] == name)

        analyzed_stocks.append({
            "code": code,
            "name": name,
            "price": cur_price,
            "open_price": open_price,
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
            "is_low_absorb": is_low_absorb,
            "is_leader": is_leader,
            "reasons": reasons,
            "risks": risks,
            "is_zt": code in zt_codes,
        })

    analyzed_stocks.sort(key=lambda s: s["score"], reverse=True)

    return {
        "stocks": analyzed_stocks,
        "sectors": sec_list[:8],
        "regime": regime,
        "summary": {
            "ups": ups,
            "downs": downs,
            "up_ratio": f"{up_ratio * 100:.0f}%",
            "total_amount": fmt_amount(total_amt),
            "total_count": len(raw_stocks),
            "qualified_count": sum(1 for s in analyzed_stocks if s["qualified"]),
        }
    }


def build_scalp_feishu_card_v2(analysis_res, stage="auction"):
    """
    短线决策台 V2 专属分时段智能飞书卡片
    - 09:26 竞价阶段: 聚焦【🔥 竞价爆量弱转强】
    - 09:35 确认阶段: 分组呈现【💥 强攻打板先锋】与【🛡️ 稳健回踩VWAP低吸】
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary = analysis_res.get("summary", {})
    regime = analysis_res.get("regime", "中性")
    sectors = analysis_res.get("sectors", [])
    stocks = analysis_res.get("stocks", [])

    is_confirm = (stage == "confirm")
    title_text = f"🚀 缅A开盘承接强攻榜 ({now_str[11:16]})" if is_confirm else f"☀️ 缅A早盘竞价初筛榜 ({now_str[11:16]})"
    header_color = "red" if is_confirm else "orange"

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title_text},
            "template": header_color
        },
        "elements": []
    }

    # 1. 市场环境与领涨主线
    regime_emoji = "🔥" if regime == "进攻" else "🛡️" if regime == "防守" else "⚖️"
    lead_sec_str = " | ".join([f"{s['name']}(+{s['avg_pct']:.1f}%{(' 👑' + s['leader']) if s.get('leader') else ''})" for s in sectors[:3]]) if sectors else "暂无"
    market_md = (
        f"{regime_emoji} **大盘姿态**: 【**{regime}模式**】 (上涨: {summary.get('ups', 0)} / 下跌: {summary.get('downs', 0)} | 占比 {summary.get('up_ratio', '0%')})\n"
        f"📊 全市场成交: **{summary.get('total_amount', '--')}** | 领涨主线: **{lead_sec_str}**"
    )
    card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": market_md}})
    card["elements"].append({"tag": "hr"})

    qualified_stocks = [s for s in stocks if s["qualified"]]

    if not is_confirm:
        # ── 09:26 竞价初筛阶段 ──
        section_title = "🎯 **【竞价高分先锋 · 锁定今日观察池】**"
        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": section_title}})

        top_auction_picks = (
            [s for s in qualified_stocks if s["is_breakthrough"]][:3] or
            qualified_stocks[:4] or
            stocks[:3]
        )

        stock_md_list = []
        for s in top_auction_picks:
            grade_badge = f"【{s['grade']}级 {s['score']}分】"
            leader_tag = " 👑板块龙头" if s["is_leader"] else ""
            zt_tag = " [涨停板]" if s["is_zt"] else ""
            reasons_str = "、".join(s["reasons"][:3]) if s["reasons"] else "符合竞价动能模型"

            stock_md_list.append(
                f"🟢 **{s['code']} {s['name']}** (竞价开盘: **￥{s['open_price']:.2f}** | {s['auction_change']:+.2f}%){leader_tag}{zt_tag}\n"
                f"> 战法: **`{s['strategy_tag']}`** | 评级: **{grade_badge}**\n"
                f"> 行业: `{s['sector']}` | 竞价成交: `{fmt_amount(s['amount'])}` | 流通: `{s['float_cap']:.1f}亿`\n"
                f"> 特征: {reasons_str}\n"
                f"> 🎯 **盯盘策略**: 9:30开盘观察分时承接，不破 ￥{s['open_price']:.2f} 即可择机买入"
            )

        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "\n\n".join(stock_md_list) if stock_md_list else "⚠️ 今日早盘竞价无达到合格门槛的标的，建议防守观望。"}})

    else:
        # ── 09:35 开盘确认阶段 (强攻打板 + 回踩低吸 分组呈现) ──
        break_picks = [s for s in qualified_stocks if s["is_breakthrough"] or s["score"] >= 82][:2]
        absorb_picks = [s for s in qualified_stocks if s["is_low_absorb"] and s not in break_picks][:2]

        if not break_picks and not absorb_picks:
            break_picks = qualified_stocks[:2]
            absorb_picks = qualified_stocks[2:4]

        # 1. 强攻打板先锋
        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "💥 **【强攻打板 / 弱转强先锋】**"}})
        if break_picks:
            break_md = []
            for s in break_picks:
                leader_tag = " 👑板块龙头" if s["is_leader"] else ""
                reasons_str = "、".join(s["reasons"][:3]) if s["reasons"] else "开盘资金持续抢筹"
                break_md.append(
                    f"🟢 **{s['code']} {s['name']}** (现价: **￥{s['price']:.2f}** | {s['change']:+.2f}%){leader_tag}\n"
                    f"> 战法: **`{s['strategy_tag']}`** | 评级: **【{s['grade']}级 {s['score']}分】**\n"
                    f"> 行业: `{s['sector']}` | 均线偏离: `VWAP {s['vwap_diff']:+.1f}%`\n"
                    f"> 依据: {reasons_str}\n"
                    f"> 💡 **强攻买入**: 现价或开盘价上方挂单抢筹\n"
                    f"> 🚨 **防守止损线**: `￥{s['stop_loss']:.2f}` (跌破开盘2%坚决止损)"
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
                leader_tag = " 👑板块龙头" if s["is_leader"] else ""
                reasons_str = "、".join(s["reasons"][:3]) if s["reasons"] else "稳稳站上分时均线"
                absorb_md.append(
                    f"🟢 **{s['code']} {s['name']}** (现价: **￥{s['price']:.2f}** | {s['change']:+.2f}%){leader_tag}\n"
                    f"> 战法: **`{s['strategy_tag']}`** | 评级: **【{s['grade']}级 {s['score']}分】**\n"
                    f"> 行业: `{s['sector']}` | 均线偏离: `VWAP {s['vwap_diff']:+.1f}%`\n"
                    f"> 依据: {reasons_str}\n"
                    f"> 💡 **低吸区间**: `￥{s['open_price']:.2f} ~ ￥{s['price']:.2f}` (回踩均线买入)\n"
                    f"> 🚨 **防守止损线**: `￥{s['stop_loss']:.2f}`"
                )
            card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "\n\n".join(absorb_md)}})
        else:
            card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "暂无明显均线低吸标的"}})

    card["elements"].append({"tag": "hr"})

    # 3. 底部短线纪律提示
    if is_confirm:
        tips_md = "⚠️ **短线买入铁律**: 单只标的仓位 $\\le 30\\%$，盘中若跌破防守线且3分钟无法收回，无条件执行止损！"
    else:
        tips_md = "💡 **竞价操作提醒**: 9:25-9:30 为锁单期不可撤单，请在 9:30 开盘后根据分时承接决定是否买入。"

    card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": tips_md}})

    return card
