# OOT · Stability Study — 광동 품질·시험 통합 대시보드

Tableau(`OOT_추출용`)의 품질·시험 데이터를 실시간으로 가져와 **OOT(이상추세) 빠른 조회**, **안정성 회귀분석(ICH Q1E 유효기간)**, **실시간 메일 알람**을 한 화면에서 제공하는 웹 대시보드입니다. (FastAPI 백엔드 + 정적 HTML/JS 프론트엔드)

## 주요 기능
- **OOT 빠른 조회** — 시험종류·품목·LOT 선택 → σ편차 기반 관리이탈/주의/정상 판정, 정상 항목 시험결과 표시, 실시간 알람 상태.
- **안정성 회귀분석** — 시점별 함량 회귀로 유효기간(95% CI가 규격 교차) 산출. 0개월(완제품 출하) 기준값 결합, **추정 저장수명 vs 허가 유효기간 비교·경고**, 합산성 검정(ANCOVA, statsmodels), 인터랙티브 그래프(Plotly), **계산 검증 단계별 수치**, 두 방식(통합/배치별 독립) 비교표, 상세 요약표, 시점간 OOT 표, 원자료/Excel 다운로드.
- **알림 설정** — 비밀번호 보호(초기 131103), 발송 정책·수신자·주기·야간발송, 테스트 발송, 비밀번호 변경.
- OOT → 안정성 **교차 연동**(선택 LOT만 분석).

## 빠른 시작
```bash
# 1) 의존성 설치
python -m pip install -r requirements.txt

# 2) 설정 (.env.example 복사 후 값 입력)
copy .env.example .env      # Windows

# 3) 실행 → http://localhost:8600
python -m uvicorn dashboard_api:app --host 0.0.0.0 --port 8600
```
Windows에서는 **`setup.bat`**(1회 설치) → **`run.bat`**(실행, 브라우저 자동) 으로 더 간단히 쓸 수 있습니다. 비전공자용 상세 안내는 [`사용설명서.md`](사용설명서.md) 참고.

## 요구사항
- Python 3.10+
- 사내망(또는 VPN) — Tableau 서버 접근 가능해야 함
- 패키지: fastapi, uvicorn, httpx, pandas, numpy, scipy, statsmodels, openpyxl, python-dotenv, urllib3

## 구성
```
dashboard_api.py   FastAPI 서버 + 정적 프론트 서빙 + JSON API
kdp_core.py        Tableau 조회 · OOT 분류 · 안정성 회귀 · ANCOVA
stability.py       회귀 엔진(ICH Q1E)
lims_parser.py     시점/규격 파싱 보조
oot_mail.py        알림 설정·메일 발송(SMTP)
webapp/            프론트엔드(index.html, app.js — Plotly via CDN)
```

## 보안 주의
- `.env`(Tableau 토큰·메일 비밀번호)는 **절대 커밋하지 마세요**(`.gitignore` 처리됨). 배포 시 `.env.example`을 복사해 채웁니다.
- 알림 설정 비밀번호는 `oot_alert_config.json`에 해시로 저장(런타임 생성, 커밋 제외).

## 면책
자동 산출 결과는 참고용입니다. 최종 판정·유효기간은 QC 책임자 검토·승인 및 ICH Q1A/Q1E·사내 SOP 확인이 필요합니다.
