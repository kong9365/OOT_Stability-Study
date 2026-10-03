# -*- coding: utf-8 -*-
"""알람 발송 기록 열쇠 옮김(M3) — 지우지 않음 · 한 번만 · 되돌려도 메일이 몰리지 않음.

옛 코드는 tests/fixtures/oot_alarm_a4ef25c.py(a4ef25c 의 oot_alarm.py 그대로)로 돌린다.
메일은 보내지 않고 부른 내용만 모은다. 받는 주소는 지어낸 것이다.
"""
from __future__ import annotations

import importlib.util
import os

import pytest

import oot_fake_rows as F

HERE = os.path.dirname(os.path.abspath(__file__))
CRIT, WARN = "관리이탈 (±3σ 초과)", "주의 (±2σ~±3σ)"


def cand(tt, lot, group, item, label):
    return {"시험종류": tt, "품목": F.P1_NAME, "품목코드": F.P1, "제조번호": lot, "대분류": group,
            "시험항목": item, "LOT결과_0제외": "1", "OOT_구간분류_히트맵": label,
            "확인_평균": "0", "확인_표준편차": "1"}


A = cand(F.TT_FIN, "23010", "함량", "성분가", CRIT)
B = cand(F.TT_FIN, "23011", "함량", "성분나", WARN)
C = cand(F.TT_LT, "23002", "함량", "성분가", WARN)
D = cand(F.TT_FIN, "23001", "용출", "성분가", CRIT)     # 진짜 새 건(옛 꼴 열쇠도 기록에 없음)
E = cand(F.TT_FIN, "23010", "용출", "성분가", CRIT)     # 옛 꼴 열쇠가 A 와 같음(대분류만 다름)
G = cand(F.TT_FIN, "23011", "용출", "성분나", WARN)     # 옛 꼴 열쇠가 B 와 같음 — 옮긴 뒤에 생김


@pytest.fixture
def alarm(tmp_path, monkeypatch):
    import kdp_core
    import oot_alarm
    import oot_mail
    import storage_io

    spec = importlib.util.spec_from_file_location(
        "oot_alarm_a4ef25c", os.path.join(HERE, "fixtures", "oot_alarm_a4ef25c.py"))
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)

    state = str(tmp_path / ".oot_alarm_state.json")
    sent: list[list[dict]] = []
    box = {"cands": []}
    monkeypatch.setattr(storage_io, "_s3", None)
    for mod in (oot_alarm, old):
        monkeypatch.setattr(mod, "STATE_PATH", state)
        monkeypatch.setattr(mod, "LOG_PATH", str(tmp_path / "oot_alarm.log"))
        monkeypatch.setattr(mod, "_ensure_internet_before_send", lambda: True)
    monkeypatch.setattr(oot_mail, "load_config", lambda: {
        "enabled": True, "policy": "관리이탈·주의",
        "recipient_groups": {F.TT_FIN: ["qa@example.invalid"], F.TT_LT: ["qa@example.invalid"]}})
    monkeypatch.setattr(oot_mail, "send_oot_alert", lambda recs, **kw: (sent.append(recs), (True, "ok"))[1])
    monkeypatch.setattr(kdp_core, "fetch_oot_rows_for_types", lambda tts: [dict(c) for c in box["cands"]])

    def run(module, cands):
        box["cands"] = cands
        sent.clear()
        module.check_once()
        return sorted((r["제조번호"], r.get("대분류", ""), r["시험항목"]) for recs in sent for r in recs)

    def keys():
        return set(storage_io.read_json(state, default=[]))

    return {"new": oot_alarm, "old": old, "run": run, "keys": keys, "monkeypatch": monkeypatch}


def _old_baseline(a):
    assert a["run"](a["old"], [A, B, C]) == []            # 옛 코드 첫 실행 = 기준선
    assert a["run"](a["old"], [A, B, C]) == []
    assert "#keys-v2" not in a["keys"]()


def test_migrate_sends_only_truly_new_then_nothing(alarm):
    _old_baseline(alarm)
    before = alarm["keys"]()
    # (A) 옛 기록 + 새 코드 → 진짜 새 건(D)만
    assert alarm["run"](alarm["new"], [A, B, C, D, E]) == [("23001", "용출", "성분가")]
    after = alarm["keys"]()
    assert before <= after                                 # 옛 열쇠는 하나도 지우지 않음
    assert "#keys-v2" in after
    # 두 번째 실행 → 0건
    assert alarm["run"](alarm["new"], [A, B, C, D, E]) == []
    # 옮긴 기록 + a4ef25c 코드(되돌리기) → 0건
    assert alarm["run"](alarm["old"], [A, B, C, D, E]) == []


def test_migration_happens_only_once(alarm):
    _old_baseline(alarm)
    alarm["run"](alarm["new"], [A, B, C])
    # 옮긴 뒤 새로 생긴 건은 옛 꼴 열쇠가 기록에 있어도 새 건이다(늘 옛 꼴로 막지 않음)
    assert alarm["run"](alarm["new"], [A, B, C, G]) == [("23011", "용출", "성분나")]
    assert alarm["run"](alarm["new"], [A, B, C, G]) == []


def test_rebaseline_sends_nothing_and_keeps_old_keys(alarm):
    alarm["monkeypatch"].setattr(alarm["new"], "KEY_MODE", "rebaseline")
    _old_baseline(alarm)
    before = alarm["keys"]()
    assert alarm["run"](alarm["new"], [A, B, C, D, E]) == []     # (B) 기준선 다시 잡기 → 0건
    assert before <= alarm["keys"]()
    assert alarm["run"](alarm["new"], [A, B, C, D, E]) == []
    assert alarm["run"](alarm["old"], [A, B, C, D, E]) == []


def test_fresh_baseline_by_new_code_is_rollback_safe(alarm):
    assert alarm["run"](alarm["new"], [A, B, C, D]) == []        # 기록 없음 → 기준선
    assert "#keys-v2" in alarm["keys"]()
    assert alarm["run"](alarm["new"], [A, B, C, D]) == []
    assert alarm["run"](alarm["old"], [A, B, C, D]) == []        # 되돌려도 0건


def test_new_send_is_recorded_in_old_form_too(alarm):
    _old_baseline(alarm)
    alarm["run"](alarm["new"], [A, B, C])                        # 옮김만
    assert alarm["run"](alarm["new"], [A, B, C, D]) == [("23001", "용출", "성분가")]
    assert alarm["run"](alarm["old"], [A, B, C, D]) == []        # 새 코드가 보낸 건은 옛 코드도 본 것으로
