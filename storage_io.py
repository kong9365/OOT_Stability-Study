# -*- coding: utf-8 -*-
"""
storage_io.py — 설정/상태 파일의 영속 저장 계층.

axhub에 STORAGE_* 환경변수가 주입되면(storage: enabled: true) axhub 객체 스토리지(S3 호환)를
쓰고, 없으면(로컬 PC 실행) 기존처럼 로컬 디스크를 그대로 쓴다. 호출부는 로컬 파일 전체 경로를
그대로 넘기면 되고, 실제 저장 위치(S3 key 또는 로컬 경로)는 이 모듈이 알아서 정한다.

로컬 폴백 동작은 기존 코드와 100% 동일해서 원래 PC(run_webapp.bat/run_alarm.bat)에서는
아무 영향이 없다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_ENDPOINT = os.environ.get("STORAGE_ENDPOINT")
_BUCKET = os.environ.get("STORAGE_BUCKET")
_PREFIX = "oot-state/"

_s3 = None
if _ENDPOINT and _BUCKET:
    try:
        import boto3
        from botocore.config import Config

        _s3 = boto3.client(
            "s3",
            endpoint_url=_ENDPOINT,
            region_name="auto",
            aws_access_key_id=os.environ["STORAGE_ACCESS_KEY"],
            aws_secret_access_key=os.environ["STORAGE_SECRET_KEY"],
            config=Config(
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )
    except Exception:
        _s3 = None  # 스토리지 클라이언트 구성 실패 시 로컬 디스크로 자동 폴백


def _key(path) -> str:
    return _PREFIX + Path(path).name


def exists(path) -> bool:
    if _s3:
        try:
            _s3.head_object(Bucket=_BUCKET, Key=_key(path))
            return True
        except Exception:
            return False
    return os.path.exists(path)


def read_text(path, encoding: str = "utf-8") -> str | None:
    """없으면 None(기존 os.path.exists 가드 패턴과 동일하게 사용)."""
    if _s3:
        try:
            obj = _s3.get_object(Bucket=_BUCKET, Key=_key(path))
            return obj["Body"].read().decode(encoding)
        except Exception:
            return None
    if not os.path.exists(path):
        return None
    with open(path, encoding=encoding) as f:
        return f.read()


def write_text(path, content: str, encoding: str = "utf-8") -> None:
    if _s3:
        _s3.put_object(Bucket=_BUCKET, Key=_key(path), Body=content.encode(encoding),
                        ContentType="text/plain; charset=utf-8")
        return
    with open(path, "w", encoding=encoding) as f:
        f.write(content)


def append_text(path, content: str, encoding: str = "utf-8") -> None:
    """작은 로그/CSV용 — 기존 내용을 읽어 이어붙여 다시 쓴다(S3는 네이티브 append가 없음)."""
    prev = read_text(path, encoding=encoding) or ""
    write_text(path, prev + content, encoding=encoding)


def remove(path) -> None:
    if _s3:
        try:
            _s3.delete_object(Bucket=_BUCKET, Key=_key(path))
        except Exception:
            pass
        return
    if os.path.exists(path):
        os.remove(path)


def read_json(path, default=None):
    text = read_text(path)
    if text is None:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def write_json(path, obj) -> None:
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2))
