# -*- coding: utf-8 -*-
"""离线测试：信号规则、解析器，以及用文档格式的模拟响应跑通整份简报。不访问网络。

运行： python -m pytest -q
"""
import io
import json
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import btc_brief as bb  # noqa: E402

DAY = 86400_000
NOW = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)
TODAY_OPEN = NOW_MS - NOW_MS % DAY


def candle(i_from_today, o, h, l, c, vol=100.0, closed=True):
    ot = TODAY_OPEN - i_from_today * DAY
    return bb.Candle(ot, o, h, l, c, vol, ot + DAY - 1, vol * c, 1000, vol / 2, closed)


def flat_history(n=40, price=100.0, vol=100.0):
    """n 根已收盘的平稳日线（最早的在前），不含当日。"""
    return [candle(i, price, price + 2, price - 2, price, vol) for i in range(n, 0, -1)]


# ---- 放量长下影线 ---------------------------------------------------------
def test_hammer_detected():
    d = flat_history()
    d[-1] = candle(1, 100, 101, 90, 99.5, vol=200)   # 下影 9.5，实体 0.5，振幅 11，量比 2
    assert bb.sig_hammer(d).status == "出现"


def test_hammer_needs_volume():
    d = flat_history()
    d[-1] = candle(1, 100, 101, 90, 99.5, vol=120)   # 形态满足但量比只有 1.2
    assert bb.sig_hammer(d).status == "未出现"


def test_hammer_ignores_unclosed_candle():
    d = flat_history()
    d.append(candle(0, 100, 101, 90, 99.5, vol=300, closed=False))
    assert bb.sig_hammer(d).status == "未出现"


def test_hammer_no_data():
    assert bb.sig_hammer(None).status == "无法判定"


# ---- 不创新低 -------------------------------------------------------------
def falling_then(tail):
    d = flat_history(40)
    return d[:-len(tail)] + tail if tail else d


def test_no_new_low_when_today_breaks():
    d = flat_history()
    d.append(candle(0, 100, 100, 90, 91, closed=False))
    s = bb.sig_no_new_low(d)
    assert s.status == "未出现"
    assert any("已创新低" in f for f in s.facts)


def test_no_new_low_after_two_quiet_days():
    d = flat_history()
    d[-3] = candle(3, 100, 100, 80, 82)              # 3 天前创新低
    d[-2] = candle(2, 82, 86, 81, 85)
    d[-1] = candle(1, 85, 88, 83, 87)
    d.append(candle(0, 87, 89, 85, 88, closed=False))
    assert bb.sig_no_new_low(d).status == "出现"


def test_no_new_low_only_one_quiet_day():
    d = flat_history()
    d[-2] = candle(2, 100, 100, 80, 82)              # 2 天前创新低，只隔了 1 根已收盘日线
    d[-1] = candle(1, 82, 86, 81, 85)
    d.append(candle(0, 85, 88, 83, 87, closed=False))
    assert bb.sig_no_new_low(d).status == "未出现"


# ---- 资金费率 -------------------------------------------------------------
def test_funding():
    hist = [{"fundingRate": "0.0001", "fundingTime": NOW_MS - 8 * 3600_000 * i} for i in range(5, 0, -1)]
    assert bb.sig_funding({"lastFundingRate": "0.00005"}, hist).status == "未出现"
    assert bb.sig_funding({"lastFundingRate": "-0.00005"}, hist).status == "出现"
    hist[-1]["fundingRate"] = "-0.0002"
    assert bb.sig_funding({"lastFundingRate": "0.00005"}, hist).status == "出现"
    assert bb.sig_funding(None, None).status == "无法判定"


# ---- 未平仓量 -------------------------------------------------------------
def oi_series(values):
    n = len(values)
    return [{"sumOpenInterest": str(v), "sumOpenInterestValue": str(v * 65000),
             "timestamp": NOW_MS - (n - 1 - i) * 3600_000} for i, v in enumerate(values)]


def test_oi_drop_from_peak():
    hist = oi_series([100000] * 100 + [88000] * 60)
    assert bb.sig_oi({"openInterest": "88000"}, hist, NOW_MS).status == "出现"


def test_oi_stable():
    hist = oi_series([100000] * 160)
    assert bb.sig_oi({"openInterest": "99000"}, hist, NOW_MS).status == "未出现"


def test_oi_24h_drop():
    hist = oi_series([100000] * 150 + [94000] * 10)
    assert bb.sig_oi({"openInterest": "94000"}, hist, NOW_MS).status == "出现"


def test_oi_missing():
    assert bb.sig_oi(None, None, NOW_MS).status == "无法判定"


# ---- ETF ------------------------------------------------------------------
def etf(flows, last=date(2026, 11, 13)):
    days, d = [], last
    for v in reversed(flows):
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        days.append({"date": d, "flow": v * 1e6})
        d -= timedelta(days=1)
    return {"days": list(reversed(days))}


def test_etf_turn():
    assert bb.sig_etf(etf([-100, -200, -50, 80]), date(2026, 11, 14)).status == "出现"
    assert bb.sig_etf(etf([-100, -200, 50, 80]), date(2026, 11, 14)).status == "出现"


def test_etf_still_outflow_or_old_inflow():
    assert bb.sig_etf(etf([50, -100, -200, -50]), date(2026, 11, 14)).status == "未出现"
    assert bb.sig_etf(etf([-10, 5, 5, 5, 5]), date(2026, 11, 14)).status == "未出现"   # 转折已超过 3 个交易日


def test_etf_stale_warning():
    s = bb.sig_etf(etf([-100, -200], last=date(2026, 11, 11)), date(2026, 11, 14))
    assert any("11-12、11-13" in f for f in s.facts)
    assert bb.sig_etf(None, date(2026, 11, 14)).status == "无法判定"


# ---- 阶段归类 -------------------------------------------------------------
def decline(low_days_ago, last_price):
    d = [candle(i, 120, 122, 118, 120) for i in range(40, 10, -1)]
    d += [candle(i, 110, 112, 100, 105) for i in range(10, 0, -1)]
    d[-low_days_ago] = candle(low_days_ago, 100, 101, 90, 92)
    d.append(candle(0, last_price, last_price + 1, last_price - 1, last_price, closed=False))
    return d


def test_stage_labels():
    assert bb.infer_stage(decline(1, 93), 93, []).label == "下跌"
    assert bb.infer_stage(decline(4, 92), 92, []).label == "止跌"
    assert bb.infer_stage(decline(4, 99), 99, []).label == "反弹"
    near_high = flat_history(40) + [candle(0, 100, 102, 99, 101, closed=False)]
    assert bb.infer_stage(near_high, 101, []).label.startswith("不适用")
    assert bb.infer_stage(None, None, []).label == "无法判定"


# ---- iCalendar ------------------------------------------------------------
ICS = """BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
DTSTART;TZID=US-Eastern:20261210T083000\r
SUMMARY:Consumer Price Index\r
END:VEVENT\r
BEGIN:VEVENT\r
DTSTART:20261204T133000Z\r
SUMMARY:Employment\r
  Situation\r
END:VEVENT\r
BEGIN:VEVENT\r
DTSTART;VALUE=DATE:20261215\r
SUMMARY:Producer Price Index\r
END:VEVENT\r
END:VCALENDAR\r
"""


def test_parse_ics():
    ev = bb.parse_ics(ICS)
    assert [e["summary"] for e in ev] == ["Consumer Price Index", "Employment Situation", "Producer Price Index"]
    assert ev[0]["dtstart"].astimezone(timezone.utc) == datetime(2026, 12, 10, 13, 30, tzinfo=timezone.utc)
    assert ev[1]["dtstart"] == datetime(2026, 12, 4, 13, 30, tzinfo=timezone.utc)
    assert ev[2]["has_time"] is False and ev[2]["date"] == date(2026, 12, 15)


# ---- 用模拟响应跑通整份简报 ----------------------------------------------
class FakeResp:
    def __init__(self, status=200, body=b""):
        self.status_code, self.content = status, body
        self.text = body.decode("utf-8", errors="replace")


def kl(c: bb.Candle):
    return [c.open_time, str(c.open), str(c.high), str(c.low), str(c.close), str(c.volume), c.close_time,
            str(c.quote_volume), c.trades, str(c.taker_buy_base), "0", "0"]


class FakeSession:
    """按路径返回与官方文档字段一致的模拟数据；fapi_status 用来模拟 451。"""

    def __init__(self, fapi_status=200, archive_days=()):
        self.headers, self.fapi_status, self.calls, self.sent_headers = {}, fapi_status, [], []
        self.archive_days = set(archive_days)

    def archive(self, url):
        """模拟 data.binance.vision：有的日期返回 zip，没有的返回 404。"""
        day = url.rsplit("-", 3)[-3:]
        day = "-".join(day).replace(".zip", "")
        if day not in self.archive_days:
            return FakeResp(404, b"<Error><Code>NoSuchKey</Code></Error>")
        d0 = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)
        if "/metrics/" in url:
            oi = 86000 if day == max(self.archive_days) else 100000
            lines = ["create_time,symbol,sum_open_interest,sum_open_interest_value,"
                     "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,"
                     "count_long_short_ratio,sum_taker_long_short_vol_ratio"]
            for k in range(288):
                ts = datetime.fromtimestamp((d0 + k * 300_000) / 1000, timezone.utc)
                lines.append(f"{ts:%Y-%m-%d %H:%M:%S},BTCUSDT,{oi},{oi * 93},2.5,2.1,3.0,0.9")
            name, body = f"BTCUSDT-metrics-{day}.csv", "\n".join(lines)
        else:
            head = "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore"
            name, body = f"BTCUSDT-1d-{day}.csv", f"{head}\n{d0},100,102,98,99,1000,{d0 + DAY - 1},99000,5000,450,44550,0"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(name, body)
        return FakeResp(200, buf.getvalue())

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append(url)
        self.sent_headers.append((url, headers or {}))
        daily = decline(1, 93)
        hours = [NOW_MS - i * 3600_000 for i in range(199, -1, -1)]
        if "data.binance.vision" in url:
            return self.archive(url)
        if "fapi.binance.com" in url and self.fapi_status != 200:
            return FakeResp(self.fapi_status, b'{"code":0,"msg":"restricted location"}')
        routes = {
            "/api/v3/ticker/24hr": {"lastPrice": "93", "priceChangePercent": "-4.2", "highPrice": "101",
                                    "lowPrice": "90", "volume": "150"},
            "/api/v3/klines": [kl(c) for c in daily],
            "/fapi/v1/klines": [kl(c) for c in daily],
            "/fapi/v1/premiumIndex": {"symbol": "BTCUSDT", "markPrice": "92.9", "indexPrice": "93",
                                      "lastFundingRate": "-0.00012", "nextFundingTime": NOW_MS + 3600_000,
                                      "time": NOW_MS},
            "/fapi/v1/fundingRate": [{"symbol": "BTCUSDT", "fundingRate": "0.0001",
                                      "fundingTime": NOW_MS - 8 * 3600_000 * i, "markPrice": "95"}
                                     for i in range(30, 0, -1)],
            "/fapi/v1/openInterest": {"openInterest": "85000", "symbol": "BTCUSDT", "time": NOW_MS},
            "/futures/data/openInterestHist": [{"symbol": "BTCUSDT", "sumOpenInterest": "100000" if i < 150 else "86000",
                                                "sumOpenInterestValue": "9300000", "timestamp": t}
                                               for i, t in enumerate(hours)],
            "/futures/data/globalLongShortAccountRatio": [{"symbol": "BTCUSDT", "longShortRatio": "1.8",
                                                           "longAccount": "0.6429", "shortAccount": "0.3571",
                                                           "timestamp": t} for t in hours],
            "/futures/data/takerlongshortRatio": [{"buySellRatio": "0.9", "buyVol": "90", "sellVol": "100",
                                                   "timestamp": t} for t in hours],
        }
        for path, payload in routes.items():
            if url.endswith(path):
                return FakeResp(200, json.dumps(payload).encode())
        return FakeResp(403, b"<html><title>Access Denied</title></html>")


def render(fapi_status=200, archive_days=None):
    clock = bb.Clock(now=NOW)
    f = bb.Fetcher(session=FakeSession(fapi_status, archive_days or ()))
    spot = bb.fetch_spot(f, clock.now_ms)
    fut = bb.fetch_futures(f, clock.now_ms)
    if archive_days is not None:
        fut["archive"] = bb.fetch_futures_archive(f, clock.now)
    report = bb.build_report(clock, f, spot, fut, bb.fetch_fng(f), bb.fetch_etf(f), bb.fetch_announcements(f),
                             None, None, bb.fetch_fed_calendar(f), bb.fetch_bls(f))
    return report, f


def test_report_with_futures_data():
    report, f = render()
    assert all(f.sources[s].ok for s in ("S1", "S2", "S3", "F1", "F2", "F3", "F4", "F5", "F6", "F7"))
    assert "| 3 | 资金费率转负 | ✅ 出现 |" in report
    assert "| 4 | 未平仓量大幅下降（杠杆出清） | ✅ 出现 |" in report
    assert "【推断】当前阶段归类：下跌" in report
    assert "1.800（多 64.3% / 空 35.7%）" in report


def test_report_marks_failures_without_inventing_data():
    report, f = render(fapi_status=451)
    assert not f.sources["F1"].ok and "451" in f.sources["F1"].error
    assert "| 3 | 资金费率转负 | ⚠️ 无法判定（获取失败） |" in report
    assert "| 4 | 未平仓量大幅下降（杠杆出清） | ⚠️ 无法判定（获取失败） |" in report
    # 被拒绝后不再对同一主机重复请求
    assert sum("fapi.binance.com" in u for u in f.session.calls) == 1
    # 其余来源（ETF、恐惧贪婪、公告、日历）在本测试里也都是失败，应全部如实标出
    for sid in ("E1", "G1", "B1", "C1", "M1"):
        assert not f.sources[sid].ok
    assert report.count("获取失败") >= 10


def test_only_get_requests_and_no_credentials():
    src = Path(bb.__file__).read_text(encoding="utf-8")
    for banned in (".post(", ".put(", ".delete(", "X-MBX-APIKEY", "signature=", "/order", "/transfer"):
        assert banned not in src


def test_contact_is_sent_only_to_bls(monkeypatch):
    monkeypatch.setenv("BTC_BRIEF_CONTACT", "contact-placeholder")
    _, f = render()
    for url, headers in f.session.sent_headers:
        has_contact = "contact-placeholder" in headers.get("User-Agent", "")
        assert has_contact == ("www.bls.gov" in url), url


# ---- 归档回退 -------------------------------------------------------------
def last_days(n, skip=0):
    return [(NOW.date() - timedelta(days=k)).isoformat() for k in range(1 + skip, n + 1 + skip)]


def test_archive_fallback_fills_oi_but_not_funding():
    report, f = render(fapi_status=451, archive_days=last_days(8))
    assert f.sources["A1"].ok and f.sources["A2"].ok
    assert "T-1 归档，非实时" in f.sources["A1"].note
    # 未平仓量：T-1 当日 86000，此前 100000 → 较峰值 -14%，信号出现且带归档限定语
    assert "| 4 | 未平仓量大幅下降（杠杆出清） | ✅ 出现（按 T-1 归档数据） |" in report
    assert "未平仓量（永续，**归档 T-1**，截至 2026-11-13 23:55 UTC" in report
    assert "3.000（折算多 75.0% / 空 25.0%）" in report
    assert "0.818（买 450 / 卖 550 BTC）" in report
    # 资金费率归档补不了，必须仍是失败
    assert "| 3 | 资金费率转负 | ⚠️ 无法判定（获取失败） |" in report
    assert not f.sources["F2"].ok


def test_archive_too_old_is_rejected():
    # 最新只到 3 天前：超过 48 小时，不采用
    report, f = render(fapi_status=451, archive_days=last_days(6, skip=2))
    assert not f.sources["A1"].ok and "不采用" in f.sources["A1"].error
    assert "| 4 | 未平仓量大幅下降（杠杆出清） | ⚠️ 无法判定（获取失败） |" in report
    assert "归档 T-1" not in report.split("## 2.")[1].split("## 3.")[0]


def test_archive_missing_latest_day_is_disclosed():
    _, f2 = render(fapi_status=451, archive_days=last_days(7, skip=1))   # T-1 文件尚未发布
    assert f2.sources["A1"].ok and "未取到：11-13" in f2.sources["A1"].note
    assert "数据截至 2026-11-12 23:55 UTC" in f2.sources["A1"].note


# ---- 模拟单结算 -----------------------------------------------------------
import paper_trade as pt  # noqa: E402


def test_paper_trade_short_profit_and_loss():
    liq = pt.liquidation_move(10, 0.005)
    assert 0.094 < liq < 0.095
    # 价格跌 5%：10 美元保证金、名义 100 美元 → +5，扣 0.10 手续费
    r = pt.settle("short", 100, 10, 10, 0.0005, liq, [(101, 97, 98), (99, 94, 95)])
    assert abs(r["pnl"] - 4.90) < 1e-9 and r["liquidated_index"] is None
    assert abs(r["worst_adverse_move"] - 0.01) < 1e-9
    # 价格涨 5%：-5 再扣手续费
    r = pt.settle("short", 100, 10, 10, 0.0005, liq, [(106, 100, 105)])
    assert abs(r["pnl"] + 5.10) < 1e-9


def test_paper_trade_liquidation_overrides_final_price():
    liq = pt.liquidation_move(10, 0.005)
    # 途中先涨 10% 触及强平线，之后即使跌回去也按亏完保证金计
    r = pt.settle("short", 100, 10, 10, 0.0005, liq, [(110, 100, 109), (109, 80, 80)])
    assert r["liquidated_index"] == 0 and r["pnl"] == -10


def test_paper_trade_has_no_order_code():
    src = Path(pt.__file__).read_text(encoding="utf-8")
    for banned in (".post(", ".put(", ".delete(", "X-MBX-APIKEY", "signature=", "/fapi/v1/order", "/api/v3/order"):
        assert banned not in src
