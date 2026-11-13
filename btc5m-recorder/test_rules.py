import unittest
import rules

NOON = 4 * 3600          # 北京时间 12:00
LATE = 14 * 3600 + 600   # 北京时间 22:10
DATA = 12 * 3600 + 1800  # 北京时间 20:30


def ev(elapsed, dev, rng=0.2, ts=NOON, prev=None):
    return rules.evaluate(elapsed, dev, rng, ts, prev)


class EvaluateTest(unittest.TestCase):
    def test_small_deviation_no_signal(self):
        r = ev(210, 0.019)
        self.assertFalse(r["signal"])
        self.assertEqual(r["side"], "up")

    def test_rows_at_first_checkpoint(self):
        self.assertEqual(ev(210, 0.03)["max_price"], 0.75)
        self.assertEqual(ev(210, -0.05)["max_price"], 0.86)
        self.assertEqual(ev(210, -0.05)["side"], "down")
        self.assertEqual(ev(210, 0.08)["max_price"], 0.91)
        self.assertFalse(ev(210, 0.12)["signal"])

    def test_rows_at_second_checkpoint(self):
        self.assertEqual(ev(240, 0.03)["max_price"], 0.80)
        self.assertEqual(ev(240, 0.05)["max_price"], 0.89)
        self.assertFalse(ev(240, 0.08)["signal"])

    def test_high_vol_uses_lower_row(self):
        self.assertFalse(ev(210, 0.03, rng=0.5)["signal"])
        r = ev(210, 0.05, rng=0.5)
        self.assertTrue(r["high_vol"])
        self.assertEqual(r["max_price"], 0.75)
        self.assertEqual(ev(240, 0.08, rng=0.5)["max_price"], 0.89)

    def test_missing_range_no_signal(self):
        self.assertFalse(ev(210, 0.05, rng=None)["signal"])

    def test_late_hour_discount(self):
        self.assertAlmostEqual(ev(210, 0.05, ts=LATE)["max_price"], 0.81)

    def test_blackout(self):
        self.assertFalse(ev(210, 0.05, ts=DATA)["signal"])

    def test_second_checkpoint_shrinking(self):
        prev = {"dev_pct": 0.06, "signal": True}
        self.assertFalse(ev(240, 0.05, prev=prev)["signal"])
        self.assertTrue(ev(240, 0.065, prev=prev)["signal"])

    def test_second_checkpoint_reversal(self):
        self.assertFalse(ev(240, -0.05, prev={"dev_pct": 0.05, "signal": True})["signal"])
        self.assertTrue(ev(240, -0.05, prev={"dev_pct": 0.01, "signal": False})["signal"])


def sig(ts, side="up", result="up", max_price=0.8, app_price=None):
    return {"round_ts": ts, "side": side, "result": result,
            "max_price": max_price, "app_price": app_price}


class OrderTest(unittest.TestCase):
    def test_threshold_fill(self):
        o = rules.order_from(sig(0))
        self.assertAlmostEqual(o["pnl"], 0.25)

    def test_app_price_fill_and_reject(self):
        self.assertAlmostEqual(rules.order_from(sig(0, app_price=0.5))["pnl"], 1.0)
        self.assertIsNone(rules.order_from(sig(0, app_price=0.85)))

    def test_loss_and_tie(self):
        self.assertEqual(rules.order_from(sig(0, result="down"))["pnl"], -1.0)
        self.assertEqual(rules.order_from(sig(0, result="tie"))["pnl"], -1.0)


class RiskTest(unittest.TestCase):
    def test_streak_pause(self):
        losses = [sig(i * 300, result="down") for i in range(3)]
        end = 2 * 300 + 300
        self.assertIsNotNone(rules.risk_block(losses, end + 10))
        self.assertIsNone(rules.risk_block(losses, end + 3601))
        self.assertIsNone(rules.risk_block(losses[:2], end))

    def test_win_resets_streak(self):
        s = [sig(0, result="down"), sig(300, result="down"), sig(600), sig(900, result="down")]
        self.assertIsNone(rules.risk_block(s, 1300))

    def test_unfilled_orders_ignored(self):
        s = [sig(i * 300, result="down", app_price=0.95) for i in range(5)]
        self.assertIsNone(rules.risk_block(s, 1600))

    def test_daily_cap(self):
        s = [sig(i * 300, result="down") for i in range(10)]
        self.assertEqual(rules.risk_block(s, 10 * 300 + 7200), "当日亏损达上限")
        self.assertIsNone(rules.risk_block(s, 10 * 300 + 86400))


if __name__ == "__main__":
    unittest.main()
