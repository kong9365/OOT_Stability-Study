# -*- coding: utf-8 -*-
"""
offline_dbx.py — 개발용. databricks_client.query 대신 오프라인 LIMS 사본(parquet)을 DuckDB 로 읽어
같은 조회문을 돌린다. 운영 모듈은 고치지 않고 `oot_export.py --offline <사본> --out <폴더>` 로만 끼운다.
이미지에는 들어가지 않는다(.dockerignore). DuckDB 는 따로 설치해야 한다(설치는 사용자 허락 뒤).

사본 폴더 꼴: <사본>/lims_bronze/<표 이름>/part-*.parquet + _table.json(칸 이름·Databricks 꼴)
- 조회문의 `광동제약_gmp_lims`.bronze.<표> → <표>, ':이름' → '$이름'
- parquet 에 글로 저장된 decimal 칸은 _table.json 의 꼴로 되돌린다(저장 숫자의 글자 꼴을 맞추려고).
  적재 시각 같은 timestamp 칸은 ISO 글 그대로 둔다(같은 꼴이라 크기 비교가 맞음)
- 돌려주는 값은 databricks_client.query 와 같게: DATE → 'YYYY-MM-DD', TIMESTAMP → ISO 글, DECIMAL → Decimal
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone

TABLES = ["lims_dbo_test_request_receive", "lims_dbo_test_order_result",
          "lims_dbo_test_testitem_result", "lims_dbo_cm_item_info", "lims_dbo_qm_bizprocess_master"]
_CATALOG = re.compile(r"`[^`]+`\.bronze\.(\w+)")
_PARAM = re.compile(r"(?<![:\w]):(\w+)")
_CASTS = ("decimal",)


def translate(sql: str) -> str:
    """Databricks 조회문 → DuckDB 조회문(표 이름·변수 표기만 바꾼다)."""
    return _PARAM.sub(lambda m: "$" + m.group(1), _CATALOG.sub(lambda m: m.group(1), sql))


def _duckdb():
    try:
        import duckdb
    except ImportError:
        raise RuntimeError("DuckDB 가 설치되어 있지 않습니다(사용자 허락 뒤 F: 가상환경에 설치).") from None
    return duckdb


def _value(v):
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def query_on(con):
    """DuckDB 연결 위에서 databricks_client.query 와 같은 꼴로 도는 함수."""
    def _q(sql: str, params: dict | None = None, large: bool = False) -> list[dict]:
        cur = con.execute(translate(sql), {k: (None if v is None else str(v)) for k, v in (params or {}).items()})
        names = [d[0] for d in cur.description]
        return [{n: _value(v) for n, v in zip(names, row)} for row in cur.fetchall()]
    return _q


def connect(snapshot_dir: str):
    """사본의 다섯 표를 DuckDB 보기(view)로 연다."""
    con = _duckdb().connect()
    for t in TABLES:
        folder = os.path.join(snapshot_dir, "lims_bronze", t)
        with open(os.path.join(folder, "_table.json"), encoding="utf-8") as f:
            spec = json.load(f)
        casts = [f'TRY_CAST("{c["name"]}" AS {c["type"].upper()}) AS "{c["name"]}"'
                 for c in spec.get("columns", []) if str(c.get("type", "")).lower().startswith(_CASTS)]
        glob = os.path.join(folder, "*.parquet").replace("\\", "/")
        repl = f" REPLACE ({', '.join(casts)})" if casts else ""
        con.execute(f"CREATE VIEW {t} AS SELECT *{repl} FROM read_parquet('{glob}')")
    return con


def make_query(snapshot_dir: str):
    return query_on(connect(snapshot_dir))
