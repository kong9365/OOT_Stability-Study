# -*- coding: utf-8 -*-
"""사내 PC 에서 LIMS 를 읽어 OOT 앱 보관함에 사본을 올린다. 바탕화면 바로가기로 실행한다.

앱이 쓰는 칸만(lims_snapshot.COLUMNS), 공장 005 행만 올린다. 보관함 키는 실행할 때 axhub CLI 로
받아 메모리에서만 쓰고 파일에 적지 않는다. Databricks 는 서비스 계정으로만 읽는다(SELECT·DESCRIBE 만).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

os.environ.pop("DATABRICKS_ALLOW_USER_AUTH", None)      # 개인 인증으로 넘어가지 않게
for _k in ("STORAGE_ENDPOINT", "STORAGE_BUCKET"):       # 이 PC 에서는 보관함 모듈이 S3 를 열지 않는다
    os.environ.pop(_k, None)

import databricks_client as dbx  # noqa: E402 — 인증서 주입을 boto3 보다 먼저
import lims_snapshot as snap  # noqa: E402

APP = "oot-stability-study"
CATALOG = "광동제약_gmp_lims"
PLANT_CD = "005"
PREFIX = "lims-snapshot/"
KEEP = 3
MIN_RATIO = 0.8        # 직전 판보다 표가 20% 넘게 줄면 잘못 읽은 것으로 보고 올리지 않는다
KST = timezone(timedelta(hours=9))
CAST_CHECKS = {
    "lims_dbo_test_request_receive": ("try_cast(nullif(REQUEST_DATE,'') AS DATE)", "try_cast(nullif(LOT_DATE,'') AS DATE)",
                                      "try_cast(nullif(EXPIRE_DATE,'') AS DATE)"),
    "lims_dbo_test_testitem_result": ("try_cast(RESULT_VALUE AS DOUBLE)",
                                      "try_cast(replace(RESULT_VALUE, ',', '') AS DOUBLE)"),
}


class UploadError(RuntimeError):
    """사용자에게 그대로 보여 줄 수 있는 실패(비밀값 없음)."""


def _duck_type(databricks_type: str) -> str:
    t = databricks_type.strip().lower()
    if t.startswith("decimal"):
        return t.upper()
    if t in ("int", "integer"):
        return "INTEGER"
    if t in ("bigint", "long"):
        return "BIGINT"
    if t in ("string", "timestamp", "timestamp_ntz", "date") or t.startswith(("varchar", "char")):
        return "VARCHAR"      # 시각은 Databricks 가 준 글 그대로 둔다(앱은 글로 받아 왔다)
    raise UploadError(f"처리하지 못하는 칸 형식입니다: {databricks_type}")


def _axhub() -> str:
    home = os.path.expanduser("~/.axhub/bin/axhub.exe")
    exe = shutil.which("axhub") or (home if os.path.exists(home) else None)
    if not exe:
        raise UploadError("axhub CLI 를 찾지 못했습니다.")
    return exe


def _bucket():
    """보관함 연결. 키는 이 함수 밖 파일·화면으로 나가지 않는다."""
    r = subprocess.run([_axhub(), "apps", "storage", "status", "--app", APP, "--json"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise UploadError(f"axhub 보관함 정보를 받지 못했습니다(종료 코드 {r.returncode}). axhub 로그인 상태를 확인하세요.")
    out = json.loads(r.stdout)
    d = out.get("data", out)
    import boto3
    from botocore.config import Config
    s3 = boto3.client("s3", endpoint_url=d["endpoint"], region_name="auto",
                      aws_access_key_id=d["access_key"], aws_secret_access_key=d["secret_key"],
                      config=Config(request_checksum_calculation="when_required",
                                    response_checksum_validation="when_required"))
    return s3, d["bucket"]


def _load_table(con, table: str, cols: tuple) -> int:
    import pyarrow as pa
    full = f"`{CATALOG}`.bronze.{table}"
    types = {c["col_name"]: c["data_type"] for c in dbx.query(f"DESCRIBE TABLE {full}")}
    missing = [c for c in cols if c not in types]
    if missing:
        raise UploadError(f"{table}: 칸이 없습니다 {missing}")
    expected = int(dbx.query(f"SELECT count(*) AS N FROM {full} WHERE PLANT_CD='{PLANT_CD}'")[0]["N"])
    select = ", ".join(f"CAST(`{c}` AS STRING) AS `{c}`" for c in cols)
    data: dict[str, list] = {c: [] for c in cols}
    for row in dbx.query_iter(f"SELECT {select} FROM {full} WHERE PLANT_CD='{PLANT_CD}'"):
        for c in cols:
            data[c].append(row[c])
    got = len(data[cols[0]])
    if got != expected:
        raise UploadError(f"{table}: 행 수가 맞지 않습니다({got}/{expected})")
    staged = pa.table({c: pa.array(data[c], type=pa.string()) for c in cols})   # noqa: F841 — 아래 조회문이 이름으로 읽는다
    casts = ", ".join(f'CAST("{c}" AS {_duck_type(types[c])}) AS "{c}"' for c in cols)
    con.execute(f"CREATE TABLE {table} AS SELECT {casts} FROM staged")
    n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    if n != expected:
        raise UploadError(f"{table}: 저장 행 수가 맞지 않습니다({n}/{expected})")
    return n


def _to_kst(ingested: str) -> datetime:
    """_ingested_at(시간대 없는 UTC 글) → 한국 시각."""
    t = datetime.fromisoformat(str(ingested).strip().replace("Z", "+00:00").replace(" ", "T", 1))
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(KST)


def _check_casts(con) -> None:
    """글을 날짜·숫자로 바꾸는 규칙이 Databricks 와 DuckDB 에서 같게 나오는지 전체 건수로 대조한다."""
    for table, exprs in CAST_CHECKS.items():
        for expr in exprs:
            total = f"sum({expr})" if "DOUBLE" in expr else "0"
            sql = f"SELECT count({expr}) AS N, count(DISTINCT {expr}) AS D, {total} AS S FROM {{}} WHERE PLANT_CD='{PLANT_CD}'"
            r = dbx.query(sql.format(f"`{CATALOG}`.bronze.{table}"))[0]
            n, d, s = con.execute(sql.format(table)).fetchone()
            if (int(r["N"]), int(r["D"])) != (n, d) or not math.isclose(float(r["S"] or 0), float(s or 0), rel_tol=1e-9):
                raise UploadError(f"{table}: 값 해석이 Databricks 와 다릅니다({expr}). 올리지 않았습니다.")


def build(path: str) -> dict:
    import duckdb
    counts, as_of = {}, None
    con = duckdb.connect(path)
    try:
        for table, cols in snap.COLUMNS.items():
            t0 = time.time()
            counts[table] = _load_table(con, table, cols)
            m = con.execute(f'SELECT max("_ingested_at") FROM {table}').fetchone()[0]
            if not m:
                raise UploadError(f"{table}: 적재 시각이 없습니다.")
            t = _to_kst(m)
            as_of = t if as_of is None else min(as_of, t)      # 가장 늦게 멈춘 표 기준(넘김 판정과 같은 뜻)
            print(f"  {table}: {counts[table]:,}행 ({time.time() - t0:.0f}초)", flush=True)
        _check_casts(con)
        con.execute("CHECKPOINT")
    finally:
        con.close()
    return {"row_counts": counts, "data_as_of": as_of.isoformat(timespec="seconds")}


def _previous(s3, bucket: str) -> dict | None:
    try:
        return json.loads(s3.get_object(Bucket=bucket, Key=PREFIX + snap.LATEST)["Body"].read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        if str(getattr(e, "response", {}).get("Error", {}).get("Code", "")) in ("NoSuchKey", "404", "NotFound"):
            return None
        raise UploadError(f"직전 판을 읽지 못했습니다({type(e).__name__}). 다시 시도하세요.") from None


def _check_shrink(prev: dict | None, counts: dict) -> None:
    for table, n in ((prev or {}).get("row_counts") or {}).items():
        if counts.get(table, 0) < n * MIN_RATIO:
            raise UploadError(f"{table} 행 수가 직전 판보다 크게 줄었습니다({n:,} → {counts.get(table, 0):,}). 올리지 않았습니다.")


def _prune(s3, bucket: str, current: str) -> None:
    items = s3.list_objects_v2(Bucket=bucket, Prefix=PREFIX).get("Contents") or []
    olds = sorted((o for o in items if o["Key"].endswith(".duckdb.gz") and o["Key"] != current),
                  key=lambda o: o["LastModified"], reverse=True)
    for o in olds[KEEP - 1:]:
        s3.delete_object(Bucket=bucket, Key=o["Key"])


def main() -> int:
    if not dbx._service_principal_credentials():
        raise UploadError("이 PC 에 Databricks 서비스 계정 설정이 없습니다.")
    print("[1/4] 보관함 연결 확인", flush=True)
    s3, bucket = _bucket()
    prev = _previous(s3, bucket)
    with tempfile.TemporaryDirectory(prefix="lims_upload_") as tmp:
        db, gz = os.path.join(tmp, "lims.duckdb"), os.path.join(tmp, "lims.duckdb.gz")
        print("[2/4] LIMS 읽기", flush=True)
        info = build(db)
        _check_shrink(prev, info["row_counts"])
        if os.path.getsize(db) > snap.MAX_RAW_BYTES:
            raise UploadError("사본이 앱이 받을 수 있는 크기보다 큽니다.")
        print("[3/4] 압축", flush=True)
        with open(db, "rb") as src, gzip.GzipFile(gz, "wb", mtime=0) as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        h = hashlib.sha256()
        with open(gz, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        digest, size = h.hexdigest(), os.path.getsize(gz)
        if size > snap.MAX_GZ_BYTES:
            raise UploadError("사본이 상한보다 큽니다.")
        sid = digest[:12]
        key = f"{PREFIX}lims_{sid}.duckdb.gz"
        print(f"[4/4] 올리기 ({size / 1048576:.1f}MB)", flush=True)
        s3.upload_file(gz, bucket, key)
        if s3.head_object(Bucket=bucket, Key=key)["ContentLength"] != size:
            raise UploadError("올린 파일 크기가 맞지 않습니다.")
    built = datetime.now(KST).isoformat(timespec="seconds")
    manifest = {"schema": snap.SCHEMA, "id": sid, "gz_sha256": digest, "gz_bytes": size, "built_at": built, **info}
    s3.put_object(Bucket=bucket, Key=PREFIX + snap.LATEST, Body=json.dumps(manifest).encode("utf-8"),
                  ContentType="application/json")     # 머리표는 파일을 다 올린 뒤에 바꾼다
    _prune(s3, bucket, key)
    print(f"\n완료: {built[:16].replace('T', ' ')} 기준 자료를 올렸습니다.")
    print(f"LIMS 자료 기준 시각: {info['data_as_of'][:16].replace('T', ' ')}")
    print("앱 화면은 Databricks 가 막혀 있는 동안 몇 분 안에 이 자료로 바뀝니다. 알람 메일과 성적서 검토 앱 넘김은 이 자료를 쓰지 않습니다.")
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    try:
        raise SystemExit(main())
    except UploadError as e:
        print(f"\n실패: {e}")
        raise SystemExit(1)
    except Exception as e:  # noqa: BLE001 — 키·서명 주소가 실릴 수 있어 종류만
        print(f"\n실패({type(e).__name__}). 네트워크와 로그인을 확인하고 다시 시도하세요.")
        raise SystemExit(1)
