# -*- coding: utf-8 -*-
"""
recipients_db.py — 알림 수신자 마스터 DB (이름 + 이메일).

- recipients_db.json 에 [{name, email}] 로 저장(프로젝트 폴더 기준).
- 최초에 파일이 없으면 사내 명부(QMS_메일수신자_명부_*.md) 표를 파싱해 시드.
- 화면(설정창)에서 수동 추가/삭제하면 이 DB에 병합 동기화.
⚠ 개인정보(PII) — 공개 저장소 업로드 금지(.gitignore 처리).
"""
from __future__ import annotations

import glob
import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_HERE, "recipients_db.json")
ROSTER_GLOB = os.path.join(_HERE, "QMS_메일수신자_명부_*.md")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _norm_email(e: str) -> str:
    return str(e or "").strip().lower()


def parse_roster_md(path: str) -> list[dict]:
    """명부 마크다운 표 → [{name, email}]. (이름=2열, 이메일=3열, '@' 포함 행만)"""
    out: list[dict] = []
    seen: set[str] = set()
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return out
    for ln in lines:
        s = ln.strip()
        if not s.startswith("|"):
            continue
        # | (빈) | 팀 | 이름 | 이메일 | ... → split 후 인덱스 1=팀, 2=이름, 3=이메일
        parts = [c.strip() for c in s.split("|")]
        if len(parts) < 4:
            continue
        name, email = parts[2], _norm_email(parts[3])
        if name in ("이름",) or not _EMAIL_RE.match(email):
            continue
        if email in seen:
            continue
        seen.add(email)
        out.append({"name": name, "email": parts[3].strip()})
    return out


def seed_from_roster() -> list[dict]:
    """recipients_db.json 이 없으면 최신 명부 .md 에서 시드 생성. 반환: DB 목록."""
    matches = sorted(glob.glob(ROSTER_GLOB), reverse=True)  # 최신(날짜) 우선
    db = parse_roster_md(matches[0]) if matches else []
    save_db(db)
    return db


def load_db() -> list[dict]:
    """마스터 DB 로드. 없으면 명부에서 시드(없으면 빈 목록)."""
    if not os.path.exists(DB_PATH):
        return seed_from_roster()
    try:
        with open(DB_PATH, encoding="utf-8") as f:
            data = json.load(f) or []
    except Exception:
        return []
    # 정규화: name/email 키만, 이메일 중복 제거
    out, seen = [], set()
    for r in data:
        email = _norm_email(r.get("email"))
        if not _EMAIL_RE.match(email) or email in seen:
            continue
        seen.add(email)
        out.append({"name": str(r.get("name", "")).strip(), "email": r.get("email", "").strip()})
    return out


def save_db(db: list[dict]) -> None:
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def add_recipient(name: str, email: str) -> tuple[bool, str, list[dict]]:
    """수동 추가/갱신(이메일 키). (성공, 메시지, 갱신된 DB)."""
    em = _norm_email(email)
    if not _EMAIL_RE.match(em):
        return False, "올바른 이메일 형식이 아닙니다.", load_db()
    db = load_db()
    for r in db:
        if _norm_email(r["email"]) == em:
            r["name"] = str(name or r.get("name", "")).strip()  # 이름 갱신
            save_db(db)
            return True, "기존 수신자 이름을 갱신했습니다.", db
    db.append({"name": str(name or "").strip(), "email": email.strip()})
    db.sort(key=lambda r: (r.get("name") or "", r["email"]))
    save_db(db)
    return True, "수신자가 추가되었습니다.", db


def remove_recipient(email: str) -> list[dict]:
    em = _norm_email(email)
    db = [r for r in load_db() if _norm_email(r["email"]) != em]
    save_db(db)
    return db


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    db = load_db()
    print(f"recipients_db: {len(db)}명")
    for r in db[:5]:
        print(" ", r)
