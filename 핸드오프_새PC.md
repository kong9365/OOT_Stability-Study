# 광동 OOT 품질 대시보드 — 새 PC 핸드오프 / 설치·운영 가이드

> 이 폴더 **하나만** 새 PC에 복사하면 됩니다(자립형). QMS·MISO 등 다른 폴더 불필요.
> 최신 웹 대시보드(**FastAPI + 웹, 포트 8502**) 기준입니다. (구 Streamlit 버전 아님)

---

## 0. 전제조건 (반드시 확인)
1. **인터넷 연결** — 데이터는 Databricks(`dbc-6430e2d7-1523.cloud.databricks.com`, 클라우드 SaaS)에서 받아옵니다. 사내망 SSL 검사 프록시가 있어도 `truststore` 패키지(아래 설치)가 OS 인증서 저장소를 신뢰해 자동 통과합니다.
2. **Databricks 서비스 계정 자격증명** — 이 PC가 `광동제약_gmp_lims` 카탈로그를 조회할 서비스 계정(OAuth M2M)을 가지고 있어야 합니다. 아래 둘 중 하나:
   - `%USERPROFILE%\.databrickscfg` 파일에 `[lims-sp]` 프로필(host·client_id·client_secret) — **원래 PC의 이 파일을 함께 복사**하는 것이 가장 간단합니다.
   - 또는 `.env`에 `DATABRICKS_CLIENT_ID`/`DATABRICKS_CLIENT_SECRET` 직접 설정(운영 서버 권장 방식).
   - 둘 다 없으면 `databricks_client.py`가 즉시 오류를 냅니다(개인 로그인으로 조용히 넘어가지 않음). 발급은 워크스페이스 관리자에게 요청(`Databricks/DATABRICKS_LIMS_INTEGRATION.md` §3.1 참조).
3. **Python 3.13 설치** (권장) — 설치 시 **"Add Python to PATH" 체크 필수**.
   - ⚠️ **scipy가 되는 파이썬**이어야 합니다. `run_webapp.bat`이 scipy 가능한 3.13/3.12/3.11/3.10을 **자동 탐색**합니다.
   - Python **3.14는 피하세요**(현재 scipy 미지원 이슈).

## 1. 폴더 복사
- 이 폴더 전체를 새 PC로 복사(예: `C:\OOT\광동OOT대시보드_운영본`).
- **함께 복사돼야 하는 것**: `.env`(SMTP·비번), 모든 `*.py`(`databricks_client.py` 포함), `webapp\`, `*.bat`, `requirements.txt`, `item_groups.json`, `recipients_db.json`, `oot_alert_config.json`, `sample_OOT_report.xlsx`.
- **Databricks 인증**: 위 0-2에서 `~/.databrickscfg`를 쓰기로 했다면 그 파일도 새 PC의 같은 위치(`%USERPROFILE%\.databrickscfg`)에 복사하세요. 이 파일은 프로젝트 폴더 밖에 있어 폴더 복사만으로는 따라오지 않습니다.

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
  - 첫 데이터 조회는 Databricks SQL 웨어하우스가 깨어나며 수 초~수십 초 걸릴 수 있고(콜드), 이후는 캐시로 빠릅니다.
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
- **알림 설정**: 수신자 그룹·SMTP 관리(진입 비번 = `.env`의 `OOT_ALERT_PASSWORD`).

## 6. 알림 설정
- 좌측 **[알림 설정]** → 수신자 이메일 등록 → 저장 → **테스트 발송**으로 확인.
- SMTP는 `.env`(`QMS_SMTP_*`)에 이미 설정됨(복사 시 함께 옴).

## 7. Databricks 연동 — 중요
- 데이터는 Databricks `광동제약_gmp_lims` 카탈로그(서비스 계정 OAuth M2M)에서 받아옵니다. 자격증명은 0-2 참조.
- 매일 새벽(약 03:37 KST) LIMS 원천이 Databricks로 적재됩니다 — 당일 낮에 입력한 결과는 **다음 날 새벽 이후**부터 조회에 반영됩니다(지연은 최대 24시간, Tableau 때의 extract 주기와 유사).
- 연결 확인: `python databricks_client.py` → `auth: sp-profile:lims-sp`(또는 `sp-env`)와 오늘 날짜가 찍히면 정상.
- 인증 실패 시: 서비스 계정 시크릿 만료/회수 여부를 워크스페이스 관리자에게 확인(`Databricks/DATABRICKS_LIMS_INTEGRATION.md` 참조). 사람이 직접 탐색용으로만 개인 로그인을 쓰려면 `DATABRICKS_ALLOW_USER_AUTH=1` + `databricks auth login`(앱·배치에는 금지).

## 8. 시험종류 목록
- 시험종류 드롭다운은 Databricks에서 **실제 시험 의뢰에 쓰인 시험종류**를 동적으로 조회합니다(1시간 캐시). 조회 실패 시에만 내장 목록(18종)으로 폴백합니다 — 별도 설정 불필요.

## 9. 문제 해결
| 증상 | 조치 |
|---|---|
| `ModuleNotFoundError: scipy`/`requests`/`truststore` | scipy 되는 Python으로 실행(3.13 권장) 후 `pip install -r requirements.txt` 재실행. `run_webapp.bat`이 scipy는 자동 탐색하나, 안되면 `py -3.13 -m pip install scipy` |
| 데이터 조회 안 됨/타임아웃 | 인터넷 연결 확인 → `python databricks_client.py`로 Databricks 인증 단독 확인(§7) |
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
