"""
短线决策台专属量化计算引擎 (Scalp Decision Engine)
基于 9:15-9:25 集合竞价打分 + 9:30-9:40 开盘承接确认模型
"""
import math
import time
import requests
from datetime import datetime

EM_URL = "https://push2dycalc.eastmoney.com/api/qt/clist/get"
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


def load_market_pages(max_pages=10, timeout=10):
    """拉取东财全市场行情数据"""
    all_stocks = []
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    for p in range(1, max_pages + 1):
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
        try:
            resp = requests.get(EM_URL, params=params, headers=headers, timeout=timeout)
            data = resp.json().get("data", {}).get("diff", [])
            if not data:
                break
            all_stocks.extend(data)
            if len(data) < 500:
                break
        except Exception as e:
            print(f"  ⚠️ 拉取第 {p} 页行情异常: {e}")
            break
    return all_stocks


def load_zt_pool():
    """获取涨停池"""
    today_str = datetime.now().strftime("%Y%m%d")
    url = f"{EM_POOL_URL}/getTopicZTPool"
    params = {
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "dpt": "wz.ztzt",
        "Pageindex": "0",
        "Pagesize": "500",
        "sort": "fbt:asc",
        "date": today_str,
        "_": str(int(time.time() * 1000)),
    }
    try:
        resp = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
        return resp.json().get("data", {}).get("pool", []) or []
    except Exception:
        return []


def build_sector_map(raw_stocks):
    """行业板块涨幅与强势股聚合"""
    sector_map = {}
    for x in raw_stocks:
        s_name = x.get("f100") or "其他"
        if s_name not in sector_map:
            sector_map[s_name] = {"name": s_name, "count": 0, "up": 0, "strong": 0, "sum_pct": 0.0, "amount": 0.0}
        sec = sector_map[s_name]
        chg = n(x.get("f3"))
        sec["count"] += 1
        sec["sum_pct"] += chg
        sec["amount"] += n(x.get("f6"))
        if chg > 0:
            sec["up"] += 1
        if chg >= 3.0:
            sec["strong"] += 1

    sectors = []
    for sec in sector_map.values():
        cnt = sec["count"] or 1
        avg_pct = sec["sum_pct"] / cnt
        breadth = sec["up"] / cnt
        # 行业强度得分 (0-30)
        score = clamp(avg_pct * 7 + breadth * 20 + sec["strong"] * 2, 0, 30)
        sectors.append({
            "name": sec["name"],
            "count": cnt,
            "avg_pct": avg_pct,
            "strong": sec["strong"],
            "amount": sec["amount"],
            "score": score
        })
    sectors.sort(key=lambda s: s["score"], reverse=True)
    return {s["name"]: s for s in sectors}, sectors


def get_demo_stocks():
    """生成非交易时段测试用的高仿真数据"""
    sectors = ["机器人", "电力设备", "消费电子", "汽车零部件", "半导体", "低空经济"]
    demo = []
    for i in range(72):
        strong = i < 20
        chg = 1.7 + (i % 10) * 0.58 if strong else -2.0 + (i % 13) * 0.34
        pre = 8.0 + (i % 35) * 1.7
        open_p = pre * (1 + chg / 100)
        amt = (1800 if strong else 350) * (1 + i % 8) * 10000
        cur_p = open_p * (1 + (i % 5 - 1) * 0.005)
        demo.append({
            "f12": f"{'60' if i % 3 == 0 else '00'}{1000 + i:04d}"[-6:],
            "f14": ["华锐科技", "远景动力", "启明智造", "中科新材", "恒泰股份", "新域电子"][i % 6] + (str(i) if i > 5 else ""),
            "f2": cur_p,
            "f3": chg + (i % 5 - 1) * 0.25,
            "f5": amt / open_p / 100,
            "f6": amt,
            "f8": 1.2 + i % 9,
            "f10": 1.1 + (i % 7) * 0.42,
            "f17": open_p,
            "f18": pre,
            "f21": (18 + i % 95) * 1e8,
            "f20": (30 + i % 160) * 1e8,
            "f62": amt * 0.18 if i % 2 == 0 else -amt * 0.1,
            "f100": sectors[i % len(sectors)]
        })
    return demo


def analyze_scalp_market(raw_stocks=None, is_confirm_stage=False, is_demo=False, min_score=60, min_cap=15, max_cap=150, min_amount_wan=1000):
    """
    短线决策台全市场评分算法核心
    stage: False = 9:26 竞价初筛; True = 9:35 开盘确认
    """
    if not raw_stocks:
        if is_demo:
            raw_stocks = get_demo_stocks()
        else:
            raw_stocks = load_market_pages()

    if not raw_stocks:
        return {"stocks": [], "sectors": [], "regime": "等待", "summary": {}}

    zt_pool = load_zt_pool() if not is_demo else []
    zt_codes = {str(item.get("c") or item.get("f12") or "") for item in zt_pool}

    sec_dict, sec_list = build_sector_map(raw_stocks)

    ups = sum(1 for x in raw_stocks if n(x.get("f3")) > 0)
    downs = sum(1 for x in raw_stocks if n(x.get("f3")) < 0)
    total_amt = sum(n(x.get("f6")) for x in raw_stocks)
    up_ratio = ups / len(raw_stocks) if raw_stocks else 0

    # 市场情绪评估
    if up_ratio > 0.58:
        regime = "进攻"
        market_adj = 8
    elif up_ratio < 0.38:
        regime = "防守"
        market_adj = -8
    else:
        regime = "中性"
        market_adj = 2

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
        float_cap = n(x.get("f21")) / 1e8  # 亿元
        vol_ratio = n(x.get("f10"))
        sector_name = x.get("f100") or "其他"
        sec_info = sec_dict.get(sector_name, {"score": 0, "avg_pct": 0, "strong": 0})

        # 竞价涨跌幅
        auction_chg = (open_price / pre_close - 1) * 100 if pre_close > 0 else cur_chg
        auction_amt = amt  # 在 9:25 集合竞价时刻，成交额即为竞价额

        reasons = []
        risks = []

        # ── 1. 竞价多维度打分 ──
        # 资金强度 (0-24分)
        amount_score = clamp(math.log10(max(auction_amt / 1e4, 1.0)) * 7 - 8, 0, 24)
        # 高开合理性 (0-18分)
        if 1.5 <= auction_chg <= 6.5:
            price_score = 18
        elif 0.0 < auction_chg < 9.0:
            price_score = 10
        else:
            price_score = 2
        # 量比得分 (0-15分)
        vol_score = clamp((vol_ratio - 1) * 6 + 5, 0, 15)
        # 行业板块得分 (0-20分)
        sector_score = clamp(sec_info["score"], 0, 20)
        # 市值得分 (0-10分)
        if 20 <= float_cap <= 100:
            cap_score = 10
        elif min_cap <= float_cap <= max_cap:
            cap_score = 6
        else:
            cap_score = 0

        auction_total = clamp(amount_score + price_score + vol_score + sector_score + cap_score + market_adj * 0.4, 0, 100)

        if amount_score >= 12:
            reasons.append(f"竞价成交额{fmt_amount(auction_amt)}(强度{amount_score:.0f}/24)")
        if price_score >= 10:
            reasons.append(f"黄金高开+{auction_chg:.2f}%")
        if sector_score >= 10:
            reasons.append(f"{sector_name}行业领涨(+{sec_info['avg_pct']:.1f}%)")

        # ── 2. 开盘承接确认打分 ──
        confirm_total = 0
        if is_confirm_stage:
            hold = (cur_price / open_price - 1) if open_price > 0 else 0
            # 现价是否守住开盘价 (0-22分)
            if hold >= 0:
                price_hold = 22
                reasons.append(f"开盘强势承接不破(现价高于开盘{hold * 100:+.1f}%)")
            elif hold > -0.015:
                price_hold = 12
                reasons.append("开盘小幅震荡承接")
            else:
                price_hold = 0
                risks.append(f"开盘跌破竞价价({hold * 100:.1f}%)")

            # 强度延续 (0-20分)
            trend = cur_chg - auction_chg
            if trend >= 0.3:
                trend_score = 20
                reasons.append(f"盘中持续走强(+{trend:.1f}%)")
            elif trend >= -0.5:
                trend_score = 12
            else:
                trend_score = 2
                if trend < -2.0:
                    risks.append("高开后明显回落走弱")

            # 流动性放量 (0-18分)
            liquidity_score = clamp(math.log10(max(amt / 1e4, 1.0)) * 8 - 12, 0, 18)
            confirm_total = clamp(price_hold + trend_score + liquidity_score + sector_score + market_adj * 0.5, 0, 100)

        # ── 3. 硬性否决条件 ──
        if "ST" in name.upper() or "退" in name:
            risks.append("ST/退市风险")
        if float_cap < min_cap or float_cap > max_cap:
            risks.append(f"流通市值{float_cap:.1f}亿超出范围")
        if auction_amt < min_amt:
            risks.append(f"竞价成交额{fmt_amount(auction_amt)}不足1000万")
        if auction_chg < 1.5 or auction_chg > 8.0:
            risks.append(f"高开幅度{auction_chg:+.1f}%不在优选区间")
        if cur_price < 4.0 or cur_price > 112.0:
            risks.append(f"股价{cur_price:.2f}元超出范围")

        final_score = (auction_total * 0.4 + confirm_total * 0.6) if is_confirm_stage else auction_total
        final_score = clamp(final_score, 0, 100)
        is_hard_veto = len(risks) > 0

        # 评级
        grade = "S" if final_score >= 80 else "A" if final_score >= 70 else "B" if final_score >= 60 else "C"
        is_qualified = (not is_hard_veto) and (final_score >= min_score)

        # 排除科创板/北交所
        if not code or pre_close <= 0 or code.startswith(("688", "8", "4")):
            continue

        stop_loss_price = open_price * 0.98  # 开盘价 2% 严格防守线

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
            "auction_score": round(auction_total, 1),
            "confirm_score": round(confirm_total, 1) if is_confirm_stage else None,
            "grade": grade,
            "qualified": is_qualified,
            "hard_veto": is_hard_veto,
            "reasons": reasons,
            "risks": risks,
            "is_zt": code in zt_codes,
        })

    # 按最终分数从高到低排序
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


def build_scalp_feishu_card(analysis_res, stage="auction"):
    """
    构建短线决策台专属飞书交互式卡片 JSON
    stage: 'auction' (09:26 竞价初筛) | 'confirm' (09:35 开盘确认)
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

    # 1. 市场环境概览
    regime_emoji = "🔥" if regime == "进攻" else "🛡️" if regime == "防守" else "⚖️"
    lead_sec_str = " | ".join([f"{s['name']}(+{s['avg_pct']:.1f}%)" for s in sectors[:3]]) if sectors else "暂无"
    market_md = (
        f"{regime_emoji} **市场模式**: 【**{regime}模式**】 (上涨: {summary.get('ups', 0)} / 下跌: {summary.get('downs', 0)} | 占比 {summary.get('up_ratio', '0%')})\n"
        f"📊 全市场成交额: **{summary.get('total_amount', '--')}** | 领涨主线: **{lead_sec_str}**"
    )
    card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": market_md}})
    card["elements"].append({"tag": "hr"})

    # 2. 核心买入信号推荐区 (TOP 3 ~ 5)
    qualified_stocks = [s for s in stocks if s["qualified"]]
    top_picks = qualified_stocks[:5] if qualified_stocks else stocks[:3]

    section_title = "🎯 **【强烈买入信号 (S级/A级强承接)】**" if is_confirm else "🎯 **【竞价高分候选 (加入自选盯盘)】**"
    card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": section_title}})

    if top_picks:
        stock_md_list = []
        for s in top_picks:
            grade_badge = f"【{s['grade']}级 评分:{s['score']}分】"
            zt_tag = " [涨停板]" if s["is_zt"] else ""
            reasons_str = "、".join(s["reasons"][:3]) if s["reasons"] else "符合短线动能模型"

            if is_confirm:
                # 09:35 开盘确认卡片格式：标明买入区间和严格防守线
                buy_range_str = f"{s['open_price']:.2f} ~ {s['price']:.2f}"
                stock_md_list.append(
                    f"🟢 **{s['code']} {s['name']}** (现价: **￥{s['price']:.2f}** | {s['change']:+.2f}%){zt_tag}\n"
                    f"> 评级: **{grade_badge}** | 行业: `{s['sector']}` | 流通值: `{s['float_cap']:.1f}亿`\n"
                    f"> 依据: {reasons_str}\n"
                    f"> 💡 **建议买入区间**: `￥{buy_range_str}`\n"
                    f"> 🚨 **防守止损线**: `￥{s['stop_loss']:.2f}` (跌破开盘2%坚决止损)"
                )
            else:
                # 09:26 竞价初筛卡片格式：标明竞价开盘价和特征
                stock_md_list.append(
                    f"🟢 **{s['code']} {s['name']}** (竞价开盘: **￥{s['open_price']:.2f}** | {s['auction_change']:+.2f}%){zt_tag}\n"
                    f"> 评级: **{grade_badge}** | 行业: `{s['sector']}` | 竞价成交: `{fmt_amount(s['amount'])}`\n"
                    f"> 特征: {reasons_str}\n"
                    f"> 🎯 **盯盘策略**: 9:30开盘观察承接，不跌破 ￥{s['open_price']:.2f} 即可择机买入"
                )
        card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "\n\n".join(stock_md_list)}})
    else:
        card["elements"].append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "⚠️ 今日早盘全市场无达到 S/A 级门槛的短线标的，建议防守空仓观望。"}
        })

    card["elements"].append({"tag": "hr"})

    # 3. 底部短线纪律提示
    if is_confirm:
        tips_md = "⚠️ **短线买入铁律**: 单只标的仓位 $\\le 30\\%$，若盘中跌破防守线且3分钟无法收回，无条件执行止损！"
    else:
        tips_md = "💡 **竞价操作提醒**: 9:25-9:30 为锁单期不可撤单，请在 9:30 开盘后根据分时承接决定是否买入。"

    card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": tips_md}})

    return card
