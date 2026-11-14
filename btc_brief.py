#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BTC 行情监控简报（只读）

每次运行抓取一批公开数据，输出一份中文 Markdown 简报，用于判断 BTC 当前更接近
"下跌 / 止跌 / 反弹" 中的哪个阶段。

设计约束：
  * 只发 HTTP GET，只访问无需鉴权的公开接口；不含任何下单、划转、签名逻辑，不读取任何 API Key。
  * 每个数据都带来源编号和获取时间；任何一个源失败都如实写"获取失败"，不用旧数据或估算值顶替。
  * "事实"与"推断"分开标注；推断只做规则归类并写出依据，不给买卖建议，不预测价格或时间。

接口依据（均为各家官方文档 / 官方页面，详见 README）：
  * 币安现货   https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints
  * 币安 U 本位 https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api
  * 恐惧贪婪   https://alternative.me/crypto/fear-and-greed-index/#api
  * 美联储日历  https://www.federalreserve.gov/newsevents/calendar.htm （页面所用 JSON）
  * BLS 日程   https://www.bls.gov/schedule/news_release/ （官方 iCalendar 订阅文件）
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from statistics import mean
from urllib.parse import urlencode, urlsplit

import requests

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover  (Python < 3.9)
    ZoneInfo = None  # type: ignore

# --------------------------------------------------------------------------- #
# 配置：数据源地址与判定阈值。阈值都是"规则"，改这里即可，简报里会原样打印出来。
# --------------------------------------------------------------------------- #
SYMBOL = "BTCUSDT"

SPOT_BASE = "https://data-api.binance.vision"      # 币安官方"仅行情"域名，无需鉴权
FUT_BASE = "https://fapi.binance.com"              # 币安 U 本位合约
BINANCE_ANN_URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
BINANCE_ANN_PAGE = "https://www.binance.com/en/support/announcement"
BINANCE_ANN_DETAIL = "https://www.binance.com/en/support/announcement/detail/{code}"
FNG_URL = "https://api.alternative.me/fng/"
ETF_URL = "https://www.tftc.io/bitcoin-etf-flows/data.json"
ETF_PAGE = "https://www.tftc.io/bitcoin-etf-flows"
FED_CAL_URL = "https://www.federalreserve.gov/json/calendar.json"
FED_CAL_PAGE = "https://www.federalreserve.gov/newsevents/calendar.htm"
FED_PRESS_RSS = "https://www.federalreserve.gov/feeds/press_all.xml"
SEC_PRESS_RSS = "https://www.sec.gov/news/pressreleases.rss"
BLS_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BLS_SCHEDULE_PAGE = "https://www.bls.gov/schedule/news_release/"

# 公告页分类（catalogId 取自公告页接口的实际返回）
ANN_CATALOGS = {
    48: "新币上线",
    161: "下架",
    49: "币安最新动态（含规则变更）",
    157: "维护与升级",
    51: "API 更新",
}

LOOKBACK_DAYS = 30          # "近期高/低点"的窗口（日线根数，含当日未收盘）
HAMMER_SHADOW_TO_BODY = 2.0  # 长下影线：下影线 ≥ 实体的 2 倍
HAMMER_SHADOW_TO_RANGE = 0.5  # 且下影线 ≥ 全日振幅的 50%
VOLUME_SPIKE_RATIO = 1.5    # 放量：成交量 ≥ 此前 7 日均量的 1.5 倍
HAMMER_SCAN_DAYS = 3        # 在最近 3 根已收盘日线里找
NO_NEW_LOW_MIN_DAYS = 2     # 连续 ≥2 根已收盘日线不创新低
OI_DROP_FROM_PEAK = -0.10   # 未平仓量较 7 日峰值回落 ≥10%
OI_DROP_24H = -0.05         # 或 24 小时内下降 ≥5%
ETF_TURN_MAX_STREAK = 3     # "转为净流入"：转折发生在最近 3 个交易日内
NEAR_HIGH_PCT = 0.05        # 距窗口高点不足 5% 时，不套用"下跌/止跌/反弹"
REBOUND_PCT = 0.05          # 自窗口低点回升 ≥5% 记为"反弹"
NEWS_WINDOW_HOURS = 24
EVENT_WINDOW_DAYS = 7

CRYPTO_KEYWORDS = re.compile(
    r"crypto|bitcoin|\bbtc\b|digital asset|stablecoin|token|blockchain|\betf\b|\betp\b|"
    r"interest rate|federal open market|fomc|monetary policy",
    re.I,
)

TIMEOUT = 20
ET_ZONE = "America/New_York"


def user_agent() -> str:
    """如实标识为脚本。BLS、SEC 要求自动访问附联系方式，可用环境变量 BTC_BRIEF_CONTACT 提供。"""
    contact = os.environ.get("BTC_BRIEF_CONTACT", "").strip()
    base = "btc-brief/1.0 (read-only research script"
    return f"{base}; contact: {contact})" if contact else base + ")"


# --------------------------------------------------------------------------- #
# 时间与格式化
# --------------------------------------------------------------------------- #
def zone(name: str):
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(name)
    except Exception:
        return None


class Clock:
    def __init__(self, tz_name: str = "Asia/Shanghai", now: datetime | None = None):
        self.now = now or datetime.now(timezone.utc)
        self.tz_name = tz_name
        self.tz = zone(tz_name) or timezone(timedelta(hours=8), "UTC+8")
        self.tz_label = "北京" if tz_name == "Asia/Shanghai" else tz_name

    @property
    def now_ms(self) -> int:
        return int(self.now.timestamp() * 1000)

    def fmt(self, dt: datetime | None, with_date: bool = True) -> str:
        if dt is None:
            return "—"
        u = dt.astimezone(timezone.utc)
        loc = dt.astimezone(self.tz)
        if with_date:
            local = loc.strftime("%H:%M") if loc.date() == u.date() else loc.strftime("%m-%d %H:%M")
            return f"{u:%Y-%m-%d %H:%M} UTC（{self.tz_label} {local}）"
        return f"{u:%H:%M:%S} UTC"

    def fmt_ms(self, ms: int | float | None) -> str:
        if ms is None:
            return "—"
        return self.fmt(datetime.fromtimestamp(ms / 1000, timezone.utc))


def ms_to_date(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%m-%d")


def usd(x: float | None, digits: int = 2) -> str:
    return "—" if x is None else f"{x:,.{digits}f}"


def pct(x: float | None, digits: int = 2) -> str:
    return "—" if x is None else f"{x * 100:+.{digits}f}%"


def money_m(x: float | None) -> str:
    """美元金额，按百万美元显示，带正负号。"""
    return "—" if x is None else f"{x / 1e6:+,.1f} 百万美元"


FAIL = "获取失败"

FNG_LABELS = {"Extreme Fear": "极度恐惧", "Fear": "恐惧", "Neutral": "中性",
              "Greed": "贪婪", "Extreme Greed": "极度贪婪"}


# --------------------------------------------------------------------------- #
# HTTP：只有 GET；每次请求都登记来源、时间、成败
# --------------------------------------------------------------------------- #
@dataclass
class Source:
    sid: str
    name: str
    url: str
    ok: bool = False
    fetched_at: datetime | None = None
    error: str = ""
    note: str = ""


class Fetcher:
    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent(), "Accept": "*/*"})
        self.sources: dict[str, Source] = {}
        self._blocked_hosts: dict[str, str] = {}

    def get(self, sid: str, name: str, url: str, params: dict | None = None, kind: str = "json"):
        """GET 一个公开地址。成功返回解析后的数据，失败返回 None 并登记原因。"""
        full = url + ("?" + urlencode(params) if params else "")
        src = Source(sid=sid, name=name, url=full)
        self.sources[sid] = src
        host = urlsplit(url).netloc
        if host in self._blocked_hosts:
            src.fetched_at = datetime.now(timezone.utc)
            src.error = f"同一主机已被拒绝（{self._blocked_hosts[host]}），未重复请求"
            return None
        last_err = ""
        for attempt in range(2):  # 仅对网络层错误重试一次
            try:
                resp = self.session.get(url, params=params, timeout=TIMEOUT)
                src.fetched_at = datetime.now(timezone.utc)
            except requests.RequestException as exc:
                src.fetched_at = datetime.now(timezone.utc)
                last_err = f"网络错误：{type(exc).__name__}"
                time.sleep(1.0)
                continue
            err = self._classify(resp)
            if err:
                src.error = err
                if resp.status_code in (401, 403, 405, 451):
                    self._blocked_hosts[host] = f"HTTP {resp.status_code}"
                return None
            try:
                # 统一按 UTF-8 解码并去掉 BOM（美联储的 JSON、RSS 带 BOM）
                data = resp.content.decode("utf-8-sig", errors="replace")
                if kind == "json":
                    data = json.loads(data)
            except ValueError:
                src.error = "返回内容不是合法 JSON"
                return None
            src.ok = True
            return data
        src.error = last_err or "未知错误"
        return None

    @staticmethod
    def _classify(resp: requests.Response) -> str:
        code = resp.status_code
        head = resp.text[:600] if resp.content else ""
        if code == 451:
            return "HTTP 451：对方按访问所在地区拒绝服务（币安合约接口的地区限制）"
        if code in (403, 405) or (code == 202 and not resp.content):
            if "Just a moment" in head or "Human Verification" in head or code == 202:
                return f"HTTP {code}：对方站点要求人机验证，脚本不绕过"
            if "Access Denied" in head:
                return f"HTTP {code}：对方拒绝自动访问（Access Denied）"
            return f"HTTP {code}：对方拒绝访问"
        if code == 429:
            return "HTTP 429：触发对方限频"
        if code != 200:
            return f"HTTP {code}"
        if not resp.content:
            return "返回内容为空"
        return ""

    def tag(self, *sids: str) -> str:
        """生成形如 [S1 15:40:02 UTC] 的来源标注。"""
        parts = []
        for sid in sids:
            s = self.sources.get(sid)
            if s is None:
                continue
            t = s.fetched_at.strftime("%H:%M:%S UTC") if s.fetched_at else "—"
            parts.append(f"{sid} {t}")
        return "[" + "；".join(parts) + "]" if parts else ""

    def reason(self, sid: str) -> str:
        s = self.sources.get(sid)
        return f"{FAIL}（{s.error}）" if s and s.error else FAIL


# --------------------------------------------------------------------------- #
# 数据获取与解析
# --------------------------------------------------------------------------- #
@dataclass
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float          # 基础币种成交量（BTC）
    close_time: int
    quote_volume: float    # 计价币种成交额（USDT）
    trades: int
    taker_buy_base: float  # 主动买入成交量（BTC）
    closed: bool = True

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def lower_shadow(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def taker_buy_share(self) -> float | None:
        return self.taker_buy_base / self.volume if self.volume else None


def parse_klines(raw, now_ms: int) -> list[Candle]:
    """K 线数组各位置含义见币安文档：0 开盘时间 1 开 2 高 3 低 4 收 5 成交量 6 收盘时间
    7 成交额 8 成交笔数 9 主动买入成交量 10 主动买入成交额 11 忽略。"""
    out = []
    for r in raw or []:
        out.append(Candle(
            open_time=int(r[0]), open=float(r[1]), high=float(r[2]), low=float(r[3]),
            close=float(r[4]), volume=float(r[5]), close_time=int(r[6]),
            quote_volume=float(r[7]), trades=int(r[8]), taker_buy_base=float(r[9]),
            closed=int(r[6]) < now_ms,
        ))
    return out


def fetch_spot(f: Fetcher, now_ms: int) -> dict:
    d: dict = {}
    d["ticker"] = f.get("S1", "币安现货 24 小时行情", f"{SPOT_BASE}/api/v3/ticker/24hr", {"symbol": SYMBOL})
    k1d = f.get("S2", "币安现货日线 K 线", f"{SPOT_BASE}/api/v3/klines",
                {"symbol": SYMBOL, "interval": "1d", "limit": 120})
    k4h = f.get("S3", "币安现货 4 小时 K 线", f"{SPOT_BASE}/api/v3/klines",
                {"symbol": SYMBOL, "interval": "4h", "limit": 60})
    d["daily"] = parse_klines(k1d, now_ms) if k1d else None
    d["h4"] = parse_klines(k4h, now_ms) if k4h else None
    return d


def fetch_futures(f: Fetcher, now_ms: int) -> dict:
    d: dict = {}
    sym = {"symbol": SYMBOL}
    hist = {"symbol": SYMBOL, "period": "1h", "limit": 200}  # 200 小时 > 7 天
    d["premium"] = f.get("F1", "币安永续 标记价格与当期资金费率", f"{FUT_BASE}/fapi/v1/premiumIndex", sym)
    d["funding"] = f.get("F2", "币安永续 资金费率历史", f"{FUT_BASE}/fapi/v1/fundingRate",
                         {"symbol": SYMBOL, "limit": 100})
    d["oi"] = f.get("F3", "币安永续 当前未平仓量", f"{FUT_BASE}/fapi/v1/openInterest", sym)
    d["oi_hist"] = f.get("F4", "币安永续 未平仓量历史（1h）", f"{FUT_BASE}/futures/data/openInterestHist", hist)
    d["ls"] = f.get("F5", "币安永续 多空账户比（1h）", f"{FUT_BASE}/futures/data/globalLongShortAccountRatio", hist)
    d["taker"] = f.get("F6", "币安永续 主动买卖量（1h）", f"{FUT_BASE}/futures/data/takerlongshortRatio", hist)
    k = f.get("F7", "币安永续 日线 K 线", f"{FUT_BASE}/fapi/v1/klines",
              {"symbol": SYMBOL, "interval": "1d", "limit": 30})
    d["daily"] = parse_klines(k, now_ms) if k else None
    return d


def fetch_announcements(f: Fetcher) -> list[dict] | None:
    raw = f.get("B1", "币安官方公告页", BINANCE_ANN_URL, {"type": 1, "pageNo": 1, "pageSize": 20})
    if not raw:
        return None
    try:
        catalogs = raw["data"]["catalogs"]
    except (KeyError, TypeError):
        f.sources["B1"].ok = False
        f.sources["B1"].error = "返回结构与预期不符"
        return None
    items = []
    for c in catalogs:
        cid = c.get("catalogId")
        if cid not in ANN_CATALOGS:
            continue
        for a in c.get("articles") or []:
            try:
                ts = datetime.fromtimestamp(int(a["releaseDate"]) / 1000, timezone.utc)
            except (KeyError, TypeError, ValueError):
                continue
            items.append({
                "source": "币安公告", "sid": "B1", "category": ANN_CATALOGS[cid],
                "title": str(a.get("title", "")).strip(), "time": ts,
                "link": BINANCE_ANN_DETAIL.format(code=a.get("code", "")),
            })
    return items


def fetch_rss(f: Fetcher, sid: str, name: str, url: str, label: str) -> list[dict] | None:
    text = f.get(sid, name, url, kind="text")
    if not text:
        return None
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError:
        f.sources[sid].ok = False
        f.sources[sid].error = "RSS 解析失败"
        return None
    items = []
    for it in root.iter("item"):
        title = " ".join((it.findtext("title") or "").split())
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        try:
            ts = parsedate_to_datetime(pub)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        items.append({"source": label, "sid": sid, "category": (it.findtext("category") or "").strip(),
                      "title": title, "time": ts.astimezone(timezone.utc), "link": link})
    return items


def fetch_fng(f: Fetcher) -> list[dict] | None:
    raw = f.get("G1", "恐惧贪婪指数（Alternative.me）", FNG_URL, {"limit": 8})
    if not raw:
        return None
    try:
        return [{"value": int(x["value"]), "label": x["value_classification"],
                 "time": datetime.fromtimestamp(int(x["timestamp"]), timezone.utc)} for x in raw["data"]]
    except (KeyError, TypeError, ValueError):
        f.sources["G1"].ok = False
        f.sources["G1"].error = "返回结构与预期不符"
        return None


def fetch_etf(f: Fetcher) -> dict | None:
    raw = f.get("E1", "美国现货 BTC ETF 每日净流量（TFTC 汇总）", ETF_URL)
    if not raw:
        return None
    try:
        days = [{"date": date.fromisoformat(x["date"]), "flow": float(x["netFlowUsd"])}
                for x in raw["days"] if x.get("netFlowUsd") is not None]
        days.sort(key=lambda x: x["date"])
        f.sources["E1"].note = f"上游：{raw.get('sources', '未注明')}"
        return {"days": days, "updated_through": raw.get("updatedThrough"),
                "modified": raw.get("dateModified"), "upstream": raw.get("sources", "")}
    except (KeyError, TypeError, ValueError):
        f.sources["E1"].ok = False
        f.sources["E1"].error = "返回结构与预期不符"
        return None


FED_TITLE_ZH = {"fomc meeting": "FOMC 议息会议", "fomc minutes": "FOMC 会议纪要",
                "fomc press conference": "FOMC 新闻发布会", "beige book": "褐皮书"}

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*([ap])\.?m\.?", re.I)


def _clean_html(s: str) -> str:
    s = html.unescape(html.unescape(s or ""))
    return " ".join(re.sub(r"<[^>]+>", " ", s).split())


def fetch_fed_calendar(f: Fetcher) -> list[dict] | None:
    """美联储官网日历页所用的 JSON。时间为美东时间。"""
    raw = f.get("C1", "美联储官网日历", FED_CAL_URL)
    if not raw:
        return None
    et = zone(ET_ZONE)
    events = []
    for e in raw.get("events", []) if isinstance(raw, dict) else []:
        if not e or e.get("type") not in ("FOMC", "Beige", "Testimony", "Speeches", "Board"):
            continue
        try:
            y, m = (int(x) for x in str(e["month"]).split("-"))
            day = int(re.search(r"\d+", str(e["days"])).group())
            d = date(y, m, day)
        except (KeyError, ValueError, AttributeError):
            continue
        when, has_time = None, False
        tm = _TIME_RE.search(str(e.get("time", "")))
        if tm and et is not None:
            hh = int(tm.group(1)) % 12 + (12 if tm.group(3).lower() == "p" else 0)
            when = datetime(y, m, day, hh, int(tm.group(2)), tzinfo=et).astimezone(timezone.utc)
            has_time = True
        title = _clean_html(e.get("title", ""))
        desc = _clean_html(e.get("description", ""))
        zh = FED_TITLE_ZH.get(title.lower())
        events.append({"date": d, "when": when, "has_time": has_time, "type": e["type"],
                       "is_meeting": title.lower() == "fomc meeting",
                       "title": (f"{zh}｜" if zh else "") + title + (f"：{desc}" if desc else ""), "sid": "C1",
                       "raw_time": str(e.get("time", "")).strip(), "link": FED_CAL_PAGE})
    return events


def parse_ics(text: str) -> list[dict]:
    """解析 iCalendar（RFC 5545）中的 VEVENT，只取 DTSTART 与 SUMMARY。无时区后缀的时间按美东处理。"""
    et = zone(ET_ZONE)
    lines: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]       # 折行续接
        else:
            lines.append(line)
    events, cur = [], None
    for line in lines:
        if line.startswith("BEGIN:VEVENT"):
            cur = {}
        elif line.startswith("END:VEVENT"):
            if cur and "dtstart" in cur and "summary" in cur:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            key, val = line.split(":", 1)
            name = key.split(";")[0].upper()
            if name == "SUMMARY":
                cur["summary"] = val.replace("\\,", ",").replace("\\;", ";").strip()
            elif name == "DTSTART":
                m = re.match(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?(Z)?)?", val.strip())
                if not m:
                    continue
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                cur["date"] = date(y, mo, d)
                if m.group(4):
                    tz = timezone.utc if m.group(7) else (et or timezone.utc)
                    cur["dtstart"] = datetime(y, mo, d, int(m.group(4)), int(m.group(5)), tzinfo=tz)
                    cur["has_time"] = True
                    if not m.group(7):
                        cur["date"] = date(y, mo, d)
                else:
                    cur["dtstart"] = datetime(y, mo, d, tzinfo=timezone.utc)
                    cur["has_time"] = False
    return events


def fetch_bls(f: Fetcher) -> list[dict] | None:
    """BLS 官方发布日程（iCalendar）。BLS 会拒绝未附联系方式的自动访问。"""
    text = f.get("M1", "BLS 发布日程（CPI、非农）", BLS_ICS_URL, kind="text")
    if not text:
        if "M1" in f.sources and not os.environ.get("BTC_BRIEF_CONTACT"):
            f.sources["M1"].note = "BLS 要求自动访问附联系方式，可设置环境变量 BTC_BRIEF_CONTACT 后重试"
        return None
    if "BEGIN:VCALENDAR" not in text:
        f.sources["M1"].ok = False
        f.sources["M1"].error = "返回内容不是 iCalendar"
        return None
    out = []
    for e in parse_ics(text):
        s = e["summary"]
        if re.search(r"consumer price index", s, re.I):
            kind = "美国 CPI"
        elif re.search(r"employment situation", s, re.I):
            kind = "美国非农就业（Employment Situation）"
        else:
            continue
        out.append({"date": e["date"], "when": e["dtstart"].astimezone(timezone.utc) if e["has_time"] else None,
                    "has_time": e["has_time"], "type": "BLS", "title": f"{kind}：{s}", "sid": "M1",
                    "raw_time": "", "link": BLS_SCHEDULE_PAGE})
    return out


# --------------------------------------------------------------------------- #
# 计算：指标对比
# --------------------------------------------------------------------------- #
def series_since(rows, now_ms: int, days: float, ts_key: str = "timestamp"):
    cut = now_ms - int(days * 86400_000)
    return [r for r in rows or [] if int(r[ts_key]) >= cut]


def safe_mean(vals) -> float | None:
    vals = [v for v in vals if v is not None]
    return mean(vals) if vals else None


def rel(cur: float | None, base: float | None) -> float | None:
    if cur is None or base in (None, 0):
        return None
    return cur / base - 1


def completed(candles: list[Candle] | None) -> list[Candle]:
    return [c for c in candles or [] if c.closed]


# --------------------------------------------------------------------------- #
# 止跌信号：每个函数返回 Signal，status ∈ {"出现", "未出现", "无法判定"}
# --------------------------------------------------------------------------- #
@dataclass
class Signal:
    name: str
    status: str
    rule: str
    facts: list[str] = field(default_factory=list)
    tags: str = ""

    @property
    def available(self) -> bool:
        return self.status != "无法判定"


def sig_hammer(daily: list[Candle] | None) -> Signal:
    rule = (f"最近 {HAMMER_SCAN_DAYS} 根已收盘日线中，任意一根同时满足：下影线 ≥ 实体的 {HAMMER_SHADOW_TO_BODY:g} 倍、"
            f"下影线 ≥ 当日振幅的 {HAMMER_SHADOW_TO_RANGE:.0%}、成交量 ≥ 此前 7 日均量的 {VOLUME_SPIKE_RATIO:g} 倍")
    sig = Signal("放量长下影线", "无法判定", rule)
    done = completed(daily)
    if len(done) < HAMMER_SCAN_DAYS + 7:
        sig.facts.append("日线数据不足或获取失败")
        return sig
    hit = False
    for i in range(len(done) - HAMMER_SCAN_DAYS, len(done)):
        c = done[i]
        base = mean(x.volume for x in done[i - 7:i])
        vol_ratio = c.volume / base if base else 0.0
        shadow_range = c.lower_shadow / c.range if c.range else 0.0
        long_shadow = (c.range > 0 and c.lower_shadow >= HAMMER_SHADOW_TO_BODY * c.body
                       and shadow_range >= HAMMER_SHADOW_TO_RANGE)
        spike = vol_ratio >= VOLUME_SPIKE_RATIO
        ok = long_shadow and spike
        hit = hit or ok
        sig.facts.append(f"{ms_to_date(c.open_time)}：下影线占振幅 {shadow_range:.0%}、"
                         f"下影线/实体 {(c.lower_shadow / c.body if c.body else float('inf')):.1f} 倍、"
                         f"量比 {vol_ratio:.2f} → {'满足' if ok else '不满足'}")
    sig.status = "出现" if hit else "未出现"
    return sig


def new_low_flags(daily: list[Candle], lookback: int = LOOKBACK_DAYS) -> list[bool]:
    """flags[i] 为真：第 i 根日线的最低价低于它之前 lookback 根日线的最低价。"""
    flags = []
    for i, c in enumerate(daily):
        prev = daily[max(0, i - lookback):i]
        flags.append(bool(prev) and c.low < min(p.low for p in prev))
    return flags


def sig_no_new_low(daily: list[Candle] | None) -> Signal:
    rule = (f"最近连续 ≥{NO_NEW_LOW_MIN_DAYS} 根已收盘日线都没有跌破各自之前 {LOOKBACK_DAYS} 日的最低价，"
            f"且当日（未收盘）也未跌破")
    sig = Signal("连续 2 到 3 天不创新低", "无法判定", rule)
    if not daily or len(daily) < LOOKBACK_DAYS + 5:
        sig.facts.append("日线数据不足或获取失败")
        return sig
    flags = new_low_flags(daily)
    last = daily[-1]
    today_open = not last.closed
    today_new_low = flags[-1] if today_open else False
    idx = len(daily) - (2 if today_open else 1)   # 最近一根已收盘日线
    streak = 0
    while idx >= 0 and not flags[idx]:
        streak += 1
        idx -= 1
    last_new_low = next((i for i in range(len(daily) - 1, -1, -1) if flags[i]), None)
    if last_new_low is not None:
        c = daily[last_new_low]
        sig.facts.append(f"最近一次创 {LOOKBACK_DAYS} 日新低：{ms_to_date(c.open_time)}"
                         f"{'（当日，未收盘）' if not c.closed else ''}，最低 {usd(c.low)}")
    else:
        sig.facts.append(f"已获取的日线范围内没有出现 {LOOKBACK_DAYS} 日新低")
    sig.facts.append(f"已收盘日线连续不创新低：{streak if last_new_low is not None else '≥' + str(streak)} 根；"
                     f"当日未收盘 K 线{'已' if today_new_low else '未'}创新低")
    ok = streak >= NO_NEW_LOW_MIN_DAYS and not today_new_low
    if ok and last_new_low is not None and (len(daily) - 1 - last_new_low) > 10:
        sig.facts.append("距上次新低已超过 10 天，这一项对判断当前是否止跌的参考意义有限")
    sig.status = "出现" if ok else "未出现"
    return sig


def sig_funding(premium: dict | None, funding: list | None) -> Signal:
    rule = "最近一次已结算资金费率 < 0，或当期预测资金费率 < 0"
    sig = Signal("资金费率转负", "无法判定", rule)
    cur = None
    if premium and premium.get("lastFundingRate") not in (None, ""):
        cur = float(premium["lastFundingRate"])
    last = float(funding[-1]["fundingRate"]) if funding else None
    if cur is None and last is None:
        sig.facts.append("资金费率数据获取失败")
        return sig
    if last is not None:
        recent = [float(x["fundingRate"]) for x in funding[-9:]]
        sig.facts.append(f"最近一次已结算：{last * 100:+.4f}%；最近 {len(recent)} 次结算中为负的有 "
                         f"{sum(1 for r in recent if r < 0)} 次")
    if cur is not None:
        sig.facts.append(f"当期预测：{cur * 100:+.4f}%")
    sig.status = "出现" if any(v is not None and v < 0 for v in (cur, last)) else "未出现"
    return sig


def sig_oi(oi_now: dict | None, oi_hist: list | None, now_ms: int) -> Signal:
    rule = (f"以 BTC 计的未平仓量较 7 日峰值回落 ≥{abs(OI_DROP_FROM_PEAK):.0%}，"
            f"或较 24 小时前下降 ≥{abs(OI_DROP_24H):.0%}（用币本位数量，排除价格下跌本身的影响）")
    sig = Signal("未平仓量大幅下降（杠杆出清）", "无法判定", rule)
    week = series_since(oi_hist, now_ms, 7)
    if not week:
        sig.facts.append("未平仓量历史获取失败")
        return sig
    vals = [float(r["sumOpenInterest"]) for r in week]
    cur = float(oi_now["openInterest"]) if oi_now and oi_now.get("openInterest") else vals[-1]
    peak = max(vals)
    day_ago_rows = [r for r in week if int(r["timestamp"]) <= now_ms - 86400_000]
    day_ago = float(day_ago_rows[-1]["sumOpenInterest"]) if day_ago_rows else None
    d_peak, d_24h = rel(cur, peak), rel(cur, day_ago)
    sig.facts.append(f"当前 {usd(cur, 0)} BTC；7 日峰值 {usd(peak, 0)} BTC，较峰值 {pct(d_peak)}；较 24 小时前 {pct(d_24h)}")
    hit = (d_peak is not None and d_peak <= OI_DROP_FROM_PEAK) or (d_24h is not None and d_24h <= OI_DROP_24H)
    sig.status = "出现" if hit else "未出现"
    return sig


def missing_weekdays(latest: date, today_et: date) -> list[date]:
    """latest 之后、today_et 之前的工作日（未考虑美国节假日）。"""
    out, d = [], latest + timedelta(days=1)
    while d < today_et:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def sig_etf(etf: dict | None, today_et: date) -> Signal:
    rule = (f"最新一个交易日为净流入，往前追溯这段连续净流入不超过 {ETF_TURN_MAX_STREAK} 个交易日，"
            f"且它之前的那个交易日为净流出")
    sig = Signal("ETF 由净流出转为净流入", "无法判定", rule)
    days = (etf or {}).get("days") or []
    if len(days) < 2:
        sig.facts.append("ETF 净流量数据获取失败")
        return sig
    recent = days[-6:]
    sig.facts.append("最近几个交易日净流量：" + "，".join(f"{d['date']:%m-%d} {d['flow'] / 1e6:+,.0f}" for d in recent)
                     + "（百万美元）")
    streak, i = 0, len(days) - 1
    while i >= 0 and days[i]["flow"] > 0:
        streak += 1
        i -= 1
    turned = 1 <= streak <= ETF_TURN_MAX_STREAK and i >= 0 and days[i]["flow"] < 0
    sig.status = "出现" if turned else "未出现"
    gap = missing_weekdays(days[-1]["date"], today_et)
    if gap:
        sig.facts.append(f"注意：数据只到 {days[-1]['date']:%m-%d}，之后的工作日 "
                         f"{'、'.join(f'{g:%m-%d}' for g in gap)} 尚未收录，本项结论可能滞后")
    return sig


# --------------------------------------------------------------------------- #
# 阶段归类（推断）
# --------------------------------------------------------------------------- #
@dataclass
class Stage:
    label: str
    basis: list[str]
    caveats: list[str]


def infer_stage(daily: list[Candle] | None, price: float | None, signals: list[Signal]) -> Stage:
    if not daily or price is None or len(daily) < LOOKBACK_DAYS:
        return Stage("无法判定", ["现货价格或日线数据获取失败"], [])
    win = daily[-LOOKBACK_DAYS:]
    hi = max(win, key=lambda c: c.high)
    lo = min(win, key=lambda c: c.low)
    days_since_low = len(win) - 1 - win.index(lo)
    from_high, from_low = price / hi.high - 1, price / lo.low - 1
    basis = [
        f"近 {LOOKBACK_DAYS} 日高点 {usd(hi.high)}（{ms_to_date(hi.open_time)}），现价距高点 {pct(from_high)}",
        f"近 {LOOKBACK_DAYS} 日低点 {usd(lo.low)}（{ms_to_date(lo.open_time)}，"
        f"{'即当日' if days_since_low == 0 else f'{days_since_low} 根日线前'}），现价距低点 {pct(from_low)}",
    ]
    if -from_high < NEAR_HIGH_PCT:
        label = "不适用（非下跌语境）"
        basis.append(f"规则：现价距窗口高点不足 {NEAR_HIGH_PCT:.0%}，不套用下跌/止跌/反弹")
    elif days_since_low <= 1:
        label = "下跌"
        basis.append("规则：窗口最低价出现在当日或前一日，即最近两根日线内仍在创新低 → 归为下跌")
    elif from_low >= REBOUND_PCT:
        label = "反弹"
        basis.append(f"规则：已 ≥2 根日线未再创新低，且现价自低点回升 ≥{REBOUND_PCT:.0%} → 归为反弹")
    else:
        label = "止跌"
        basis.append(f"规则：已 ≥2 根日线未再创新低，但自低点回升不足 {REBOUND_PCT:.0%} → 归为止跌（横盘观察）")
    avail = [s for s in signals if s.available]
    seen = [s for s in avail if s.status == "出现"]
    basis.append(f"止跌信号佐证：可判定的 {len(avail)} 项中出现 {len(seen)} 项"
                 + (f"（{'、'.join(s.name for s in seen)}）" if seen else ""))
    caveats = []
    if len(avail) < len(signals):
        miss = [s.name for s in signals if not s.available]
        caveats.append(f"有 {len(miss)} 项信号因数据获取失败无法判定（{'、'.join(miss)}），佐证不完整")
    caveats.append("这是按上述固定规则对当前状态的归类，不是对后续走势的预测；阈值可在脚本顶部调整")
    return Stage(label, basis, caveats)


# --------------------------------------------------------------------------- #
# 简报渲染
# --------------------------------------------------------------------------- #
def build_report(clock: Clock, f: Fetcher, spot: dict, fut: dict, fng, etf, anns, fed_news, sec_news,
                 fed_cal, bls) -> str:
    now_ms = clock.now_ms
    L: list[str] = []
    add = L.append
    daily: list[Candle] | None = spot.get("daily")
    h4: list[Candle] | None = spot.get("h4")
    ticker = spot.get("ticker")
    price = float(ticker["lastPrice"]) if ticker else None

    et = zone(ET_ZONE)
    today_et = clock.now.astimezone(et).date() if et else clock.now.date()

    signals = [
        sig_hammer(daily),
        sig_no_new_low(daily),
        sig_funding(fut.get("premium"), fut.get("funding")),
        sig_oi(fut.get("oi"), fut.get("oi_hist"), now_ms),
        sig_etf(etf, today_et),
    ]
    signals[0].tags = f.tag("S2")
    signals[1].tags = f.tag("S2")
    signals[2].tags = f.tag("F1", "F2")
    signals[3].tags = f.tag("F3", "F4")
    signals[4].tags = f.tag("E1")
    stage = infer_stage(daily, price, signals)

    add("# BTC 行情监控简报")
    add("")
    add(f"- 生成时间：{clock.fmt(clock.now)}")
    add("- 性质：只读信息汇总与规则化归类，不构成任何买卖建议，不预测价格或时间。")
    add("- 标注约定：**【事实】** 为接口原始值或对其直接算术计算；**【推断】** 为按固定规则得出的归类，均附依据。"
        "方括号内是来源编号与获取时间（UTC），编号对应文末「数据源状态」。")
    add("")

    # ---- 概览 -------------------------------------------------------------
    add("## 概览")
    add("")
    add(f"**【推断】当前阶段归类：{stage.label}**")
    add("")
    add("依据：")
    for b in stage.basis:
        add(f"- {b}")
    for c in stage.caveats:
        add(f"- 说明：{c}")
    failed = [s for s in f.sources.values() if not s.ok]
    if failed:
        add(f"- 本次有 {len(failed)} 个数据源获取失败：{'、'.join(s.sid for s in failed)}（详见文末），相关条目均标为「{FAIL}」。")
    add("")

    # ---- 1. 价格 ----------------------------------------------------------
    add("## 1. 价格")
    add("")
    add("| 项目 | 数值 | 来源与获取时间 |")
    add("|---|---|---|")
    if ticker:
        add(f"| 现货现价（BTCUSDT） | {usd(price)} USDT | {f.tag('S1')} |")
        add(f"| 24 小时涨跌幅（滚动） | {float(ticker['priceChangePercent']):+.2f}% | {f.tag('S1')} |")
        add(f"| 24 小时最高 / 最低 | {usd(float(ticker['highPrice']))} / {usd(float(ticker['lowPrice']))} | {f.tag('S1')} |")
    else:
        add(f"| 现货现价、24 小时涨跌幅 | {f.reason('S1')} | {f.tag('S1')} |")
    prem = fut.get("premium")
    if prem:
        mark = float(prem["markPrice"])
        add(f"| 永续标记价格 | {usd(mark)} USDT | {f.tag('F1')} |")
        if price:
            add(f"| 永续相对现货的基差 | {pct(mark / price - 1, 3)} | {f.tag('F1', 'S1')} |")
    else:
        add(f"| 永续标记价格 | {f.reason('F1')} | {f.tag('F1')} |")
    if h4 and price:
        target = now_ms - 7 * 86400_000
        ref = next((c for c in h4 if c.open_time >= target), None)
        if ref:
            add(f"| 7 日涨跌幅 | {pct(price / ref.open - 1)}（基准 {usd(ref.open)}，"
                f"取 {clock.fmt_ms(ref.open_time)} 开盘的 4 小时 K 线开盘价） | {f.tag('S3', 'S1')} |")
    else:
        add(f"| 7 日涨跌幅 | {f.reason('S3')} | {f.tag('S3')} |")
    if daily and price:
        for n in (7, LOOKBACK_DAYS, 90):
            win = daily[-n:]
            if len(win) < n:
                continue
            hi = max(win, key=lambda c: c.high)
            lo = min(win, key=lambda c: c.low)
            add(f"| 近 {n} 日高点 / 距离 | {usd(hi.high)}（{ms_to_date(hi.open_time)}） / {pct(price / hi.high - 1)} | {f.tag('S2', 'S1')} |")
            add(f"| 近 {n} 日低点 / 距离 | {usd(lo.low)}（{ms_to_date(lo.open_time)}） / {pct(price / lo.low - 1)} | {f.tag('S2', 'S1')} |")
    else:
        add(f"| 距近期高点、低点的距离 | {f.reason('S2')} | {f.tag('S2')} |")
    add("")
    add("以上均为【事实】。日线按 UTC 0 点切分，窗口包含当日未收盘的 K 线。")
    done4 = completed(h4)
    if len(done4) >= 12:
        last6, prev6 = done4[-6:], done4[-12:-6]
        lo_a, lo_b = min(c.low for c in last6), min(c.low for c in prev6)
        hi_a, hi_b = max(c.high for c in last6), max(c.high for c in prev6)
        add("")
        add(f"【事实】4 小时级别：最近 6 根已收盘 K 线（约 24 小时）的最低 {usd(lo_a)}、最高 {usd(hi_a)}；"
            f"再往前 6 根的最低 {usd(lo_b)}、最高 {usd(hi_b)}。低点{'抬高' if lo_a > lo_b else '下移'}，"
            f"高点{'抬高' if hi_a > hi_b else '下移'}。{f.tag('S3')}")
    add("")

    # ---- 2. 关键指标 ------------------------------------------------------
    add("## 2. 关键指标与 7 日均值对比")
    add("")
    add("| 指标 | 当前值 | 7 日均值 | 当前相对均值 | 来源与获取时间 |")
    add("|---|---|---|---|---|")

    funding = fut.get("funding")
    if funding:
        wk = series_since(funding, now_ms, 7, "fundingTime")
        avg = safe_mean(float(x["fundingRate"]) for x in wk)
        last = float(funding[-1]["fundingRate"])
        diff = f"{(last - avg) * 100:+.4f} 个百分点" if avg is not None else "—"
        add(f"| 资金费率（最近一次已结算，{clock.fmt_ms(int(funding[-1]['fundingTime']))}） | {last * 100:+.4f}% | "
            f"{'—' if avg is None else f'{avg * 100:+.4f}%'}（{len(wk)} 次结算） | {diff} | {f.tag('F2')} |")
    else:
        add(f"| 资金费率（已结算） | {f.reason('F2')} | — | — | {f.tag('F2')} |")
    if prem and prem.get("lastFundingRate") not in (None, ""):
        add(f"| 资金费率（当期预测，下次结算 {clock.fmt_ms(int(prem['nextFundingTime']))}） | "
            f"{float(prem['lastFundingRate']) * 100:+.4f}% | — | — | {f.tag('F1')} |")
    else:
        add(f"| 资金费率（当期预测） | {f.reason('F1')} | — | — | {f.tag('F1')} |")

    oi_hist, oi_now = fut.get("oi_hist"), fut.get("oi")
    if oi_hist:
        wk = series_since(oi_hist, now_ms, 7)
        avg = safe_mean(float(r["sumOpenInterest"]) for r in wk)
        cur = float(oi_now["openInterest"]) if oi_now else float(wk[-1]["sumOpenInterest"])
        val = float(wk[-1]["sumOpenInterestValue"])
        add(f"| 未平仓量（永续） | {usd(cur, 0)} BTC（名义约 {val / 1e9:,.2f} 十亿美元） | {usd(avg, 0)} BTC | "
            f"{pct(rel(cur, avg))} | {f.tag('F3', 'F4')} |")
    else:
        add(f"| 未平仓量（永续） | {f.reason('F4')} | — | — | {f.tag('F3', 'F4')} |")

    ls = fut.get("ls")
    if ls:
        wk = series_since(ls, now_ms, 7)
        avg = safe_mean(float(r["longShortRatio"]) for r in wk)
        cur_row = ls[-1]
        cur = float(cur_row["longShortRatio"])
        add(f"| 多空账户比（全市场账户数） | {cur:.3f}（多 {float(cur_row['longAccount']):.1%} / 空 {float(cur_row['shortAccount']):.1%}） | "
            f"{'—' if avg is None else f'{avg:.3f}'} | {pct(rel(cur, avg))} | {f.tag('F5')} |")
    else:
        add(f"| 多空账户比 | {f.reason('F5')} | — | — | {f.tag('F5')} |")

    done = completed(daily)
    if ticker and len(done) >= 7:
        v24 = float(ticker["volume"])
        avg = mean(c.volume for c in done[-7:])
        add(f"| 现货成交量（滚动 24 小时） | {usd(v24, 0)} BTC | {usd(avg, 0)} BTC（最近 7 根已收盘日线） | "
            f"{pct(rel(v24, avg))} | {f.tag('S1', 'S2')} |")
    else:
        add(f"| 现货成交量 | {f.reason('S2')} | — | — | {f.tag('S1', 'S2')} |")
    fdone = completed(fut.get("daily"))
    if len(fdone) >= 8:
        last_d = fdone[-1]
        avg = mean(c.volume for c in fdone[-8:-1])
        add(f"| 永续成交量（最近一根已收盘日线 {ms_to_date(last_d.open_time)}） | {usd(last_d.volume, 0)} BTC | "
            f"{usd(avg, 0)} BTC（此前 7 日） | {pct(rel(last_d.volume, avg))} | {f.tag('F7')} |")
    else:
        add(f"| 永续成交量 | {f.reason('F7')} | — | — | {f.tag('F7')} |")

    taker = fut.get("taker")
    if taker:
        d1, wk = series_since(taker, now_ms, 1), series_since(taker, now_ms, 7)
        buy, sell = sum(float(r["buyVol"]) for r in d1), sum(float(r["sellVol"]) for r in d1)
        wbuy, wsell = sum(float(r["buyVol"]) for r in wk), sum(float(r["sellVol"]) for r in wk)
        cur, avg = (buy / sell if sell else None), (wbuy / wsell if wsell else None)
        add(f"| 永续主动买卖量比（近 24 小时，买/卖） | {'—' if cur is None else f'{cur:.3f}'}"
            f"（买 {usd(buy, 0)} / 卖 {usd(sell, 0)} BTC） | {'—' if avg is None else f'{avg:.3f}'}（7 日合计口径） | "
            f"{pct(rel(cur, avg))} | {f.tag('F6')} |")
    else:
        add(f"| 永续主动买卖量比 | {f.reason('F6')} | — | — | {f.tag('F6')} |")
    if daily and len(done) >= 7:
        today = daily[-1]
        cur = today.taker_buy_share
        avg = safe_mean(c.taker_buy_share for c in done[-7:])
        label = "当日未收盘" if not today.closed else "最近一根日线"
        add(f"| 现货主动买入占比（{label}，补充） | {'—' if cur is None else f'{cur:.1%}'} | "
            f"{'—' if avg is None else f'{avg:.1%}'} | "
            f"{'—' if cur is None or avg is None else f'{(cur - avg) * 100:+.1f} 个百分点'} | {f.tag('S2')} |")

    if fng:
        cur = fng[0]
        prev = fng[1:8]
        avg = safe_mean(x["value"] for x in prev)
        label = FNG_LABELS.get(cur["label"], cur["label"])
        avg_s = "—" if avg is None else f"{avg:.1f}"
        diff_s = "—" if avg is None else f"{cur['value'] - avg:+.1f} 点"
        add(f"| 恐惧贪婪指数（{cur['time']:%m-%d} 值） | {cur['value']}（{label}） | "
            f"{avg_s}（此前 {len(prev)} 日） | {diff_s} | {f.tag('G1')} |")
    else:
        add(f"| 恐惧贪婪指数 | {f.reason('G1')} | — | — | {f.tag('G1')} |")

    if etf and etf["days"]:
        days = etf["days"]
        cur = days[-1]
        prev = days[-8:-1]
        avg = safe_mean(d["flow"] for d in prev)
        add(f"| 美国现货 BTC ETF 净流量（{cur['date']:%m-%d} 交易日） | {money_m(cur['flow'])} | "
            f"{money_m(avg)}（此前 {len(prev)} 个交易日） | — | {f.tag('E1')} |")
    else:
        add(f"| 美国现货 BTC ETF 净流量 | {f.reason('E1')} | — | — | {f.tag('E1')} |")
    add("")
    add("以上均为【事实】。「7 日均值」的口径写在各行括号内。恐惧贪婪指数来源："
        "[Alternative.me](https://alternative.me/crypto/fear-and-greed-index/)。"
        f"ETF 数据来源：[The Commoner Bitcoin ETF Tracker by TFTC]({ETF_PAGE})（CC BY 4.0，上游见文末），"
        "属于二手汇总而非发行方原始披露。")
    add("")

    # ---- 3. 止跌信号 ------------------------------------------------------
    add("## 3. 止跌信号检查表")
    add("")
    add("| # | 信号 | 状态 | 来源与获取时间 |")
    add("|---|---|---|---|")
    for i, s in enumerate(signals, 1):
        mark = {"出现": "✅ 出现", "未出现": "❌ 未出现"}.get(s.status, f"⚠️ 无法判定（{FAIL}）")
        add(f"| {i} | {s.name} | {mark} | {s.tags} |")
    add("")
    for i, s in enumerate(signals, 1):
        add(f"**{i}. {s.name}：{s.status}**")
        add(f"- 【推断】判定规则：{s.rule}")
        for fact in s.facts:
            add(f"- 【事实】{fact}")
        add("")
    add("说明：状态栏是把【事实】代入固定规则后的【推断】。数据源失败的项目标「无法判定」，既不算出现也不算未出现。")
    add("")

    # ---- 4. 过去 24 小时消息 ---------------------------------------------
    add(f"## 4. 过去 {NEWS_WINDOW_HOURS} 小时的重要消息")
    add("")
    cutoff = clock.now - timedelta(hours=NEWS_WINDOW_HOURS)
    groups = [("币安官方公告", "B1", anns), ("美联储新闻稿", "N1", fed_news), ("SEC 新闻稿", "N2", sec_news)]
    for title, sid, items in groups:
        add(f"### {title} {f.tag(sid)}")
        if sid == "B1":
            add(f"公告页：{BINANCE_ANN_PAGE}　收录分类：{'、'.join(ANN_CATALOGS.values())}")
        if items is None:
            add(f"- {f.reason(sid)}")
            add("")
            continue
        recent = sorted((x for x in items if x["time"] >= cutoff), key=lambda x: x["time"], reverse=True)
        if not recent:
            newest = max(items, key=lambda x: x["time"], default=None)
            add(f"- 过去 {NEWS_WINDOW_HOURS} 小时内无新发布。"
                + (f"该来源最近一条发布于 {clock.fmt(newest['time'])}。" if newest else ""))
        for x in recent[:20]:
            flag = "（标题含加密/货币政策关键词）" if sid != "B1" and CRYPTO_KEYWORDS.search(x["title"]) else ""
            cat = f"〔{x['category']}〕" if x["category"] else ""
            add(f"- {clock.fmt(x['time'])} {cat}[{x['title']}]({x['link']}){flag}")
        add("")
    add("以上均为【事实】：标题保留原文，时间为来源给出的发布时间。脚本没有判断消息的利好或利空。")
    add("")

    # ---- 5. 未来 7 天 -----------------------------------------------------
    add(f"## 5. 未来 {EVENT_WINDOW_DAYS} 天需要关注的事件")
    add("")
    start, end = clock.now, clock.now + timedelta(days=EVENT_WINDOW_DAYS)

    def in_window(e) -> bool:
        if e["when"] is not None:
            return start <= e["when"] <= end
        return today_et <= e["date"] <= (today_et + timedelta(days=EVENT_WINDOW_DAYS))

    def ev_line(e) -> str:
        when = clock.fmt(e["when"]) if e["when"] is not None else f"{e['date']:%Y-%m-%d}（美东日期，时间未注明）"
        return f"- {when}　{e['title']}　[来源]({e['link']})"

    def sort_key(e):
        return e["when"] or datetime(e["date"].year, e["date"].month, e["date"].day, tzinfo=timezone.utc)

    add(f"### 美国 CPI、非农 {f.tag('M1')}")
    if bls is None:
        add(f"- {f.reason('M1')}")
        note = f.sources["M1"].note if "M1" in f.sources else ""
        if note:
            add(f"- {note}")
        add(f"- 可人工核对官方日程页：{BLS_SCHEDULE_PAGE}")
    else:
        hits = sorted((e for e in bls if in_window(e)), key=sort_key)
        for e in hits:
            add(ev_line(e))
        if not hits:
            add(f"- 未来 {EVENT_WINDOW_DAYS} 天内没有 CPI 或非农发布。")
            for kw in ("CPI", "非农"):
                nxt = sorted((e for e in bls if kw in e["title"] and sort_key(e) > end), key=sort_key)
                if nxt:
                    add(f"  - 窗口外的下一次：{ev_line(nxt[0])[2:]}")
    add("")
    add(f"### 美联储 {f.tag('C1')}")
    if fed_cal is None:
        add(f"- {f.reason('C1')}")
    else:
        hits = sorted((e for e in fed_cal if in_window(e)), key=sort_key)
        key_types = ("FOMC", "Beige", "Testimony")
        major = [e for e in hits if e["type"] in key_types]
        minor = [e for e in hits if e["type"] not in key_types]
        if any(e["is_meeting"] for e in major):
            add("- **窗口内有 FOMC 议息会议。**")
        elif not major:
            add(f"- 未来 {EVENT_WINDOW_DAYS} 天内没有 FOMC 议息会议、纪要、褐皮书或国会听证。")
        for e in major:
            add(ev_line(e))
        if minor:
            add(f"- 官员讲话与其他日程（{len(minor)} 项）：")
            for e in minor[:15]:
                add("  " + ev_line(e))
        nxt = sorted((e for e in fed_cal if e["is_meeting"] and sort_key(e) > end), key=sort_key)
        if nxt:
            add(f"- 窗口外的下一次议息会议：{ev_line(nxt[0])[2:]}")
    add("")
    add("以上均为【事实】，取自官方日程；官方可能调整日期，以来源页面为准。")
    add("")

    # ---- 数据源状态 -------------------------------------------------------
    add("## 数据源状态")
    add("")
    add("| 编号 | 数据源 | 状态 | 获取时间 | 地址 |")
    add("|---|---|---|---|---|")
    for s in f.sources.values():
        status = "成功" if s.ok else f"{FAIL}：{s.error}"
        if s.note:
            status += f"<br>{s.note}"
        t = f"{s.fetched_at:%Y-%m-%d %H:%M:%S} UTC" if s.fetched_at else "—"
        add(f"| {s.sid} | {s.name} | {status} | {t} | {s.url} |")
    add("")
    add("本脚本只发送 GET 请求，不携带任何 API Key，不包含下单、划转等写操作。")
    add("")
    return "\n".join(L)


# --------------------------------------------------------------------------- #
def run(tz_name: str = "Asia/Shanghai") -> str:
    clock = Clock(tz_name)
    f = Fetcher()
    spot = fetch_spot(f, clock.now_ms)
    fut = fetch_futures(f, clock.now_ms)
    anns = fetch_announcements(f)
    etf = fetch_etf(f)
    fng = fetch_fng(f)
    bls = fetch_bls(f)
    fed_cal = fetch_fed_calendar(f)
    fed_news = fetch_rss(f, "N1", "美联储新闻稿 RSS", FED_PRESS_RSS, "美联储")
    sec_news = fetch_rss(f, "N2", "SEC 新闻稿 RSS", SEC_PRESS_RSS, "SEC")
    return build_report(clock, f, spot, fut, fng, etf, anns, fed_news, sec_news, fed_cal, bls)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成一份 BTC 行情监控中文简报（只读，不做任何交易操作）")
    ap.add_argument("--tz", default="Asia/Shanghai", help="简报中附带显示的本地时区，默认 Asia/Shanghai")
    ap.add_argument("--out-dir", default="reports", help="简报保存目录，默认 reports/")
    ap.add_argument("--no-save", action="store_true", help="只打印到终端，不写文件")
    args = ap.parse_args(argv)

    report = run(args.tz)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(report)
    if not args.no_save:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"btc_brief_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}Z.md"
        path.write_text(report, encoding="utf-8")
        print(f"\n（已保存到 {path}）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
