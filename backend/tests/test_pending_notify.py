import pandas as pd

from stockeye.cloud import pending_notify as pn


class FakeSB:
    def __init__(self, pend, tests, cfg=()):
        self.pend, self.tests, self.cfg, self.updates = pend, tests, cfg, []

    def select(self, table, params):
        if table == "app_config":
            return [{"value": v} for v in self.cfg]
        if "test_notify_at" in params:
            return self.tests
        return self.pend

    def update(self, table, flt, patch, returning=False):
        self.updates.append((flt, patch))
        return [1]


def test_signup_and_test_sent():
    sb = FakeSB([{"user_id": "u1", "email": "a@b.c"}], [{"user_id": "u2", "ntfy_topic": "mytopic123"}], cfg=["adm-topic1"])
    sent = []
    n = pn.run(sb, ["env-topic"], send=lambda tp, t, b: sent.append((tp, t)) or True, now=pd.Timestamp("2026-10-24 12:00"))
    assert n == 2
    assert ("adm-topic1", "StockEye 가입 승인 요청") in sent and ("env-topic", "StockEye 가입 승인 요청") in sent
    assert ("mytopic123", "StockEye 테스트") in sent
    assert ({"user_id": "eq.u1"}, {"signup_notified": True, "signup_tries": 99}) in sb.updates
    assert ({"user_id": "eq.u2"}, {"test_notify_at": None}) in sb.updates


def test_failed_send_keeps_signup_pending():
    sb = FakeSB([{"user_id": "u1", "email": "a@b.c"}], [])
    n = pn.run(sb, ["t1"], send=lambda *a: False, now=pd.Timestamp("2026-10-24 12:00"))
    assert n == 0 and sb.updates == []


def test_nothing_pending():
    assert pn.run(FakeSB([], []), ["t"], send=lambda *a: True) == 0
