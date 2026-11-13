# BTC 5 分钟预测记录器

只记录信号,不下单。程序每秒读取 BTC/USDT 现货价,在每轮开盘后 3:30 和 4:00 各检查一次,
按门槛表判断是否出信号,并在下一轮开始时记下结果。它只用公开行情,不需要任何账号或密钥。

## 运行

需要 Python 3.9 以上,不依赖第三方库。

```bash
DASH_PASSWORD=换成你的密码 python3 recorder.py
```

然后用浏览器打开 `http://服务器IP:8787`,用户名随意,密码是上面设置的值。
不设置 `DASH_PASSWORD` 时程序只监听 `127.0.0.1`,外网无法访问。

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `DASH_PASSWORD` | 无 | 看板密码 |
| `HOST` / `PORT` | `0.0.0.0` / `8787` | 监听地址和端口 |
| `BINANCE_BASE` | `https://data-api.binance.vision` | 行情接口,连不上时可换成 `https://api.binance.com` |
| `DB_PATH` | `data/recorder.db` | 记录保存位置(SQLite) |

密码通过 HTTP 基本认证传输。直接用 IP 访问时密码是明文传输的,
建议用 SSH 隧道(`ssh -L 8787:127.0.0.1:8787 服务器`)或在前面加一层 HTTPS 反向代理。

### 开机自启(systemd)

```ini
# /etc/systemd/system/btc5m-recorder.service
[Unit]
Description=BTC 5m recorder
After=network-online.target

[Service]
WorkingDirectory=/opt/btc5m-recorder
Environment=DASH_PASSWORD=换成你的密码
ExecStart=/usr/bin/python3 recorder.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now btc5m-recorder
```

## 怎么用

1. 信号出现时,卡片会显示"买涨/买跌,价格不高于 X%"。
2. 打开 App,看这一边订单簿的卖一价,填进输入框并保存。也可以事后在"信号记录"里补填。
3. 攒够 200 条已结算信号后看统计:
   - 实际胜率是否接近"表中预期";
   - 填过价格的信号里,有多少低于门槛(能成交);
   - 按 App 价估算的盈亏是否为正。

## 规则

规则都在 `rules.py`,改动后运行 `python3 -m unittest` 验证。

| 偏离目标价 | 第 3:30 最高买入价 | 第 4:00 最高买入价 |
|---|---|---|
| 不足 0.02% | 不下 | 不下 |
| 0.02–0.04% | 75% | 80% |
| 0.04–0.07% | 86% | 89% |
| 0.07–0.10% | 91% | 不下 |
| 0.10% 以上 | 不下 | 不下 |

- 过去 30 分钟高低价差超过 0.3% 时,按偏离小一档的那一行查表。
- 北京时间 22:00–23:00,最高买入价再减 5 个点。
- 第 4:00 的偏离比第 3:30 缩小时不出信号;第 3:30 已出信号而方向反转时也不出。
- 北京时间 20:25–20:35、21:25–21:35 不出信号(美国数据常见公布时间)。
- 风控:当日估算亏损达 $10 停到第二天;连输 3 笔暂停 1 小时。暂停期间的信号照常记录,但不计入统计。

## 已知限制

- 程序看不到预测市场的订单簿,App 价格需要手动填。没填的信号按最高买入价估算盈亏。
- 目标价取现货在本轮第一秒的开盘价,结算取最后一秒的收盘价,可能与 App 的口径略有差别。
  刚开始用时请对照几轮 App 上显示的目标价。
- 平局(收盘价等于目标价)按输计算。
- 门槛表基于 2026 年 9–11 月的 60 天数据,波动水平变化后需要重算。
