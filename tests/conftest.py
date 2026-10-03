# -*- coding: utf-8 -*-
"""시험 공통 준비 — 앱 폴더를 불러오기 경로에 넣고, Databricks·저장소 접속을 막는다."""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

# storage_io 는 불러올 때 S3 설정을 읽는다 — 시험은 언제나 디스크 모드.
for k in ("STORAGE_ENDPOINT", "STORAGE_BUCKET", "STORAGE_ACCESS_KEY", "STORAGE_SECRET_KEY",
          "OOT_EXPORT_KEY"):
    os.environ.pop(k, None)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """시험 중 실제 Databricks 로 나가는 길을 막는다(가짜 조회만 허용)."""
    import databricks_client as dbx

    def _blocked(*a, **k):
        raise RuntimeError("시험 중 Databricks 접속 금지")

    monkeypatch.setattr(dbx, "query", _blocked)
    monkeypatch.setattr(dbx, "_get_token", _blocked)


@pytest.fixture
def fake_dbx(monkeypatch):
    """가짜 조회 rows 를 끼우는 함수를 돌려준다. kdp_core 임시 저장은 비우고 디스크 저장은 끈다."""
    import databricks_client as dbx
    import kdp_core
    import oot_fake_rows

    monkeypatch.setattr(kdp_core, "_save_cache_disk", lambda: None)

    def _install(rows):
        kdp_core._DATA_CACHE.clear()
        monkeypatch.setattr(dbx, "query", oot_fake_rows.fake_query(rows))

    yield _install
    kdp_core._DATA_CACHE.clear()
