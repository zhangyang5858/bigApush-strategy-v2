"""
短线决策台四策略 (S1~S4) 核心量化规则与观察池引擎
(Strategy Four Pillars Engine)

依据短线经典战法四大著作深度落地：
- S1 竞价首板：《短线操盘笔记》竞价首板体系
- S2 主线龙头主升：《主升龙头空空1090》主线及龙头阶段描述
- S3 涨停后回调低吸：《量价操盘笔记》涨停回调与洗盘再启动
- S4 量价突破回踩：《Mistery趋势交易论2025》平台突破与回踩多周期确认
"""
import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Any


def is_st_or_delisted(name: str) -> bool:
    """检查是否为ST、*ST、退市或次新N/C标的"""
    if not name:
        return True
    uname = name.upper()
    return uname.startswith(("ST", "*ST", "N", "C")) or "ST" in uname or "退" in uname


def is_eligible_cap(float_cap: float, min_cap: float = 15.0, max_cap: float = 160.0) -> bool:
    """流通市值筛选区间（默认 15~160 亿）"""
    return min_cap <= float_cap <= max_cap


# ─────────────────────────────────────────────────────────────
# S1: 竞价首板 (Auction First Board)
# ─────────────────────────────────────────────────────────────
def detect_s1_auction_first_board(
    stock: Dict[str, Any],
    confirm_stock: Optional[Dict[str, Any]] = None,
    yesterday: Optional[Dict[str, Any]] = None,
    sector_info: Optional[Dict[str, Any]] = None,
    min_amount: float = 5_000_000.0,
) -> Optional[Dict[str, Any]]:
    """
    S1 竞价首板判定
    - 09:25: 竞价金额>=500万，高开 1.5%~6.5%，非连板，板块走强，量比>=1.4 -> WATCHING
    - 09:32: 现价守住开盘价，放量活跃 -> CONFIRMED
    - 失效: ST、开盘跌破开盘价2%、高开低走走弱超2% -> INVALIDATED
    """
    code = str(stock.get("code") or "")
    name = str(stock.get("name") or "")
    price = float(stock.get("price") or stock.get("open_price") or 0.0)
    open_price = float(stock.get("open_price") or stock.get("price") or 0.0)
    pre_close = float(stock.get("pre_close") or open_price)
    auction_amt = float(stock.get("auction_amount") or stock.get("amount") or 0.0)
    auction_chg = float(stock.get("auction_change") or ((open_price / pre_close - 1) * 100 if pre_close > 0 else 0.0))
    vr = float(stock.get("vr") or stock.get("vol_ratio") or 1.0)
    float_cap = float(stock.get("float_cap") or 0.0)

    # 硬性排雷排查
    reasons = []
    if is_st_or_delisted(name):
        return {
            "strategy_id": "S1", "strategy_name": "S1 竞价首板", "code": code, "name": name,
            "status": "INVALIDATED", "stage_desc": "ST/退市硬性否决",
            "support_price": open_price, "invalid_reason": "ST或退市风险", "reasons": []
        }

    # 板块检查
    sec = sector_info or {}
    sec_avg_pct = float(sec.get("avg_pct", 0.0) or 0.0)
    sec_breadth = float(sec.get("breadth", 0.0) or 0.0)
    is_sector_strong = (sec_breadth >= 0.45 or sec_avg_pct >= 0.5 or int(sec.get("flow_rank", 999)) <= 8)

    # 昨日是否涨停（非连板）
    y_zt = (yesterday or {}).get("is_limit_up", False)
    if y_zt:
        return None  # 连板票不属于 S1 首板候选

    # 竞价初筛基础条件
    is_auction_qualified = (
        auction_amt >= min_amount
        and 1.5 <= auction_chg <= 6.5
        and vr >= 1.3
        and is_sector_strong
    )

    if not is_auction_qualified:
        # 若金额或涨幅不符合，不触发 S1
        return None

    reasons.append(f"竞价金额{auction_amt / 1e4:.0f}万(门槛500万)")
    reasons.append(f"黄金高开{auction_chg:+.2f}%")
    reasons.append(f"量比{vr:.1f}")
    if sec.get("name"):
        reasons.append(f"{sec['name']}板块同步走强({sec_avg_pct:+.1f}%)")

    # 09:25 初筛入选
    if confirm_stock is None:
        return {
            "strategy_id": "S1",
            "strategy_name": "S1 竞价首板",
            "code": code,
            "name": name,
            "status": "WATCHING",
            "stage_desc": "竞价入选",
            "price": open_price,
            "open_price": open_price,
            "support_price": open_price,
            "reasons": reasons,
            "invalid_reason": None,
            "strategy_variant": "竞价首板入选"
        }

    # 09:32~09:38 开盘确认阶段
    cur_price = float(confirm_stock.get("price") or price)
    cur_amt = float(confirm_stock.get("amount") or 0.0)
    cur_chg = float(confirm_stock.get("change") or auction_chg)

    # 失效判断：跌破开盘价超过2% 或 高开低走超2%
    if cur_price < open_price * 0.98:
        return {
            "strategy_id": "S1", "strategy_name": "S1 竞价首板", "code": code, "name": name,
            "status": "INVALIDATED", "stage_desc": "开盘破位失效",
            "price": cur_price, "open_price": open_price, "support_price": open_price,
            "reasons": reasons, "invalid_reason": f"现价跌破开盘价超过2% ({cur_price:.2f} < {open_price * 0.98:.2f})"
        }
    if cur_chg - auction_chg < -2.0:
        return {
            "strategy_id": "S1", "strategy_name": "S1 竞价首板", "code": code, "name": name,
            "status": "INVALIDATED", "stage_desc": "高开低走走弱失效",
            "price": cur_price, "open_price": open_price, "support_price": open_price,
            "reasons": reasons, "invalid_reason": f"开盘走弱超2% (差值{cur_chg - auction_chg:+.2f}%)"
        }

    # 确认通过：守住开盘价且成交放量
    if cur_price >= open_price and cur_amt >= auction_amt:
        reasons.append(f"守住开盘价￥{open_price:.2f}")
        reasons.append("成交活跃持续放量")
        return {
            "strategy_id": "S1",
            "strategy_name": "S1 竞价首板",
            "code": code,
            "name": name,
            "status": "CONFIRMED",
            "stage_desc": "开盘确认",
            "price": cur_price,
            "open_price": open_price,
            "support_price": open_price,
            "reasons": reasons,
            "invalid_reason": None,
            "strategy_variant": "开盘承接确认"
        }

    return {
        "strategy_id": "S1",
        "strategy_name": "S1 竞价首板",
        "code": code,
        "name": name,
        "status": "WATCHING",
        "stage_desc": "观察承接中",
        "price": cur_price,
        "open_price": open_price,
        "support_price": open_price,
        "reasons": reasons,
        "invalid_reason": None,
        "strategy_variant": "竞价首板观察"
    }


# ─────────────────────────────────────────────────────────────
# S2: 主线龙头主升 (Mainline Leader Surge)
# ─────────────────────────────────────────────────────────────
def detect_s2_mainline_leader(
    stock: Dict[str, Any],
    sector_rank_info: Dict[str, Any],
    stage: str = "auction",
    min_amount: float = 30_000_000.0,
) -> Optional[Dict[str, Any]]:
    """
    S2 主线龙头主升判定
    - 早盘先锁定主线板块（前3名且breadth>=50%）与龙头候选（板块前排+成交>=3000万）
    - 09:40/10:00 检查个股承接（现价>=开盘价，分时VWAP均线上方），避免收盘后倒推龙头
    - 失效: 板块退潮、失去领涨前排地位、破分时走弱
    """
    code = str(stock.get("code") or "")
    name = str(stock.get("name") or "")
    if is_st_or_delisted(name):
        return None

    price = float(stock.get("price") or stock.get("open_price") or 0.0)
    open_price = float(stock.get("open_price") or price)
    cur_chg = float(stock.get("change") or stock.get("auction_change") or 0.0)
    amt = float(stock.get("amount") or 0.0)
    vwap_diff = float(stock.get("vwap_diff") or 0.0)

    sec_name = sector_rank_info.get("name", "")
    sec_rank = int(sector_rank_info.get("flow_rank") or sector_rank_info.get("rank") or 999)
    sec_breadth = float(sector_rank_info.get("breadth") or 0.0)
    sec_flow = float(sector_rank_info.get("net_flow") or 0.0)
    sec_avg_pct = float(sector_rank_info.get("avg_pct") or 0.0)

    # 1. 主线板块门槛：排名前 3 或均涨幅>=2.5%且上涨家数比>=50%
    is_mainline = (sec_rank <= 3 or sec_avg_pct >= 2.5) and sec_breadth >= 0.50 and sec_flow >= -1e8
    if not is_mainline:
        return None

    # 2. 个股处于板块前排且成交额达标
    is_leader_candidate = (cur_chg >= 2.0 and amt >= min_amount)
    if not is_leader_candidate:
        return None

    reasons = [
        f"归属主线板块【{sec_name}】(TOP{sec_rank}, 上涨占比{sec_breadth * 100:.0f}%)",
        f"个股领涨前排({cur_chg:+.2f}%)",
        f"成交额{amt / 1e4:.0f}万(超3000万流动性门槛)"
    ]

    # 早盘候选阶段
    if stage in ["auction", "instant"]:
        return {
            "strategy_id": "S2",
            "strategy_name": "S2 主线龙头主升",
            "code": code,
            "name": name,
            "status": "WATCHING",
            "stage_desc": "主线龙头候选",
            "price": price,
            "open_price": open_price,
            "support_price": open_price,
            "reasons": reasons,
            "invalid_reason": None,
            "strategy_variant": "主线龙头候选"
        }

    # 09:40 / 10:00 早盘定势承接阶段
    # 失效判定：板块大额资金断崖流出 或 个股跌破开盘价超过2%
    if sec_flow < -4e8:
        return {
            "strategy_id": "S2", "strategy_name": "S2 主线龙头主升", "code": code, "name": name,
            "status": "INVALIDATED", "stage_desc": "板块退潮失效",
            "price": price, "open_price": open_price, "support_price": open_price,
            "reasons": reasons, "invalid_reason": f"所属板块主力大额净流出({sec_flow / 1e8:.2f}亿)"
        }
    if price < open_price * 0.98:
        return {
            "strategy_id": "S2", "strategy_name": "S2 主线龙头主升", "code": code, "name": name,
            "status": "INVALIDATED", "stage_desc": "承接走弱失效",
            "price": price, "open_price": open_price, "support_price": open_price,
            "reasons": reasons, "invalid_reason": f"现价跌破开盘价超过2% ({price:.2f} < {open_price * 0.98:.2f})"
        }

    # 承接确认：现价保持在开盘价及 VWAP 均线之上
    if price >= open_price and vwap_diff >= -0.5:
        reasons.append(f"稳居分时均线之上({vwap_diff:+.1f}%)")
        return {
            "strategy_id": "S2",
            "strategy_name": "S2 主线龙头主升",
            "code": code,
            "name": name,
            "status": "CONFIRMED",
            "stage_desc": "龙头定势确认",
            "price": price,
            "open_price": open_price,
            "support_price": open_price,
            "reasons": reasons,
            "invalid_reason": None,
            "strategy_variant": "主线龙头定势"
        }

    return {
        "strategy_id": "S2",
        "strategy_name": "S2 主线龙头主升",
        "code": code,
        "name": name,
        "status": "WATCHING",
        "stage_desc": "承接跟踪中",
        "price": price,
        "open_price": open_price,
        "support_price": open_price,
        "reasons": reasons,
        "invalid_reason": None,
        "strategy_variant": "主线龙头跟踪"
    }


# ─────────────────────────────────────────────────────────────
# S3: 涨停后回调低吸 (Limit-up Pullback)
# ─────────────────────────────────────────────────────────────
def detect_s3_limitup_pullback(
    stock: Dict[str, Any],
    s3_item: Dict[str, Any],
    stage: str = "confirm",
) -> Optional[Dict[str, Any]]:
    """
    S3 涨停后回调低吸判定
    - 基于盘前根据已完成历史日线建立的观察池 (首板低点 support_low, 实体中点 midpoint, 缩量调整)
    - 变体 A: 回调低吸（触及实体中点~支撑低点区间，站稳开盘价止跌）
    - 变体 B: 洗盘再启动（调整后放量突破昨日高点转强拉升）
    - 失效: 有效跌破首板低点支撑
    """
    code = str(stock.get("code") or "")
    name = str(stock.get("name") or "")
    if is_st_or_delisted(name):
        return None

    price = float(stock.get("price") or stock.get("open_price") or 0.0)
    open_price = float(stock.get("open_price") or price)
    cur_chg = float(stock.get("change") or 0.0)

    support_low = float(s3_item.get("support_low", 0.0) or 0.0)
    midpoint = float(s3_item.get("midpoint", 0.0) or 0.0)
    first_date = s3_item.get("first_board_date", "--")
    adjust_days = s3_item.get("adjust_days", 3)

    if support_low <= 0:
        return None

    # 失效判断：跌破首板低点支撑
    if price < support_low * 0.99:
        return {
            "strategy_id": "S3", "strategy_name": "S3 涨停后回调低吸", "code": code, "name": name,
            "status": "INVALIDATED", "stage_desc": "跌破首板支撑失效",
            "price": price, "open_price": open_price, "support_price": support_low,
            "reasons": [], "invalid_reason": f"跌破{first_date}首板最低价支撑({support_low:.2f})",
            "strategy_variant": "破位失效"
        }

    reasons = [
        f"前序自然首板({first_date})，调整{adjust_days}天",
        f"首板低点支撑￥{support_low:.2f} | 实体中点￥{midpoint:.2f}"
    ]

    # 变体 B: 洗盘后再启动（调整后放量上攻突破，涨幅>=3.0%且位于中点之上且不破开盘）
    if cur_chg >= 3.0 and price >= midpoint and price >= open_price:
        reasons.append(f"放量长阳突破转强(+{cur_chg:.2f}%)")
        return {
            "strategy_id": "S3",
            "strategy_name": "S3 涨停后回调低吸",
            "code": code,
            "name": name,
            "status": "CONFIRMED",
            "stage_desc": "洗盘再启动确认",
            "price": price,
            "open_price": open_price,
            "support_price": support_low,
            "midpoint": midpoint,
            "reasons": reasons,
            "invalid_reason": None,
            "strategy_variant": "洗盘再启动"
        }

    # 变体 A: 回调低吸到位（价格处于实体中点~支撑低点区间，站稳开盘价止跌）
    in_support_zone = (support_low * 0.995 <= price <= midpoint * 1.025)
    if in_support_zone and price >= open_price:
        reasons.append(f"触及支撑区止跌企稳(现价￥{price:.2f})")
        return {
            "strategy_id": "S3",
            "strategy_name": "S3 涨停后回调低吸",
            "code": code,
            "name": name,
            "status": "CONFIRMED",
            "stage_desc": "回调低吸到位确认",
            "price": price,
            "open_price": open_price,
            "support_price": support_low,
            "midpoint": midpoint,
            "reasons": reasons,
            "invalid_reason": None,
            "strategy_variant": "回调低吸"
        }

    # 处于观察池中但尚未到止跌或启动时点
    return {
        "strategy_id": "S3",
        "strategy_name": "S3 涨停后回调低吸",
        "code": code,
        "name": name,
        "status": "WATCHING",
        "stage_desc": "回调企稳观察中",
        "price": price,
        "open_price": open_price,
        "support_price": support_low,
        "midpoint": midpoint,
        "reasons": reasons,
        "invalid_reason": None,
        "strategy_variant": "回调观察"
    }


# ─────────────────────────────────────────────────────────────
# S4: 量价突破回踩 (Volume-Price Breakout Retest)
# ─────────────────────────────────────────────────────────────
def detect_s4_breakout_retest(
    stock: Dict[str, Any],
    s4_item: Dict[str, Any],
    stage: str = "confirm",
) -> Optional[Dict[str, Any]]:
    """
    S4 量价突破回踩判定
    - 基于盘前根据已完成历史日线建立的观察池 (突破前20日平台顶 Ceiling, 严禁未来数据)
    - 记录首次回踩 (分时最低价触及 Ceiling 附近) 且当前重新上行守稳 -> 回踩确认
    - 直接放量突破上攻 -> 直接突破
    - 失效: 跌回平台内超过2%
    """
    code = str(stock.get("code") or "")
    name = str(stock.get("name") or "")
    if is_st_or_delisted(name):
        return None

    price = float(stock.get("price") or stock.get("open_price") or 0.0)
    open_price = float(stock.get("open_price") or price)
    low_price = float(stock.get("low") or open_price)
    cur_chg = float(stock.get("change") or 0.0)

    ceiling = float(s4_item.get("ceiling", 0.0) or 0.0)
    breakout_date = s4_item.get("breakout_date", "--")
    vol_ratio = float(s4_item.get("breakout_vol_ratio", 1.5) or 1.5)

    if ceiling <= 0:
        return None

    # 失效判断：跌回平台深处
    if price < ceiling * 0.98:
        return {
            "strategy_id": "S4", "strategy_name": "S4 量价突破回踩", "code": code, "name": name,
            "status": "INVALIDATED", "stage_desc": "跌回平台失效",
            "price": price, "open_price": open_price, "support_price": ceiling,
            "reasons": [], "invalid_reason": f"跌破突破前高平台({ceiling:.2f})超过2%",
            "strategy_variant": "破位失效"
        }

    reasons = [
        f"前期放量突破20日平台顶￥{ceiling:.2f}({breakout_date})",
        f"突破放量{vol_ratio:.1f}倍基准均量"
    ]

    # 判断是否发生回踩
    touched_ceiling = (low_price <= ceiling * 1.015)

    # 变体 1: 回踩确认（日内发生回踩且现价守稳平台顶并站上开盘价）
    if touched_ceiling and price >= ceiling and price >= open_price:
        reasons.append(f"首次回踩平台顶不破并企稳(低点￥{low_price:.2f}➔现价￥{price:.2f})")
        return {
            "strategy_id": "S4",
            "strategy_name": "S4 量价突破回踩",
            "code": code,
            "name": name,
            "status": "CONFIRMED",
            "stage_desc": "回踩企稳确认",
            "price": price,
            "open_price": open_price,
            "support_price": ceiling,
            "reasons": reasons,
            "invalid_reason": None,
            "strategy_variant": "回踩确认"
        }

    # 变体 2: 直接突破（持续放量强势拉升，未发生深度回踩）
    if price > ceiling and cur_chg >= 2.5 and not touched_ceiling:
        reasons.append(f"放量直接长阳加速上攻(+{cur_chg:+.2f}%)")
        return {
            "strategy_id": "S4",
            "strategy_name": "S4 量价突破回踩",
            "code": code,
            "name": name,
            "status": "CONFIRMED",
            "stage_desc": "直接突破放量",
            "price": price,
            "open_price": open_price,
            "support_price": ceiling,
            "reasons": reasons,
            "invalid_reason": None,
            "strategy_variant": "直接突破"
        }

    return {
        "strategy_id": "S4",
        "strategy_name": "S4 量价突破回踩",
        "code": code,
        "name": name,
        "status": "WATCHING",
        "stage_desc": "回踩观察中",
        "price": price,
        "open_price": open_price,
        "support_price": ceiling,
        "reasons": reasons,
        "invalid_reason": None,
        "strategy_variant": "回踩观察"
    }


# ─────────────────────────────────────────────────────────────
# 观察池自动构建函数 (盘前/收盘由历史日线生成)
# ─────────────────────────────────────────────────────────────
def build_observation_pools(daily_bars_map: Dict[str, List[Dict[str, Any]]], target_date_str: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """
    基于已完成的日线历史数据，自动构建次日 S3 (涨停回调) 与 S4 (突破回踩) 监控池
    - 绝不引入当日未来数据
    - S3: 自然首板 + 随后 1~4 日缩量调整不破首板低点
    - S4: 前 1~2 日放量突破此前 20 日平台最高价 Ceiling (严格突破前数据)
    """
    s3_pool = []
    s4_pool = []

    for code, bars in daily_bars_map.items():
        if len(bars) < 3:
            continue

        # 保证按日期升序排序
        sorted_bars = sorted(bars, key=lambda b: str(b.get("date") or ""))

        # ── 1. S3 涨停回调低吸候选池构建 ──
        # 寻找最近 1~5 天内出现的自然首板
        for offset in range(1, min(6, len(sorted_bars))):
            fb_idx = len(sorted_bars) - 1 - offset
            if fb_idx < 0:
                break
            fb_bar = sorted_bars[fb_idx]
            pre_fb_bar = sorted_bars[fb_idx - 1] if fb_idx > 0 else {}

            is_fb = (fb_bar.get("is_limit_up") is True and pre_fb_bar.get("is_limit_up") is not True)
            if is_fb:
                # 检查首板之后的调整交易日
                adjust_bars = sorted_bars[fb_idx + 1:]
                if not (1 <= len(adjust_bars) <= 5):
                    continue

                fb_low = float(fb_bar.get("low", 0.0) or 0.0)
                fb_open = float(fb_bar.get("open", 0.0) or 0.0)
                fb_close = float(fb_bar.get("close", 0.0) or 0.0)
                fb_vol = float(fb_bar.get("volume", 0.0) or 0.0)
                midpoint = round((fb_open + fb_close) / 2.0, 3)

                # 调整期条件：低点未跌破首板低点，且均量 < 首板量
                adjust_lows = [float(b.get("low", 0.0) or 0.0) for b in adjust_bars]
                adjust_vols = [float(b.get("volume", 0.0) or 0.0) for b in adjust_bars]
                if fb_low > 0 and all(l >= fb_low * 0.99 for l in adjust_lows):
                    avg_adjust_vol = (sum(adjust_vols) / len(adjust_vols)) if adjust_vols else 0
                    if avg_adjust_vol < fb_vol * 1.05:  # 缩量调整
                        s3_pool.append({
                            "code": code,
                            "first_board_date": str(fb_bar.get("date")),
                            "support_low": fb_low,
                            "midpoint": midpoint,
                            "first_vol": fb_vol,
                            "adjust_days": len(adjust_bars),
                            "target_date": target_date_str or datetime.now().strftime("%Y-%m-%d")
                        })
                break

        # ── 2. S4 量价突破回踩候选池构建 ──
        # 寻找前 1~2 日刚刚放量突破 20 日平台的个股
        if len(sorted_bars) >= 22:
            for b_offset in [1, 2]:
                break_idx = len(sorted_bars) - b_offset
                if break_idx < 21:
                    continue
                breakout_bar = sorted_bars[break_idx]
                baseline_bars = sorted_bars[break_idx - 20:break_idx]

                ceiling = max(float(b.get("high", 0.0) or 0.0) for b in baseline_bars)
                avg_base_vol = sum(float(b.get("volume", 0.0) or 0.0) for b in baseline_bars) / 20.0
                break_vol = float(breakout_bar.get("volume", 0.0) or 0.0)
                break_close = float(breakout_bar.get("close", 0.0) or 0.0)

                # 严格突破：收盘价高于前20日最高价平台，成交量 >= 1.4倍基准量
                if ceiling > 0 and break_close > ceiling and avg_base_vol > 0:
                    vol_ratio = break_vol / avg_base_vol
                    if vol_ratio >= 1.4:
                        s4_pool.append({
                            "code": code,
                            "breakout_date": str(breakout_bar.get("date")),
                            "ceiling": round(ceiling, 3),
                            "avg_vol": avg_base_vol,
                            "breakout_vol": break_vol,
                            "breakout_vol_ratio": round(vol_ratio, 2),
                            "target_date": target_date_str or datetime.now().strftime("%Y-%m-%d")
                        })
                        break

    return {
        "s3_pullback_pool": s3_pool,
        "s4_breakout_pool": s4_pool,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


def save_observation_pools_to_json(pools: Dict[str, Any], path: str = "data/observation_pools.json") -> bool:
    """持久化保存观察池到 JSON"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(pools, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"⚠️ 保存观察池失败: {e}")
        return False


def load_observation_pools_from_json(path: str = "data/observation_pools.json") -> Dict[str, Any]:
    """从 JSON 加载观察池"""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            pass
    return {"s3_pullback_pool": [], "s4_breakout_pool": []}
