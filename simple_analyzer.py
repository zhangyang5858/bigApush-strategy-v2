"""
简单买入建议分析模块
基于技术指标给股票打分，提供买入建议
"""
import requests
import json


def get_stock_kline(code):
    """获取股票K线数据"""
    try:
        # 判断市场
        if code.startswith("6") or code.startswith("88"):
            market = "sh"
        else:
            market = "sz"
        
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market}{code},day,,,60,qfq"
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        data = resp.json()
        
        klines = []
        stock_data = data.get("data", {}).get(f"{market}{code}", {})
        day_data = stock_data.get("qfqday") or stock_data.get("day", [])
        
        for item in day_data:
            if len(item) >= 6:
                klines.append({
                    "date": item[0],
                    "open": float(item[1]),
                    "close": float(item[2]),
                    "high": float(item[3]),
                    "low": float(item[4]),
                    "volume": float(item[5])
                })
        return klines
    except Exception:
        return []


def calculate_ma(klines, period):
    """计算移动平均线"""
    if len(klines) < period:
        return None
    closes = [k["close"] for k in klines[-period:]]
    return sum(closes) / period


def calculate_rsi(klines, period=14):
    """计算RSI"""
    if len(klines) < period + 1:
        return None
    
    closes = [k["close"] for k in klines[-(period + 1):]]
    gains = []
    losses = []
    
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0.0001
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_macd(klines):
    """计算MACD"""
    if len(klines) < 26:
        return None, None, None
    
    closes = [k["close"] for k in klines]
    
    # EMA12
    ema12 = closes[0]
    for i in range(1, len(closes)):
        ema12 = closes[i] * (2/13) + ema12 * (11/13)
    
    # EMA26
    ema26 = closes[0]
    for i in range(1, len(closes)):
        ema26 = closes[i] * (2/27) + ema26 * (25/27)
    
    dif = ema12 - ema26
    
    # 简化计算DEA
    dea = dif * 0.2
    
    macd = (dif - dea) * 2
    
    return dif, dea, macd


def analyze_stock(code, name, price=None):
    """分析单只股票，返回评分和建议"""
    klines = get_stock_kline(code)
    
    current_price = price
    if not current_price or current_price == "-":
        if klines and len(klines) > 0:
            current_price = f"{klines[-1]['close']:.2f}"
        else:
            current_price = "-"

    if not klines or len(klines) < 20:
        return {
            "code": code,
            "name": name,
            "price": current_price,
            "score": 0,
            "advice": "数据不足",
            "reasons": [],
            "strategies": []
        }
    
    score = 50  # 基础分
    reasons = []
    
    current = klines[-1]["close"]
    
    # 1. 均线分析
    ma5 = calculate_ma(klines, 5)
    ma10 = calculate_ma(klines, 10)
    ma20 = calculate_ma(klines, 20)
    
    if ma5 and ma10 and ma20:
        if ma5 > ma10 > ma20:
            score += 15
            reasons.append("均线多头")
        elif current > ma5:
            score += 5
            reasons.append("站上5日线")
    
    # 2. RSI分析
    rsi = calculate_rsi(klines)
    if rsi:
        if 30 < rsi < 70:
            score += 10
            reasons.append(f"RSI适中({rsi:.0f})")
        elif rsi < 30:
            score += 15
            reasons.append(f"RSI超卖({rsi:.0f})")
        elif rsi > 70:
            score -= 10
            reasons.append(f"RSI超买({rsi:.0f})")
    
    # 3. MACD分析
    dif, dea, macd = calculate_macd(klines)
    if dif is not None:
        if dif > 0 and macd > 0:
            score += 10
            reasons.append("MACD多头")
        elif dif < 0 and macd < 0:
            score -= 5
            reasons.append("MACD空头")
    
    # 4. 成交量分析
    if len(klines) >= 5:
        avg_vol = sum(k["volume"] for k in klines[-5:]) / 5
        last_vol = klines[-1]["volume"]
        if last_vol > avg_vol * 1.5:
            score += 5
            reasons.append("放量上涨")
        elif last_vol < avg_vol * 0.5:
            score -= 5
            reasons.append("缩量调整")
    
    # 5. 涨跌幅分析
    if len(klines) >= 2:
        pct = (current - klines[-2]["close"]) / klines[-2]["close"] * 100
        if 0 < pct < 3:
            score += 5
            reasons.append("温和上涨")
        elif pct > 5:
            score -= 5
            reasons.append("涨幅过大")
    
    # 限制分数范围
    score = max(0, min(100, score))
    
    # 给出建议
    if score >= 70:
        advice = "建议买入"
    elif score >= 55:
        advice = "可以关注"
    elif score >= 40:
        advice = "建议观望"
    else:
        advice = "建议回避"
    
    return {
        "code": code,
        "name": name,
        "price": current_price,
        "score": score,
        "advice": advice,
        "reasons": reasons,
        "strategies": []
    }


def aggregate_and_analyze_stocks(all_stocks):
    """
    按股票代码去重、汇总所命中策略并打分
    all_stocks 可以是股票字典的列表 (需含 code, name, 可选 price, strategy)
    """
    if not all_stocks:
        return []

    stock_map = {}
    for s in all_stocks:
        code = s.get("code")
        if not code:
            continue
        name = s.get("name", "")
        price = s.get("price")
        strategy = s.get("strategy") or s.get("strategy_name") or ""

        if code not in stock_map:
            stock_map[code] = {
                "code": code,
                "name": name,
                "price": price if price and price != "-" else None,
                "strategies": [strategy] if strategy else []
            }
        else:
            if strategy and strategy not in stock_map[code]["strategies"]:
                stock_map[code]["strategies"].append(strategy)
            if not stock_map[code]["price"] and price and price != "-":
                stock_map[code]["price"] = price

    analyses = []
    for code, info in stock_map.items():
        res = analyze_stock(info["code"], info["name"], info["price"])
        res["strategies"] = info["strategies"]
        
        # 多策略共振加分
        strat_cnt = len(info["strategies"])
        if strat_cnt >= 2:
            res["score"] = min(100, res["score"] + (strat_cnt - 1) * 5)
            res["reasons"].insert(0, f"🔥{strat_cnt}策略共振")
        
        # 再次确认建议评级
        if res["score"] >= 70:
            res["advice"] = "建议买入"
        elif res["score"] >= 55:
            res["advice"] = "可以关注"
        elif res["score"] >= 40:
            res["advice"] = "建议观望"
        else:
            res["advice"] = "建议回避"
            
        analyses.append(res)

    analyses.sort(key=lambda x: (len(x["strategies"]), x["score"]), reverse=True)
    return analyses


def format_analysis_message(analyses, top_n=10):
    """格式化分析结果为纯文本飞书消息（降级模式，已去重）"""
    if not analyses:
        return ""
    
    lines = ["━━━━━━━━━━━━━━━━━━━━"]
    lines.append(f"🎯 买入建议精选 (共{len(analyses)}只去重标的)")
    lines.append("")
    
    # 只取高分推荐与多策略共振的前 top_n 只
    display_items = [a for a in analyses if a["score"] >= 70 or len(a["strategies"]) >= 2]
    if not display_items:
        display_items = analyses[:top_n]
    else:
        display_items = display_items[:top_n]
    
    for a in display_items:
        emoji = "🟢" if a["score"] >= 70 else "🟡" if a["score"] >= 55 else "⚪"
        strat_tag = f" [{'+'.join(a['strategies'])}]" if a['strategies'] else ""
        price_str = f" ￥{a['price']}" if a['price'] != '-' else ""
        lines.append(f"{emoji} {a['code']} {a['name']}{price_str}{strat_tag}")
        lines.append(f"  评分: {a['score']}分 | {a['advice']}")
        if a["reasons"]:
            lines.append(f"  依据: {', '.join(a['reasons'][:3])}")
        lines.append("")
    
    remaining = len(analyses) - len(display_items)
    if remaining > 0:
        lines.append(f"💡 另有 {remaining} 只低分/普通标的已自动折叠简报")
        lines.append("")
    
    return "\n".join(lines)


def build_feishu_card(total_count, strategy_grouped_stocks, deduplicated_analyses, market_lines=None, sector_text=None, news_list=None, diff_lines=None):
    """
    构建飞书交互式卡片 (Interactive Card JSON)
    """
    from datetime import datetime
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Header 卡片头
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📊 缅A每日决策推送 ({now_str[:10]})"},
            "template": "red"
        },
        "elements": []
    }

    # 概要说明
    top_resonances = [a for a in deduplicated_analyses if len(a["strategies"]) >= 2]
    high_score = [a for a in deduplicated_analyses if a["score"] >= 80]
    
    summary_md = (
        f"**今日共筛选出 {total_count} 次策略信号**（去重后共 **{len(deduplicated_analyses)}** 只独立股票）\n"
        f"🔥 **多策略共振**: {len(top_resonances)} 只 | ⚡ **高分标的(≥80分)**: {len(high_score)} 只"
    )
    card["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": summary_md}})
    card["elements"].append({"tag": "hr"})

    # 2. 🎯 核心焦点：多策略共振 & 高分推荐 (TOP 5)
    card["elements"].append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": "🎯 **【重点聚焦】高分与共振推荐标的**"}
    })

    top_candidates = []
    # 优先共振且高分
    for a in deduplicated_analyses:
        if a in top_candidates:
            continue
        if len(a["strategies"]) >= 2 or a["score"] >= 80:
            top_candidates.append(a)
        if len(top_candidates) >= 5:
            break
    
    # 不够5只则补足前5只
    if len(top_candidates) < 5:
        for a in deduplicated_analyses:
            if a not in top_candidates:
                top_candidates.append(a)
            if len(top_candidates) >= 5:
                break

    if top_candidates:
        top_md_list = []
        for stock in top_candidates:
            price_str = f"￥{stock['price']}" if stock['price'] != '-' else '现价暂缺'
            strats_str = " + ".join(stock["strategies"]) if stock["strategies"] else "单策略"
            reasons_str = "、".join(stock["reasons"][:3])
            
            emoji = "🟢" if stock["score"] >= 70 else "🟡"
            top_md_list.append(
                f"{emoji} **{stock['code']} {stock['name']}** ({price_str}) — **{stock['score']}分** ({stock['advice']})\n"
                f"> 策略: `<{strats_str}>` \n"
                f"> 依据: {reasons_str}"
            )
        card["elements"].append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "\n\n".join(top_md_list)}
        })
    else:
        card["elements"].append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "今日暂无高评分标的"}
        })

    card["elements"].append({"tag": "hr"})

    # 3. 📋 策略触发精简清单 (去重折叠展示)
    if strategy_grouped_stocks:
        strat_md_lines = ["📋 **策略选股一览**"]
        for g in strategy_grouped_stocks:
            s_name = g.get("name", "")
            s_stocks = g.get("stocks", [])
            if not s_stocks:
                continue
            
            stock_fmt = []
            for st in s_stocks[:6]:
                p = st.get("price")
                p_str = f"({p})" if p and p != '-' else ""
                stock_fmt.append(f"{st['name']}{p_str}")
            
            more_str = f" 等{len(s_stocks)}只" if len(s_stocks) > 6 else ""
            strat_md_lines.append(f"• **{s_name}** ({len(s_stocks)}只): " + "、".join(stock_fmt) + more_str)
        
        card["elements"].append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "\n".join(strat_md_lines)}
        })
        card["elements"].append({"tag": "hr"})

    # 4. 📈 大盘复盘 & 板块热力图
    if market_lines:
        mkt_md = "\n".join(market_lines).strip()
        if mkt_md:
            card["elements"].append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": mkt_md}
            })

    if sector_text:
        card["elements"].append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": sector_text}
        })
        card["elements"].append({"tag": "hr"})

    # 5. 📰 今日财经要闻 (防整句断裂截断)
    if news_list:
        clean_news = ["📰 **核心财经要闻**"]
        for n in news_list[:5]:
            t = n.get("title", "").strip()
            intro = n.get("intro", "").strip()
            if not t:
                continue
            if len(t) > 40:
                t = t[:40] + "..."
            if intro:
                if len(intro) > 60:
                    intro = intro[:60] + "..."
                clean_news.append(f"• **{t}**\n  {intro}")
            else:
                clean_news.append(f"• **{t}**")
        
        card["elements"].append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "\n".join(clean_news)}
        })

    return card

