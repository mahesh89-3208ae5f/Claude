#!/usr/bin/env python3
"""5 分钟预测记录器(BTC / ETH / BNB):只记录信号,不下单。

用法:  python3 recorder.py
环境变量:
  DASH_PASSWORD  看板密码。不设置时只监听 127.0.0.1。
  HOST / PORT    监听地址和端口(默认 0.0.0.0 / 8787,无密码时强制 127.0.0.1)。
  BINANCE_BASE   行情接口地址(默认 https://data-api.binance.vision)。
  DB_PATH        BTC 的数据库文件(默认 data/recorder.db);其他币种存到同目录的 recorder_<币种>.db。
  SYMBOLS        要记录的币种,逗号分隔(默认 BTCUSDT,ETHUSDT,BNBUSDT),必须在 rules.PROFILES 里有参数。
"""
import base64
import hmac
import json
import os
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import rules

HERE = Path(__file__).resolve().parent
BASE = os.environ.get("BINANCE_BASE", "https://data-api.binance.vision").rstrip("/")
SYMBOLS = [x.strip().upper() for x in os.environ.get("SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT").split(",") if x.strip()]
DB_PATH = Path(os.environ.get("DB_PATH", HERE / "data" / "recorder.db"))
PASSWORD = os.environ.get("DASH_PASSWORD", "")
KEEP_SECONDS = 2400
STALE_AFTER = 3.0


class Market:
    """逐秒行情缓存。秒级 K 线的开盘价和收盘价与回测口径一致。"""

    def __init__(self, symbol):
        self.symbol = symbol
        self.op, self.cl = {}, {}
        self.latest = None
        self.last_ok = 0.0
        self.error = None

    def _get(self, **params):
        q = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{BASE}/api/v3/klines?symbol={self.symbol}&interval=1s&{q}"
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read())

    def _store(self, rows):
        for k in rows:
            sec = k[0] // 1000
            self.op[sec], self.cl[sec] = float(k[1]), float(k[4])
        if rows:
            self.latest = max(self.latest or 0, rows[-1][0] // 1000)

    def update(self):
        gap = time.time() - self.last_ok
        if self.latest is None or gap > 900:
            self.op.clear(); self.cl.clear(); self.latest = None
            rows = self._get(limit=1000)
            self._store(rows)
            first = rows[0][0]
            self._store(self._get(limit=1000, startTime=first - 1000_000, endTime=first - 1000))
        else:
            self._store(self._get(limit=min(1000, max(5, int(gap) + 5))))
        self.last_ok = time.time()
        self.error = None
        cutoff = self.latest - KEEP_SECONDS
        for sec in [s for s in self.cl if s < cutoff]:
            del self.cl[sec]; self.op.pop(sec, None)

    def range_pct(self, end_sec, span=1800):
        vals = [self.cl[s] for s in range(end_sec - span + 1, end_sec + 1) if s in self.cl]
        if len(vals) < rules.MIN_RANGE_SAMPLES:
            return None
        return (max(vals) - min(vals)) / vals[-1] * 100


class Store:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS rounds(
            start_ts INTEGER PRIMARY KEY, open REAL, close REAL, result TEXT);
        CREATE TABLE IF NOT EXISTS evals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_ts INTEGER, cp INTEGER, ts INTEGER,
            open REAL, price REAL, dev_pct REAL, dev_usd REAL,
            side TEXT, signal INTEGER, reason TEXT, row TEXT,
            table_p REAL, max_price REAL, range30 REAL, high_vol INTEGER,
            blocked TEXT, app_price REAL,
            UNIQUE(round_ts, cp));
        """)

    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def x(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur.rowcount

    SIGNALS = """SELECT e.*, r.result, r.close FROM evals e
                 LEFT JOIN rounds r ON r.start_ts = e.round_ts"""

    def settled_signals(self):
        return self.q(self.SIGNALS + """ WHERE e.signal=1 AND e.blocked IS NULL
                      AND r.result IS NOT NULL ORDER BY e.ts""")


class Engine:
    def __init__(self, market, store):
        self.m, self.s = market, store
        self.symbol = market.symbol
        self.profile = rules.PROFILES[market.symbol]
        self.lock = threading.Lock()
        self.done = set((r["round_ts"], r["cp"]) for r in store.q("SELECT round_ts, cp FROM evals"))
        self.settled = set(r["start_ts"] for r in store.q("SELECT start_ts FROM rounds"))

    def tick(self):
        m = self.m
        latest = m.latest
        start = latest // rules.ROUND_SECONDS * rules.ROUND_SECONDS
        self._settle(start)
        if start not in m.op:
            return
        for cp in rules.CHECKPOINTS:
            t = start + cp["elapsed"] - 1          # 检查点前最后一个完整的秒
            if (start, cp["id"]) in self.done or t not in m.cl:
                continue
            if t < latest <= t + rules.SIGNAL_WINDOW:
                self._evaluate(start, cp, t)

    def _settle(self, current_start):
        m = self.m
        r = current_start - rules.ROUND_SECONDS
        while r in m.op and (r + rules.ROUND_SECONDS - 1) in m.cl:
            if r not in self.settled:
                o, c = m.op[r], m.cl[r + rules.ROUND_SECONDS - 1]
                result = "up" if c > o else "down" if c < o else "tie"
                self.s.x("INSERT OR IGNORE INTO rounds VALUES(?,?,?,?)", (r, o, c, result))
                self.settled.add(r)
            r -= rules.ROUND_SECONDS

    def _evaluate(self, start, cp, t):
        m = self.m
        o, price = m.op[start], m.cl[t]
        dev_pct = (price / o - 1) * 100
        rng = m.range_pct(t)
        prev = None
        if cp["id"] > 1:
            rows = self.s.q("SELECT dev_pct, signal, blocked FROM evals WHERE round_ts=? AND cp=?",
                            (start, cp["id"] - 1))
            if rows:
                prev = {"dev_pct": rows[0]["dev_pct"],
                        "signal": bool(rows[0]["signal"]) and rows[0]["blocked"] is None}
        e = rules.evaluate(cp["elapsed"], dev_pct, rng, t + 1, prev, self.symbol)
        blocked = rules.risk_block(self.s.settled_signals(), t + 1) if e["signal"] else None
        self.s.x("""INSERT OR IGNORE INTO evals(round_ts, cp, ts, open, price, dev_pct, dev_usd,
                    side, signal, reason, row, table_p, max_price, range30, high_vol, blocked)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (start, cp["id"], t + 1, o, price, dev_pct, price - o, e["side"],
                  int(e["signal"]), e["reason"], e["row"], e["table_p"], e["max_price"],
                  rng, int(e["high_vol"]), blocked))
        self.done.add((start, cp["id"]))

    # ---- 给看板的数据 ----
    def state(self):
        m = self.m
        stale = time.time() - m.last_ok
        out = {"healthy": m.latest is not None and stale < STALE_AFTER,
               "stale_s": round(stale, 1) if m.last_ok else None, "error": m.error,
               "round": None, "checkpoints": [], "stake": rules.STAKE_USD,
               "symbol": self.symbol, "name": self.profile["name"],
               "high_vol_range": self.profile["high_vol_range"],
               "symbols": [{"symbol": x, "name": rules.PROFILES[x]["name"]} for x in SYMBOLS]}
        if m.latest is None:
            return out
        latest = m.latest
        start = latest // rules.ROUND_SECONDS * rules.ROUND_SECONDS
        o = m.op.get(start)
        price = m.cl.get(latest)
        rng = m.range_pct(latest)
        out["round"] = {
            "start": start, "elapsed": latest - start, "open": o, "price": price,
            "dev_usd": None if o is None else price - o,
            "dev_pct": None if o is None else (price / o - 1) * 100,
            "series": [m.cl.get(s) for s in range(start, latest + 1)],
            "range30": rng,
            "high_vol": rng is not None and rng > self.profile["high_vol_range"],
        }
        evals = {e["cp"]: e for e in self.s.q("SELECT * FROM evals WHERE round_ts=?", (start,))}
        for cp in rules.CHECKPOINTS:
            e = evals.get(cp["id"])
            status = "done" if e else ("missed" if latest - start > cp["elapsed"] + rules.SIGNAL_WINDOW else "pending")
            out["checkpoints"].append({"cp": cp["id"], "elapsed": cp["elapsed"],
                                       "label": cp["label"], "status": status, "eval": e})
        out["risk_blocked"] = rules.risk_block(self.s.settled_signals(), latest)
        return out

    def summary(self, limit=80, include_all=False):
        where = "" if include_all else " WHERE e.signal=1"
        history = self.s.q(self.s.SIGNALS + where + " ORDER BY e.ts DESC LIMIT ?", (limit,))
        for h in history:
            h["order"] = None
            if h["signal"] and h["result"] and not h["blocked"]:
                h["order"] = rules.order_from(h)

        sigs = self.s.settled_signals()
        n = len(sigs)
        wins = sum(s["result"] == s["side"] for s in sigs)
        thr_pnl = sum(rules.STAKE_USD * (1 / s["max_price"] - 1) if s["result"] == s["side"]
                      else -rules.STAKE_USD for s in sigs)
        priced = [s for s in sigs if s["app_price"] is not None]
        fill = [s for s in priced if s["app_price"] <= s["max_price"] + 1e-9]
        avg = lambda xs: sum(xs) / len(xs) if xs else None
        today = rules.beijing_day(self.m.latest or int(time.time()))
        day_pnl = 0.0
        for s in sigs:
            o = rules.order_from(s)
            if o and rules.beijing_day(o["settle_ts"]) == today:
                day_pnl += o["pnl"]
        stats = {
            "rounds": len(self.settled),
            "signals": n, "wins": wins,
            "win_rate": wins / n if n else None,
            "avg_table_p": avg([s["table_p"] for s in sigs]),
            "avg_max_price": avg([s["max_price"] for s in sigs]),
            "threshold_pnl": thr_pnl,
            "priced": len(priced), "fillable": len(fill),
            "fill_avg_price": avg([s["app_price"] for s in fill]),
            "fill_win_rate": avg([float(s["result"] == s["side"]) for s in fill]),
            "fill_pnl": sum(rules.order_from(s)["pnl"] for s in fill),
            "blocked": self.s.q("SELECT COUNT(*) c FROM evals WHERE blocked IS NOT NULL")[0]["c"],
            "day_pnl": day_pnl,
            "target": 200,
        }
        return {"stats": stats, "history": history}

    def set_app_price(self, eval_id, pct):
        price = None
        if pct is not None:
            pct = float(pct)
            if not 1 <= pct <= 99:
                raise ValueError("价格应在 1 到 99 之间")
            price = round(pct / 100, 4)
        if not self.s.x("UPDATE evals SET app_price=? WHERE id=? AND signal=1", (price, int(eval_id))):
            raise ValueError("找不到这条信号")


def poll_loop(market, engine):
    while True:
        t0 = time.time()
        try:
            with engine.lock:
                market.update()
                engine.tick()
        except Exception as exc:            # 网络抖动:记下原因,下一秒重试
            market.error = f"{type(exc).__name__}: {exc}"[:200]
        time.sleep(max(0.2, 1.0 - (time.time() - t0)))


def make_handler(engines):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8", extra=()):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _authed(self):
            if not PASSWORD:
                return True
            h = self.headers.get("Authorization", "")
            if h.startswith("Basic "):
                try:
                    pw = base64.b64decode(h[6:]).decode().split(":", 1)[1]
                    if hmac.compare_digest(pw.encode(), PASSWORD.encode()):
                        return True
                except Exception:
                    pass
            self._send(401, {"error": "需要密码"}, extra=[("WWW-Authenticate", 'Basic realm="recorder"')])
            return False

        def do_GET(self):
            if not self._authed():
                return
            path, _, query = self.path.partition("?")
            params = urllib.parse.parse_qs(query)
            engine = engines.get(params.get("symbol", [SYMBOLS[0]])[0].upper())
            if engine is None:
                return self._send(400, {"error": "未知币种"})
            if path == "/":
                self._send(200, (HERE / "static" / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/state":
                with engine.lock:
                    data = engine.state()
                self._send(200, data)
            elif path == "/api/summary":
                with engine.lock:
                    data = engine.summary(include_all=params.get("all") == ["1"])
                self._send(200, data)
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._authed():
                return
            if self.path != "/api/app_price":
                return self._send(404, {"error": "not found"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0))
                engine = engines[str(body.get("symbol", SYMBOLS[0])).upper()]
                with engine.lock:
                    engine.set_app_price(body["id"], body.get("price"))
                self._send(200, {"ok": True})
            except (ValueError, KeyError, TypeError) as exc:
                self._send(400, {"error": str(exc)})

    return Handler


def main():
    engines = {}
    for sym in SYMBOLS:
        if sym not in rules.PROFILES:
            raise SystemExit(f"rules.PROFILES 里没有 {sym} 的参数")
        # BTC 沿用原来的文件名,旧记录不受影响
        path = DB_PATH if sym == rules.DEFAULT_SYMBOL else DB_PATH.with_name(f"{DB_PATH.stem}_{sym.lower()}{DB_PATH.suffix}")
        market = Market(sym)
        engines[sym] = Engine(market, Store(path))
        threading.Thread(target=poll_loop, args=(market, engines[sym]), daemon=True).start()
    host = os.environ.get("HOST", "0.0.0.0") if PASSWORD else "127.0.0.1"
    port = int(os.environ.get("PORT", "8787"))
    print(f"记录器已启动: http://{host}:{port}  币种: {', '.join(SYMBOLS)}  (只记录,不下单)", flush=True)
    if not PASSWORD:
        print("未设置 DASH_PASSWORD,只允许本机访问。", flush=True)
    ThreadingHTTPServer((host, port), make_handler(engines)).serve_forever()


if __name__ == "__main__":
    main()
