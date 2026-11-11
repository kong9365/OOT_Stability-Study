# -*- coding: utf-8 -*-
"""PC 가 올린 LIMS 사본으로 조회한다 — axhub 에서 Databricks 가 403 으로 막혔을 때만 쓰는 임시 길.

사내 PC 는 Databricks 를 읽을 수 있으므로, PC 가 필요한 칸만 DuckDB 파일로 만들어 앱 보관함에 올린다
(lims_upload.py). 화면(웹 프로세스)은 Databricks 를 먼저 시도하고, 403 일 때만 이 사본을 쓴다. BLOCK_SEC 뒤에는
다시 Databricks 를 시도하므로 연동이 살아나면 저절로 돌아간다. 다른 오류(SQL 오류·시간 초과)는 사본으로 넘기지 않는다.
알람(메일)과 넘김(다른 앱으로 가는 자료)은 disable() 로 사본을 쓰지 않는다. 사본은 MAX_AGE_SEC 이 지나면 쓰지 않는다.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
from datetime import date, datetime, timedelta, timezone

import storage_io

SCHEMA = "lims-snapshot/1"
LATEST = "lims_latest.json"
BLOCK_SEC = 600            # 403 뒤 이 시간 동안은 사본만 쓰고, 지나면 Databricks 를 다시 시도
CHECK_SEC = 300            # 새 사본이 올라왔는지 확인하는 간격(실패 뒤 다시 받는 간격도 같다)
STALE_SEC = 36 * 3600      # 자료 기준 시각이 이보다 오래되면 화면에 경고
MAX_AGE_SEC = 7 * 86400    # 이보다 오래된 사본은 쓰지 않는다
MAX_GZ_BYTES = 64 << 20
MAX_RAW_BYTES = 256 << 20
RUN_WAIT_SEC = 60          # 사본 조회 줄에서 기다리는 상한
_ID = re.compile(r"[0-9a-f]{12}")
_KST = timezone(timedelta(hours=9))

# 앱 조회문이 실제로 쓰는 칸만 올린다. 담당자 칸은 없지만 REQUEST_REMARK 는 자유 입력이라 내용까지 보증하지는 않는다.
COLUMNS = {
    "lims_dbo_test_request_receive": ("PLANT_CD", "REQUEST_ID", "BIZPROCESS_CD", "ITEM_CD", "REQUEST_NO", "REQUEST_DATE",
                                      "LOT_DATE", "LOT_NO", "EXPIRE_DATE", "REQUEST_REMARK", "UPDATE_TIME",
                                      "ITEM_NM_REPORT", "PLAN_ID", "_ingested_at"),
    "lims_dbo_test_order_result": ("PLANT_CD", "REQUEST_ID", "ORDER_ID", "ORDER_SEQ", "ORDER_STATUS", "RESULT_YN",
                                   "EXPIRE_DATE", "UPDATE_TIME", "_ingested_at"),
    "lims_dbo_test_testitem_result": ("PLANT_CD", "REQUEST_ID", "ORDER_ID", "TESTITEM_ID", "TESTITEM_SEQ", "GROUP_NM",
                                      "TESTITEM_NM", "STANDARD_TEXT", "RESULT_VALUE", "RESULT_YN", "RETEST_ITEM_YN",
                                      "UPDATE_TIME", "RESULT_VALUE_NUMBER", "_ingested_at"),
    "lims_dbo_cm_item_info": ("PLANT_CD", "ITEM_CD", "ITEM_NM", "UPDATE_TIME", "_ingested_at"),
    "lims_dbo_qm_bizprocess_master": ("PLANT_CD", "BIZPROCESS_CD", "BIZPROCESS_NM", "UPDATE_TIME", "_ingested_at"),
    "lims_dbo_st_stability_plan": ("PLANT_CD", "PLAN_ID", "ITEM_CD", "LOT_NO", "LOT_DATE", "EXPIRE_DATE", "UPDATE_TIME",
                                   "STABILITY_TEST_STATUS", "END_TYPE", "ORDER_ID", "_ingested_at"),
    "lims_dbo_st_stability_schedule": ("PLANT_CD", "PLAN_ID", "SCHEDULE_NUM", "SCHEDULE_PERIOD", "SCHEDULE_DATE",
                                       "SCHEDULE_STATUS", "REQUEST_ID", "UPDATE_TIME", "_ingested_at"),
}

_CATALOG = re.compile(r"`[^`]+`\.bronze\.(\w+)")
_PARAM = re.compile(r"(?<![:\w]):(\w+)")

_lock = threading.Lock()         # 아래 상태 값을 잠깐 읽고 바꿀 때만. 내려받는 동안 잡지 않는다.
_first_load = threading.Lock()   # 열어 둔 사본이 없을 때의 첫 적재만 줄 세운다
_run = threading.Semaphore(1)    # 사본 조회는 한 번에 하나(메모리·CPU)
_thread = threading.local()      # 스레드별 직전 조회의 실제 출처
_blocked_until = 0.0
_con = None
_meta: dict = {}
_checked = 0.0
_failed_at = 0.0
_refreshing = False
_answered_from_snapshot = False
_disabled = False


class SnapshotUnavailable(RuntimeError):
    """올라온 사본이 없거나 쓸 수 없다."""


def translate(sql: str) -> str:
    """Databricks 조회문 → DuckDB 조회문(표 이름·변수 표기만 바꾼다)."""
    return _PARAM.sub(lambda m: "$" + m.group(1), _CATALOG.sub(lambda m: m.group(1), sql))


def _value(v):
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def _dir() -> str:
    d = os.path.join(os.environ.get("TMPDIR") or tempfile.gettempdir(), "lims_snapshot")
    os.makedirs(d, exist_ok=True)
    return d


def _as_of(meta: dict) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(meta.get("data_as_of") or ""))
    except ValueError:
        return None
    return t if t.tzinfo else None


def _age_sec(meta: dict) -> float | None:
    t = _as_of(meta)
    return None if t is None else time.time() - t.timestamp()


def _expired(meta: dict) -> bool:
    age = _age_sec(meta)
    return age is None or age > MAX_AGE_SEC


def _fetch(meta: dict) -> str:
    """사본을 받아 크기·해시를 확인하고 풀어 둔다. 임시 이름으로 받아 한 번에 바꾼다."""
    sid = meta["id"]
    path = os.path.join(_dir(), f"lims_{sid}.duckdb")
    if os.path.exists(path):
        return path
    declared = int(meta.get("gz_bytes") or 0)
    if declared <= 0 or declared > MAX_GZ_BYTES:
        raise SnapshotUnavailable("사본 크기가 허용 범위를 벗어났습니다")
    if shutil.disk_usage(_dir()).free < declared + MAX_RAW_BYTES:
        raise SnapshotUnavailable("임시 공간이 부족합니다")
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}"
    try:
        storage_io.snapshot_download(f"lims_{sid}.duckdb.gz", tmp + ".gz")
        if os.path.getsize(tmp + ".gz") != declared:
            raise SnapshotUnavailable("사본 크기가 머리표와 다릅니다")
        h = hashlib.sha256()
        with open(tmp + ".gz", "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        if h.hexdigest() != meta.get("gz_sha256"):
            raise SnapshotUnavailable("사본 해시가 맞지 않습니다")
        written = 0
        with gzip.open(tmp + ".gz", "rb") as src, open(tmp, "wb") as dst:
            for block in iter(lambda: src.read(1 << 20), b""):
                written += len(block)
                if written > MAX_RAW_BYTES:
                    raise SnapshotUnavailable("풀린 사본이 상한보다 큽니다")
                dst.write(block)
        os.replace(tmp, path)
    finally:
        for p in (tmp, tmp + ".gz"):
            if os.path.exists(p):
                os.remove(p)
    for name in os.listdir(_dir()):      # 지금 것 말고 옛 사본은 지운다(열려 있어 못 지우면 넘어간다)
        if name.endswith(".duckdb") and name != os.path.basename(path):
            try:
                os.remove(os.path.join(_dir(), name))
            except OSError:
                pass
    return path


def _connect(path: str):
    import duckdb
    # 넘침 폴더는 연결마다 따로 — 같이 쓰면 넘침 파일 이름이 겹쳐 프로세스가 죽는다.
    spill = tempfile.mkdtemp(dir=_dir(), prefix=f"spill-{os.getpid()}-")
    con = duckdb.connect(path, read_only=True, config={"memory_limit": "192MB", "threads": "1", "temp_directory": spill,
                                                       "max_temp_directory_size": "512MiB"})
    con.execute("SET enable_external_access=false")     # 조회문으로 파일·네트워크에 닿지 못하게
    con.execute("SET lock_configuration=true")
    return con


def _refresh() -> None:
    """머리표를 읽고 판이 바뀌었으면 새 사본을 연다."""
    global _con, _meta
    raw = storage_io.snapshot_read(LATEST)
    if raw is None:
        raise SnapshotUnavailable("올라온 사본이 없습니다")
    meta = json.loads(raw.decode("utf-8"))
    if meta.get("schema") != SCHEMA or not _ID.fullmatch(str(meta.get("id", ""))) or _as_of(meta) is None:
        raise SnapshotUnavailable("사본 머리표 꼴이 맞지 않습니다")
    with _lock:
        same = _con is not None and meta["id"] == _meta.get("id")
    if same:
        return
    con = _connect(_fetch(meta))
    with _lock:
        _con, _meta = con, meta
    print(f"[자료] PC 업로드 사본 사용 — 판 {meta['id']} · 자료 기준 {meta['data_as_of']}", flush=True)


def _background_refresh() -> None:
    global _refreshing
    try:
        _refresh()
    except Exception as e:  # noqa: BLE001 — 키·서명 주소가 실릴 수 있어 종류만
        print(f"[자료] 새 사본 확인 실패({type(e).__name__}) — 열어 둔 사본을 계속 씁니다", flush=True)
    finally:
        with _lock:
            _refreshing = False


def _connection():
    """쓸 수 있는 사본 연결. 열어 둔 연결이 있으면 기다리지 않고 돌려주고, 새 판 확인은 뒤에서 한다."""
    global _checked, _refreshing, _failed_at
    with _lock:
        con, meta = _con, _meta
        if con is not None and time.time() - _checked >= CHECK_SEC and not _refreshing:
            _checked, _refreshing = time.time(), True
            threading.Thread(target=_background_refresh, daemon=True).start()
    if con is None:
        with _first_load:
            with _lock:
                con, meta = _con, _meta
            if con is None:
                if time.time() - _failed_at < CHECK_SEC:
                    raise SnapshotUnavailable("사본을 조금 전에 열지 못했습니다")
                try:
                    _refresh()
                except Exception as e:  # noqa: BLE001 — 키·서명 주소가 실릴 수 있어 종류만
                    _failed_at = time.time()
                    detail = str(e) if isinstance(e, SnapshotUnavailable) else type(e).__name__
                    raise SnapshotUnavailable(f"사본을 열지 못했습니다({detail})") from None
                with _lock:
                    con, meta = _con, _meta
                    _checked = time.time()
    if _expired(meta):
        raise SnapshotUnavailable("사본이 너무 오래되었습니다")
    return con


def in_use() -> bool:
    return not _disabled and time.time() < _blocked_until and not (_meta and _expired(_meta))


def disable() -> None:
    """이 프로세스는 사본을 쓰지 않는다(알람·넘김)."""
    global _disabled
    _disabled = True


def activate() -> bool:
    """Databricks 가 403 일 때 부른다. 쓸 수 있는 사본이 있으면 True."""
    global _blocked_until
    if _disabled:
        return False
    try:
        _connection()
    except SnapshotUnavailable as e:
        print(f"[자료] Databricks 403, 사본 사용 불가: {e}", flush=True)
        return False
    _blocked_until = time.time() + BLOCK_SEC
    return True


def mark_databricks() -> None:
    """Databricks 가 답했다 — 화면 안내를 되돌린다."""
    global _answered_from_snapshot
    _answered_from_snapshot = False
    _thread.answered = ""


def _execute(sql: str, params: dict | None):
    global _answered_from_snapshot
    cur = _connection().cursor()
    cur.execute(translate(sql), {k: (None if v is None else str(v)) for k, v in (params or {}).items()})
    _answered_from_snapshot = True
    _thread.answered = f"snap:{_meta.get('id', '')}|"
    return cur


def query(sql: str, params: dict | None = None, large: bool = False) -> list[dict]:
    if not _run.acquire(timeout=RUN_WAIT_SEC):        # 줄이 밀리면 스레드를 붙잡지 않고 실패시킨다
        raise SnapshotUnavailable("사본 조회가 밀려 있습니다. 잠시 뒤 다시 시도해 주세요")
    try:
        cur = _execute(sql, params)
        names = [d[0] for d in cur.description]
        return [{n: _value(v) for n, v in zip(names, row)} for row in cur.fetchall()]
    finally:
        _run.release()


def query_iter(sql: str, params: dict | None = None):
    cur = _execute(sql, params)
    names = [d[0] for d in cur.description]
    while True:
        rows = cur.fetchmany(2000)
        if not rows:
            return
        for row in rows:
            yield {n: _value(v) for n, v in zip(names, row)}


def cache_tag() -> str:
    """조회 결과 임시 저장의 열쇠에 붙인다 — 사본 결과가 Databricks 결과로 재사용되지 않게."""
    return f"snap:{_meta.get('id', '')}|" if in_use() else ""


def answered_tag() -> str:
    """이 스레드의 직전 조회에 실제로 답한 출처 — 조회 결과를 담을 때의 열쇠에 쓴다."""
    return getattr(_thread, "answered", "")


def as_of_date() -> date | None:
    """사본으로 답하는 중이면 자료 기준 날짜(한국). 일정 지연 판정이 '오늘' 대신 이 날짜를 쓴다."""
    t = _as_of(_meta) if _answered_from_snapshot and _meta else None
    return t.astimezone(_KST).date() if t else None


def status() -> dict:
    """화면 안내용 — 어떤 자료로 답하고 있는지(개인정보 없음)."""
    if _answered_from_snapshot and _meta:
        age = _age_sec(_meta)
        return {"source": "snapshot", "built_at": _meta.get("built_at", ""), "data_as_of": _meta.get("data_as_of", ""),
                "stale": age is None or age > STALE_SEC}
    return {"source": "databricks"}
