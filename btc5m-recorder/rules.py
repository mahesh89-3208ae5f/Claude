"""下单规则(纯函数,不联网)。

门槛表来自 BTC/USDT 现货 60 天逐秒数据的回测:
最高买入价 = 历史胜率的 95% 置信下限 - 2 个百分点(为手续费和滑点预留)。
波动水平变化后需要用新数据重算。
"""

ROUND_SECONDS = 300
SIGNAL_WINDOW = 10          # 检查点之后多少秒内仍算有效
STAKE_USD = 1.0             # 每笔模拟金额

# 两个检查点:开盘后第 210 秒(剩 90 秒)和第 240 秒(剩 60 秒)
CHECKPOINTS = (
    {"id": 1, "elapsed": 210, "label": "3:30"},
    {"id": 2, "elapsed": 240, "label": "4:00"},
)

# 偏离分档(占目标价的百分比)
BIN_EDGES = (0.02, 0.04, 0.07, 0.10)

# 每个币种一套参数:
#   table:          检查点 -> 分档序号 -> (历史胜率, 最高买入价)
#   high_vol_range: 过去 30 分钟高低价差(%)超过它,按小一档查表
#   late_hours:     这些小时(北京时间)最高买入价再下调 LATE_HOUR_DISCOUNT
PROFILES = {
    "BTCUSDT": {
        "name": "BTC",
        "table": {
            210: {0: (0.782, 0.75), 1: (0.892, 0.86), 2: (0.938, 0.91)},
            240: {0: (0.832, 0.80), 1: (0.915, 0.89)},
        },
        "high_vol_range": 0.30,
        "late_hours": (22,),
    },
    # ETH 波动约为 BTC 的 1.4 倍,同样的偏离更容易反转,门槛更低
    "ETHUSDT": {
        "name": "ETH",
        "table": {
            210: {0: (0.766, 0.73), 1: (0.853, 0.82), 2: (0.916, 0.88)},
            240: {0: (0.799, 0.76), 1: (0.891, 0.86)},
        },
        "high_vol_range": 0.40,
        "late_hours": (22,),
    },
}
DEFAULT_SYMBOL = "BTCUSDT"

MIN_RANGE_SAMPLES = 1500    # 计算 30 分钟价差至少需要的秒数
LATE_HOUR_DISCOUNT = 0.05
# 美国重要数据常见公布时间前后 5 分钟(北京时间,分钟数)
BLACKOUT_MINUTES = ((20 * 60 + 25, 20 * 60 + 35), (21 * 60 + 25, 21 * 60 + 35))

DAILY_LOSS_CAP = 10.0       # 当日模拟亏损达到后停到第二天
LOSS_STREAK = 3             # 连输几笔后暂停
STREAK_PAUSE_SECONDS = 3600


def bin_index(abs_dev_pct):
    """偏离落在第几档;小于最低档返回 -1。"""
    idx = -1
    for i, edge in enumerate(BIN_EDGES):
        if abs_dev_pct >= edge:
            idx = i
    return idx


def bin_label(idx):
    if idx < 0:
        return f"<{BIN_EDGES[0]:.2f}%"
    if idx == len(BIN_EDGES) - 1:
        return f"≥{BIN_EDGES[idx]:.2f}%"
    return f"{BIN_EDGES[idx]:.2f}–{BIN_EDGES[idx + 1]:.2f}%"


def beijing_minutes(ts):
    return ((ts + 8 * 3600) % 86400) // 60


def beijing_day(ts):
    return (ts + 8 * 3600) // 86400


def evaluate(elapsed, dev_pct, range30_pct, ts, prev=None, symbol=DEFAULT_SYMBOL):
    """在一个检查点判断是否出信号。

    prev: 本轮上一个检查点的结果 {"dev_pct": float, "signal": bool},没有则为 None。
    返回 dict:signal / side / reason / table_p / max_price / row / high_vol。
    """
    prof = PROFILES[symbol]
    out = {"signal": False, "side": None, "reason": None, "table_p": None,
           "max_price": None, "row": None, "high_vol": False}
    if dev_pct == 0:
        out["reason"] = "价格等于目标价"
        return out
    side = "up" if dev_pct > 0 else "down"
    out["side"] = side
    a = abs(dev_pct)

    if range30_pct is None:
        out["reason"] = "行情数据不足 30 分钟"
        return out
    high_vol = range30_pct > prof["high_vol_range"]
    out["high_vol"] = high_vol

    idx = bin_index(a)
    if idx < 0:
        out["reason"] = "偏离不足 0.02%"
        return out

    if prev is not None and prev.get("dev_pct"):
        same_side = (prev["dev_pct"] > 0) == (dev_pct > 0)
        if same_side and a < abs(prev["dev_pct"]):
            out["reason"] = "偏离比上一次缩小"
            return out
        if not same_side and prev.get("signal"):
            out["reason"] = "方向反转,不反手"
            return out

    minute = beijing_minutes(ts)
    if any(lo <= minute < hi for lo, hi in BLACKOUT_MINUTES):
        out["reason"] = "数据公布时段"
        return out

    row = idx - 1 if high_vol else idx
    if row < 0:
        out["reason"] = "高波动降档后偏离不足"
        return out
    cell = prof["table"][elapsed].get(row)
    if cell is None:
        out["reason"] = "偏离过大,收益率低于 10%"
        return out

    table_p, max_price = cell
    if minute // 60 in prof["late_hours"]:
        max_price = round(max_price - LATE_HOUR_DISCOUNT, 4)
    out.update(signal=True, table_p=table_p, max_price=max_price, row=bin_label(row))
    return out


def order_from(sig):
    """把一条信号换算成模拟订单;不成交返回 None。

    没填 App 价格时假设按门槛价成交;填了且高于门槛则视为不成交。
    sig 需要包含 max_price / app_price / side / result / round_ts。
    """
    price = sig["max_price"]
    if sig.get("app_price") is not None:
        if sig["app_price"] > sig["max_price"] + 1e-9:
            return None
        price = sig["app_price"]
    win = sig["result"] == sig["side"]       # 平局按输算
    pnl = STAKE_USD * (1 / price - 1) if win else -STAKE_USD
    return {"price": price, "win": win, "pnl": pnl,
            "settle_ts": sig["round_ts"] + ROUND_SECONDS}


def risk_block(settled_signals, now_ts):
    """根据已结算的信号判断风控是否暂停。返回原因或 None。

    settled_signals: 按时间升序、未被风控拦截且已结算的信号。
    """
    today = beijing_day(now_ts)
    day_pnl = 0.0
    streak = 0
    pause_until = 0
    for s in settled_signals:
        o = order_from(s)
        if o is None:
            continue
        if beijing_day(o["settle_ts"]) == today:
            day_pnl += o["pnl"]
        if o["win"]:
            streak = 0
        else:
            streak += 1
            if streak >= LOSS_STREAK:
                pause_until = o["settle_ts"] + STREAK_PAUSE_SECONDS
                streak = 0
    if day_pnl <= -DAILY_LOSS_CAP:
        return "当日亏损达上限"
    if now_ts < pause_until:
        return f"连输 {LOSS_STREAK} 笔,暂停 1 小时"
    return None
