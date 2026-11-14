# BTC 行情监控简报

- 生成时间：2026-11-14 15:43 UTC（北京 23:43）
- 性质：只读信息汇总与规则化归类，不构成任何买卖建议，不预测价格或时间。
- 标注约定：**【事实】** 为接口原始值或对其直接算术计算；**【推断】** 为按固定规则得出的归类，均附依据。方括号内是来源编号与获取时间（UTC），编号对应文末「数据源状态」。

## 概览

**【推断】当前阶段归类：下跌**

依据：
- 近 30 日高点 84,898.00（10-21），现价距高点 -22.75%
- 近 30 日低点 65,066.66（11-14，即当日），现价距低点 +0.80%
- 规则：窗口最低价出现在当日或前一日，即最近两根日线内仍在创新低 → 归为下跌
- 止跌信号佐证：可判定的 3 项中出现 0 项
- 说明：有 2 项信号因数据获取失败无法判定（资金费率转负、未平仓量大幅下降（杠杆出清）），佐证不完整
- 说明：这是按上述固定规则对当前状态的归类，不是对后续走势的预测；阈值可在脚本顶部调整
- 本次有 8 个数据源获取失败：F1、F2、F3、F4、F5、F6、F7、M1（详见文末），相关条目均标为「获取失败」。

## 1. 价格

| 项目 | 数值 | 来源与获取时间 |
|---|---|---|
| 现货现价（BTCUSDT） | 65,586.01 USDT | [S1 15:43:22 UTC] |
| 24 小时涨跌幅（滚动） | -3.77% | [S1 15:43:22 UTC] |
| 24 小时最高 / 最低 | 69,134.01 / 65,066.66 | [S1 15:43:22 UTC] |
| 永续标记价格 | 获取失败（HTTP 451：对方按访问所在地区拒绝服务（币安合约接口的地区限制）） | [F1 15:43:22 UTC] |
| 7 日涨跌幅 | -13.43%（基准 75,758.01，取 2026-11-07 16:00 UTC（北京 11-08 00:00） 开盘的 4 小时 K 线开盘价） | [S3 15:43:22 UTC；S1 15:43:22 UTC] |
| 近 7 日高点 / 距离 | 76,200.00（11-08） / -13.93% | [S2 15:43:22 UTC；S1 15:43:22 UTC] |
| 近 7 日低点 / 距离 | 65,066.66（11-14） / +0.80% | [S2 15:43:22 UTC；S1 15:43:22 UTC] |
| 近 30 日高点 / 距离 | 84,898.00（10-21） / -22.75% | [S2 15:43:22 UTC；S1 15:43:22 UTC] |
| 近 30 日低点 / 距离 | 65,066.66（11-14） / +0.80% | [S2 15:43:22 UTC；S1 15:43:22 UTC] |
| 近 90 日高点 / 距离 | 87,395.67（09-21） / -24.96% | [S2 15:43:22 UTC；S1 15:43:22 UTC] |
| 近 90 日低点 / 距离 | 62,751.10（08-17） / +4.52% | [S2 15:43:22 UTC；S1 15:43:22 UTC] |

以上均为【事实】。日线按 UTC 0 点切分，窗口包含当日未收盘的 K 线。

【事实】4 小时级别：最近 6 根已收盘 K 线（约 24 小时）的最低 66,456.00、最高 70,214.31；再往前 6 根的最低 67,568.00、最高 73,152.01。低点下移，高点下移。[S3 15:43:22 UTC]

## 2. 关键指标与 7 日均值对比

| 指标 | 当前值 | 7 日均值 | 当前相对均值 | 来源与获取时间 |
|---|---|---|---|---|
| 资金费率（已结算） | 获取失败（同一主机已被拒绝（HTTP 451），未重复请求） | — | — | [F2 15:43:22 UTC] |
| 资金费率（当期预测） | 获取失败（HTTP 451：对方按访问所在地区拒绝服务（币安合约接口的地区限制）） | — | — | [F1 15:43:22 UTC] |
| 未平仓量（永续） | 获取失败（同一主机已被拒绝（HTTP 451），未重复请求） | — | — | [F3 15:43:22 UTC；F4 15:43:22 UTC] |
| 多空账户比 | 获取失败（同一主机已被拒绝（HTTP 451），未重复请求） | — | — | [F5 15:43:22 UTC] |
| 现货成交量（滚动 24 小时） | 23,066 BTC | 15,407 BTC（最近 7 根已收盘日线） | +49.71% | [S1 15:43:22 UTC；S2 15:43:22 UTC] |
| 永续成交量 | 获取失败（同一主机已被拒绝（HTTP 451），未重复请求） | — | — | [F7 15:43:22 UTC] |
| 永续主动买卖量比 | 获取失败（同一主机已被拒绝（HTTP 451），未重复请求） | — | — | [F6 15:43:22 UTC] |
| 现货主动买入占比（当日未收盘，补充） | 44.6% | 50.8% | -6.2 个百分点 | [S2 15:43:22 UTC] |
| 恐惧贪婪指数（11-14 值） | 13（极度恐惧） | 27.3（此前 7 日） | -14.3 点 | [G1 15:43:23 UTC] |
| 美国现货 BTC ETF 净流量（11-11 交易日） | -299.9 百万美元 | -225.4 百万美元（此前 7 个交易日） | — | [E1 15:43:23 UTC] |

以上均为【事实】。「7 日均值」的口径写在各行括号内。恐惧贪婪指数来源：[Alternative.me](https://alternative.me/crypto/fear-and-greed-index/)。ETF 数据来源：[The Commoner Bitcoin ETF Tracker by TFTC](https://www.tftc.io/bitcoin-etf-flows)（CC BY 4.0，上游见文末），属于二手汇总而非发行方原始披露。

## 3. 止跌信号检查表

| # | 信号 | 状态 | 来源与获取时间 |
|---|---|---|---|
| 1 | 放量长下影线 | ❌ 未出现 | [S2 15:43:22 UTC] |
| 2 | 连续 2 到 3 天不创新低 | ❌ 未出现 | [S2 15:43:22 UTC] |
| 3 | 资金费率转负 | ⚠️ 无法判定（获取失败） | [F1 15:43:22 UTC；F2 15:43:22 UTC] |
| 4 | 未平仓量大幅下降（杠杆出清） | ⚠️ 无法判定（获取失败） | [F3 15:43:22 UTC；F4 15:43:22 UTC] |
| 5 | ETF 由净流出转为净流入 | ❌ 未出现 | [E1 15:43:23 UTC] |

**1. 放量长下影线：未出现**
- 【推断】判定规则：最近 3 根已收盘日线中，任意一根同时满足：下影线 ≥ 实体的 2 倍、下影线 ≥ 当日振幅的 50%、成交量 ≥ 此前 7 日均量的 1.5 倍
- 【事实】11-11：下影线占振幅 37%、下影线/实体 2.7 倍、量比 1.01 → 不满足
- 【事实】11-12：下影线占振幅 11%、下影线/实体 0.1 倍、量比 1.00 → 不满足
- 【事实】11-13：下影线占振幅 19%、下影线/实体 0.2 倍、量比 2.18 → 不满足

**2. 连续 2 到 3 天不创新低：未出现**
- 【推断】判定规则：最近连续 ≥2 根已收盘日线都没有跌破各自之前 30 日的最低价，且当日（未收盘）也未跌破
- 【事实】最近一次创 30 日新低：11-14（当日，未收盘），最低 65,066.66
- 【事实】已收盘日线连续不创新低：0 根；当日未收盘 K 线已创新低

**3. 资金费率转负：无法判定**
- 【推断】判定规则：最近一次已结算资金费率 < 0，或当期预测资金费率 < 0
- 【事实】资金费率数据获取失败

**4. 未平仓量大幅下降（杠杆出清）：无法判定**
- 【推断】判定规则：以 BTC 计的未平仓量较 7 日峰值回落 ≥10%，或较 24 小时前下降 ≥5%（用币本位数量，排除价格下跌本身的影响）
- 【事实】未平仓量历史获取失败

**5. ETF 由净流出转为净流入：未出现**
- 【推断】判定规则：最新一个交易日为净流入，往前追溯这段连续净流入不超过 3 个交易日，且它之前的那个交易日为净流出
- 【事实】最近几个交易日净流量：11-04 +75，11-05 -430，11-06 -412，11-09 -201，11-10 -95，11-11 -300（百万美元）
- 【事实】注意：数据只到 11-11，之后的工作日 11-12、11-13 尚未收录，本项结论可能滞后

说明：状态栏是把【事实】代入固定规则后的【推断】。数据源失败的项目标「无法判定」，既不算出现也不算未出现。

## 4. 过去 24 小时的重要消息

### 币安官方公告 [B1 15:43:22 UTC]
公告页：https://www.binance.com/en/support/announcement　收录分类：新币上线、下架、币安最新动态（含规则变更）、维护与升级、API 更新
- 2026-11-14 03:52 UTC（北京 11:52） 〔币安最新动态（含规则变更）〕[Recovery Update: Withdrawals Reopened for More Networks (2026-11-14)](https://www.binance.com/en/support/announcement/detail/432646a7f7c34c2a85b69db99af32c16)

### 美联储新闻稿 [N1 15:43:24 UTC]
- 2026-11-13 21:15 UTC（北京 11-14 05:15） 〔Banking and Consumer Regulatory Policy〕[Agencies extend comment period for proposed third-party risk management guidance](https://www.federalreserve.gov/newsevents/pressreleases/bcreg20261113a.htm)

### SEC 新闻稿 [N2 15:43:25 UTC]
- 2026-11-13 16:57 UTC（北京 11-14 00:57） [SEC Proposes Executive and Director Compensation Disclosure Reforms](https://www.sec.gov/newsroom/press-releases/2026-114-sec-proposes-executive-director-compensation-disclosure-reforms)

以上均为【事实】：标题保留原文，时间为来源给出的发布时间。脚本没有判断消息的利好或利空。

## 5. 未来 7 天需要关注的事件

### 美国 CPI、非农 [M1 15:43:24 UTC]
- 获取失败（HTTP 403：对方拒绝自动访问（Access Denied））
- BLS 要求自动访问附联系方式，可设置环境变量 BTC_BRIEF_CONTACT 后重试
- 可人工核对官方日程页：https://www.bls.gov/schedule/news_release/

### 美联储 [C1 15:43:24 UTC]
- 2026-11-18 19:00 UTC（北京 11-19 03:00）　FOMC 会议纪要｜FOMC Minutes：Meeting of October 27-28　[来源](https://www.federalreserve.gov/newsevents/calendar.htm)
- 官员讲话与其他日程（8 项）：
  - 2026-11-16 10:00 UTC（北京 18:00）　Speech - Governor Michael S. Barr：Artificial Intelligence and Financial Stability　[来源](https://www.federalreserve.gov/newsevents/calendar.htm)
  - 2026-11-16 17:00 UTC（北京 11-17 01:00）　Speech - Chairman Kevin Warsh：Opening Remarks　[来源](https://www.federalreserve.gov/newsevents/calendar.htm)
  - 2026-11-17 14:10 UTC（北京 22:10）　Speech - Governor Christopher J. Waller：Payments　[来源](https://www.federalreserve.gov/newsevents/calendar.htm)
  - 2026-11-18 18:35 UTC（北京 11-19 02:35）　Speech - Governor Michael S. Barr：Community Development Investments　[来源](https://www.federalreserve.gov/newsevents/calendar.htm)
  - 2026-11-19 14:25 UTC（北京 22:25）　Discussion - Vice Chair Philip N. Jefferson：Economic Shocks　[来源](https://www.federalreserve.gov/newsevents/calendar.htm)
  - 2026-11-19 19:15 UTC（北京 11-20 03:15）　Discussion - Governor Michael S. Barr：Artificial Intelligence　[来源](https://www.federalreserve.gov/newsevents/calendar.htm)
  - 2026-11-20 13:25 UTC（北京 21:25）　Speech - Governor Christopher J. Waller：Welcoming Remarks　[来源](https://www.federalreserve.gov/newsevents/calendar.htm)
  - 2026-11-20 17:15 UTC（北京 11-21 01:15）　Speech - Governor Lisa D. Cook：The U.S. Economy in Global Context　[来源](https://www.federalreserve.gov/newsevents/calendar.htm)
- 窗口外的下一次议息会议：2026-12-09 19:00 UTC（北京 12-10 03:00）　FOMC 议息会议｜FOMC Meeting：Two-day meeting, December 8 - 9 Press Conference　[来源](https://www.federalreserve.gov/newsevents/calendar.htm)

以上均为【事实】，取自官方日程；官方可能调整日期，以来源页面为准。

## 数据源状态

| 编号 | 数据源 | 状态 | 获取时间 | 地址 |
|---|---|---|---|---|
| S1 | 币安现货 24 小时行情 | 成功 | 2026-11-14 15:43:22 UTC | https://data-api.binance.vision/api/v3/ticker/24hr?symbol=BTCUSDT |
| S2 | 币安现货日线 K 线 | 成功 | 2026-11-14 15:43:22 UTC | https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=120 |
| S3 | 币安现货 4 小时 K 线 | 成功 | 2026-11-14 15:43:22 UTC | https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=4h&limit=60 |
| F1 | 币安永续 标记价格与当期资金费率 | 获取失败：HTTP 451：对方按访问所在地区拒绝服务（币安合约接口的地区限制） | 2026-11-14 15:43:22 UTC | https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT |
| F2 | 币安永续 资金费率历史 | 获取失败：同一主机已被拒绝（HTTP 451），未重复请求 | 2026-11-14 15:43:22 UTC | https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=100 |
| F3 | 币安永续 当前未平仓量 | 获取失败：同一主机已被拒绝（HTTP 451），未重复请求 | 2026-11-14 15:43:22 UTC | https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT |
| F4 | 币安永续 未平仓量历史（1h） | 获取失败：同一主机已被拒绝（HTTP 451），未重复请求 | 2026-11-14 15:43:22 UTC | https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1h&limit=200 |
| F5 | 币安永续 多空账户比（1h） | 获取失败：同一主机已被拒绝（HTTP 451），未重复请求 | 2026-11-14 15:43:22 UTC | https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=1h&limit=200 |
| F6 | 币安永续 主动买卖量（1h） | 获取失败：同一主机已被拒绝（HTTP 451），未重复请求 | 2026-11-14 15:43:22 UTC | https://fapi.binance.com/futures/data/takerlongshortRatio?symbol=BTCUSDT&period=1h&limit=200 |
| F7 | 币安永续 日线 K 线 | 获取失败：同一主机已被拒绝（HTTP 451），未重复请求 | 2026-11-14 15:43:22 UTC | https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1d&limit=30 |
| B1 | 币安官方公告页 | 成功 | 2026-11-14 15:43:22 UTC | https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&pageNo=1&pageSize=20 |
| E1 | 美国现货 BTC ETF 每日净流量（TFTC 汇总） | 成功<br>上游：SoSoValue (daily aggregates and per-fund flows); issuer disclosures as tabulated by Farside Investors (per-fund history through mid-2026); mempool.space (BTC price, ~21:00 UTC mark). | 2026-11-14 15:43:23 UTC | https://www.tftc.io/bitcoin-etf-flows/data.json |
| G1 | 恐惧贪婪指数（Alternative.me） | 成功 | 2026-11-14 15:43:23 UTC | https://api.alternative.me/fng/?limit=8 |
| M1 | BLS 发布日程（CPI、非农） | 获取失败：HTTP 403：对方拒绝自动访问（Access Denied）<br>BLS 要求自动访问附联系方式，可设置环境变量 BTC_BRIEF_CONTACT 后重试 | 2026-11-14 15:43:24 UTC | https://www.bls.gov/schedule/news_release/bls.ics |
| C1 | 美联储官网日历 | 成功 | 2026-11-14 15:43:24 UTC | https://www.federalreserve.gov/json/calendar.json |
| N1 | 美联储新闻稿 RSS | 成功 | 2026-11-14 15:43:24 UTC | https://www.federalreserve.gov/feeds/press_all.xml |
| N2 | SEC 新闻稿 RSS | 成功 | 2026-11-14 15:43:25 UTC | https://www.sec.gov/news/pressreleases.rss |

本脚本只发送 GET 请求，不携带任何 API Key，不包含下单、划转等写操作。

