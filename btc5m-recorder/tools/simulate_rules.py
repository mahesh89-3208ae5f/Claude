"""把 rules.py 的规则在历史逐秒数据上重放一遍,统计信号数量和胜率。
用法: python3 simulate_rules.py 数据文件.json [币种,默认 BTCUSDT]
注意:只能检验"信号的胜率是否高于最高买入价",不能说明实际能否按该价格成交。"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import rules

path = sys.argv[1]
symbol = sys.argv[2] if len(sys.argv) > 2 else "BTCUSDT"
D = json.load(open(path)); op, cl = D["op"], D["cl"]; t0 = D["start"] // 1000
nw = len(op) // 300
sigs = []
for w in range(7, nw):
    i = w * 300; o = op[i]; c = cl[i + 299]
    result = "up" if c > o else "down" if c < o else "tie"
    prev = None
    for cp in rules.CHECKPOINTS:
        t = i + cp["elapsed"] - 1
        seg = cl[t - 1799:t + 1]
        rng = (max(seg) - min(seg)) / seg[-1] * 100
        dev = (cl[t] / o - 1) * 100
        e = rules.evaluate(cp["elapsed"], dev, rng, t0 + t + 1, prev, symbol)
        prev = {"dev_pct": dev, "signal": e["signal"]}
        if e["signal"]:
            sigs.append(dict(cp=cp["id"], hour=((t0 + t) // 3600 + 8) % 24, win=e["side"] == result,
                             q=e["max_price"], p=e["table_p"], row=e["row"], hv=e["high_vol"], w=w))

def line(label, L):
    if not L: return
    n = len(L); wr = sum(s["win"] for s in L) / n; q = sum(s["q"] for s in L) / n
    print(f"{label:26s} n={n:5d}  胜率 {wr:6.1%}  平均最高买入价 {q:6.1%}  余量 {(wr - q) * 100:+5.1f} 点")

days = nw / 288
print(f"{symbol}: {nw} 轮({days:.0f} 天),有信号的轮次 {len(set(s['w'] for s in sigs)) / nw:.1%},平均每天 {len(sigs) / days:.0f} 条信号")
line("全部信号", sigs)
for cp in (1, 2): line(f"第 {cp} 次检查", [s for s in sigs if s["cp"] == cp])
line("正常波动", [s for s in sigs if not s["hv"]]); line("高波动(已降档)", [s for s in sigs if s["hv"]])
for row in sorted(set(s["row"] for s in sigs)): line("档位 " + row, [s for s in sigs if s["row"] == row])
third = nw // 3
for k in range(3): line(f"第 {k + 1} 个 20 天", [s for s in sigs if k * third <= s["w"] < (k + 1) * third])
print("按北京时间小时:")
for h in range(24): line(f"  {h:02d} 时", [s for s in sigs if s["hour"] == h])
