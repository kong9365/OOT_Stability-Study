# -*- coding: utf-8 -*-
"""알람 재시도·새 업로드 감지·과거 재판정 제외."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import oot_fake_rows as F

CRIT = "관리이탈 (±3σ 초과)"


def _at(monkeypatch, oot_alarm, hh, mm):
    monkeypatch.setattr(oot_alarm.kst, "now", lambda: datetime(2026, 11, 12, hh, mm))


@pytest.mark.parametrize("hh,mm,retry", [(7, 31, True), (21, 29, True), (21, 30, True), (21, 31, False), (23, 0, False)])
def test_retry_until_22(monkeypatch, hh, mm, retry):
    import oot_alarm
    _at(monkeypatch, oot_alarm, hh, mm)
    monkeypatch.setattr(oot_alarm, "_log", lambda *_: None)
    monkeypatch.setattr(oot_alarm, "_seconds_until_daily", lambda dt: 86400.0)
    nxt = oot_alarm._next_after_attempt(False, "07:31", 1000.0)
    assert nxt == (1000.0 + oot_alarm.RETRY_SEC if retry else 1000.0 + 86400.0)


def test_done_waits_for_tomorrow(monkeypatch):
    import oot_alarm
    monkeypatch.setattr(oot_alarm, "_seconds_until_daily", lambda dt: 86400.0)
    assert oot_alarm._next_after_attempt(True, "07:31", 1000.0) == 87400.0


def test_stale_data_does_not_check(monkeypatch):
    import oot_alarm
    ran, released = [], []
    monkeypatch.setattr(oot_alarm, "_data_fresh", lambda: False)
    monkeypatch.setattr(oot_alarm, "check_once", lambda: ran.append(1) or True)
    monkeypatch.setattr(oot_alarm.lims_snapshot, "release", lambda: released.append(1))
    assert oot_alarm._attempt() is False
    assert ran == [] and released == [1]


def test_fresh_data_checks(monkeypatch):
    import oot_alarm
    monkeypatch.setattr(oot_alarm, "_data_fresh", lambda: True)
    monkeypatch.setattr(oot_alarm, "check_once", lambda: True)
    assert oot_alarm._attempt() is True


@pytest.mark.parametrize("seen,as_of,want", [
    (None, "2026-11-11T14:09:44+09:00", True),
    ("2026-11-11T12:09:11+09:00", "2026-11-11T14:09:44+09:00", True),
    ("2026-11-11T14:09:44+09:00", "2026-11-11T14:09:44+09:00", False),
    ("2026-11-11T15:00:00+09:00", "2026-11-11T14:09:44+09:00", False),
])
def test_new_upload_detected_by_data_time(monkeypatch, seen, as_of, want):
    import oot_alarm
    monkeypatch.setattr(oot_alarm.lims_snapshot, "latest_meta", lambda: {"data_as_of": as_of})
    assert (oot_alarm._new_upload_as_of(seen) == as_of) is want


def test_no_upload(monkeypatch):
    import oot_alarm
    monkeypatch.setattr(oot_alarm.lims_snapshot, "latest_meta", lambda: None)
    assert oot_alarm._new_upload_as_of(None) is None


def test_stale_upload_is_marked_seen_without_check(monkeypatch):
    import oot_alarm
    ran = []
    monkeypatch.setattr(oot_alarm, "_data_fresh", lambda: False)
    monkeypatch.setattr(oot_alarm, "check_once", lambda: ran.append(1))
    monkeypatch.setattr(oot_alarm.lims_snapshot, "release", lambda: None)
    assert oot_alarm._check_upload() is True and ran == []


def test_upload_read_failure_retries(monkeypatch):
    import oot_alarm

    def boom():
        raise RuntimeError("x")
    monkeypatch.setattr(oot_alarm, "_data_fresh", boom)
    monkeypatch.setattr(oot_alarm, "_log", lambda *_: None)
    monkeypatch.setattr(oot_alarm.lims_snapshot, "release", lambda: None)
    assert oot_alarm._check_upload() is False


def kst_today():
    import kst
    return kst.now().date()


class _Stop(Exception):
    pass


def _main_once(monkeypatch, oot_alarm, schedule):
    """주 반복을 한 바퀴만 돌린다."""
    import sys
    import threading

    def stop(_):
        raise _Stop
    monkeypatch.delenv("OOT_ALARM_OFF", raising=False)
    monkeypatch.setattr(sys, "argv", ["oot_alarm.py"])
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    monkeypatch.setattr(oot_alarm.time, "sleep", stop)
    monkeypatch.setattr(oot_alarm, "_log", lambda *_: None)
    monkeypatch.setattr(oot_alarm, "_beat", lambda: None)
    monkeypatch.setattr(oot_alarm, "BOOT_DELAY_SEC", -1)
    monkeypatch.setattr(oot_alarm.oot_mail, "load_config", lambda **kw: {"schedule": schedule})
    with pytest.raises(_Stop):
        oot_alarm.main()


@pytest.mark.parametrize("ok,saved", [(True, ["2026-11-11T14:09:44+09:00"]), (False, [])])
def test_main_checks_new_upload_and_records_only_when_handled(monkeypatch, ok, saved):
    import oot_alarm
    got, checked = [], []
    monkeypatch.setattr(oot_alarm, "_load_seen", lambda: (True, None))
    monkeypatch.setattr(oot_alarm, "_new_upload_as_of", lambda seen: "2026-11-11T14:09:44+09:00")
    monkeypatch.setattr(oot_alarm, "_check_upload", lambda: checked.append(1) or ok)
    monkeypatch.setattr(oot_alarm, "_save_seen", got.append)
    monkeypatch.setattr(oot_alarm, "_seconds_until_daily", lambda dt: 86400.0)
    _main_once(monkeypatch, oot_alarm, {"mode": "daily", "daily_time": "07:31"})
    assert checked == [1] and got == saved


def test_main_skips_upload_check_when_seen_file_unreadable(monkeypatch):
    import oot_alarm
    monkeypatch.setattr(oot_alarm, "_load_seen", lambda: (False, None))
    monkeypatch.setattr(oot_alarm, "_new_upload_as_of", lambda seen: pytest.fail("읽지 못했는데 점검함"))
    monkeypatch.setattr(oot_alarm, "_seconds_until_daily", lambda dt: 86400.0)
    _main_once(monkeypatch, oot_alarm, {"mode": "daily", "daily_time": "07:31"})


def test_main_daily_failure_uses_retry_schedule(monkeypatch):
    import oot_alarm
    seen = []
    monkeypatch.setattr(oot_alarm, "_seconds_until_daily", lambda dt: 0.0)
    monkeypatch.setattr(oot_alarm, "_attempt", lambda: False)
    monkeypatch.setattr(oot_alarm, "_next_after_attempt", lambda done, dt, ts: seen.append(done) or ts + 1800)
    monkeypatch.setattr(oot_alarm, "_load_seen", lambda: (True, None))
    monkeypatch.setattr(oot_alarm, "_new_upload_as_of", lambda s: None)
    _main_once(monkeypatch, oot_alarm, {"mode": "daily", "daily_time": "07:31"})
    assert seen == [False]


def test_main_upload_failure_waits_with_same_limit(monkeypatch):
    import oot_alarm
    import sys
    import threading
    calls, waits = [], []
    ticks = iter([None, None, _Stop])

    def sleep(_):
        t = next(ticks)
        if t:
            raise t
    monkeypatch.delenv("OOT_ALARM_OFF", raising=False)
    monkeypatch.setattr(sys, "argv", ["oot_alarm.py"])
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    monkeypatch.setattr(oot_alarm.time, "sleep", sleep)
    monkeypatch.setattr(oot_alarm, "_log", lambda *_: None)
    monkeypatch.setattr(oot_alarm, "_beat", lambda: None)
    monkeypatch.setattr(oot_alarm, "BOOT_DELAY_SEC", -1)
    monkeypatch.setattr(oot_alarm.oot_mail, "load_config", lambda **kw: {"schedule": {"mode": "daily", "daily_time": "07:31"}})
    monkeypatch.setattr(oot_alarm, "_seconds_until_daily", lambda dt: 86400.0)
    monkeypatch.setattr(oot_alarm, "_load_seen", lambda: (True, None))
    monkeypatch.setattr(oot_alarm, "_new_upload_as_of", lambda s: "2026-11-11T14:09:44+09:00")
    monkeypatch.setattr(oot_alarm, "_check_upload", lambda: calls.append(1) or False)
    monkeypatch.setattr(oot_alarm, "_next_after_attempt", lambda done, dt, ts: waits.append(done) or ts + 1800)
    with pytest.raises(_Stop):
        oot_alarm.main()
    assert calls == [1] and waits == [False]      # 세 바퀴 돌아도 대기 시각 전에는 다시 보지 않는다


def test_main_remembers_seen_upload_in_memory(monkeypatch):
    import oot_alarm
    import sys
    import threading
    calls, seen_args = [], []
    ticks = iter([None, _Stop])

    def sleep(_):
        t = next(ticks)
        if t:
            raise t
    monkeypatch.delenv("OOT_ALARM_OFF", raising=False)
    monkeypatch.setattr(sys, "argv", ["oot_alarm.py"])
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    monkeypatch.setattr(oot_alarm.time, "sleep", sleep)
    monkeypatch.setattr(oot_alarm, "_log", lambda *_: None)
    monkeypatch.setattr(oot_alarm, "_beat", lambda: None)
    monkeypatch.setattr(oot_alarm, "BOOT_DELAY_SEC", -1)
    monkeypatch.setattr(oot_alarm.oot_mail, "load_config", lambda **kw: {"schedule": {"mode": "daily", "daily_time": "07:31"}})
    monkeypatch.setattr(oot_alarm, "_seconds_until_daily", lambda dt: 86400.0)
    monkeypatch.setattr(oot_alarm, "_load_seen", lambda: (True, None))
    monkeypatch.setattr(oot_alarm, "_new_upload_as_of", lambda s: seen_args.append(s) or ("A" if s is None else None))
    monkeypatch.setattr(oot_alarm, "_check_upload", lambda: calls.append(1) or True)
    monkeypatch.setattr(oot_alarm, "_save_seen", lambda v: None)
    with pytest.raises(_Stop):
        oot_alarm.main()
    assert calls == [1] and seen_args == [None, "A"]


def test_main_survives_broken_seen_file(monkeypatch):
    import oot_alarm

    def boom():
        raise AttributeError("x")
    monkeypatch.setattr(oot_alarm, "_load_seen", boom)
    monkeypatch.setattr(oot_alarm, "_seconds_until_daily", lambda dt: 86400.0)
    _main_once(monkeypatch, oot_alarm, {"mode": "daily", "daily_time": "07:31"})   # _Stop 까지 죽지 않음


def test_main_never_disables_snapshot(monkeypatch):
    import oot_alarm
    called = []
    monkeypatch.setattr(oot_alarm.lims_snapshot, "disable", lambda: called.append(1))
    monkeypatch.setattr(oot_alarm, "_load_seen", lambda: (True, None))
    monkeypatch.setattr(oot_alarm, "_new_upload_as_of", lambda s: None)
    monkeypatch.setattr(oot_alarm, "_seconds_until_daily", lambda dt: 86400.0)
    _main_once(monkeypatch, oot_alarm, {"mode": "daily", "daily_time": "07:31"})
    assert not called


def test_config_read_failure_keeps_schedule(monkeypatch):
    import oot_alarm
    import sys
    import threading
    resets = []
    ticks = iter([None, _Stop])
    reads = iter([{"schedule": {"mode": "daily", "daily_time": "07:31"}}] * 2 + [RuntimeError("x")] * 5)

    def sleep(_):
        t = next(ticks)
        if t:
            raise t

    def cfg(**kw):
        v = next(reads)
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.delenv("OOT_ALARM_OFF", raising=False)
    monkeypatch.setattr(sys, "argv", ["oot_alarm.py"])
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    monkeypatch.setattr(oot_alarm.time, "sleep", sleep)
    monkeypatch.setattr(oot_alarm, "_log", lambda *_: None)
    monkeypatch.setattr(oot_alarm, "_beat", lambda: None)
    monkeypatch.setattr(oot_alarm, "BOOT_DELAY_SEC", 3600)
    monkeypatch.setattr(oot_alarm.oot_mail, "load_config", cfg)
    monkeypatch.setattr(oot_alarm, "_seconds_until_daily", lambda dt: resets.append(dt) or 86400.0)
    with pytest.raises(_Stop):
        oot_alarm.main()
    assert resets == ["07:31"]                    # 읽기 실패를 일정 변경으로 보지 않는다


def _fresh_rows(ts):
    import oot_export
    return [{"T": t, "M": ts} for t in oot_export._TABLES]


def test_data_fresh_requires_today_load(monkeypatch):
    import oot_alarm
    import oot_export
    from datetime import timezone
    monkeypatch.setattr(oot_alarm, "_log", lambda *_: None)
    monkeypatch.setattr(oot_export, "now_utc", lambda: datetime(2026, 11, 11, 3, 0, tzinfo=timezone.utc))   # 12:00 KST
    monkeypatch.setattr(oot_alarm.core.dbx, "query", lambda sql, params=None: _fresh_rows("2026-11-10T19:00:00Z"))  # 04:00 KST
    assert oot_alarm._data_fresh() is True
    monkeypatch.setattr(oot_alarm.core.dbx, "query", lambda sql, params=None: _fresh_rows("2026-11-10T17:00:00Z"))  # 02:00 KST
    assert oot_alarm._data_fresh() is False


def test_check_upload_releases_snapshot(monkeypatch):
    import oot_alarm
    released = []
    monkeypatch.setattr(oot_alarm, "_data_fresh", lambda: True)
    monkeypatch.setattr(oot_alarm, "check_once", lambda: True)
    monkeypatch.setattr(oot_alarm.lims_snapshot, "release", lambda: released.append(1))
    assert oot_alarm._check_upload() is True and released == [1]


def test_alarm_query_carries_update_date(monkeypatch):
    import kdp_core
    assert "ttr.UPDATE_TIME AS RESULT_UPDATE_TIME" in kdp_core._OOT_CTE_ALARM
    rows = [{"ITEM_CD": F.P1, "ITEM_NM": F.P1_NAME, "LOT_NO": f"L{i}", "BIZPROCESS_NM": F.TT_FIN, "GROUP_NM": "g",
             "TESTITEM_NM": "i", "RULE_VALUE": 100.0 + (i % 3) * 0.1, "RESULT_TEXT": "", "RESULT_YN": "Y",
             "EXCLUDED_REASON": "", "REQUEST_NO": "", "RESULT_UPDATE_TIME": "2026-01-01T00:00:00Z"} for i in range(20)]
    rows.append({**rows[0], "LOT_NO": "BAD", "RULE_VALUE": 200.0, "RESULT_UPDATE_TIME": "2026-11-10T09:30:00Z"})
    seen = []
    monkeypatch.setattr(kdp_core.dbx, "query_iter", lambda sql, params=None: iter(seen.append(sql) or rows))
    out = kdp_core.fetch_oot_rows_for_types([F.TT_FIN])
    assert "RESULT_UPDATE_TIME" in seen[0].rsplit("FROM ruled", 1)[0].rsplit("SELECT", 1)[1]
    assert [o["수정일"] for o in out if o["제조번호"] == "BAD"] == ["2026-11-10"]


def test_interval_mode_also_requires_fresh_data(monkeypatch):
    import oot_alarm
    attempts = []
    monkeypatch.setattr(oot_alarm, "_attempt", lambda: attempts.append(1) or False)
    monkeypatch.setattr(oot_alarm, "check_once", lambda: pytest.fail("신선도 확인 없이 점검함"))
    _main_once(monkeypatch, oot_alarm, {"mode": "interval", "interval_min": 10})
    assert attempts == [1]


@pytest.fixture
def run(tmp_path, monkeypatch):
    import kdp_core
    import oot_alarm
    import oot_mail
    import storage_io
    sent = []
    box = {}
    state = str(tmp_path / "s.json")
    monkeypatch.setattr(oot_alarm, "_mailed", set())
    monkeypatch.setattr(oot_alarm, "_fails", {})
    monkeypatch.setattr(oot_alarm, "BOOTSTRAP_LAST_OK", kst_today())   # 표지 없음 = 기본 7일(첫 배포 시험은 따로)
    monkeypatch.setattr(storage_io, "_s3", None)
    monkeypatch.setattr(oot_alarm, "STATE_PATH", state)
    monkeypatch.setattr(oot_alarm, "LOG_PATH", str(tmp_path / "a.log"))
    monkeypatch.setattr(oot_alarm, "_ensure_internet_before_send", lambda: True)
    monkeypatch.setattr(oot_mail, "load_config", lambda **kw: {
        "enabled": True, "policy": "관리이탈만", "recipient_groups": {F.TT_FIN: ["qa@example.invalid"]}})
    monkeypatch.setattr(oot_mail, "send_oot_alert", lambda recs, **kw: (sent.append((recs, kw)), (True, "ok"))[1])
    monkeypatch.setattr(kdp_core, "fetch_oot_rows_for_types", lambda tts: [dict(c) for c in box["c"]])
    storage_io.write_json(state, [oot_alarm.KEY_MARK, oot_alarm.PARSE_MARK])

    def go(cands):
        box["c"] = cands
        sent.clear()
        assert oot_alarm.check_once() is True
        return [r["제조번호"] for recs, _ in sent for r in recs]
    go.state = lambda: set(storage_io.read_json(state, default=[]))
    go.sent = sent
    go.path = state
    return go


def _cand(lot, updated):
    return {"시험종류": F.TT_FIN, "품목": F.P1_NAME, "품목코드": F.P1, "제조번호": lot, "대분류": "g", "시험항목": "i",
            "LOT결과_0제외": "1", "OOT_구간분류_히트맵": CRIT, "확인_평균": "0", "확인_표준편차": "1", "수정일": updated}


def _days_ago(n):
    import kst
    return (kst.now().date() - timedelta(days=n)).isoformat()


def test_past_result_not_mailed(run):
    assert run([_cand("OLD", _days_ago(8)), _cand("NEW", _days_ago(0)), _cand("EDGE", _days_ago(7))]) == ["NEW", "EDGE"]


def test_missing_update_date_not_mailed(run):
    assert run([_cand("X", "")]) == []


def test_past_result_mailed_after_lims_update(run):
    assert run([_cand("OLD", _days_ago(400))]) == []
    assert not any("OLD" in k for k in run.state())       # 기록하지 않아 수정되면 다시 대상
    assert run([_cand("OLD", _days_ago(0))]) == ["OLD"]
    assert run([_cand("OLD", _days_ago(0))]) == []         # 한 번만


def test_same_key_uses_latest_update(run):
    assert run([_cand("L", _days_ago(0)), _cand("L", _days_ago(100))]) == ["L"]


def test_same_key_mails_values_of_latest_row(run):
    new, old = _cand("L", _days_ago(0)), _cand("L", _days_ago(100))
    new["LOT결과_0제외"], old["LOT결과_0제외"] = "NEW", "OLD"
    run([new, old])
    assert run.sent[0][0][0]["결과값"] == "NEW"


def _with_last_ok(run, days):
    import oot_alarm
    import storage_io
    storage_io.write_json(run.path, [oot_alarm.KEY_MARK, oot_alarm.PARSE_MARK, f"{oot_alarm.LAST_OK_MARK}{_days_ago(days)}"])


def test_outage_gap_is_not_lost(run):
    _with_last_ok(run, 20)
    assert run([_cand("GAP", _days_ago(15)), _cand("EDGE", _days_ago(21)), _cand("OLD", _days_ago(22))]) == ["GAP", "EDGE"]


def test_recent_last_ok_keeps_seven_days(run):
    _with_last_ok(run, 1)
    assert run([_cand("IN", _days_ago(7)), _cand("OUT", _days_ago(8))]) == ["IN"]


def test_finished_check_records_today(run):
    import oot_alarm
    _with_last_ok(run, 20)
    run([])
    marks = [k for k in run.state() if k.startswith(oot_alarm.LAST_OK_MARK)]
    assert marks == [f"{oot_alarm.LAST_OK_MARK}{_days_ago(0)}"]


def test_state_save_failure_does_not_resend(run, monkeypatch):
    import oot_alarm

    def boom(_):
        raise OSError("x")
    monkeypatch.setattr(oot_alarm, "save_state", boom)
    assert run([_cand("N", _days_ago(0))]) == ["N"]
    assert run([_cand("N", _days_ago(0))]) == []


def _fail_send(monkeypatch, calls):
    import oot_mail
    monkeypatch.setattr(oot_mail, "send_oot_alert", lambda recs, **kw: (calls.append(1), (False, "x"))[1])


def test_send_failure_retries_then_stops_for_the_day(run, monkeypatch):
    import oot_alarm
    import kdp_core
    calls = []
    _fail_send(monkeypatch, calls)
    monkeypatch.setattr(kdp_core, "fetch_oot_rows_for_types", lambda tts: [_cand("N", _days_ago(0))])
    results = [oot_alarm.check_once() for _ in range(5)]
    assert results == [False, False, True, True, True]
    assert len(calls) == oot_alarm.MAX_SEND_FAILS
    assert not any("N" in k and "|" in k for k in run.state() if not k.startswith("#"))   # 보낸 것으로 기록하지 않음
    assert any(k.startswith(oot_alarm.HELD_MARK) for k in run.state())                    # 미뤄 둔 표시만


def test_one_group_failure_does_not_block_others(run, monkeypatch):
    import oot_alarm
    import oot_mail
    import kdp_core
    sent = []
    monkeypatch.setattr(oot_mail, "load_config", lambda **kw: {
        "enabled": True, "policy": "관리이탈만",
        "recipient_groups": {F.TT_FIN: ["a@example.invalid"], F.TT_LT: ["b@example.invalid"]}})
    monkeypatch.setattr(oot_mail, "send_oot_alert", lambda recs, **kw: (
        sent.append(recs[0]["제조번호"]), (recs[0]["시험종류"] != F.TT_FIN, "x"))[1])
    a = _cand("A", _days_ago(0))
    monkeypatch.setattr(kdp_core, "fetch_oot_rows_for_types", lambda tts: [dict(a)])
    for _ in range(oot_alarm.MAX_SEND_FAILS):
        oot_alarm.check_once()
    b = {**_cand("B", _days_ago(0)), "시험종류": F.TT_LT}
    monkeypatch.setattr(kdp_core, "fetch_oot_rows_for_types", lambda tts: [dict(a), dict(b)])
    sent.clear()
    assert oot_alarm.check_once() is True
    assert sent == ["B"]                                   # 막힌 A 는 보내지 않고 B 는 보낸다
    assert f"{oot_alarm.LAST_OK_MARK}{_days_ago(0)}" in run.state()


def test_long_failing_group_keeps_its_backlog(run, monkeypatch):
    import oot_alarm
    import oot_mail
    import kdp_core
    ok = {"v": False}
    sent = []
    monkeypatch.setattr(oot_mail, "send_oot_alert", lambda recs, **kw: (sent.append(recs[0]["제조번호"]), (ok["v"], "x"))[1])
    monkeypatch.setattr(kdp_core, "fetch_oot_rows_for_types", lambda tts: [_cand("A", _days_ago(0))])
    for _ in range(oot_alarm.MAX_SEND_FAILS):
        oot_alarm.check_once()
    import storage_io
    st = run.state()
    assert any(k.startswith(oot_alarm.HELD_MARK) for k in st)
    assert f"{oot_alarm.LAST_OK_MARK}{_days_ago(0)}" in st           # 상한으로 그만둔 날도 표지는 오늘로 감
    # 여러 날 실패가 이어진 뒤 수신자를 고친 상황: 그 건의 수정일은 이제 9일 전이다
    monkeypatch.setattr(oot_alarm, "_fails", {})
    ok["v"] = True
    sent.clear()
    monkeypatch.setattr(kdp_core, "fetch_oot_rows_for_types", lambda tts: [_cand("A", _days_ago(9))])
    assert storage_io.read_json(run.path, default=[])
    assert oot_alarm.check_once() is True
    assert sent == ["A"]
    assert not any(k.startswith(oot_alarm.HELD_MARK) for k in run.state())


def test_first_run_without_mark_uses_bootstrap_date(run, monkeypatch):
    import oot_alarm
    from datetime import date
    monkeypatch.setattr(oot_alarm, "BOOTSTRAP_LAST_OK", date.fromisoformat(_days_ago(20)))
    assert run([_cand("GAP", _days_ago(15)), _cand("OLD", _days_ago(22))]) == ["GAP"]


def test_first_config_read_failure_does_not_crash(monkeypatch):
    import oot_alarm
    import sys
    import threading

    def boom(**kw):
        raise OSError("x")
    monkeypatch.delenv("OOT_ALARM_OFF", raising=False)
    monkeypatch.setattr(sys, "argv", ["oot_alarm.py"])
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    monkeypatch.setattr(oot_alarm.time, "sleep", lambda _: (_ for _ in ()).throw(_Stop()))
    monkeypatch.setattr(oot_alarm, "_log", lambda *_: None)
    monkeypatch.setattr(oot_alarm, "_beat", lambda: None)
    monkeypatch.setattr(oot_alarm, "BOOT_DELAY_SEC", 3600)
    monkeypatch.setattr(oot_alarm.oot_mail, "load_config", boom)
    monkeypatch.setattr(oot_alarm, "_seconds_until_daily", lambda dt: 86400.0)
    with pytest.raises(_Stop):
        oot_alarm.main()


def test_upload_not_checked_during_boot_delay(monkeypatch):
    import oot_alarm
    monkeypatch.setattr(oot_alarm, "_new_upload_as_of", lambda s: pytest.fail("기동 유예 중에 업로드 확인"))
    monkeypatch.setattr(oot_alarm, "_load_seen", lambda: pytest.fail("기동 유예 중에 업로드 확인"))
    monkeypatch.setattr(oot_alarm, "_seconds_until_daily", lambda dt: 86400.0)
    import sys
    import threading
    monkeypatch.delenv("OOT_ALARM_OFF", raising=False)
    monkeypatch.setattr(sys, "argv", ["oot_alarm.py"])
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    monkeypatch.setattr(oot_alarm.time, "sleep", lambda _: (_ for _ in ()).throw(_Stop()))
    monkeypatch.setattr(oot_alarm, "_log", lambda *_: None)
    monkeypatch.setattr(oot_alarm, "_beat", lambda: None)
    monkeypatch.setattr(oot_alarm.oot_mail, "load_config", lambda **kw: {"schedule": {"mode": "daily", "daily_time": "07:31"}})
    assert oot_alarm.BOOT_DELAY_SEC >= 60
    with pytest.raises(_Stop):
        oot_alarm.main()


def test_once_does_not_disable_snapshot(monkeypatch):
    import oot_alarm
    import sys
    called, ran = [], []
    monkeypatch.delenv("OOT_ALARM_OFF", raising=False)
    monkeypatch.setattr(sys, "argv", ["oot_alarm.py", "--once"])
    monkeypatch.setattr(oot_alarm.lims_snapshot, "disable", lambda: called.append(1))
    monkeypatch.setattr(oot_alarm, "check_once", lambda: ran.append(1) or True)
    oot_alarm.main()
    assert ran == [1] and not called


def test_send_failure_does_not_advance_last_ok(run, monkeypatch):
    import oot_alarm
    import kdp_core
    _with_last_ok(run, 20)
    _fail_send(monkeypatch, [])
    monkeypatch.setattr(kdp_core, "fetch_oot_rows_for_types", lambda tts: [_cand("N", _days_ago(0))])
    assert oot_alarm.check_once() is False
    assert f"{oot_alarm.LAST_OK_MARK}{_days_ago(20)}" in run.state()


def test_lims_failure_returns_false_without_raw_error(run, monkeypatch):
    import oot_alarm
    import kdp_core
    logs = []

    def boom(_):
        raise RuntimeError("SELECT secret_value")
    monkeypatch.setattr(kdp_core, "fetch_oot_rows_for_types", boom)
    monkeypatch.setattr(oot_alarm, "_log", logs.append)
    assert oot_alarm.check_once() is False
    assert not any("secret_value" in m for m in logs)


def test_state_read_failure_returns_false(run, monkeypatch):
    import oot_alarm
    import kdp_core

    def boom():
        raise OSError("x")
    monkeypatch.setattr(kdp_core, "fetch_oot_rows_for_types", lambda tts: [])
    monkeypatch.setattr(oot_alarm, "load_state", boom)
    assert oot_alarm.check_once() is False


def test_subject_marks_snapshot(run, monkeypatch):
    import oot_alarm
    monkeypatch.setattr(oot_alarm.lims_snapshot, "status",
                        lambda: {"source": "snapshot", "data_as_of": "2026-11-11T14:09:44+09:00"})
    run([_cand("N", _days_ago(0))])
    assert "PC 업로드 자료 기준 2026-11-11 14:09" in run.sent[0][1]["subject"]


def test_databricks_subject_unchanged(run):
    run([_cand("N", _days_ago(0))])
    assert "PC 업로드" not in run.sent[0][1]["subject"]
