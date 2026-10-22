# -*- coding: utf-8 -*-
"""axhub 플랫폼 메일(HTTPS) — 운영에서 쓰는 메일 발송 길.

axhub 에 올라간 앱은 밖으로 HTTPS(443)만 나갈 수 있어 SMTP(587) 직접 발송은 시간 초과로 끝난다
(공식 문서 '밖으로는 HTTPS(443)만 나간다'). 그래서 플랫폼이 넣어 주는 AXHUB_API_URL·AXHUB_APP_TOKEN 이
있으면 POST {AXHUB_API_URL}/api/v1/app/mails 로 보낸다. 없으면(로컬 PC) 예전 SMTP 길을 쓴다.

플랫폼 메일은 메일 주소가 아니라 **axhub 사용자 ID** 로 보낸다. 수신자는 지금처럼 이메일로 관리하고,
이메일 → 사용자 ID 표(사용자 사전)를 보관함에 둔다. 사전은 두 길로 채운다.
  ① 앱에 들어온 사람의 SSO 머리말(X-AxHub-User-ID · X-AxHub-User-Email) — 저절로
  ② 알림설정 화면을 연 관리자의 로그인(_hub_access)으로 앱 멤버 목록 조회 — 초대된 멤버 전체
AXHUB_APP_TOKEN 은 알림·메일 발송 전용이라 멤버 조회에는 못 쓴다(②가 로그인을 쓰는 까닭).
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

import storage_io

_HERE = os.path.dirname(os.path.abspath(__file__))
DIRECTORY_PATH = os.path.join(_HERE, "user_directory.json")    # 보관함 oot-state/user_directory.json
APP_ID = os.environ.get("OOT_AXHUB_APP_ID", "4e261b39-a411-4813-8b87-7d981dab5b51")   # oot-stability-study
MAX_TO = 100              # 한 번에 보낼 사람 수 상한(플랫폼)
SUBJECT_MAX = 500         # 메일 제목 상한(플랫폼)
_TIMEOUT = 20

_lock = threading.Lock()
_dir_cache: Optional[dict] = None       # {email(소문자): {"id":..., "name":...}}
_dir_at = 0.0                           # 사전을 마지막으로 읽은 시각 — 알람 프로세스도 1분마다 새로 읽는다
_DIR_TTL = 60.0
_members_at = 0.0                       # 마지막 멤버 목록 조회 시각(10분에 한 번)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """리디렉트를 따라가지 않는다 — Authorization(앱 토큰·사용자 로그인)이 다른 곳으로 새지 않게."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def api_url() -> str:
    """AXHUB_API_URL — https 일 때만 쓴다(토큰을 평문으로 보내지 않는다)."""
    u = (os.environ.get("AXHUB_API_URL") or "").rstrip("/")
    return u if u.startswith("https://") else ""


def behind_gate() -> bool:
    """axhub 게이트 뒤에서 도는가 — 그때만 X-AxHub-* 머리말을 믿는다(로컬 실행에서는 누구나 보낼 수 있다).
    AXHUB_RELAY_SIGNING_SECRET 은 axhub 가 모든 앱에 항상 넣는 값이다."""
    return bool(os.environ.get("AXHUB_RELAY_SIGNING_SECRET"))


def available() -> bool:
    """플랫폼 메일을 쓸 수 있는가(배포된 앱에 메일 기능이 켜져 값 두 개가 들어왔을 때)."""
    return bool(api_url() and os.environ.get("AXHUB_APP_TOKEN"))


def transport_name() -> str:
    return "axhub 플랫폼 메일(HTTPS)" if available() else "SMTP(로컬)"


# ── 사용자 사전(이메일 → 사용자 ID) ──────────────────────────────────────────────
def _read_fresh() -> Optional[dict]:
    """보관함에서 새로 읽는다. 읽기 오류면 None(이때는 캐시도 저장도 하지 않는다)."""
    try:
        d = storage_io.read_json_strict(DIRECTORY_PATH, default={}) or {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return None


def _load() -> dict:
    """사전(1분 캐시). 읽기 오류면 직전 캐시를 그대로(없으면 빈 사전) 쓰되 캐시를 덮지 않는다."""
    global _dir_cache, _dir_at
    with _lock:
        if _dir_cache is not None and time.time() - _dir_at < _DIR_TTL:
            return _dir_cache
    fresh = _read_fresh()
    with _lock:
        if fresh is not None:
            _dir_cache, _dir_at = fresh, time.time()
        return _dir_cache if _dir_cache is not None else {}


def _put(entries: list[tuple[str, str, str]]) -> int:
    """(email, user_id, name) 들을 사전에 넣는다. 저장 직전에 보관함을 새로 읽어 병합하고,
    읽기 오류면 저장하지 않는다(한 번의 오류로 사전 전체가 지워지지 않게). 바뀐 수 반환."""
    global _dir_cache, _dir_at
    base = _read_fresh()
    if base is None:
        return 0
    changed = 0
    for email, uid, name in entries:
        e = str(email or "").strip().lower()
        u = str(uid or "").strip()
        if not e or not u or "@" not in e:
            continue
        cur = base.get(e) or {}
        if cur.get("id") != u or (name and cur.get("name") != name):
            base[e] = {"id": u, "name": name or cur.get("name", "")}
            changed += 1
    if changed:
        try:
            storage_io.write_json(DIRECTORY_PATH, base)
        except Exception:
            return 0
    with _lock:
        _dir_cache, _dir_at = base, time.time()
    return changed


def _b64(v: str) -> str:
    if not v:
        return ""
    try:
        return base64.b64decode(v + "=" * (-len(v) % 4)).decode("utf-8")
    except Exception:
        return ""


def remember_from_headers(headers) -> None:
    """요청 머리말(SSO)에서 본인 이메일·사용자 ID 를 사전에 넣는다. 이미 같으면 아무것도 안 한다."""
    if not behind_gate():
        return
    uid = (headers.get("x-axhub-user-id") or "").strip()
    email = _b64(headers.get("x-axhub-user-email") or "").strip().lower()
    if not uid or not email:
        return
    cur = _load().get(email) or {}
    if cur.get("id") == uid:
        return
    _put([(email, uid, _b64(headers.get("x-axhub-user-name") or ""))])


def _get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with _opener.open(req, timeout=_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def refresh_from_members(user_token: str, force: bool = False) -> tuple[int, str]:
    """관리자 로그인으로 앱 멤버 목록(이메일·사용자 ID)을 받아 사전에 넣는다. (넣은 수, 설명)."""
    global _members_at
    if not user_token or not api_url():
        return 0, "로그인 정보나 API 주소가 없어 멤버 목록을 읽지 않았습니다."
    if not force and time.time() - _members_at < 600:
        return 0, "최근에 읽었습니다."
    entries, cursor, pages = [], "", 0
    try:
        while pages < 20:
            q = {"limit": 100, **({"cursor": cursor} if cursor else {})}
            url = (f"{api_url()}/api/v1/apps/{urllib.parse.quote(APP_ID, safe='')}/members?"
                   + urllib.parse.urlencode(q))
            body = _get_json(url, user_token)
            body = body.get("data", body) if isinstance(body, dict) else {}
            for it in body.get("items") or []:
                user = it.get("user") or {}
                entries.append((it.get("email") or user.get("email"), it.get("userId") or user.get("id"),
                                user.get("name") or ""))
            cursor = body.get("nextCursor") or ""
            pages += 1
            if not cursor:
                break
    except urllib.error.HTTPError as e:
        return 0, f"앱 멤버 목록을 읽지 못했습니다(HTTP {e.code})."
    except Exception as e:  # noqa: BLE001
        return 0, f"앱 멤버 목록을 읽지 못했습니다({type(e).__name__})."
    _members_at = time.time()
    n = _put(entries)
    return n, f"앱 멤버 {len(entries)}명 확인(사전 갱신 {n}건)."


def resolve(emails: list[str]) -> tuple[list[str], list[str]]:
    """이메일 → 사용자 ID. (찾은 ID 목록, 못 찾은 이메일 목록) — 순서 보존·중복 제거."""
    d = _load()
    ids, missing, seen = [], [], set()
    for e in emails:
        k = str(e or "").strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        hit = (d.get(k) or {}).get("id")
        (ids.append(hit) if hit else missing.append(str(e).strip()))
    return ids, missing


# ── 발송 ────────────────────────────────────────────────────────────────────
def send_mail(user_ids: list[str], subject: str, html: str) -> tuple[bool, str]:
    """플랫폼 메일 발송(비동기 접수). 하나라도 접수되면 성공."""
    if not available():
        return False, "플랫폼 메일 설정(AXHUB_API_URL·AXHUB_APP_TOKEN)이 없습니다."
    if not user_ids:
        return False, "보낼 사용자 ID 가 없습니다."
    queued = failed = 0
    errs: list[str] = []
    for i in range(0, len(user_ids), MAX_TO):
        payload = json.dumps({"to": user_ids[i:i + MAX_TO], "subject": subject[:SUBJECT_MAX],
                              "html": html}).encode("utf-8")
        req = urllib.request.Request(
            f"{api_url()}/api/v1/app/mails", data=payload, method="POST",
            headers={"Authorization": f"Bearer {os.environ['AXHUB_APP_TOKEN']}",
                     "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with _opener.open(req, timeout=_TIMEOUT) as r:
                body = json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            reason = {400: "요청 형식 오류", 401: "앱 토큰 거절", 404: "받을 수 있는 사람이 없음(회사 활성 멤버 아님)",
                      429: "하루 발송 상한 초과", 503: "일시 장애"}.get(e.code, "")
            errs.append(f"HTTP {e.code} {reason}".strip())
            continue
        except Exception as e:  # noqa: BLE001
            errs.append(type(e).__name__)
            continue
        body = body.get("data", body) if isinstance(body, dict) else {}
        q = body.get("queuedCount")
        f = int(body.get("failedCount") or 0)
        queued += int(q) if q is not None else len(user_ids[i:i + MAX_TO]) - f
        failed += f
    if queued:
        return True, f"플랫폼 메일 접수 {queued}명" + (f" · 실패 {failed}명" if failed else "")
    return False, "플랫폼 메일 발송 실패: " + (", ".join(errs) or f"접수 0명(실패 {failed}명)")
