#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模拟单记录与结算（只读，不下单）

  python paper_trade.py open  --side short --leverage 10 --margin 10 --hours 72 BTCUSDT ETHUSDT
  python paper_trade.py check paper_trades/<记录文件>.json

open  读取币安现货当前价格作为入场价，写一份 JSON 记录。
check 读取入场到现在（或到期时刻）的 1 分钟 K 线，计算盈亏、途中最大不利波动，以及是否触及强平线。

只访问币安官方"仅行情"域名的公开接口，不需要 API Key，不含任何下单、划转代码。
用现货价格近似永续合约价格；强平线、手续费、资金费率都是写在记录里的假设，见 README。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE = "https://data-api.binance.vision"
HEADERS = {"User-Agent": "btc-brief/1.0 (read-only research script)"}
TIMEOUT = 20
MIN = 60_000


def get(path: str, params: dict):
    r = requests.get(BASE + path, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def to_ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def liquidation_move(leverage: float, maint_margin_rate: float) -> float:
    """逐仓强平大致对应的不利价格变动比例（近似）：做空时为价格上涨的幅度。"""
    return (1 + 1 / leverage) / (1 + maint_margin_rate) - 1


def settle(side: str, entry: float, leverage: float, margin: float, fee_rate: float, liq_move: float,
           candles: list[tuple[float, float, float]]) -> dict:
    """candles 为入场后的 (最高, 最低, 收盘) 序列，按时间先后。返回结算结果。"""
    sign = -1.0 if side == "short" else 1.0
    notional = margin * leverage
    worst, liquidated_at = 0.0, None
    for i, (high, low, _close) in enumerate(candles):
        adverse = (high / entry - 1) if side == "short" else (1 - low / entry)
        worst = max(worst, adverse)
        if liquidated_at is None and adverse >= liq_move:
            liquidated_at = i
    last = candles[-1][2] if candles else entry
    move = last / entry - 1
    fees = notional * fee_rate * 2
    pnl = -margin if liquidated_at is not None else sign * notional * move - fees
    return {"last_price": last, "price_move": move, "worst_adverse_move": worst,
            "liquidated_index": liquidated_at, "fees": 0.0 if liquidated_at is not None else fees,
            "pnl": pnl, "return_on_margin": pnl / margin}


def fetch_minutes(symbol: str, start_ms: int, end_ms: int) -> list[list]:
    out, t = [], start_ms
    while t < end_ms:
        batch = get("/api/v3/klines", {"symbol": symbol, "interval": "1m", "startTime": t,
                                       "endTime": end_ms - 1, "limit": 1000})
        if not batch:
            break
        out += batch
        t = batch[-1][0] + MIN
    return out


def cmd_open(a) -> int:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    legs = []
    for sym in a.symbols:
        px = float(get("/api/v3/ticker/price", {"symbol": sym})["price"])
        legs.append({"symbol": sym, "entry_price": px,
                     "entry_price_source": f"{BASE}/api/v3/ticker/price?symbol={sym}（现货最新成交价）"})
    rec = {
        "type": "模拟单（未实际下单）",
        "side": a.side, "leverage": a.leverage, "margin_usd_per_leg": a.margin,
        "notional_usd_per_leg": a.margin * a.leverage,
        "opened_at": now.isoformat(), "planned_close_at": (now + timedelta(hours=a.hours)).isoformat(),
        "hold_hours": a.hours,
        "assumptions": {
            "price_proxy": "用币安现货价格近似 U 本位永续价格（本环境访问不了合约接口）",
            "taker_fee_rate_per_side": a.fee,
            "maintenance_margin_rate": a.mmr,
            "liquidation_adverse_move": round(liquidation_move(a.leverage, a.mmr), 5),
            "funding": "未计入。72 小时内有 9 次资金费率结算，方向和大小取决于当时费率",
            "note": "手续费率、维持保证金率是假设值，以账户实际费率和下单面板显示的强平价为准",
        },
        "legs": legs,
    }
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{now:%Y%m%d_%H%M%S}Z_{a.side}_{'_'.join(s.lower() for s in a.symbols)}.json"
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    print(f"\n已记录到 {path}", file=sys.stderr)
    return 0


def cmd_check(a) -> int:
    rec = json.loads(Path(a.record).read_text(encoding="utf-8"))
    start, end = to_ms(rec["opened_at"]), to_ms(rec["planned_close_at"])
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    until = min(now, end)
    done = now >= end
    asm = rec["assumptions"]
    print(f"模拟单：{rec['leverage']} 倍{'做空' if rec['side'] == 'short' else '做多'}，每笔保证金 "
          f"{rec['margin_usd_per_leg']} 美元（名义 {rec['notional_usd_per_leg']} 美元）")
    print(f"开仓 {iso(start)}　计划平仓 {iso(end)}　"
          f"{'已到期，按到期时刻结算' if done else f'未到期，按当前时刻估值（已持有 {(now - start) / 3600_000:.1f} 小时）'}")
    total = 0.0
    for leg in rec["legs"]:
        ks = fetch_minutes(leg["symbol"], start, until)
        candles = [(float(k[2]), float(k[3]), float(k[4])) for k in ks]
        r = settle(rec["side"], leg["entry_price"], rec["leverage"], rec["margin_usd_per_leg"],
                   asm["taker_fee_rate_per_side"], asm["liquidation_adverse_move"], candles)
        total += r["pnl"]
        print(f"\n{leg['symbol']}：入场 {leg['entry_price']:,.2f} → "
              f"{'到期价' if done else '现价'} {r['last_price']:,.2f}（{r['price_move']:+.2%}），"
              f"数据截至 {iso(ks[-1][6]) if ks else '—'}")
        print(f"  途中最大不利波动 {r['worst_adverse_move']:+.2%}（强平线约 {asm['liquidation_adverse_move']:+.2%}）")
        if r["liquidated_index"] is not None:
            print(f"  已触及强平线（{iso(ks[r['liquidated_index']][0])}）：按亏完保证金计，盈亏 {r['pnl']:+.2f} 美元")
        else:
            print(f"  盈亏 {r['pnl']:+.2f} 美元（已扣假设手续费 {r['fees']:.2f}，未计资金费率），"
                  f"相对保证金 {r['return_on_margin']:+.1%}")
    print(f"\n合计盈亏 {total:+.2f} 美元（{'最终' if done else '未到期，仅为当前估值'}）")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="模拟单记录与结算（只读，不下单）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("open", help="按当前价格记录一笔模拟单")
    o.add_argument("symbols", nargs="+")
    o.add_argument("--side", choices=["short", "long"], required=True)
    o.add_argument("--leverage", type=float, default=10)
    o.add_argument("--margin", type=float, default=10, help="每个交易对的保证金（美元）")
    o.add_argument("--hours", type=float, default=72)
    o.add_argument("--fee", type=float, default=0.0005, help="假设的单边吃单费率，默认 0.05%%")
    o.add_argument("--mmr", type=float, default=0.005, help="假设的维持保证金率，默认 0.5%%")
    o.add_argument("--out-dir", default="paper_trades")
    o.set_defaults(func=cmd_open)
    c = sub.add_parser("check", help="结算或估值一笔已记录的模拟单")
    c.add_argument("record")
    c.set_defaults(func=cmd_check)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
