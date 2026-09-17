"""
短线决策交易数据库与 Excel 报表生成引擎
(Scalp Trade Database & Multi-Sheet Styled Excel Export Engine)

功能定位：
1. SQLite 底层持久化：轻量单文件数据库 (data/scalp_trading.db)，存储平仓流水、持仓、日结与推送信号
2. 历史数据自愈与迁移：自动读取现有 JSON 账户数据并同步至 SQLite
3. 量化策略归因分析：按战法、时段快速计算胜率 (Win Rate)、盈亏比 (Profit Factor)、平均收益率
4. 商业级多 Sheet 带样式 Excel 报表自动导出 (基于 pandas + openpyxl)
"""
import os
import sqlite3
import json
from datetime import datetime
import pandas as pd
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

DB_PATH = "data/scalp_trading.db"
EXCEL_REPORT_PATH = "data/短线决策收益与战法透视报表.xlsx"


def get_db_connection():
    """获取 SQLite 数据库连接并启用 WAL 模式提高并发性能"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def infer_strategy_id(tag):
    """根据战法标签推断四柱战法 ID (S1~S4)"""
    tag = str(tag or "")
    if "S1" in tag or "竞价" in tag:
        return "S1"
    elif "S2" in tag or "龙头" in tag or "主线" in tag or "秒板" in tag or "强攻" in tag:
        return "S2"
    elif "S3" in tag or "回调" in tag or "二波" in tag or "低吸" in tag:
        return "S3"
    elif "S4" in tag or "突破" in tag or "回踩" in tag:
        return "S4"
    return "S1"


def init_db():
    """初始化数据库表结构并自动迁移更新新增字段"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 1. 历史平仓交易记录表 (每笔交易的完整买卖生命周期)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS closed_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id TEXT DEFAULT 'S1',
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            buy_date TEXT NOT NULL,
            buy_time TEXT,
            buy_stage TEXT,
            strategy_tag TEXT,
            buy_price REAL NOT NULL,
            sell_date TEXT NOT NULL,
            sell_time TEXT,
            sell_stage TEXT,
            sell_price REAL NOT NULL,
            shares INTEGER NOT NULL,
            cost_amount REAL NOT NULL,
            gross_sell_amount REAL NOT NULL,
            fee REAL NOT NULL,
            realized_profit REAL NOT NULL,
            realized_profit_pct REAL NOT NULL,
            hold_days INTEGER DEFAULT 1,
            action TEXT,
            reason TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(code, buy_date, sell_date, shares)
        );
        """)

        # 2. 当前持仓表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            code TEXT PRIMARY KEY,
            strategy_id TEXT DEFAULT 'S1',
            name TEXT NOT NULL,
            buy_date TEXT NOT NULL,
            buy_time TEXT,
            buy_stage TEXT,
            strategy_tag TEXT,
            buy_price REAL NOT NULL,
            current_price REAL NOT NULL,
            open_price REAL,
            stop_loss REAL,
            shares INTEGER NOT NULL,
            cost_amount REAL NOT NULL,
            fee REAL NOT NULL,
            market_value REAL,
            unrealized_profit_pct REAL,
            unrealized_profit_amount REAL,
            is_zt INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        """)

        # 3. 每日账户资产日结与资金曲线表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_settlements (
            date TEXT PRIMARY KEY,
            total_assets REAL NOT NULL,
            cash REAL NOT NULL,
            position_market_value REAL NOT NULL,
            daily_profit REAL NOT NULL,
            daily_return_pct REAL NOT NULL,
            total_profit REAL NOT NULL,
            total_return_pct REAL NOT NULL,
            position_count INTEGER NOT NULL,
            win_rate_today REAL DEFAULT 0.0,
            zt_count_today INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        """)

        # 4. 每日各时段推送信号明细表 (用于后续复盘回测与选股准确率检验)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS push_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            time TEXT,
            stage TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            push_price REAL NOT NULL,
            open_price REAL,
            pre_close REAL,
            cur_change REAL,
            net_flow REAL,
            flow_ratio REAL,
            sector TEXT,
            score REAL,
            grade TEXT,
            strategy_tag TEXT,
            is_zt INTEGER DEFAULT 0,
            is_leader INTEGER DEFAULT 0,
            strategy_id TEXT DEFAULT 'S1',
            signal_stage TEXT DEFAULT 'CONFIRMED',
            strategy_variant TEXT,
            support_price REAL,
            invalid_reason TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(date, stage, code)
        );
        """)

        # 5. S3/S4 战法观察池持久化表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS strategy_observation_pool (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT,
            support_price REAL,
            trigger_condition TEXT,
            target_date TEXT,
            status TEXT DEFAULT 'ACTIVE',
            meta_json TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(strategy_id, code, target_date)
        );
        """)

        # ── 数据库平滑自愈与字段迁移检查 ──
        # push_signals 字段迁移
        cursor.execute("PRAGMA table_info(push_signals);")
        ps_cols = {col["name"] for col in cursor.fetchall()}
        ps_add_cols = [
            ("strategy_id", "TEXT DEFAULT 'S1'"),
            ("signal_stage", "TEXT DEFAULT 'CONFIRMED'"),
            ("strategy_variant", "TEXT"),
            ("support_price", "REAL"),
            ("invalid_reason", "TEXT")
        ]
        for cname, ctype in ps_add_cols:
            if cname not in ps_cols:
                try:
                    cursor.execute(f"ALTER TABLE push_signals ADD COLUMN {cname} {ctype};")
                except Exception:
                    pass

        # closed_trades 字段迁移
        cursor.execute("PRAGMA table_info(closed_trades);")
        ct_cols = {col["name"] for col in cursor.fetchall()}
        if "strategy_id" not in ct_cols:
            try:
                cursor.execute("ALTER TABLE closed_trades ADD COLUMN strategy_id TEXT DEFAULT 'S1';")
            except Exception:
                pass

        # positions 字段迁移
        cursor.execute("PRAGMA table_info(positions);")
        pos_cols = {col["name"] for col in cursor.fetchall()}
        if "strategy_id" not in pos_cols:
            try:
                cursor.execute("ALTER TABLE positions ADD COLUMN strategy_id TEXT DEFAULT 'S1';")
            except Exception:
                pass

        conn.commit()


# ===================== 数据写入与同步接口 =====================

def record_closed_trade(trade_dict):
    """记录一笔平仓交易"""
    init_db()
    stg_id = trade_dict.get("strategy_id") or infer_strategy_id(trade_dict.get("strategy_tag"))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO closed_trades (
            strategy_id, code, name, buy_date, buy_time, buy_stage, strategy_tag,
            buy_price, sell_date, sell_time, sell_stage, sell_price,
            shares, cost_amount, gross_sell_amount, fee,
            realized_profit, realized_profit_pct, hold_days, action, reason
        ) VALUES (
            :strategy_id, :code, :name, :buy_date, :buy_time, :buy_stage, :strategy_tag,
            :buy_price, :sell_date, :sell_time, :sell_stage, :sell_price,
            :shares, :cost_amount, :gross_sell_amount, :fee,
            :realized_profit, :realized_profit_pct, :hold_days, :action, :reason
        );
        """, {
            "strategy_id": stg_id,
            "code": str(trade_dict.get("code") or ""),
            "name": str(trade_dict.get("name") or ""),
            "buy_date": str(trade_dict.get("buy_date") or ""),
            "buy_time": str(trade_dict.get("buy_time") or ""),
            "buy_stage": str(trade_dict.get("buy_stage") or ""),
            "strategy_tag": str(trade_dict.get("strategy_tag") or "🎯 综合短线"),
            "buy_price": float(trade_dict.get("buy_price") or 0.0),
            "sell_date": str(trade_dict.get("sell_date") or datetime.now().strftime("%Y-%m-%d")),
            "sell_time": str(trade_dict.get("sell_time") or datetime.now().strftime("%H:%M:%S")),
            "sell_stage": str(trade_dict.get("sell_stage") or ""),
            "sell_price": float(trade_dict.get("sell_price") or 0.0),
            "shares": int(trade_dict.get("shares") or 0),
            "cost_amount": float(trade_dict.get("cost_amount") or 0.0),
            "gross_sell_amount": float(trade_dict.get("gross_sell_amount") or 0.0),
            "fee": float(trade_dict.get("fee") or 0.0),
            "realized_profit": float(trade_dict.get("realized_profit") or 0.0),
            "realized_profit_pct": float(trade_dict.get("realized_profit_pct") or 0.0),
            "hold_days": int(trade_dict.get("hold_days") or 1),
            "action": str(trade_dict.get("action") or ""),
            "reason": str(trade_dict.get("reason") or "")
        })
        conn.commit()


def sync_active_positions(positions_list):
    """全量同步当前持仓表"""
    init_db()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM positions;")
        for pos in (positions_list or []):
            stg_id = pos.get("strategy_id") or infer_strategy_id(pos.get("strategy_tag"))
            cursor.execute("""
            INSERT INTO positions (
                strategy_id, code, name, buy_date, buy_time, buy_stage, strategy_tag,
                buy_price, current_price, open_price, stop_loss, shares,
                cost_amount, fee, market_value, unrealized_profit_pct,
                unrealized_profit_amount, is_zt
            ) VALUES (
                :strategy_id, :code, :name, :buy_date, :buy_time, :buy_stage, :strategy_tag,
                :buy_price, :current_price, :open_price, :stop_loss, :shares,
                :cost_amount, :fee, :market_value, :unrealized_profit_pct,
                :unrealized_profit_amount, :is_zt
            );
            """, {
                "strategy_id": stg_id,
                "code": str(pos.get("code") or ""),
                "name": str(pos.get("name") or ""),
                "buy_date": str(pos.get("buy_date") or ""),
                "buy_time": str(pos.get("buy_time") or ""),
                "buy_stage": str(pos.get("buy_stage") or ""),
                "strategy_tag": str(pos.get("strategy_tag") or "🎯 综合短线"),
                "buy_price": float(pos.get("buy_price") or 0.0),
                "current_price": float(pos.get("current_price") or pos.get("buy_price") or 0.0),
                "open_price": float(pos.get("open_price") or pos.get("buy_price") or 0.0),
                "stop_loss": float(pos.get("stop_loss") or 0.0),
                "shares": int(pos.get("shares") or 0),
                "cost_amount": float(pos.get("cost_amount") or 0.0),
                "fee": float(pos.get("fee") or 0.0),
                "market_value": float(pos.get("market_value") or 0.0),
                "unrealized_profit_pct": float(pos.get("unrealized_profit_pct") or 0.0),
                "unrealized_profit_amount": float(pos.get("unrealized_profit_amount") or 0.0),
                "is_zt": 1 if pos.get("is_zt") else 0
            })
        conn.commit()


def record_daily_settlement(settle_dict):
    """记录每日收盘账户日结数据"""
    init_db()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO daily_settlements (
            date, total_assets, cash, position_market_value, daily_profit,
            daily_return_pct, total_profit, total_return_pct, position_count,
            win_rate_today, zt_count_today
        ) VALUES (
            :date, :total_assets, :cash, :position_market_value, :daily_profit,
            :daily_return_pct, :total_profit, :total_return_pct, :position_count,
            :win_rate_today, :zt_count_today
        );
        """, {
            "date": str(settle_dict.get("date") or datetime.now().strftime("%Y-%m-%d")),
            "total_assets": float(settle_dict.get("total_assets") or 0.0),
            "cash": float(settle_dict.get("cash") or 0.0),
            "position_market_value": float(settle_dict.get("position_market_value") or 0.0),
            "daily_profit": float(settle_dict.get("daily_profit") or 0.0),
            "daily_return_pct": float(settle_dict.get("daily_return_pct") or 0.0),
            "total_profit": float(settle_dict.get("total_profit") or 0.0),
            "total_return_pct": float(settle_dict.get("total_return_pct") or 0.0),
            "position_count": int(settle_dict.get("position_count") or 0),
            "win_rate_today": float(settle_dict.get("win_rate_today") or 0.0),
            "zt_count_today": int(settle_dict.get("zt_count_today") or 0)
        })
        conn.commit()


def sync_observation_pools_to_db(pools_dict, target_date=None):
    """将 S3/S4 战法观察池同步记录至 SQLite 数据库"""
    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")
    init_db()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # 同步 S3 涨停回调候选池
        for item in pools_dict.get("s3_pullback_pool", []):
            cursor.execute("""
            INSERT OR REPLACE INTO strategy_observation_pool (
                strategy_id, code, name, support_price, trigger_condition,
                target_date, status, meta_json
            ) VALUES (
                'S3', :code, :name, :support_price, '自然首板后1~4日缩量调整',
                :target_date, 'ACTIVE', :meta_json
            );
            """, {
                "code": str(item.get("code") or ""),
                "name": str(item.get("name") or ""),
                "support_price": float(item.get("support_low") or 0.0),
                "target_date": str(item.get("target_date") or target_date),
                "meta_json": json.dumps(item, ensure_ascii=False)
            })
        # 同步 S4 量价突破候选池
        for item in pools_dict.get("s4_breakout_pool", []):
            cursor.execute("""
            INSERT OR REPLACE INTO strategy_observation_pool (
                strategy_id, code, name, support_price, trigger_condition,
                target_date, status, meta_json
            ) VALUES (
                'S4', :code, :name, :support_price, '放量突破前20日平台Ceiling回踩',
                :target_date, 'ACTIVE', :meta_json
            );
            """, {
                "code": str(item.get("code") or ""),
                "name": str(item.get("name") or ""),
                "support_price": float(item.get("ceiling") or 0.0),
                "target_date": str(item.get("target_date") or target_date),
                "meta_json": json.dumps(item, ensure_ascii=False)
            })
        conn.commit()


def record_push_signals(stage, pushed_stocks, date_str=None, force=False):
    """记录时段推送的所有选股信号快照"""
    init_db()
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M:%S")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        # 快照不可变保护：若当天该时段早盘已记录过有效推送信号，且非 force，跳过覆盖
        if not force:
            cursor.execute("SELECT count(*) as cnt FROM push_signals WHERE date = ? AND stage = ?", (date_str, stage))
            row = cursor.fetchone()
            if row and row["cnt"] > 0:
                print(f"  🔒 [DB快照保护] {stage} 阶段在 {date_str} 已存在 {row['cnt']} 条推送信号记录，跳过重复覆盖。")
                return
        for s in (pushed_stocks or []):
            stg_id = s.get("strategy_id") or infer_strategy_id(s.get("strategy_tag"))
            cursor.execute("""
            INSERT OR REPLACE INTO push_signals (
                date, time, stage, code, name, push_price, open_price,
                pre_close, cur_change, net_flow, flow_ratio, sector,
                score, grade, strategy_tag, is_zt, is_leader,
                strategy_id, signal_stage, strategy_variant, support_price, invalid_reason
            ) VALUES (
                :date, :time, :stage, :code, :name, :push_price, :open_price,
                :pre_close, :cur_change, :net_flow, :flow_ratio, :sector,
                :score, :grade, :strategy_tag, :is_zt, :is_leader,
                :strategy_id, :signal_stage, :strategy_variant, :support_price, :invalid_reason
            );
            """, {
                "date": date_str,
                "time": now_time,
                "stage": stage,
                "code": str(s.get("code") or ""),
                "name": str(s.get("name") or ""),
                "push_price": float(s.get("push_price") or s.get("price") or s.get("open_price") or 0.0),
                "open_price": float(s.get("open_price") or 0.0),
                "pre_close": float(s.get("pre_close") or 0.0),
                "cur_change": float(s.get("change") or s.get("auction_change") or 0.0),
                "net_flow": float(s.get("net_flow") or 0.0),
                "flow_ratio": float(s.get("flow_ratio") or 0.0),
                "sector": str(s.get("sector") or "其他"),
                "score": float(s.get("score") or 0.0),
                "grade": str(s.get("grade") or "A"),
                "strategy_tag": str(s.get("strategy_tag") or "🎯 综合短线"),
                "is_zt": 1 if s.get("is_zt") else 0,
                "is_leader": 1 if s.get("is_leader") else 0,
                "strategy_id": stg_id,
                "signal_stage": str(s.get("signal_stage") or "CONFIRMED"),
                "strategy_variant": str(s.get("strategy_variant") or ""),
                "support_price": float(s.get("support_price") or 0.0),
                "invalid_reason": str(s.get("invalid_reason") or "")
            })
        conn.commit()


def import_account_json_to_db(json_path="data/scalp_account.json"):
    """从现有的 scalp_account.json 导入历史数据到 SQLite (无缝数据自愈)"""
    if not os.path.exists(json_path):
        return
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        init_db()
        # 1. 导入已平仓交易
        for trade in data.get("closed_trades", []):
            record_closed_trade(trade)

        # 2. 导入当前持仓
        sync_active_positions(data.get("positions", []))

        # 3. 导入历史日结
        for hist in data.get("daily_history", []):
            record_daily_settlement(hist)

        print(f"✅ 成功从 {json_path} 同步数据至 SQLite 数据库: {DB_PATH}")
    except Exception as e:
        print(f"⚠️ 从 JSON 迁移数据到 SQLite 异常: {e}")


# ===================== 数据查询与策略透视 =====================

def get_strategy_performance_df():
    """获取各战法的胜率、盈亏比与累计收益透视表"""
    init_db()
    with get_db_connection() as conn:
        df = pd.read_sql_query("SELECT * FROM closed_trades", conn)

    if df.empty:
        return pd.DataFrame(columns=[
            "战法策略", "交易笔数", "盈利笔数", "亏损笔数",
            "胜率 (%)", "盈亏比", "平均收益率 (%)", "累计净利润 (元)",
            "最大单笔盈利 (元)", "最大单笔亏损 (元)"
        ])

    grouped = []
    for tag, g in df.groupby("strategy_tag"):
        total_trades = len(g)
        wins = g[g["realized_profit"] > 0]
        losses = g[g["realized_profit"] < 0]
        win_cnt = len(wins)
        loss_cnt = len(losses)
        win_rate = (win_cnt / total_trades) * 100 if total_trades > 0 else 0.0

        total_win_amt = wins["realized_profit"].sum()
        total_loss_amt = abs(losses["realized_profit"].sum())
        profit_factor = (total_win_amt / total_loss_amt) if total_loss_amt > 0 else (total_win_amt if total_win_amt > 0 else 1.0)

        avg_return = g["realized_profit_pct"].mean()
        total_profit = g["realized_profit"].sum()
        max_win = wins["realized_profit"].max() if not wins.empty else 0.0
        max_loss = losses["realized_profit"].min() if not losses.empty else 0.0

        grouped.append({
            "战法策略": tag,
            "交易笔数": total_trades,
            "盈利笔数": win_cnt,
            "亏损笔数": loss_cnt,
            "胜率 (%)": round(win_rate, 2),
            "盈亏比": round(profit_factor, 2),
            "平均收益率 (%)": round(avg_return, 2),
            "累计净利润 (元)": round(total_profit, 2),
            "最大单笔盈利 (元)": round(max_win, 2),
            "最大单笔亏损 (元)": round(max_loss, 2)
        })

    res_df = pd.DataFrame(grouped)
    res_df.sort_values(by="累计净利润 (元)", ascending=False, inplace=True)
    return res_df


def get_closed_trades_df():
    """获取所有平仓交易明细 DataFrame"""
    init_db()
    with get_db_connection() as conn:
        df = pd.read_sql_query("""
        SELECT
            code AS '股票代码',
            name AS '股票名称',
            strategy_tag AS '触发战法',
            buy_date AS '买入日期',
            buy_stage AS '买入时段',
            buy_price AS '买入价格',
            sell_date AS '卖出日期',
            sell_stage AS '卖出时段',
            sell_price AS '卖出价格',
            shares AS '成交股数',
            cost_amount AS '买入成本',
            gross_sell_amount AS '卖出金额',
            fee AS '交易税费',
            realized_profit AS '实际净利润',
            realized_profit_pct AS '收益率(%)',
            hold_days AS '持股天数',
            action AS '执行操作',
            reason AS '平仓依据'
        FROM closed_trades
        ORDER BY sell_date DESC, id DESC
        """, conn)
    return df


def get_daily_settlement_df():
    """获取每日资金曲线与日结 DataFrame"""
    init_db()
    with get_db_connection() as conn:
        df = pd.read_sql_query("""
        SELECT
            date AS '结算日期',
            total_assets AS '账户总资产(元)',
            cash AS '可用现金(元)',
            position_market_value AS '持仓总市值(元)',
            daily_profit AS '当日盈亏(元)',
            daily_return_pct AS '当日收益率(%)',
            total_profit AS '累计盈利(元)',
            total_return_pct AS '累计收益率(%)',
            position_count AS '持仓标的数'
        FROM daily_settlements
        ORDER BY date DESC
        """, conn)
    return df


def get_current_positions_df():
    """获取当前持仓 DataFrame"""
    init_db()
    with get_db_connection() as conn:
        df = pd.read_sql_query("""
        SELECT
            code AS '股票代码',
            name AS '股票名称',
            strategy_tag AS '战法标签',
            buy_date AS '建仓日期',
            buy_stage AS '建仓时段',
            buy_price AS '买入价',
            current_price AS '现价',
            shares AS '持股数',
            cost_amount AS '买入成本',
            market_value AS '当前市值',
            unrealized_profit_amount AS '浮动盈亏(元)',
            unrealized_profit_pct AS '浮动收益率(%)',
            stop_loss AS '止损参考价',
            CASE WHEN is_zt = 1 THEN '是' ELSE '否' END AS '是否涨停'
        FROM positions
        ORDER BY buy_date DESC, unrealized_profit_pct DESC
        """, conn)
    return df


def get_four_pillars_attribution_df():
    """
    四柱战法全维度归因分析：
    - S1 竞价首板
    - S2 主线龙头主升
    - S3 涨停后回调低吸
    - S4 量价突破回踩
    汇总各战法的推荐次数、触发确认、封板成功率、模拟交易胜率与累计盈亏
    """
    init_db()
    with get_db_connection() as conn:
        try:
            df_signals = pd.read_sql_query("SELECT * FROM push_signals", conn)
        except Exception:
            df_signals = pd.DataFrame()
        try:
            df_closed = pd.read_sql_query("SELECT * FROM closed_trades", conn)
        except Exception:
            df_closed = pd.DataFrame()

    strategy_names = {
        "S1": "S1 竞价首板",
        "S2": "S2 主线龙头主升",
        "S3": "S3 涨停后回调低吸",
        "S4": "S4 量价突破回踩"
    }

    rows = []
    for sid in ["S1", "S2", "S3", "S4"]:
        name = strategy_names[sid]

        # 信号表现
        if not df_signals.empty and "strategy_id" in df_signals.columns:
            sig_subset = df_signals[df_signals["strategy_id"] == sid]
        elif not df_signals.empty and "strategy_tag" in df_signals.columns:
            sig_subset = df_signals[df_signals["strategy_tag"].apply(infer_strategy_id) == sid]
        else:
            sig_subset = pd.DataFrame()

        total_signals = len(sig_subset)
        zt_count = len(sig_subset[sig_subset["is_zt"] == 1]) if total_signals > 0 else 0
        zt_rate = (zt_count / total_signals) * 100 if total_signals > 0 else 0.0

        # 实盘平仓表现
        if not df_closed.empty:
            if "strategy_id" in df_closed.columns and df_closed["strategy_id"].notna().any():
                trade_subset = df_closed[df_closed["strategy_id"] == sid]
            else:
                trade_subset = df_closed[df_closed["strategy_tag"].apply(infer_strategy_id) == sid]
        else:
            trade_subset = pd.DataFrame()

        total_trades = len(trade_subset)
        if total_trades > 0:
            wins = trade_subset[trade_subset["realized_profit"] > 0]
            losses = trade_subset[trade_subset["realized_profit"] < 0]
            win_cnt = len(wins)
            win_rate = (win_cnt / total_trades) * 100
            total_win_amt = wins["realized_profit"].sum()
            total_loss_amt = abs(losses["realized_profit"].sum())
            profit_factor = (total_win_amt / total_loss_amt) if total_loss_amt > 0 else (total_win_amt if total_win_amt > 0 else 1.0)
            avg_return = trade_subset["realized_profit_pct"].mean()
            realized_profit = trade_subset["realized_profit"].sum()
        else:
            win_rate = 0.0
            profit_factor = 1.0
            avg_return = 0.0
            realized_profit = 0.0

        rows.append({
            "战法编号": sid,
            "战法全称": name,
            "推荐信号数": total_signals,
            "封板数量": zt_count,
            "封板成功率 (%)": round(zt_rate, 2),
            "实盘交易数": total_trades,
            "交易胜率 (%)": round(win_rate, 2),
            "盈亏比": round(profit_factor, 2),
            "平均收益率 (%)": round(avg_return, 2),
            "累计净利润 (元)": round(realized_profit, 2)
        })

    return pd.DataFrame(rows)


def get_observation_pool_df():
    """获取最新观察池监控清单"""
    init_db()
    with get_db_connection() as conn:
        try:
            df = pd.read_sql_query("""
            SELECT
                strategy_id AS '战法编号',
                code AS '股票代码',
                name AS '股票名称',
                support_price AS '防守关键位',
                trigger_condition AS '触发与失效条件',
                target_date AS '目标交易日',
                status AS '状态',
                created_at AS '加入时间'
            FROM strategy_observation_pool
            ORDER BY target_date DESC, strategy_id ASC
            """, conn)
            return df
        except Exception:
            return pd.DataFrame()


# ===================== 高保真带样式 Excel 导出引擎 =====================

def export_trades_to_excel(output_path=EXCEL_REPORT_PATH):
    """
    生成商业级格式化的多 Sheet 交易透视 Excel 报表
    - Sheet 1: 🏆 四柱战法归因分析 (Four Pillars Multi-Strategy Attribution)
    - Sheet 2: 📊 战法策略胜率透视 (Strategy Attribution)
    - Sheet 3: 💸 历史平仓成交明细 (Closed Trades Ledger)
    - Sheet 4: 📈 账户日结与资金曲线 (Asset Curve & Settlement)
    - Sheet 5: 🎯 当前持仓与跟踪 (Current Positions)
    - Sheet 6: 🔍 战法观察池监控 (Observation Pool, if exists)
    """
    init_db()
    # 先做一次数据迁移确保最新
    import_account_json_to_db()

    df_attribution = get_four_pillars_attribution_df()
    df_strategy = get_strategy_performance_df()
    df_closed = get_closed_trades_df()
    df_daily = get_daily_settlement_df()
    df_positions = get_current_positions_df()
    df_pool = get_observation_pool_df()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_attribution.to_excel(writer, sheet_name="四柱战法归因分析", index=False)
        df_strategy.to_excel(writer, sheet_name="战法策略胜率透视", index=False)
        df_closed.to_excel(writer, sheet_name="历史平仓明细流水", index=False)
        df_daily.to_excel(writer, sheet_name="账户日结与资金曲线", index=False)
        df_positions.to_excel(writer, sheet_name="当前持仓监控", index=False)
        if not df_pool.empty:
            df_pool.to_excel(writer, sheet_name="战法观察池监控", index=False)

        workbook = writer.book

        # ── 样式体系定义 ──
        font_header = Font(name="Microsoft YaHei", size=11, bold=True, color="FFFFFF")
        font_body = Font(name="Microsoft YaHei", size=10, color="222222")
        font_profit = Font(name="Microsoft YaHei", size=10, bold=True, color="B71C1C")   # 红涨
        font_loss = Font(name="Microsoft YaHei", size=10, bold=True, color="1B5E20")     # 绿跌

        fill_header = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")       # 深深海蓝
        fill_profit = PatternFill(start_color="FFEBEE", end_color="FFEBEE", fill_type="solid")       # 浅红高亮
        fill_loss = PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid")         # 浅绿高亮

        thin_border_side = Side(border_style="thin", color="CBD5E1")
        border_all = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)

        align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        align_left = Alignment(horizontal="left", vertical="center", wrap_text=True)
        align_right = Alignment(horizontal="right", vertical="center", wrap_text=True)

        for sheet_name in workbook.sheetnames:
            ws = workbook[sheet_name]
            ws.freeze_panes = "A2"
            max_col_letter = get_column_letter(ws.max_column)
            ws.auto_filter.ref = f"A1:{max_col_letter}{max(ws.max_row, 1)}"

            # 设置行高与单元格通用样式
            for r_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=ws.max_row), start=1):
                if r_idx == 1:
                    ws.row_dimensions[r_idx].height = 28
                else:
                    ws.row_dimensions[r_idx].height = 24

                for c_idx, cell in enumerate(row, start=1):
                    cell.border = border_all
                    if r_idx == 1:
                        cell.font = font_header
                        cell.fill = fill_header
                        cell.alignment = align_center
                    else:
                        cell.font = font_body
                        cell.alignment = align_center

                        # 数值与格式化高亮处理
                        val = cell.value
                        col_name = str(ws.cell(row=1, column=c_idx).value or "")

                        if isinstance(val, (int, float)):
                            if "率" in col_name or "%" in col_name:
                                cell.number_format = '0.00"%"' if abs(val) > 1.0 else "0.00%"
                                cell.alignment = align_right
                                if val > 0:
                                    cell.font = font_profit
                                    cell.fill = fill_profit
                                elif val < 0:
                                    cell.font = font_loss
                                    cell.fill = fill_loss
                            elif "利润" in col_name or "盈亏" in col_name or "收益" in col_name or "金额" in col_name or "资产" in col_name or "现金" in col_name or "成本" in col_name:
                                cell.number_format = "¥#,##0.00"
                                cell.alignment = align_right
                                if ("利润" in col_name or "盈亏" in col_name):
                                    if val > 0:
                                        cell.font = font_profit
                                        cell.fill = fill_profit
                                    elif val < 0:
                                        cell.font = font_loss
                                        cell.fill = fill_loss
                            elif "价格" in col_name or "价" in col_name:
                                cell.number_format = "¥0.00"
                                cell.alignment = align_right
                            elif "股数" in col_name or "笔数" in col_name or "天数" in col_name:
                                cell.number_format = "#,##0"
                                cell.alignment = align_right
                        elif isinstance(val, str) and ("依据" in col_name or "原因" in col_name):
                            cell.alignment = align_left

            # 自动调整列宽
            for col in ws.columns:
                max_len = 0
                col_letter = get_column_letter(col[0].column)
                for cell in col:
                    v = str(cell.value or "")
                    # 汉字算 2 字符长度
                    length = sum(2 if ord(char) > 127 else 1 for char in v)
                    if length > max_len:
                        max_len = length
                ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    print(f"🎉 成功导出格式化多 Sheet 策略透视 Excel 报表到: {output_path}")
    return output_path


# ===================== CLI 测试与执行 =====================
if __name__ == "__main__":
    init_db()
    import_account_json_to_db()
    export_trades_to_excel()
