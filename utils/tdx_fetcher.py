"""
通达信行情高速获取器 (TongDaXin Data Fetcher)
基于 pytdx 纯 Python 实现，直连通达信行情主站服务器。
支持 Mac / Linux / Windows，免安装/免打开桌面客户端，无请求频率限制。
提供日线、分钟线、实时行情获取及本地 SQLite 增量同步功能。
"""

import time
import sqlite3
import logging
from typing import List, Dict, Optional, Tuple
import pandas as pd
from pytdx.hq import TdxHq_API

logger = logging.getLogger(__name__)

# 预设高可用、高带宽通达信行情主站服务器列表 (IP, Port, 名称)
DEFAULT_TDX_HOSTS = [
    ("218.75.126.9", 7709, "国信证券杭州电信"),
    ("124.160.88.183", 7709, "中信证券杭州电信"),
    ("119.147.212.81", 7709, "招商证券深圳电信"),
    ("117.34.114.13", 7709, "国泰君安西安电信"),
    ("117.34.114.14", 7709, "国泰君安西安电信2"),
    ("117.34.114.15", 7709, "国泰君安西安电信3"),
    ("117.34.114.16", 7709, "国泰君安西安电信4"),
    ("221.231.141.60", 7709, "华泰证券南京电信"),
    ("114.80.63.12", 7709, "申万宏源上海电信"),
    ("60.191.117.167", 7709, "浙商证券杭州电信"),
]


class TDXFetcher:
    """通达信行情获取与同步引擎"""

    def __init__(self, host: Optional[str] = None, port: int = 7709, timeout: float = 1.5):
        self.api = TdxHq_API(raise_exception=False, auto_retry=True)
        self.host = host
        self.port = port
        self.timeout = timeout
        self.is_connected = False
        self._server_name = ""

    def connect(self) -> bool:
        """连接到通达信行情主站服务器（若未指定特定 host，则自动测速选择响应最快的节点）"""
        if self.host:
            try:
                if self.api.connect(self.host, self.port, time_out=self.timeout):
                    self.is_connected = True
                    self._server_name = f"{self.host}:{self.port}"
                    logger.info(f"✓ 成功连接指定通达信节点: {self._server_name}")
                    return True
            except Exception as e:
                logger.warning(f"连接指定通达信节点 {self.host}:{self.port} 失败: {e}")

        # 遍历候选服务器自动测速连接
        for ip, port, name in DEFAULT_TDX_HOSTS:
            try:
                if self.api.connect(ip, port, time_out=self.timeout):
                    # 发送测试快照校验有效性
                    q = self.api.get_security_quotes([(0, "000001")])
                    if q and len(q) > 0 and q[0].get("price", 0) > 0:
                        self.host = ip
                        self.port = port
                        self._server_name = name
                        self.is_connected = True
                        logger.info(f"✓ 成功直连通达信优质主站: {name} ({ip}:{port})")
                        return True
                    self.api.disconnect()
            except Exception:
                continue

        logger.error("❌ 无法连接到任何通达信行情服务器，请检查网络连接")
        self.is_connected = False
        return False

    def disconnect(self):
        """断开连接"""
        if self.is_connected:
            try:
                self.api.disconnect()
            except Exception:
                pass
            self.is_connected = False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    @staticmethod
    def get_market_code(code: str) -> int:
        """
        根据股票代码推断通达信市场标识：
        1: 沪市 (60xxxx, 68xxxx, 90xxxx)
        0: 深市 (00xxxx, 30xxxx, 20xxxx)
        2: 北交所 (4xxxxx, 8xxxxx, 92xxxx)
        """
        code_str = str(code).zfill(6)
        if code_str.startswith(("60", "68", "90")):
            return 1
        elif code_str.startswith(("00", "30", "20")):
            return 0
        elif code_str.startswith(("8", "4", "92")):
            return 2
        return 0

    def get_daily_bars(self, code: str, count: int = 800) -> pd.DataFrame:
        """
        拉取历史日 K 线数据
        category: 9 代表日 K 线
        count: 单次获取根数 (最大 800 根)
        """
        if not self.is_connected:
            if not self.connect():
                return pd.DataFrame()

        market = self.get_market_code(code)
        code_clean = str(code).zfill(6)

        try:
            bars = self.api.get_security_bars(category=9, market=market, code=code_clean, start=0, count=count)
            if not bars:
                return pd.DataFrame()

            df = self.api.to_df(bars)
            if df.empty:
                return df

            # 整理统一列名格式
            # pytdx 返回: ['open', 'close', 'high', 'low', 'vol', 'amount', 'year', 'month', 'day', 'hour', 'minute', 'datetime']
            df["date"] = df["datetime"].apply(lambda x: str(x)[:10])
            df["volume"] = df["vol"]
            df["code"] = code_clean

            # 过滤需要的字段
            cols = ["code", "date", "open", "high", "low", "close", "volume", "amount"]
            cols = [c for c in cols if c in df.columns]
            df = df[cols].sort_values("date").reset_index(drop=True)
            return df
        except Exception as e:
            logger.warning(f"获取股票 {code_clean} 日线失败: {e}")
            return pd.DataFrame()

    def get_minute_bars(self, code: str, category: int = 8, count: int = 240) -> pd.DataFrame:
        """
        获取分钟级 K 线数据 (用于日内高频回测)
        category: 8=1分钟K, 0=5分钟K, 1=15分钟K, 2=30分钟K, 3=60分钟K
        count: 根数 (240 根刚好是全天 4 小时的 1 分钟线)
        """
        if not self.is_connected:
            if not self.connect():
                return pd.DataFrame()

        market = self.get_market_code(code)
        code_clean = str(code).zfill(6)

        try:
            bars = self.api.get_security_bars(category=category, market=market, code=code_clean, start=0, count=count)
            if not bars:
                return pd.DataFrame()

            df = self.api.to_df(bars)
            if df.empty:
                return df

            df["volume"] = df["vol"]
            df["code"] = code_clean
            return df
        except Exception as e:
            logger.warning(f"获取股票 {code_clean} 分钟线失败: {e}")
            return pd.DataFrame()

    def sync_daily_to_db(self, db_path: str = "data/stock_selection.db", codes: Optional[List[str]] = None, count: int = 300) -> int:
        """
        批量同步股票最新日 K 线到本地 SQLite 数据库 (stock_kline 表)
        增量写入/覆盖更新，供老系统与回测引擎使用。
        """
        if not self.is_connected:
            if not self.connect():
                return 0

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # 如果未指定代码列表，从 stock_basic 表或 stock_kline 中获取全部股票
        if not codes:
            try:
                cur.execute("SELECT DISTINCT code FROM stock_basic;")
                rows = cur.fetchall()
                if rows:
                    codes = [r[0] for r in rows]
                else:
                    cur.execute("SELECT DISTINCT code FROM stock_kline;")
                    codes = [r[0] for r in cur.fetchall()]
            except Exception:
                pass

        if not codes:
            logger.warning("未找到待同步的股票代码")
            conn.close()
            return 0

        total = len(codes)
        synced_count = 0
        updated_rows = 0

        logger.info(f"🚀 开始通过通达信主站同步 {total} 只股票最近 {count} 个交易日 K 线到 {db_path}...")

        batch_records = []
        for idx, code in enumerate(codes):
            df = self.get_daily_bars(code, count=count)
            if df.empty:
                continue

            for _, row in df.iterrows():
                # stock_kline 表结构: (code, date, open, high, low, close, volume)
                batch_records.append((
                    str(code).zfill(6),
                    str(row["date"]),
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    int(row["volume"]),
                ))
            synced_count += 1

            # 每 100 只股票或攒够 20000 条批量写入一次
            if len(batch_records) >= 20000 or idx == total - 1:
                cur.executemany(
                    """
                    INSERT INTO stock_kline (code, date, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code, date) DO UPDATE SET
                        open = excluded.open,
                        high = excluded.high,
                        low = excluded.low,
                        close = excluded.close,
                        volume = excluded.volume,
                        updated_date = CURRENT_TIMESTAMP;
                    """,
                    batch_records
                )
                conn.commit()
                updated_rows += len(batch_records)
                batch_records = []

            if (idx + 1) % 100 == 0 or idx == total - 1:
                logger.info(f"  进度: [{idx + 1}/{total}] 已更新 {synced_count} 只股票，写入 {updated_rows} 条记录")

        conn.close()
        logger.info(f"✓ 通达信日 K 线同步完成！共更新 {synced_count}/{total} 只股票。")
        return synced_count
