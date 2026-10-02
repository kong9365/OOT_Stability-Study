# 광동 OOT 품질 대시보드 — 새 PC 핸드오프 / 설치·운영 가이드

> 이 폴더 **하나만** 새 PC에 복사하면 됩니다(자립형). QMS·MISO 등 다른 폴더 불필요.
> 최신 웹 대시보드(**FastAPI + 웹, 포트 8502**) 기준입니다. (구 Streamlit 버전 아님)

---

## 0. 전제조건 (반드시 확인)
1. **사내망 연결** — 새 PC가 Tableau 서버 `tableau.ekdp.com`(사내 10.x)에 접속 가능해야 합니다(사내 LAN/VPN). 외부 인터넷만으로는 데이터 조회 불가.
2. **Python 3.13 설치** (권장) — 설치 시 **"Add Python to PATH" 체크 필수**.
   - ⚠️ **scipy가 되는 파이썬**이어야 합니다. `run_webapp.bat`이 scipy 가능한 3.13/3.12/3.11/3.10을 **자동 탐색**합니다.
   - Python **3.14는 피하세요**(현재 scipy 미지원 이슈).

## 1. 폴더 복사
- 이 폴더 전체를 새 PC로 복사(예: `C:\OOT\광동OOT대시보드_운영본`).
- **함께 복사돼야 하는 것**: `.env`(Tableau 토큰·SMTP·비번), 모든 `*.py`, `webapp\`, `*.bat`, `requirements.txt`, `item_groups.json`, `recipients_db.json`, `oot_alert_config.json`, `sample_OOT_report.xlsx`.

## 2. 패키지 설치 (1회)
```
python -m pip install -r requirements.txt
```
- 사내망 SSL로 실패 시: `python -m pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org`
- 그래도 막히면 IT에 사내 PyPI 미러/프록시 문의.
- 주요 패키지: fastapi·uvicorn·httpx·pandas·numpy·**scipy**·statsmodels·openpyxl.

## 3. 실행
- **대시보드(웹)**: **`run_webapp.bat` 더블클릭** → `http://localhost:8502`
  - 접속 URL(이 PC/사내 공유)이 실행 창에 표시됩니다.
  - 첫 데이터 조회는 Tableau 추출로 수십 초 걸릴 수 있고(콜드), 이후는 캐시로 빠릅니다.
- **자동 알람(선택)**: **`run_alarm.bat` 더블클릭** → 10분 주기로 신규 관리이탈 메일 발송.
  - 첫 실행은 현재 상태를 기준선으로 기록(메일 없음), 이후 신규 발생분만 발송.
- 창을 닫으면 종료됩니다. (Ctrl+C 로도 중지)

## 4. 동료 접속 (사내망 공유)
- 실행 창의 **`http://<이 PC IP>:8502`** 주소로 동료가 접속.
- 접속 안 되면 이 PC **Windows 방화벽에서 TCP 8502 인바운드 허용**.

## 5. 주요 기능 (좌측 메뉴)
- **OOT 빠른 조회**: 시험종류·품목·연도 선택 → 제조번호(LOT)별 관리이탈/주의/정상 판정 · **엑셀 다운로드**(연도 표기).
- **안정성 회귀분석**: 시점별 추세·유효기간(ICH Q1E) 산출.
- **APQR용 조회(참고용·GMP 정식활용 금지)**: 유사품목 2개+ 선택 → **전 시험항목 관리도 한눈에** + **엑셀(전 항목)**. 진행률(%) 표시.
- **알림 설정**: 수신자 그룹·SMTP·PAT 만료 관리(진입 비번 = `.env`의 `OOT_ALERT_PASSWORD`).

## 6. 알림 설정
- 좌측 **[알림 설정]** → 수신자 이메일 등록 → 저장 → **테스트 발송**으로 확인.
- SMTP는 `.env`(`QMS_SMTP_*`)에 이미 설정됨(복사 시 함께 옴).

## 7. Tableau 접속키(PAT) — 중요
- `.env`의 **`TABLEAU_PAT_NAME`(현재 `MISO`)·`TABLEAU_PAT_SECRET`**로 Tableau에 인증합니다.
- **PAT 만료 관리**: 만료일은 `.env`의 `TABLEAU_PAT_EXPIRY`(현재 **2027-06-08**)로 관리. 만료 20일 전부터 접속 시 안내 팝업 + 좌측 하단 D-day 표시.
- 만료되면: Tableau에서 **PAT 신규 발급 → `.env`의 이름·시크릿·만료일 갱신 → 대시보드 재시작**.

## 8. 시험종류 목록 (자동 연동 옵션)
- 시험종류 드롭다운은 기본 **내장 목록(18종)** 을 사용합니다.
- **자동 연동을 원하면**: Tableau `OOT 대시보드` 워크북에 `시험종류`만 행에 올린 뷰(이름 **`시험종류목록`**)를 만들어 게시하면, 코드 수정 없이 전 시험종류가 자동 반영됩니다(뷰 이름을 바꾸려면 `.env`에 `KDP_TESTTYPE_VIEW=이름`).

## 9. 문제 해결
| 증상 | 조치 |
|---|---|
| `ModuleNotFoundError: scipy` | scipy 되는 Python으로 실행(3.13 권장). `run_webapp.bat`이 자동 탐색하나, 안되면 `py -3.13 -m pip install scipy` |
| 데이터 조회 안 됨/타임아웃 | 사내망(VPN) 연결·Tableau 서버 접근 확인, PAT 만료 여부 확인 |
| 포트 8502 사용 중(WinError 10048) | 기존 실행 창 종료 후 재실행 |
| 서버 기동이 멈춤(드묾, WMI 이슈) | `run_server_wmisafe.py`로 실행(`python run_server_wmisafe.py`) 또는 PC 재부팅 |
| 화면이 옛날 그대로 | 브라우저 **Ctrl+F5**(강력 새로고침) |

## 10. 보안·운영 주의
- **`.env`·`recipients_db.json`에 토큰·메일 비밀번호·수신자(개인정보) 평문 포함** → 폴더/PC 관리 주의, **사외 유출·공개 저장소(GitHub 등) 업로드 금지**.
- 24시간 운영: PC **절전 비활성화** + (선택) Windows 작업 스케줄러로 부팅 시 `run_webapp.bat`(및 `run_alarm.bat`) 자동 실행 등록.
- 변경 이력은 **`버전기록.md`** 참조(최신 기능·수정).

## 11. 자동 생성 파일 (첫 실행 후)
- `oot_alarm.log`(알람 로그) · `oot_alarm_sent.csv`(발송 이력) · `.oot_alarm_state.json`(중복 발송 차단) · `.oot_snapshot.csv`/`.webapp_alarm.json`(상태) — 삭제해도 재생성됩니다.

---
문의: 품질관리팀 · 문서 최종: 2026-07-10
