# Tableau Custom MCP Server + REST API

Tableau Personal Access Token을 사용하여 광동제약 Tableau 서버의 데이터를 조회합니다.

- **server.py**: Claude Desktop MCP 서버 (stdio)
- **api.py**: MISO 등 외부 플랫폼용 **REST API 서버** (HTTP)

## 주요 기능

- ✅ Tableau Personal Access Token (PAT) 인증
- ✅ 뷰(View) 목록 조회
- ✅ 뷰 데이터 CSV / JSON 반환
- ✅ 워크북 정보 조회
- ✅ 데이터 소스 목록 조회
- ✅ 뷰 이름으로 검색

---

## REST API 서버 (api.py) — MISO 연동용

### 1. 패키지 설치

```bash
cd "Tableau Custom MCP Server"
pip install -r requirements.txt
```

### 2. 환경 변수 설정

`.env.example` 을 복사해 `.env` 파일을 만들고, PAT 암호를 입력합니다.

```bash
copy .env.example .env
```

`.env` 파일 내용:

```
TABLEAU_SERVER=http://tableau.ekdp.com
TABLEAU_API_VERSION=3.21
TABLEAU_PAT_NAME=QMS_OOS
TABLEAU_PAT_SECRET=<여기에 PAT 시크릿 입력 · .env에만, 커밋 금지>
API_KEY=
PORT=8000
```

### 3. REST API 서버 실행

```bash
python api.py
```

또는 uvicorn으로 직접 실행:

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

서버가 뜨면 브라우저에서 API 문서 확인 가능:  
`http://localhost:8000/docs`

### 4. 제공 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/` | 서버 상태 확인 |
| GET | `/views` | 뷰 목록 (`?filter=OOS` 선택) |
| GET | `/views/{view_id}/data` | 뷰 데이터 (`?format=json` 또는 `?format=csv`) |
| GET | `/views/find` | 뷰 이름으로 검색 (`?view_name=주간레포트`) |
| GET | `/views/by-name/{view_name}/data` | 뷰 이름으로 데이터 조회 (편의용) |
| GET | `/workbooks` | 워크북 목록 |

**예시 curl:**

```bash
# 뷰 목록
curl http://localhost:8000/views

# OOS 필터
curl "http://localhost:8000/views?filter=OOS"

# 특정 뷰 데이터 (JSON)
curl "http://localhost:8000/views/7ba5f17d-5e6c-45da-aace-462ffdc7d34d/data"

# 특정 뷰 데이터 (CSV)
curl "http://localhost:8000/views/7ba5f17d-5e6c-45da-aace-462ffdc7d34d/data?format=csv"

# 뷰 이름으로 데이터 조회
curl "http://localhost:8000/views/by-name/원본파일/data"
```

### 5. MISO 설정

MISO "외부 데이터 API 연결" 모달:

| 필드 | 입력 값 |
|------|---------|
| 입력 필드 이름 | `Tableau OOS` |
| API Endpoint | `http://<이 서버 주소>:8000` |
| API Key | `.env` 의 `API_KEY` 값 (비워두면 인증 없음) |

MISO 워크플로우의 **API 요청 노드**:
- 메서드: `GET`
- 경로: `/views/by-name/원본파일/data` 또는 `/views/{view_id}/data`
- Body: `none`

---

## MCP 서버 (server.py) — Claude Desktop 설정 방법

### 1. 필요한 패키지 설치

```bash
cd tableau-custom-mcp
pip install -e .
```

### 2. Claude Desktop 설정

`claude_desktop_config.json` 파일에 다음 설정 추가:

**Windows:**
```json
{
  "mcpServers": {
    "tableau-custom": {
      "command": "python",
      "args": [
        "C:/path/to/tableau-custom-mcp/server.py"
      ]
    }
  }
}
```

**macOS/Linux:**
```json
{
  "mcpServers": {
    "tableau-custom": {
      "command": "python3",
      "args": [
        "/path/to/tableau-custom-mcp/server.py"
      ]
    }
  }
}
```

## 뷰 데이터 조회 시 권한 (401 해결)

**뷰 데이터(CSV)** 를 보려면 Tableau 서버에서 다음이 필요합니다.

- 해당 **뷰/워크북**에 대해 PAT 사용자에게 **Read** 및 **Export Data**(또는 요약 데이터 다운로드) 권한이 있어야 합니다.
- **401 Unauthorized** 가 나오면: 토큰 만료이거나, 해당 리소스에 대한 **데이터 내보내기** 권한이 없는 경우입니다.
- **조치**: Tableau 사이트 관리자에게 해당 워크북/뷰에 대해 **Export Data** 또는 **Download Summary Data** 권한을 요청하세요.

뷰 목록 조회는 가능하지만 특정 뷰 데이터만 401이 나온다면, 그 뷰/프로젝트에 대한 권한을 위와 같이 요청하면 됩니다.

## 사용 가능한 도구

### 1. tableau_list_views
모든 뷰(대시보드/시트) 목록 조회

**매개변수:**
- `filter` (옵션): 뷰 이름으로 필터링

**예시:**
```json
{
  "filter": "OOS"
}
```

### 2. tableau_get_view_data
특정 뷰의 데이터를 CSV 형식으로 가져오기

**매개변수:**
- `view_id` (필수): 뷰 ID

**예시:**
```json
{
  "view_id": "7ba5f17d-5e6c-45da-aace-462ffdc7d34d"
}
```

### 3. tableau_list_workbooks
모든 워크북 목록 조회

**매개변수:**
- `filter` (옵션): 워크북 이름으로 필터링

**예시:**
```json
{
  "filter": "QMS"
}
```

### 4. tableau_get_workbook
특정 워크북의 상세 정보 조회

**매개변수:**
- `workbook_id` (필수): 워크북 ID

**예시:**
```json
{
  "workbook_id": "69f06260-a83a-4187-81d8-7e80aba5b8a3"
}
```

### 5. tableau_list_datasources
모든 데이터 소스 목록 조회

**매개변수:**
- `filter` (옵션): 데이터 소스 이름으로 필터링

**예시:**
```json
{
  "filter": "QMS_OOS"
}
```

### 6. tableau_find_view_by_name
뷰 이름으로 검색하여 뷰 ID 찾기

**매개변수:**
- `view_name` (필수): 검색할 뷰 이름
- `workbook_name` (옵션): 워크북 이름 (더 정확한 검색)

**예시:**
```json
{
  "view_name": "주간레포트",
  "workbook_name": "QMS_OOS 대시보드"
}
```

## 사용 예시

### Claude에서 사용하기

1. **뷰 목록 조회:**
```
태블로 커스텀 서버에서 OOS 관련 뷰 목록을 보여줘
```

2. **데이터 추출:**
```
"1.주간레포트" 뷰의 데이터를 CSV로 가져와줘
```

3. **워크북 정보:**
```
QMS_OOS 대시보드 워크북의 상세 정보를 알려줘
```

## 서버 정보

- **Tableau 서버**: http://tableau.ekdp.com
- **API 버전**: 3.21
- **인증 방식**: Personal Access Token
- **Token 이름**: QMS_OOS

## 주의사항

⚠️ **보안:**
- Personal Access Token은 민감한 정보입니다.
- 코드를 공유할 때는 토큰 정보를 제거하세요.
- 정기적으로 토큰을 갱신하는 것을 권장합니다.

⚠️ **네트워크:**
- 광동제약 내부 네트워크에서만 접근 가능합니다.
- VPN 연결이 필요할 수 있습니다.

## 트러블슈팅

### 인증 오류 발생 시
```
Tableau 인증 실패: 401 Unauthorized
```
→ Personal Access Token이 만료되었거나 잘못되었습니다. Tableau 서버에서 새 토큰을 발급받으세요.

### 네트워크 연결 오류
```
Connection refused
```
→ 광동제약 내부 네트워크에 연결되어 있는지 확인하세요.

### 뷰를 찾을 수 없음
```
뷰 ID를 찾지 못했습니다
```
→ `tableau_find_view_by_name` 도구를 사용하여 정확한 뷰 이름과 ID를 확인하세요.

## 라이선스

내부용 도구 - 광동제약 품질관리팀 전용

## 개발자

품질관리팀 - 정혜리
