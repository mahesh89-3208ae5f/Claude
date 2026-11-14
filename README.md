# BTC 行情监控简报

每次运行抓取一批公开数据，输出一份中文 Markdown 简报，帮助判断 BTC 当前更接近**下跌、止跌还是反弹**。

只做信息收集和规则化归类：

- 只发 HTTP GET，只访问无需鉴权的公开接口。脚本里没有任何下单、划转、签名代码，也不读取任何 API Key。
- 每个数据都带来源编号和获取时间。任何数据源失败都写「获取失败」，不用旧数据或估算值顶替。
- 「事实」和「推断」分开标注，推断写明规则和依据。不给买卖建议，不预测价格或时间。

## 运行

需要 Python 3.10 及以上。

```bash
pip install -r requirements.txt
python btc_brief.py                 # 打印简报，并保存到 reports/btc_brief_<UTC 时间>.md
python btc_brief.py --no-save       # 只打印
python btc_brief.py --tz Asia/Tokyo # 换一个附带显示的本地时区（默认北京时间）
```

依赖只有 `requests`（Windows 上另需 `tzdata` 提供时区库，已写在 `requirements.txt` 里）。

可选环境变量 `BTC_BRIEF_CONTACT`：BLS 和 SEC 要求自动访问在 User-Agent 里留联系方式。设置后脚本会把它附在 User-Agent 中，例如 `export BTC_BRIEF_CONTACT=you@example.com`。不设置时 BLS 日程大概率返回 403，简报里会如实写「获取失败」。

离线测试（不访问网络）：

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

运行示例见 [`examples/sample_output.md`](examples/sample_output.md)，是 2026-11-14 的一次真实运行输出。

## 数据源

接口地址和参数都先核对了官方文档或官方页面的真实返回，再写进代码。

| 编号 | 内容 | 地址 | 依据 |
|---|---|---|---|
| S1–S3 | 币安现货 BTCUSDT：24 小时行情、日线、4 小时 K 线 | `data-api.binance.vision` 的 `/api/v3/ticker/24hr`、`/api/v3/klines` | [现货行情接口文档](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints)、[仅行情域名说明](https://developers.binance.com/docs/binance-spot-api-docs/faqs/market_data_only) |
| F1–F7 | 币安 U 本位永续：标记价格与资金费率、资金费率历史、未平仓量及历史、多空账户比、主动买卖量、日线 | `fapi.binance.com` 的 `/fapi/v1/premiumIndex`、`/fapi/v1/fundingRate`、`/fapi/v1/openInterest`、`/futures/data/openInterestHist`、`/futures/data/globalLongShortAccountRatio`、`/futures/data/takerlongshortRatio`、`/fapi/v1/klines` | [U 本位合约行情接口文档](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics) |
| B1 | 币安官方公告：新币上线、下架、最新动态、维护、API 更新 | `www.binance.com/bapi/composite/v1/public/cms/article/list/query` | [公告页](https://www.binance.com/en/support/announcement)自身使用的数据接口 |
| E1 | 美国现货 BTC ETF 每日净流量 | `www.tftc.io/bitcoin-etf-flows/data.json` | [TFTC 公开数据与方法说明](https://www.tftc.io/bitcoin-etf-flows)，CC BY 4.0 |
| G1 | 恐惧贪婪指数 | `api.alternative.me/fng/` | [Alternative.me API 说明](https://alternative.me/crypto/fear-and-greed-index/) |
| M1 | 美国 CPI、非农发布日程 | `www.bls.gov/schedule/news_release/bls.ics` | [BLS 发布日程](https://www.bls.gov/schedule/news_release/)的官方日历订阅文件 |
| C1 | 美联储日程：议息会议、纪要、褐皮书、听证、官员讲话 | `www.federalreserve.gov/json/calendar.json` | [美联储官网日历页](https://www.federalreserve.gov/newsevents/calendar.htm)所用数据 |
| N1 | 美联储新闻稿 | `www.federalreserve.gov/feeds/press_all.xml` | [美联储 RSS 列表](https://www.federalreserve.gov/feeds/feeds.htm) |
| N2 | SEC 新闻稿 | `www.sec.gov/news/pressreleases.rss` | SEC 官方 RSS |

## 已知限制

写脚本时逐个实测过，下面几条会直接影响简报的完整度：

1. **币安合约接口有地区限制。** 从受限地区（包括美国的云服务器）访问 `fapi.binance.com` 会返回 HTTP 451。此时资金费率、未平仓量、多空比、合约成交量、主动买卖量全部标「获取失败」，止跌信号第 3、4 项标「无法判定」。这部分代码只用符合官方文档字段的模拟数据测过，没有拿到过真实响应。现货数据走的 `data-api.binance.vision` 不受影响。
2. **BLS 拒绝未留联系方式的自动访问。** 不设 `BTC_BRIEF_CONTACT` 时 CPI、非农日程会失败。iCalendar 解析器按标准格式写成并有离线测试，但没有拿到过 BLS 的真实文件。失败时简报会给出官方日程页链接，供人工核对。
3. **ETF 数据是二手汇总，且会滞后。** TFTC 的上游是 SoSoValue 和 Farside 整理的发行方披露，不是发行方原始文件，通常比交易日晚一到数天更新。简报会写明数据截至哪一天、哪些工作日尚未收录。更常用的 Farside 页面对脚本返回 Cloudflare 人机验证，没有采用。
4. **币安公告接口不在正式 API 文档里。** 它是公告页自己调用的接口，字段随时可能变。结构不符时脚本会报「获取失败」而不是猜测。币安文档里的正式公告推送需要 API Key，不符合本工具「不使用任何 Key」的约束。
5. **消息只列标题。** 脚本不读正文，不判断利好利空，只对标题做关键词提示。

## 指标怎么读

下面是通行的解读方式。每个指标单独看都不可靠，要结合价格位置和其他指标。

| 指标 | 是什么 | 怎么读 |
|---|---|---|
| 24 小时、7 日涨跌幅 | 现价相对 24 小时前、7 天前的变化 | 看下跌的速度。7 日跌幅大而 24 小时跌幅收窄，说明跌速在放缓，但不等于止跌 |
| 距近期高点、低点 | 现价相对 7、30、90 日最高价和最低价的位置 | 贴着低点说明还在探底；离低点越远、且低点没再被刷新，越接近止跌或反弹 |
| 资金费率 | 永续合约多空双方每 8 小时互付的费用。正值是多头付给空头，负值相反 | 持续为正说明多头愿意付费持仓，杠杆偏多。下跌中转负，说明做空拥挤或多头杠杆已退出，是常见的超卖特征。「当期预测」是下次结算前的实时估计值，还会变 |
| 未平仓量（OI） | 未平仓的永续合约总量，简报用 BTC 数量计 | 反映场内杠杆规模。价格下跌同时 OI 明显下降，说明杠杆仓位被平掉或强平，即「杠杆出清」。价格下跌而 OI 上升，说明有新仓位在加，波动可能继续放大。用 BTC 计是为了排除币价下跌本身让美元名义值缩水的影响 |
| 多空账户比 | 持多仓的账户数除以持空仓的账户数，按账户数算，不按资金量 | 主要反映散户倾向。下跌中比值持续走高，说明散户在逆势加多，通常不算止跌特征；比值回落说明多头在退出 |
| 成交量 | 一段时间内成交的 BTC 数量 | 放量下跌说明抛压在集中释放；放量后价格不再创新低，才有换手完成的含义。缩量下跌往往只是没人接 |
| 主动买卖量 | 按吃单方向统计的成交。买卖比大于 1，或主动买入占比高于 50%，表示主动买入更多 | 看谁更急。下跌中主动买入占比回升，说明有资金主动承接 |
| 恐惧贪婪指数 | Alternative.me 综合波动率、成交量、社交媒体等算出的 0 到 100 情绪分数，每天更新一次 | 25 以下为极度恐惧。它描述情绪，不提示时点，极度恐惧可以持续很久 |
| ETF 净流量 | 美国现货 BTC ETF 每个交易日的申购减赎回，单位美元 | 代表传统资金通过 ETF 的买卖方向。连续净流出后转为净流入，说明这部分抛压在缓解。周末和美国假日没有数据 |

## 止跌信号与阶段归类的规则

简报里的「出现 / 未出现」是把数据代入下面的固定规则得到的。阈值都在 `btc_brief.py` 顶部，可以按自己的标准改。

| 信号 | 规则 |
|---|---|
| 放量长下影线 | 最近 3 根已收盘日线里，有一根同时满足：下影线 ≥ 实体的 2 倍、下影线 ≥ 当日振幅的 50%、成交量 ≥ 此前 7 日均量的 1.5 倍 |
| 连续 2 到 3 天不创新低 | 最近连续 ≥2 根已收盘日线都没有跌破各自之前 30 日的最低价，且当日未收盘的 K 线也没跌破 |
| 资金费率转负 | 最近一次已结算资金费率 < 0，或当期预测资金费率 < 0 |
| 未平仓量大幅下降 | 以 BTC 计的未平仓量较 7 日峰值回落 ≥10%，或较 24 小时前下降 ≥5% |
| ETF 转为净流入 | 最新交易日为净流入，这段连续净流入不超过 3 个交易日，且它之前的那个交易日为净流出 |

数据源失败时，对应信号标「无法判定」，既不算出现也不算未出现。

阶段归类只看价格结构，止跌信号作为佐证列出：

| 归类 | 规则（窗口为近 30 根日线，含当日） |
|---|---|
| 不适用 | 现价距窗口高点不足 5%，不在下跌语境里 |
| 下跌 | 窗口最低价出现在当日或前一日 |
| 反弹 | 已有 ≥2 根日线未再创新低，且现价自低点回升 ≥5% |
| 止跌 | 已有 ≥2 根日线未再创新低，但自低点回升不足 5% |

这是对当前状态的归类，不是对后续走势的预测。日线按 UTC 0 点切分。
