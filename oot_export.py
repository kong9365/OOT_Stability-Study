# -*- coding: utf-8 -*-
"""
oot_export.py — OOT 넘김 파일(줄 단위 판정 자료 + 머리표)을 만든다. 꼴: 'oot-export/1'.

화면(/api/oot/lots)과 같은 계산(kdp_core.judge_rows)을 시험종류 7개 전체 줄에 돌려, 우리 검토
도구가 참고 자료로 받아 갈 파일을 만든다. 웹 프로세스 안에서는 계산하지 않는다(M4):
일정 흐름과 POST /api/oot/export/run 은 start_child() 로 자식 프로세스만 띄운다.
- 한 번에 하나만: 프로세스 안 잠금 + 저장소의 '도는 중' 표지(oot_export_running.json)
- 하루 한 번: 03:45 KST 이후, 그날 이미 시도했으면(oot_export_state.json 의 attempt_day) 다시 돌지 않음
- 매번 '마지막 시도' 상태(시각·성공 여부·까닭·자료 기준 시각)를 남긴다(G1)
- 판 id = 줄 파일(LF, 압축 전) sha256 앞 12자리. 같은 id 의 머리표는 덮지 않는다(G6). 7판만 남김(M5)
시각은 컨테이너 시계 설정과 상관없이 세계시+9시간(KST)으로 잰다.

실행:
  python oot_export.py                      # 지금 만들기(자료 신선도는 머리표에 기록만)
  python oot_export.py --wait-fresh         # 일정 실행: 오늘 03:37 KST 뒤 적재를 15분마다 04:45 까지 기다림
  python oot_export.py --offline <사본 폴더> --out <폴더>   # 개발용: 오프라인 사본(DuckDB)으로 폴더에
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, time as dtime, timedelta, timezone

import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import databricks_client as dbx  # noqa: E402
import kdp_core as core  # noqa: E402
import storage_io  # noqa: E402

SCHEMA = "oot-export/1"
RULE_VERSION = "2026-10-04.1"
TEST_TYPES = [t for t in core.OOT_TEST_TYPES if t in ("완제품", "의약외품(완제품)") or "안정성" in t]
KEEP = 7
KST = timezone(timedelta(hours=9))
FRESH_AFTER = dtime(3, 37)          # LIMS 적재 예정 시각(KST)
START_AT = (3, 45)                  # 일정 실행 시작(KST)
DEADLINE = dtime(4, 45)             # 이때까지 적재가 안 되면 이전 판을 그대로 둠
RETRY_SEC = 15 * 60
RUNNING_STALE_SEC = 3 * 3600
CODE_FILES = ("kdp_core.py", "oot_export.py")

LATEST, STATE, INDEX, RUNNING = ("oot_export_latest.json", "oot_export_state.json",
                                 "oot_export_index.json", "oot_export_running.json")
_ID = re.compile(r"[0-9a-f]{12}")
_TABLES = ["lims_dbo_test_request_receive", "lims_dbo_test_order_result",
           "lims_dbo_test_testitem_result", "lims_dbo_cm_item_info", "lims_dbo_qm_bizprocess_master"]
FRESH_SQL = "\nUNION ALL\n".join(
    f"SELECT '{t}' AS T, max(_ingested_at) AS M FROM `{core.LIMS_CATALOG}`.bronze.{t}" for t in _TABLES)
_COLS = ("ITEM_CD, ITEM_NM, LOT_NO, BIZPROCESS_NM, TESTITEM_NM, GROUP_NM, STANDARD_TEXT, "
         "RESULT_VALUE_NUMBER, REQUEST_DATE, LOT_DATE, EXPIRE_DATE, REQUEST_REMARK, RESULT_TEXT, "
         "RESULT_NUMBER_RAW, REQUEST_NO, REQUEST_ID, ORDER_ID, TESTITEM_ID, ORDER_SEQ, TESTITEM_SEQ, "
         "RESULT_YN, RETEST_ITEM_YN, BIZPROCESS_CD, RULE_VALUE, EXCLUDED_REASON")
_WHERE = "BIZPROCESS_NM = :tt AND ITEM_CD IS NOT NULL"
COUNT_SQL = core._RESULTS_CTE + f"SELECT count(*) AS N FROM ruled WHERE {_WHERE}"
ROWS_SQL = core._RESULTS_CTE + f"SELECT {_COLS} FROM ruled WHERE {_WHERE}"
LINE_FIELDS = (
    "item_cd", "item_nm", "test_type_cd", "test_type", "lot_no", "lot_blank", "lot_date",
    "request_date", "request_no", "request_id", "order_id", "testitem_id", "order_seq",
    "testitem_seq", "group_nm", "testitem_nm", "standard_text", "result_text", "result_number_raw",
    "value", "is_quant", "in_calc", "excluded_reason", "result_yn", "retest_yn", "mean", "sd",
    "sd_raw", "sd_floored", "z", "z_raw", "base_n", "rules", "status", "status_decided", "year")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _log(msg: str) -> None:
    print(f"[{now_utc().astimezone(KST):%Y-%m-%d %H:%M:%S} KST] oot_export: {msg}", flush=True)


# ── 저장 자리 ─────────────────────────────────────────────────────────────────
class _Store:
    """storage_io 의 넘김 파일 전용 자리(S3 'oot-export/' 또는 디스크 oot_export_files/)."""

    @property
    def mode(self) -> str:
        return storage_io.export_mode()

    def read(self, name):
        return storage_io.export_read(name)

    def write(self, name, data, content_type="application/octet-stream"):
        storage_io.export_write(name, data, content_type)

    def delete(self, name):
        storage_io.export_delete(name)


class _Folder:
    """--out 폴더(개발·오프라인 재현용). 이름 꼴 검사는 저장소와 같다."""
    mode = "folder"

    def __init__(self, path: str):
        self.path = path
        os.makedirs(path, exist_ok=True)

    def read(self, name):
        p = os.path.join(self.path, storage_io.check_export_name(name))
        if not os.path.exists(p):
            return None
        with open(p, "rb") as f:
            return f.read()

    def write(self, name, data, content_type="application/octet-stream"):
        with open(os.path.join(self.path, storage_io.check_export_name(name)), "wb") as f:
            f.write(data)

    def delete(self, name):
        p = os.path.join(self.path, storage_io.check_export_name(name))
        if os.path.exists(p):
            os.remove(p)


def _json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")


def _read_json(store, name):
    data = store.read(name)
    if data is None:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None


def write_state(store, **fields) -> None:
    state = _read_json(store, STATE) or {}
    state.update(fields)
    store.write(STATE, _json_bytes(state), "application/json")


# ── 자료 신선도 ───────────────────────────────────────────────────────────────
def _parse_ts(v):
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        dt = v
    else:
        try:
            dt = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00").replace(" ", "T", 1))
        except ValueError:
            return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def freshness(by_table: dict, now: datetime) -> tuple[str, dict]:
    """(자료 기준 시각 = 표 다섯의 최신 적재 시각 가운데 가장 이른 값, {ok, reason})."""
    times = [_parse_ts(by_table.get(t)) for t in _TABLES]
    if any(t is None for t in times):
        return "", {"ok": False, "reason": "표 적재 시각을 읽지 못했습니다"}
    as_of = min(times)
    threshold = datetime.combine(now.astimezone(KST).date(), FRESH_AFTER, tzinfo=KST)
    if as_of >= threshold:
        return _iso(as_of), {"ok": True, "reason": ""}
    return _iso(as_of), {"ok": False, "reason": f"오늘 새벽 적재가 아직 안 됨(가장 이른 적재 "
                                                 f"{as_of.astimezone(KST):%Y-%m-%d %H:%M} KST)"}


# ── 줄 만들기 ─────────────────────────────────────────────────────────────────
def _num_s(x) -> str:
    """숫자 → 반올림 전 값을 가장 짧게 되읽히는 글. 숫자가 아니면 ''."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return ""
    return "" if (math.isnan(f) or math.isinf(f)) else repr(f)


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def _line(r, tt: str, excluded: bool) -> dict:
    g = lambda c: "" if r.get(c) is None else str(r.get(c))   # noqa: E731 — CSV 글자 그대로
    out = {
        "item_cd": g("품목코드"), "item_nm": g("품목"), "test_type_cd": g("시험종류코드"),
        "test_type": tt, "lot_no": g("제조번호"), "lot_blank": "Y" if not g("제조번호").strip() else "N",
        "lot_date": g("제조일자"), "request_date": g("의뢰일자"), "request_no": g("의뢰번호"),
        "request_id": g("REQUEST_ID"), "order_id": g("ORDER_ID"), "testitem_id": g("TESTITEM_ID"),
        "order_seq": g("차수"), "testitem_seq": g("순번"), "group_nm": g("대분류"),
        "testitem_nm": g("시험항목"), "standard_text": g("시험기준"), "result_text": g("결과원문"),
        "result_number_raw": _num_s(g("저장숫자원값")), "excluded_reason": g("뺀까닭"),
        "result_yn": g("적부"), "retest_yn": g("재시험"), "year": "전체",
    }
    blank = {k: "" for k in ("value", "mean", "sd", "sd_raw", "z", "z_raw", "base_n", "rules")}
    if excluded:
        out.update(blank, is_quant="Y", in_calc="N", sd_floored="N", status="계산 제외",
                   status_decided="")
        return out
    v, mu, sd, sdr = _f(r["_v"]), _f(r["_mu"]), _f(r["_sd"]), _f(r["_sd_raw"])
    quant = _f(r["_sd_t"]) > 0
    in_calc = quant and not math.isnan(v)
    if not in_calc:
        out.update(blank, is_quant="Y" if quant else "N", in_calc="N", sd_floored="N",
                   status=("데이터부족" if quant else "정성"), status_decided=("데이터부족" if quant else ""))
        return out
    z = (v - mu) / sd if (sd > 0 and not math.isnan(mu)) else float("nan")
    zr = (v - mu) / sdr if (sdr > 0 and not math.isnan(mu)) else float("nan")
    if math.isnan(zr):
        decided = "데이터부족"
    else:
        decided = "관리이탈" if abs(zr) > 3 else ("주의" if abs(zr) > 2 else "정상")
    base_n = r["_base_n"]
    out.update(value=_num_s(v), is_quant="Y", in_calc="Y", mean=_num_s(mu), sd=_num_s(sd),
               sd_raw=_num_s(sdr), z=_num_s(z), z_raw=_num_s(zr),
               base_n="" if base_n is None else str(int(base_n)),
               sd_floored="Y" if (not math.isnan(sd) and not math.isnan(sdr) and sd > sdr + 1e-12) else "N",
               rules="|".join(r["_rules"] or []), status=str(r["_상태"]), status_decided=decided)
    return out


def lines_for(rows: list[dict], tt: str) -> list[dict]:
    """한 시험종류의 조회 줄 → 넘김 줄. 화면과 같은 CSV 변환·같은 계산(품목코드마다 judge_rows, 연도 '전체')."""
    by_code: dict[str, list] = {}
    for r in rows:
        k = core._row_to_korean(r)
        by_code.setdefault(k["품목코드"], []).append(k)
    out = []
    for code in sorted(by_code):
        text = core._rows_to_csv(by_code[code], core._FULL_FIELDS)
        pdf = pd.DataFrame(list(csv.DictReader(io.StringIO(text))))
        kept, dropped = core.split_excluded(pdf)
        judged, _info = core.judge_rows(kept, None)
        out += [_line(r, tt, False) for _, r in judged.iterrows()]
        out += [_line(r, tt, True) for _, r in dropped.iterrows()]
    return out


def _row_key(line: dict):
    return tuple((0, int(x), "") if x.isdigit() else (1, 0, x)
                 for x in (line["request_id"], line["order_id"], line["testitem_id"]))


def code_sha256(root: str = _HERE) -> str:
    """코드 판 — 줄바꿈을 LF 로 맞춘 바이트(Windows 작업 폴더와 배포본이 같은 값, G6)."""
    h = hashlib.sha256()
    for fn in CODE_FILES:
        with open(os.path.join(root, fn), "rb") as f:
            h.update(fn.encode() + b"\0" + f.read().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def build(query, by_table: dict, as_of: str, fresh: dict, now: datetime):
    """조회 → (줄 파일 바이트(LF), gzip 바이트, 머리표). 받은 줄 수가 센 줄 수와 다르면 멈춘다."""
    lines, counts, codes = [], {}, []
    for tt in TEST_TYPES:
        n_src = int(query(COUNT_SQL, {"tt": tt})[0]["N"])
        rows = query(ROWS_SQL, {"tt": tt}, large=True)
        if len(rows) != n_src:
            raise RuntimeError(f"{tt}: 받은 줄 수 {len(rows)} 가 센 줄 수 {n_src} 와 다릅니다")
        got = lines_for(rows, tt)
        del rows
        counts[tt] = {"rows": len(got), "source_rows": n_src}
        codes.append({"cd": next((x["test_type_cd"] for x in got if x["test_type_cd"]), ""), "name": tt})
        lines += got
    # 줄 열쇠순, 같으면 글자순 — 같은 자료면 언제나 같은 파일
    texts = sorted((_row_key(x), json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                   for x in lines)
    jsonl = "".join(t + "\n" for _k, t in texts).encode("utf-8")
    gz = gzip.compress(jsonl, compresslevel=9, mtime=0)
    sha = hashlib.sha256(jsonl).hexdigest()
    excluded: dict[str, int] = {}
    for x in lines:
        if x["excluded_reason"]:
            excluded[x["excluded_reason"]] = excluded.get(x["excluded_reason"], 0) + 1
    meta = {
        "schema": SCHEMA, "export_id": sha[:12], "rows_sha256": sha,
        "gz_sha256": hashlib.sha256(gz).hexdigest(),
        "row_count": len(lines), "source_row_count": sum(c["source_rows"] for c in counts.values()),
        "counts_by_test_type": counts, "excluded_counts": excluded,
        "app_only_counts": {
            "sd_floor_changed": sum(1 for x in lines if x["status"] in ("정상", "주의", "관리이탈")
                                    and x["status"] != x["status_decided"]),
            "trend": sum(1 for x in lines if x["status"] == "경향이탈")},
        "app_commit": os.environ.get("APP_COMMIT", ""), "code_sha256": code_sha256(),
        "rule_version": RULE_VERSION,
        "rules": {"applied": ["D-3①", "D-3②", "D-3③", "D-3④", "쉼표 숫자(§4.4-1)", "D-4 잠정"],
                  "undecided": ["서식 결과(§4.4-2)"]},
        "rule_note": core.RULE_NOTE,
        "data_as_of": as_of, "data_as_of_by_table": {t: str(by_table.get(t) or "") for t in _TABLES},
        "freshness": fresh, "built_at": _iso(now), "year": "전체", "test_types": codes,
        "stability_note": "안정성은 앱 화면의 시점 판정과 다름 — /api/oot/lots 계산",
    }
    return jsonl, gz, meta


# ── 저장 · 판 정리 ────────────────────────────────────────────────────────────
def _prune(store, index: list, keep: int) -> list:
    """자기가 쓴 판 목록(index)에서 오래된 것만 지운다. 판 id 꼴이 아니면 손대지 않는다."""
    index = sorted(index, key=lambda e: str(e.get("built_at", "")))
    for e in index[:-keep]:
        eid = str(e.get("export_id", ""))
        if _ID.fullmatch(eid):
            store.delete(f"oot_export_{eid}.jsonl.gz")
            store.delete(f"oot_export_{eid}.meta.json")
    return index[-keep:]


def save_version(store, meta: dict, gz: bytes, keep: int = KEEP) -> bool:
    """판을 저장한다. 새 판이면 True. 같은 판 id 가 이미 있으면 머리표를 덮지 않는다(G6)."""
    eid = meta["export_id"]
    meta_name = f"oot_export_{eid}.meta.json"
    existing = store.read(meta_name)
    if existing is not None:
        latest = _read_json(store, LATEST)
        if not latest or latest.get("export_id") != eid:
            store.write(LATEST, existing, "application/json")
        return False
    meta_bytes = _json_bytes(meta)
    store.write(f"oot_export_{eid}.jsonl.gz", gz, "application/gzip")
    store.write(meta_name, meta_bytes, "application/json")
    index = [e for e in (_read_json(store, INDEX) or []) if isinstance(e, dict)]
    index = _prune(store, index + [{"export_id": eid, "built_at": meta["built_at"]}], keep)
    store.write(INDEX, _json_bytes(index), "application/json")
    store.write(LATEST, meta_bytes, "application/json")        # 현재 판을 가리키는 파일은 맨 마지막
    return True


def run_once(store, query=None, wait_fresh: bool = False, keep: int = KEEP,
             now_fn=now_utc, sleep_fn=time.sleep) -> dict:
    """한 번 시도하고 '마지막 시도' 상태를 남긴다(성공·실패 모두)."""
    query = query or dbx.query
    attempt = {"at": _iso(now_fn()), "ok": False, "reason": "", "data_as_of": "", "export_id": "",
               "new_version": False}
    try:
        if store.mode == "s3-broken":
            raise RuntimeError("저장소(S3) 설정은 있으나 연결 준비에 실패했습니다")
        while True:
            by_table = {str(r["T"]): r["M"] for r in query(FRESH_SQL)}
            as_of, fresh = freshness(by_table, now_fn())
            attempt["data_as_of"] = as_of
            if fresh["ok"] or not wait_fresh:
                break
            if now_fn().astimezone(KST).time() >= DEADLINE:
                attempt["reason"] = f"04:45 까지 자료 적재가 안 되어 이전 판을 그대로 둠 — {fresh['reason']}"
                return _finish(store, attempt)
            sleep_fn(RETRY_SEC)
        jsonl, gz, meta = build(query, by_table, as_of, fresh, now_fn())
        meta["storage"] = store.mode
        new = save_version(store, meta, gz, keep)
        attempt.update(ok=True, export_id=meta["export_id"], new_version=new, reason=fresh["reason"])
    except Exception as e:  # 까닭을 남기고 끝낸다 — 이전 판은 그대로
        attempt["reason"] = f"{type(e).__name__}: {e}"[:500]
    return _finish(store, attempt)


def _finish(store, attempt: dict) -> dict:
    try:
        write_state(store, last_attempt=attempt)
    except Exception as e:
        _log(f"마지막 시도 상태를 쓰지 못함: {type(e).__name__}")
    _log(f"시도 끝 — 성공 {attempt['ok']} · 판 {attempt['export_id'] or '-'} · "
         f"새 판 {attempt['new_version']} · 까닭 {attempt['reason'] or '-'}")
    return attempt


# ── 한 번에 하나 · 하루 한 번 ────────────────────────────────────────────────
def _marker_fresh(marker, now: datetime) -> bool:
    t = _parse_ts((marker or {}).get("started_at"))
    return bool(t and (now - t).total_seconds() < RUNNING_STALE_SEC)


def acquire_running(store, now: datetime | None = None) -> bool:
    now = now or now_utc()
    if _marker_fresh(_read_json(store, RUNNING), now):
        return False
    store.write(RUNNING, _json_bytes({"started_at": _iso(now), "pid": os.getpid()}), "application/json")
    return True


def release_running(store) -> None:
    try:
        store.delete(RUNNING)
    except Exception as e:
        _log(f"'도는 중' 표지를 지우지 못함: {type(e).__name__}")


_child_lock = threading.Lock()
_child = None


def start_child(extra_args=(), store=None) -> str:
    """자식 프로세스로 넘김 파일 만들기를 띄운다. 이미 도는 중이면 'running', 띄우면 'started'."""
    global _child
    store = store or _Store()
    with _child_lock:
        if _child is not None and _child.poll() is None:
            return "running"
        if _marker_fresh(_read_json(store, RUNNING), now_utc()):
            return "running"
        _child = subprocess.Popen([sys.executable, os.path.join(_HERE, "oot_export.py"), *extra_args],
                                  cwd=_HERE)
        return "started"


def maybe_start_scheduled(store=None, now: datetime | None = None, start=None) -> str:
    """일정 점검 한 번: 03:45 KST 이후이고 오늘 아직 안 했으면 띄운다."""
    store = store or _Store()
    k = (now or now_utc()).astimezone(KST)
    if (k.hour, k.minute) < START_AT:
        return "not-yet"
    day = k.date().isoformat()
    if (_read_json(store, STATE) or {}).get("attempt_day") == day:
        return "done-today"
    write_state(store, attempt_day=day)          # 재시작해도 같은 날 다시 돌지 않게 먼저 적는다
    return (start or start_child)(["--wait-fresh"])


def scheduler_loop(poll_sec: int = 60) -> None:
    while True:
        try:
            maybe_start_scheduled()
        except Exception as e:
            _log(f"일정 점검 오류: {type(e).__name__}: {e}")
        time.sleep(poll_sec)


# ── 주소용 읽기(dashboard_api) ────────────────────────────────────────────────
def read_latest(store=None):
    """(현재 머리표 또는 None, 마지막 시도 상태 또는 None)."""
    store = store or _Store()
    return _read_json(store, LATEST), (_read_json(store, STATE) or {}).get("last_attempt")


def read_rows(export_id: str, store=None):
    """판 id 가 12자리 16진수가 아니거나 없으면 None."""
    if not _ID.fullmatch(export_id or ""):
        return None
    return (store or _Store()).read(f"oot_export_{export_id}.jsonl.gz")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="OOT 넘김 파일 만들기")
    ap.add_argument("--wait-fresh", action="store_true", help="오늘 새벽 적재를 04:45 까지 기다림(일정 실행)")
    ap.add_argument("--out", metavar="DIR", help="저장소 대신 이 폴더에 쓴다(개발용)")
    ap.add_argument("--offline", metavar="SNAPSHOT", help="오프라인 LIMS 사본으로 조회(DuckDB 필요, --out 과 함께)")
    ap.add_argument("--keep", type=int, default=KEEP, help=f"남길 판 수(기본 {KEEP})")
    a = ap.parse_args(argv)
    query = None
    if a.offline:
        if not a.out:
            print("--offline 은 --out 폴더와 함께 써야 합니다.")
            return 2
        try:
            import offline_dbx
            query = offline_dbx.make_query(a.offline)
        except Exception as e:
            print(f"오프라인 조회를 준비하지 못했습니다: {e}")
            return 2
    store = _Folder(a.out) if a.out else _Store()
    if not acquire_running(store):
        _log("이미 도는 중 — 이번 실행은 건너뜀")
        return 0
    try:
        res = run_once(store, query, wait_fresh=a.wait_fresh, keep=max(1, a.keep))
    finally:
        release_running(store)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
