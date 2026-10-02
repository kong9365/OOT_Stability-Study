# -*- coding: utf-8 -*-
"""
databricks_client.py — 광동제약 GMP LIMS(Databricks) SQL Statement Execution API 클라이언트.

인증 순서(먼저 찾은 것을 사용, 서비스 계정 우선):
  1. DATABRICKS_CLIENT_ID + DATABRICKS_CLIENT_SECRET 환경변수      → 서비스 계정 OAuth M2M(운영 서버)
  2. ~/.databrickscfg 의 [lims-sp](DATABRICKS_CONFIG_PROFILE로 변경 가능) 프로필 → 서비스 계정(이 PC, 이미 설정됨)
  3. DATABRICKS_TOKEN 또는 Databricks CLI 로그인                   → DATABRICKS_ALLOW_USER_AUTH=1 명시 시에만(사람이 직접 탐색할 때)

1·2가 모두 없고 3도 허용하지 않으면 예외를 낸다(조용히 개인 인증으로 넘어가지 않음).
원본: Databricks/integration/databricks_lims_client.py (2026-09-14 서비스 계정 검증 완료).
"""
from __future__ import annotations

import configparser
import json
import os
import shutil
import subprocess
import time
from decimal import Decimal

import requests

try:  # 사내망 SSL 검사 프록시 대응: OS 인증서 저장소 신뢰(검증을 끄지 않음)
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

HOST = os.environ.get("DATABRICKS_HOST", "https://dbc-6430e2d7-1523.cloud.databricks.com").rstrip("/")
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "ec6e1860e1e62aff")
DEFAULT_PROFILE = "lims-sp"

_token = {"value": None, "expires": 0.0}
AUTH_MODE: str | None = None  # "sp-env" | "sp-profile:<name>" | "user-pat" | "user-cli"


def _service_principal_credentials() -> tuple[str, str, str] | None:
    cid, secret = os.environ.get("DATABRICKS_CLIENT_ID"), os.environ.get("DATABRICKS_CLIENT_SECRET")
    if cid and secret:
        return cid, secret, "sp-env"
    path = os.path.expanduser(os.environ.get("DATABRICKS_CONFIG_FILE", "~/.databrickscfg"))
    profile = os.environ.get("DATABRICKS_CONFIG_PROFILE", DEFAULT_PROFILE)
    if os.path.exists(path):
        cfg = configparser.ConfigParser()
        cfg.read(path, encoding="utf-8")
        if cfg.has_section(profile) and cfg[profile].get("client_id") and cfg[profile].get("client_secret"):
            host = cfg[profile].get("host", HOST).rstrip("/")
            if host != HOST:
                raise RuntimeError(f"profile [{profile}] host {host} does not match DATABRICKS_HOST {HOST}")
            return cfg[profile]["client_id"], cfg[profile]["client_secret"], f"sp-profile:{profile}"
    return None


def _get_token() -> str:
    global AUTH_MODE
    if _token["value"] and time.time() < _token["expires"] - 60:
        return _token["value"]
    sp = _service_principal_credentials()
    if sp:
        cid, secret, mode = sp
        r = requests.post(f"{HOST}/oidc/v1/token", auth=(cid, secret),
                          data={"grant_type": "client_credentials", "scope": "all-apis"}, timeout=30)
        if r.status_code in (400, 401):
            raise RuntimeError(f"서비스 계정 토큰 발급 거부(HTTP {r.status_code}, auth={mode}). "
                               "client_id/secret을 확인하거나 워크스페이스 관리자에게 시크릿 재발급을 요청하세요.")
        r.raise_for_status()
        body = r.json()
        _token.update(value=body["access_token"], expires=time.time() + int(body.get("expires_in", 3600)))
        AUTH_MODE = mode
        return _token["value"]
    if os.environ.get("DATABRICKS_ALLOW_USER_AUTH") != "1":
        raise RuntimeError(
            "Databricks 서비스 계정 자격증명을 찾지 못했습니다. DATABRICKS_CLIENT_ID/DATABRICKS_CLIENT_SECRET 환경변수를 설정하거나, "
            f"~/.databrickscfg의 [{os.environ.get('DATABRICKS_CONFIG_PROFILE', DEFAULT_PROFILE)}] 프로필에 client_id/client_secret을 추가하세요. "
            "개인 인증은 DATABRICKS_ALLOW_USER_AUTH=1(탐색 전용)일 때만 허용됩니다.")
    if os.environ.get("DATABRICKS_TOKEN"):
        _token.update(value=os.environ["DATABRICKS_TOKEN"], expires=time.time() + 3600)
        AUTH_MODE = "user-pat"
    else:
        cli = os.environ.get("DATABRICKS_CLI") or shutil.which("databricks") or os.path.expandvars(
            r"%LOCALAPPDATA%\Microsoft\WinGet\Links\databricks.exe")
        env = {k: v for k, v in os.environ.items() if k not in ("DATABRICKS_CONFIG_PROFILE", "DATABRICKS_CONFIG_FILE")}
        out = subprocess.run([cli, "auth", "token", "--host", HOST], capture_output=True, text=True, timeout=60, check=True, env=env)
        _token.update(value=json.loads(out.stdout)["access_token"], expires=time.time() + 1800)
        AUTH_MODE = "user-cli"
    return _token["value"]


def _request(method: str, url: str, **kw) -> dict:
    for attempt in range(6):
        try:
            r = requests.request(method, url, headers={"Authorization": f"Bearer {_get_token()}"}, timeout=120, **kw)
            if r.status_code == 401 and attempt == 0:
                _token["value"] = None
                continue
            if r.status_code in (429, 503):
                time.sleep(2 + attempt * 3)
                continue
            r.raise_for_status()
            return r.json()
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt == 5:
                raise
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"request failed: {method} {url}")


def _convert(value, type_name: str):
    if value is None:
        return None
    t = type_name.upper()
    if t in ("INT", "BIGINT", "SMALLINT", "TINYINT", "LONG", "SHORT", "BYTE"):
        return int(value)
    if t in ("DOUBLE", "FLOAT"):
        return float(value)
    if t == "DECIMAL":
        return Decimal(value)
    if t == "BOOLEAN":
        return value in (True, "true", "True")
    return value  # STRING, DATE('2026-09-14'), TIMESTAMP(ISO 문자열), BINARY(base64 문자열)


def query(sql: str, params: dict | None = None, large: bool = False) -> list[dict]:
    """SQL 실행 후 행을 dict 목록으로 반환. 파라미터는 :name 마커 사용. 결과 25MB 초과 예상 시 large=True."""
    body = {
        "warehouse_id": WAREHOUSE_ID,
        "statement": sql,
        "wait_timeout": "30s",
        "on_wait_timeout": "CONTINUE",
        "format": "JSON_ARRAY",
        "disposition": "EXTERNAL_LINKS" if large else "INLINE",
    }
    if params:
        body["parameters"] = [{"name": k, "value": None if v is None else str(v)} for k, v in params.items()]
    resp = _request("POST", f"{HOST}/api/2.0/sql/statements", json=body)
    sid = resp["statement_id"]
    while resp["status"]["state"] in ("PENDING", "RUNNING"):
        time.sleep(2)
        resp = _request("GET", f"{HOST}/api/2.0/sql/statements/{sid}")
    if resp["status"]["state"] != "SUCCEEDED":
        raise RuntimeError(f"statement {sid} {resp['status']['state']}: {resp['status'].get('error')}")

    columns = resp["manifest"]["schema"]["columns"]
    names = [c["name"] for c in columns]
    types = [c["type_name"] for c in columns]
    rows: list[list] = []
    chunk = resp.get("result") or {}
    while True:
        nxt = chunk.get("next_chunk_internal_link")
        if large:
            for link in chunk.get("external_links") or []:
                # 사전서명 클라우드 스토리지 URL: Databricks Authorization 헤더를 붙이지 않음
                data = requests.get(link["external_link"], timeout=300)
                data.raise_for_status()
                rows.extend(data.json())
                nxt = link.get("next_chunk_internal_link") or nxt
        else:
            rows.extend(chunk.get("data_array") or [])
        if not nxt:
            break
        chunk = _request("GET", HOST + nxt)
    expected = resp["manifest"].get("total_row_count")
    if expected is not None and expected != len(rows):
        raise RuntimeError(f"statement {sid}: expected {expected} rows, received {len(rows)}")
    return [{n: _convert(v, t) for n, v, t in zip(names, row, types)} for row in rows]


if __name__ == "__main__":
    print(query("SELECT current_user() AS me, current_date() AS today"), "auth:", AUTH_MODE)
