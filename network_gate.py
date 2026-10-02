"""
network_gate.py — 사내 캡티브 포털(Kwangdong 로그인) 자동 통과 모듈

목적:
    인터넷이 필요한 작업(구글 캘린더 등) 실행 전에, 사내망 캡티브 포털이 인터넷을
    막고 있는지 감지하고, 막혀 있으면 아이디/비밀번호로 자동 로그인해 인터넷을 연다.

핵심 아이디어(오프라인 자기검증):
    - 이 스크립트는 "사용자 PC"에서 로컬로 돈다. 포털이 인터넷을 막고 있어도 실행된다.
    - 인터넷 생존 여부는 구글 연결확인 엔드포인트(http://www.gstatic.com/generate_204)로 판정.
        · 정상: HTTP 204 + 빈 본문
        · 포털이 가로챔: 204가 아니라 포털 HTML(200/302) 이 돌아옴  → "포털 있음"
    - 로그인 후 같은 검사를 재시도하며 성공을 "스스로" 검증한다. (원격 확인 불필요)

자격증명 우선순위:
    환경변수(NET_LOGIN_ID / NET_PASSWORD) > integrated_config.json 의 network_gate 섹션
    (network_gate 에 값이 없으면 mail_settings 의 mail_login_id/mail_password 로 폴백 — 그룹웨어 계정 재사용)

단독 실행:
    python network_gate.py            # 필요 시 포털 로그인까지 (ensure)
    python network_gate.py --check    # 인터넷 생존 여부만 검사 (로그인 안 함)
    python network_gate.py --capture  # 포털이 떠 있을 때 화면/HTML 덤프 (셀렉터 튜닝용)
    python network_gate.py --headless # 브라우저 숨김
"""

from __future__ import annotations

import os
import sys
import json
import time
import logging
import datetime
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

try:
    from path_utils import get_base_path
except Exception:  # 단독 배치된 경우
    def get_base_path() -> str:
        return os.path.dirname(os.path.abspath(__file__))


# ----------------------------------------------------------------------------- 기본 설정
DEFAULT_GATE: Dict[str, Any] = {
    "enabled": True,
    # 포털을 유발시키는 순수 HTTP URL(HTTPS 아님) — 포털이 이 요청을 가로채 로그인 폼을 띄운다.
    "trigger_url": "http://www.gstatic.com/generate_204",
    # 인터넷 생존 판정용 엔드포인트들(204 + 빈본문이면 정상). 여러 개 중 하나만 통과해도 정상.
    "check_urls": [
        "http://www.gstatic.com/generate_204",
        "http://connectivitycheck.gstatic.com/generate_204",
        "http://www.msftconnecttest.com/connecttest.txt",
    ],
    "login_id": "",
    "password": "",
    "max_attempts": 3,        # 로그인+재확인 최대 시도 횟수
    "verify_retries": 6,      # 로그인 후 인터넷 복구를 기다리며 재확인하는 횟수
    "verify_interval": 2.0,   # 재확인 간격(초)
    "headless": True,
    # 폼 요소 셀렉터(포털 화면이 바뀌면 여기만 교체). 비워두면 방어적 자동탐지 사용.
    "selectors": {
        "id": "",       # 예: "input[name='userId']"
        "password": "",  # 예: "input[type='password']"
        "submit": "",   # 예: "//input[@value='Login']"
    },
}

_MSFT_EXPECTED = "Microsoft Connect Test"


def _log() -> logging.Logger:
    return logging.getLogger("network_gate")


# ----------------------------------------------------------------------------- 설정 로딩
def load_gate_config(config_file: str = "integrated_config.json") -> Dict[str, Any]:
    path = config_file
    if not os.path.isabs(path):
        path = os.path.join(get_base_path(), path)
    cfg: Dict[str, Any] = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            _log().warning("설정 파일 로딩 실패(%s) — 기본값 사용: %s", path, e)

    gate = dict(DEFAULT_GATE)
    gate["selectors"] = dict(DEFAULT_GATE["selectors"])
    user_gate = cfg.get("network_gate", {}) or {}
    for k, v in user_gate.items():
        if k == "selectors" and isinstance(v, dict):
            gate["selectors"].update(v)
        else:
            gate[k] = v

    # 자격증명 우선순위: env > network_gate > mail_settings(그룹웨어 계정 폴백)
    env_id = os.environ.get("NET_LOGIN_ID")
    env_pw = os.environ.get("NET_PASSWORD")
    if env_id:
        gate["login_id"] = env_id
    if env_pw:
        gate["password"] = env_pw
    if not gate.get("login_id"):
        gate["login_id"] = cfg.get("mail_settings", {}).get("mail_login_id", "")
    if not gate.get("password"):
        gate["password"] = cfg.get("mail_settings", {}).get("mail_password", "")
    return gate


# ----------------------------------------------------------------------------- 인터넷 검사
def _probe(url: str, timeout: float = 6.0) -> bool:
    """단일 엔드포인트로 인터넷 생존 여부 판정. True=정상, False=포털/차단/오프라인."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (network-gate connectivity check)",
                 "Cache-Control": "no-cache"},
    )
    try:
        # redirect 를 따라가지 않도록 커스텀 opener(포털은 302로 리다이렉트하는 경우가 많다)
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None  # 리다이렉트 발생 → 포털로 간주(아래 except 처리)

        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(req, timeout=timeout) as resp:
            code = resp.getcode()
            body = resp.read(256)
            if url.endswith("/generate_204"):
                return code == 204 and not body.strip()
            if "connecttest" in url:
                return code == 200 and _MSFT_EXPECTED.encode() in body
            # 그 밖의 URL: 2xx + 리다이렉트 없음이면 정상으로 간주
            return 200 <= code < 300
    except urllib.error.HTTPError as e:
        # 포털이 302/200 HTML 로 응답 → 인터넷 아님
        _log().debug("probe HTTPError %s: %s", url, e)
        return False
    except Exception as e:
        _log().debug("probe 실패 %s: %s", url, e)
        return False


def check_internet(gate: Optional[Dict[str, Any]] = None) -> bool:
    """check_urls 중 하나라도 통과하면 인터넷 정상."""
    gate = gate or DEFAULT_GATE
    for url in gate.get("check_urls", DEFAULT_GATE["check_urls"]):
        if _probe(url):
            _log().info("인터넷 정상 확인: %s", url)
            return True
    _log().info("인터넷 없음/포털 감지 (모든 check_url 실패)")
    return False


# ----------------------------------------------------------------------------- 포털 로그인
def _diag_dir() -> str:
    d = os.path.join(get_base_path(), "network_gate_diag")
    os.makedirs(d, exist_ok=True)
    return d


def _dump_page(driver, tag: str) -> None:
    """포털 화면/HTML 저장 (셀렉터 튜닝·디버깅용)."""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(_diag_dir(), f"portal_{tag}_{ts}")
    try:
        driver.save_screenshot(base + ".png")
    except Exception:
        pass
    try:
        with open(base + ".html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        _log().info("포털 화면/HTML 저장: %s.(png|html)", base)
    except Exception as e:
        _log().debug("page dump 실패: %s", e)


_PORTAL_IFRAME_HINTS = ("auth_login", "auth", "login", "captive", "webauth")


def _iframe_is_portal(driver) -> bool:
    """최상위 문서에 포털 로그인 iframe이 있는지(IP주소/auth_login 등) 판정."""
    import re
    from selenium.webdriver.common.by import By
    try:
        for fr in driver.find_elements(By.TAG_NAME, "iframe"):
            src = (fr.get_attribute("src") or "").lower()
            if not src:
                continue
            if any(h in src for h in _PORTAL_IFRAME_HINTS):
                return True
            # https://<IP>/... 형태(사내 인증 게이트웨이)
            if re.search(r"https?://\d{1,3}(\.\d{1,3}){3}", src):
                return True
    except Exception:
        pass
    return False


def _looks_like_portal(driver) -> bool:
    """현재 페이지가 캡티브 포털 로그인 화면인지 방어적으로 판정(iframe 포함)."""
    try:
        from selenium.webdriver.common.by import By
        has_pw = bool(driver.find_elements(By.CSS_SELECTOR, "input[type='password']"))
        src = (driver.page_source or "")
        markers = ("아이디", "비밀번호", "Kwangdong", "로그아웃", "Login", "login", "인증", "차단")
        if has_pw and any(m in src for m in markers):
            return True
        # 실제 폼이 iframe 안에 있는 포털(예: 121.166.x.x/auth_login.html)
        if _iframe_is_portal(driver):
            return True
        return False
    except Exception:
        return False


def _switch_into_login_frame(driver) -> bool:
    """
    로그인 폼(password 입력칸)이 있는 프레임으로 전환.
    - 최상위에 password 칸이 있으면 그대로 True.
    - 없으면 iframe들을 훑어 password 칸이 있는 프레임으로 switch (1~2단계 중첩 지원).
    성공 시 driver 는 해당 프레임 컨텍스트에 머문다. 실패 시 default_content 로 복귀 후 False.
    """
    from selenium.webdriver.common.by import By

    def _has_pw() -> bool:
        try:
            return bool(driver.find_elements(By.CSS_SELECTOR, "input[type='password']"))
        except Exception:
            return False

    driver.switch_to.default_content()
    if _has_pw():
        return True

    def _scan(depth: int) -> bool:
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        for idx in range(len(frames)):
            # 프레임 재조회(전환 후 stale 방지)
            frames2 = driver.find_elements(By.TAG_NAME, "iframe")
            if idx >= len(frames2):
                break
            try:
                driver.switch_to.frame(frames2[idx])
            except Exception:
                continue
            if _has_pw():
                return True
            if depth > 0 and _scan(depth - 1):
                return True
            driver.switch_to.parent_frame()
        return False

    if _scan(2):
        return True
    driver.switch_to.default_content()
    return False


def _find_id_field(driver):
    from selenium.webdriver.common.by import By
    # 보이는 text/이메일/텍스트류 input 중 password 가 아닌 첫 번째
    candidates = driver.find_elements(
        By.CSS_SELECTOR,
        "input[type='text'], input[type='email'], input:not([type]), input[type='id']",
    )
    for el in candidates:
        try:
            if el.is_displayed() and el.is_enabled():
                return el
        except Exception:
            continue
    return None


def _find_submit(driver):
    from selenium.webdriver.common.by import By
    xpaths = [
        "//input[@type='submit']",
        "//button[@type='submit']",
        "//*[self::button or self::a or self::input]"
        "[normalize-space(@value)='Login' or normalize-space(text())='Login'"
        " or contains(., '로그인') or contains(@class,'login') or contains(@id,'login')]",
    ]
    for xp in xpaths:
        els = driver.find_elements(By.XPATH, xp)
        for el in els:
            try:
                if el.is_displayed() and el.is_enabled():
                    return el
            except Exception:
                continue
    return None


def _build_driver(headless: bool):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    options = Options()
    for arg in (
        "--disable-gpu", "--no-sandbox", "--ignore-ssl-errors",
        "--ignore-certificate-errors", "--ignore-certificate-errors-spki-list",
        "--allow-running-insecure-content", "--disable-dev-shm-usage",
        "--window-size=1280,900",
    ):
        options.add_argument(arg)
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-features=CalculateNativeWinOcclusion")
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(30)
    return driver


def login_portal(gate: Dict[str, Any], capture_only: bool = False) -> bool:
    """포털에 접속해 로그인 시도. capture_only=True 면 로그인 없이 화면만 덤프."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    login_id = gate.get("login_id") or ""
    password = gate.get("password") or ""
    if not capture_only and (not login_id or not password):
        _log().error("포털 자격증명이 없습니다. NET_LOGIN_ID/NET_PASSWORD 또는 "
                     "config.network_gate.login_id/password 를 설정하세요.")
        return False

    sel = gate.get("selectors", {})
    driver = None
    try:
        driver = _build_driver(gate.get("headless", True))
        _log().info("포털 유발 URL 접속: %s", gate.get("trigger_url"))
        try:
            driver.get(gate.get("trigger_url", DEFAULT_GATE["trigger_url"]))
        except Exception as e:
            _log().debug("trigger_url 로딩 예외(포털 리다이렉트일 수 있음): %s", e)

        # 폼(최상위 password) 또는 포털 iframe 이 나타날 때까지 잠깐 대기
        try:
            WebDriverWait(driver, 10).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, "input[type='password']")
                or d.find_elements(By.TAG_NAME, "iframe")
            )
        except Exception:
            pass

        if not _looks_like_portal(driver):
            _log().warning("포털 로그인 화면을 확인하지 못했습니다. 현재 화면 덤프 후 종료.")
            _dump_page(driver, "notportal")
            return False

        # 실제 폼은 iframe 안에 있을 수 있으므로 로그인 프레임으로 전환
        in_frame = _switch_into_login_frame(driver)
        if in_frame:
            _log().info("로그인 폼 프레임으로 전환 완료")
        else:
            _log().warning("password 입력칸이 있는 프레임을 찾지 못했습니다(최상위 문서 기준으로 진행).")

        if capture_only:
            _dump_page(driver, "capture_frame")   # 현재 컨텍스트(프레임 내부) 덤프
            driver.switch_to.default_content()
            _dump_page(driver, "capture_top")      # 최상위 문서 덤프
            return True

        # --- 필드 탐색(설정 셀렉터 우선, 없으면 자동탐지) ---
        id_el = None
        pw_el = None
        submit_el = None
        try:
            if sel.get("id"):
                id_el = driver.find_element(By.CSS_SELECTOR, sel["id"])
            if sel.get("password"):
                pw_el = driver.find_element(By.CSS_SELECTOR, sel["password"])
            if sel.get("submit"):
                by = By.XPATH if sel["submit"].strip().startswith(("/", "(")) else By.CSS_SELECTOR
                submit_el = driver.find_element(by, sel["submit"])
        except Exception as e:
            _log().debug("설정 셀렉터 탐색 실패, 자동탐지로 전환: %s", e)

        if pw_el is None:
            pw_el = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        if id_el is None:
            id_el = _find_id_field(driver)
        if submit_el is None:
            submit_el = _find_submit(driver)

        if id_el is None or pw_el is None:
            _log().error("아이디/비밀번호 입력칸을 찾지 못했습니다. 화면 덤프 후 종료.")
            _dump_page(driver, "fields_notfound")
            return False

        _log().info("자격증명 입력 (ID=%s)", login_id)
        id_el.clear(); id_el.send_keys(login_id)
        pw_el.clear(); pw_el.send_keys(password)

        if submit_el is not None:
            _log().info("Login 버튼 클릭")
            try:
                submit_el.click()
            except Exception:
                driver.execute_script("arguments[0].click();", submit_el)
        else:
            _log().info("Login 버튼 미발견 — Enter 키로 제출")
            pw_el.send_keys(Keys.ENTER)

        time.sleep(3)  # 세션 확립 대기
        return True

    except Exception as e:
        _log().error("포털 로그인 중 오류: %s", e)
        if driver is not None:
            _dump_page(driver, "error")
        return False
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


# ----------------------------------------------------------------------------- 오케스트레이션
def ensure_internet(config_file: str = "integrated_config.json",
                    gate: Optional[Dict[str, Any]] = None) -> bool:
    """
    인터넷을 확보한 뒤 True 반환. 이미 되면 즉시 True.
    포털이 막고 있으면 로그인→재확인 루프. 실패하면 False(호출측이 작업 중단하도록).
    """
    gate = gate or load_gate_config(config_file)

    if not gate.get("enabled", True):
        _log().info("network_gate 비활성화 — 인터넷 검사 스킵")
        return True

    if check_internet(gate):
        return True  # 포털 없음/이미 로그인됨

    max_attempts = int(gate.get("max_attempts", 3))
    for attempt in range(1, max_attempts + 1):
        _log().info("=== 캡티브 포털 로그인 시도 %d/%d ===", attempt, max_attempts)
        ok = login_portal(gate)
        if not ok:
            _log().warning("로그인 시도 %d 실패", attempt)
            time.sleep(2)
            continue
        # 로그인 후 인터넷 복구를 기다리며 재확인
        for i in range(int(gate.get("verify_retries", 6))):
            if check_internet(gate):
                _log().info("✅ 인터넷 확보 완료 (시도 %d)", attempt)
                return True
            time.sleep(float(gate.get("verify_interval", 2.0)))
        _log().warning("로그인은 됐으나 인터넷 재확인 실패 (시도 %d)", attempt)

    _log().error("❌ 캡티브 포털 통과 실패 — 인터넷 사용 불가. network_gate_diag 폴더의 "
                 "화면/HTML을 확인해 셀렉터/자격증명을 점검하세요.")
    return False


# ----------------------------------------------------------------------------- 단독 실행
def _setup_standalone_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="사내 캡티브 포털 자동 통과")
    ap.add_argument("--config", default="integrated_config.json")
    ap.add_argument("--check", action="store_true", help="인터넷 생존 여부만 검사")
    ap.add_argument("--capture", action="store_true", help="포털 화면/HTML 덤프(로그인 안 함)")
    ap.add_argument("--headless", action="store_true", help="브라우저 숨김")
    ap.add_argument("--show", action="store_true", help="브라우저를 화면에 표시(관찰용, headless 강제 해제)")
    args = ap.parse_args()

    _setup_standalone_logging()
    gate = load_gate_config(args.config)
    if args.headless:
        gate["headless"] = True
    if args.show:
        gate["headless"] = False

    if args.check:
        ok = check_internet(gate)
        print("INTERNET:", "OK" if ok else "BLOCKED/OFFLINE")
        return 0 if ok else 2

    if args.capture:
        ok = login_portal(gate, capture_only=True)
        return 0 if ok else 2

    ok = ensure_internet(gate=gate)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
