# -*- coding: utf-8 -*-
"""2026-10-22 배포 전 전체 재점검 지적 회귀 시험 — 계산·표시·운영·보안."""
from __future__ import annotations

import time

import pytest

import oot_fake_rows as F
import result_parse as rp


# ── 결과 해석 ────────────────────────────────────────────────────────────────
def test_regex_no_catastrophic_backtracking():
    t = time.time()
    for n in (2000, 20000):
        rp.parse_result("N" + " " * n + "x", "x", "")
        rp.parse_result("1" + " " * n + "미만" + " " * n + "x", "x", "")
    assert time.time() - t < 1.0


def test_thousands_in_multi_values():
    assert rp.parse_result("1,050 mg, 1,060 mg", "질량편차(1차)", "제제균일성")[0] == 1055.0


@pytest.mark.parametrize("name,stage", [("3차원 구조", None), ("12차 시험", None), ("2차 포장", None),
                                        ("13차)", None), ("함량균일성(2차)", 2), ("용출시험(S3)", 3),
                                        ("디오스민(질량편차2차)", 2), ("4 시간 후 용출률(L1)", 1)])
def test_stage_marker_only_in_parentheses(name, stage):
    assert rp.stage_of(name) == stage


def test_censored_values_never_flagged():
    assert rp.judge_z(-13.0, 0.0, 0.05, True) == 0.0       # 낮은 쪽도 이탈 아님
    assert rp.judge_z(5.0, 0.0, None, True) == 0.0


# ── 계산: 판정 z 를 표시에도, 2차 진입(표기 없는 1차) ─────────────────────────────────
def _rows_loq():
    b = F._Builder()
    for i in range(12):
        lot, d = f"24{i:03d}", F._dates(i)
        common = dict(code=F.P1, tt=F.TT_FIN, lot=lot, **d)
        b.add(group="함량", item="성분가", std="95.0 ~ 105.0 %", num=100 + (i % 3) * 0.3, **common)
        b.add(group="유연물질", item="유연물질B", std="0.5 % 이하", num=None, seq=2,
              text=("0.04 %" if i == 11 else "0.01 %" if i % 2 else "0.02 %") if i != 5 else "<0.05 %", **common)
        b.add(group="제제균일성", item="함량균일성", std="15 이하", num=4 + (i % 2), seq=3, **common)
        if i in (3, 4):
            b.add(group="제제균일성", item="함량균일성(2차)", std="15 이하", num=5.0, seq=4, **common)
    return b.rows


def test_item_z_uses_judged_z(fake_dbx):
    import kdp_core
    fake_dbx(_rows_loq())
    resp = kdp_core.oot_lot_summary(F.P1, F.TT_FIN, None)
    for lot in resp["lots"]:
        for it in lot["items"] + lot["normalItems"]:
            if it["status"] == "정상" and it["z"] is not None:
                assert abs(it["z"]) <= 2 or it.get("rules"), (lot["lot"], it)   # 정상인데 z>2 표시 없음


def test_stage_events_count_unlabeled_first_stage(fake_dbx):
    import kdp_core
    fake_dbx(_rows_loq())
    resp = kdp_core.oot_lot_summary(F.P1, F.TT_FIN, None)
    ev = resp.get("stageEvents") or []
    assert ev and ev[0]["family"] == "함량균일성"
    assert ev[0]["recentLots"] == 10                 # 12 로트 모두 1차를 했으므로 최근 10배치
    assert ev[0]["enteredLots"] == ["24003", "24004"]
    assert any("최근 10배치 중 2배치" in r for r in ev[0]["rules"]) and "연속 2배치 2차 이상 진입" in ev[0]["rules"]


# ── 운영: 보관함 읽기 오류면 덮어쓰지 않는다 ─────────────────────────────────────────
def test_alarm_skips_cycle_when_state_unreadable(monkeypatch, tmp_path):
    import kdp_core
    import oot_alarm
    import oot_mail
    import storage_io
    sent = []
    monkeypatch.setattr(storage_io, "_s3", None)
    monkeypatch.setattr(oot_alarm, "LOG_PATH", str(tmp_path / "a.log"))
    monkeypatch.setattr(oot_mail, "load_config", lambda **kw: {"enabled": True, "policy": "관리이탈만",
                                                                "recipient_groups": {F.TT_FIN: ["a@x.invalid"]}})
    monkeypatch.setattr(kdp_core, "fetch_oot_rows_for_types", lambda tts: [
        {"시험종류": F.TT_FIN, "품목코드": F.P1, "제조번호": "1", "대분류": "g", "시험항목": "i",
         "OOT_구간분류_히트맵": "관리이탈 (±3σ 초과)"}])
    monkeypatch.setattr(oot_mail, "send_oot_alert", lambda *a, **k: (sent.append(1), (True, "ok"))[1])
    saved = []
    monkeypatch.setattr(oot_alarm, "save_state", lambda keys: saved.append(keys))

    def boom(*a, **k):
        raise storage_io.StorageReadError("x")
    monkeypatch.setattr(storage_io, "read_json_strict", boom)
    oot_alarm.check_once()
    assert sent == [] and saved == []               # 메일도, 기록 덮어쓰기도 없음


def test_alarm_skips_when_config_unreadable(monkeypatch, tmp_path):
    import oot_alarm
    import oot_mail
    import storage_io
    monkeypatch.setattr(oot_alarm, "LOG_PATH", str(tmp_path / "a.log"))

    def boom(*a, **k):
        raise storage_io.StorageReadError("x")
    monkeypatch.setattr(storage_io, "read_json_strict", boom)
    called = []
    import kdp_core
    monkeypatch.setattr(kdp_core, "fetch_oot_rows_for_types", lambda tts: called.append(1) or [])
    oot_alarm.check_once()
    assert called == []                             # 설정을 못 읽으면 '수신 그룹 없음'으로 오판하지 않고 건너뜀
    assert oot_mail.load_config()["recipient_groups"] == {}   # 화면용 느슨한 읽기는 그대로


def test_recipients_db_not_reseeded_on_read_error(monkeypatch):
    import recipients_db
    import storage_io
    wrote = []
    monkeypatch.setattr(storage_io, "write_json", lambda *a, **k: wrote.append(a))

    def boom(*a, **k):
        raise storage_io.StorageReadError("x")
    monkeypatch.setattr(storage_io, "read_json_strict", boom)
    with pytest.raises(storage_io.StorageReadError):
        recipients_db.load_db()
    assert wrote == []


def test_append_text_does_not_truncate_on_read_error(monkeypatch):
    import storage_io
    wrote = []
    monkeypatch.setattr(storage_io, "write_text", lambda *a, **k: wrote.append(a))

    def boom(*a, **k):
        raise storage_io.StorageReadError("x")
    monkeypatch.setattr(storage_io, "read_text_strict", boom)
    with pytest.raises(storage_io.StorageReadError):
        storage_io.append_text("x.csv", "new")
    assert wrote == []


def test_download_error_hides_signed_url(monkeypatch):
    import databricks_client as dbx
    import requests

    class R:
        status_code = 403

    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    with pytest.raises(RuntimeError) as ei:
        dbx._download("https://bucket.example/x?X-Amz-Signature=secret")
    assert "secret" not in str(ei.value) and "https://" not in str(ei.value)


def test_alarm_log_masks_urls(monkeypatch, tmp_path):
    import oot_alarm
    monkeypatch.setattr(oot_alarm, "LOG_PATH", str(tmp_path / "a.log"))
    oot_alarm._log("실패: https://bucket.example/x?sig=secret 끝")
    assert "secret" not in (tmp_path / "a.log").read_text(encoding="utf-8")


# ── API: 품목군 삭제 관리자만 · 502 에 내부 글 없음 · 헬스체크 알람 생존 ─────────────────────
@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import dashboard_api
    import storage_io
    monkeypatch.setattr(storage_io, "_s3", None)
    monkeypatch.setenv("AXHUB_RELAY_SIGNING_SECRET", "gate-test")
    monkeypatch.setattr(dashboard_api, "_admin_tokens", {})
    return TestClient(dashboard_api.app), dashboard_api


def test_group_delete_requires_admin(client):
    c, _ = client
    assert c.post("/api/group/delete", json={"group_id": "g1"}).status_code == 403
    assert c.post("/api/group/delete", json={"group_id": "g1"},
                  headers={"X-AxHub-App-Role": "owner"}).status_code == 200


def test_502_has_no_internal_detail(client, monkeypatch):
    c, d = client
    import kdp_core

    def boom(*a, **k):
        raise RuntimeError("SELECT * FROM secret_table https://x?sig=1")
    monkeypatch.setattr(kdp_core, "oot_lot_summary", boom)
    r = c.get("/api/oot/lots?code=1&test_type=%EC%99%84%EC%A0%9C%ED%92%88")
    assert r.status_code == 502 and "secret_table" not in r.text and "sig=" not in r.text


def test_health_reports_dead_alarm(client, monkeypatch, tmp_path):
    c, d = client
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.delenv("OOT_ALARM_OFF", raising=False)
    monkeypatch.setattr(d, "_STARTED", time.time() - 3600)          # 유예 시간 지남
    assert c.get("/api/health").status_code == 200                   # 표시 파일 없음 → 판단 안 함(재시작 반복 방지)
    (tmp_path / "oot_alarm_heartbeat").write_text(str(time.time() - 3600), encoding="utf-8")
    assert c.get("/api/health").status_code == 503                   # 1시간 갱신 없음 → 알람 프로세스 정지
    (tmp_path / "oot_alarm_heartbeat").write_text(str(time.time()), encoding="utf-8")
    assert c.get("/api/health").status_code == 200
    monkeypatch.setenv("OOT_ALARM_OFF", "1")
    (tmp_path / "oot_alarm_heartbeat").write_text("0", encoding="utf-8")
    assert c.get("/api/health").status_code == 200                   # 알람을 일부러 끈 환경은 확인 안 함


def test_health_ok_during_startup_grace(client, monkeypatch, tmp_path):
    c, d = client
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.delenv("OOT_ALARM_OFF", raising=False)
    monkeypatch.setattr(d, "_STARTED", time.time())
    assert c.get("/api/health").status_code == 200


def test_no_foreign_pyproject_and_dockerignore_covers_pii():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert not os.path.exists(os.path.join(root, "pyproject.toml"))
    ig = open(os.path.join(root, ".dockerignore"), encoding="utf-8").read().split()
    assert "*.md" in ig and "network_gate.py" in ig
    gi = open(os.path.join(root, ".gitignore"), encoding="utf-8").read()
    assert "QMS_메일수신자_명부_*.md" in gi



def test_group_overwrite_requires_admin(client, monkeypatch, tmp_path):
    import dashboard_api
    import oot_group
    monkeypatch.setattr(dashboard_api, "_GROUPS", oot_group.GroupStore(tmp_path / "g.json"))
    c, _ = client
    body = {"group_id": "g1", "group_name": "g1", "member_codes": ["10001", "10002"]}
    assert c.post("/api/group", json=body).status_code == 200                 # 새로 만들기: 누구나
    assert c.post("/api/group", json=body).status_code == 403                 # 덮어쓰기: 관리자만
    assert c.post("/api/group", json=body, headers={"X-AxHub-App-Role": "owner"}).status_code == 200
    big = dict(body, group_id="g2", member_codes=[str(i) for i in range(300)])
    assert c.post("/api/group", json=big).status_code == 400


def test_settings_not_overwritten_when_store_unreadable(client, monkeypatch):
    import oot_mail
    import storage_io
    c, _ = client
    wrote = []
    monkeypatch.setattr(storage_io, "write_json", lambda *a, **k: wrote.append(a))

    def boom(*a, **k):
        raise storage_io.StorageReadError("x")
    monkeypatch.setattr(storage_io, "read_json_strict", boom)
    r = c.post("/api/alarm/config", json={"policy": "관리이탈만"}, headers={"X-AxHub-App-Role": "owner"})
    assert r.status_code == 503 and wrote == []
