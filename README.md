# AI News Trend Analysis

AI 뉴스 트렌드 분석 팀 프로젝트


## 프로젝트 구조

본 프로젝트는 기능별로 모듈을 분리하여 개발합니다.

```text
project/
│
├── main.py              # CLI 실행 (모든 서브커맨드 연결)
├── collector.py         # 뉴스 수집 (API/RSS, 크롤링)
├── cleaner.py           # 정제 핵심 로직 (필드 검증, 텍스트 정규화, 날짜 통일, 결측값 처리)
├── store.py             # raw 읽기 / clean 저장 / 중복 처리(skip·upsert)
├── clean_command.py     # clean 서브커맨드 진입점
├── log_setup.py         # 파이프라인 공통 로깅 설정
├── analyzer.py          # AI 뉴스 요약 및 트렌드 분석
├── analyze_command.py   # summarize / analyze 서브커맨드 진입점
├── reporter.py          # 집계·품질지표·리포트 문서 생성
├── visualizer.py        # matplotlib 차트 생성 (PNG)
├── exporter.py          # CSV / JSONL / Excel 내보내기
├── report_command.py    # report 서브커맨드 진입점
├── export_command.py    # export 서브커맨드 진입점
├── query_command.py     # list / show 조회 서브커맨드 (보너스)
│
├── data/
│   ├── raw/             # 수집한 원본 뉴스 데이터 (google/naver/govuk_news.jsonl)
│   ├── clean/           # 정제된 뉴스 데이터 (news_clean.jsonl)
│   └── analyzed/        # AI 요약·트렌드 분석 결과
│
├── output/
│   ├── charts/          # 차트 PNG
│   ├── reports/         # 리포트 MD / TXT
│   └── exports/         # CSV / JSONL / Excel
├── logs/                # 실행 로그 (collector.log, pipeline.log)
│
├── .github/workflows/   # 정기 수집 자동화 (GitHub Actions)
├── config.json          # 뉴스 소스, 정제 설정, 중복 처리 정책 등
├── requirements.txt     # Python 패키지 목록
└── README.md
```

### 팀 역할

| 역할            | 담당 기능                                  |
| -------------- | ------------------------------------- |
|   뉴스 수집     | RSS / API / 웹 크롤링을 통한 AI 뉴스 수집   |
|   데이터 정제   | HTML 제거, 날짜 통일, 중복 제거          |
|     AI 분석     | 뉴스 요약, 카테고리 분류, 키워드 추출         |
| 시각화·리포트  | 차트 생성, 집계·리포트, CSV/Excel 내보내기      |


## CLI 한눈에 보기

모든 기능은 `main.py` 의 서브커맨드로 실행합니다.

```text
python main.py fetch      --source google --limit 20     # 1. 뉴스 수집
python main.py clean      --policy skip                  # 2. 데이터 정제
python main.py summarize  --unsummarized                 # 3. AI 요약
python main.py analyze                                   # 3. AI 트렌드 분석
python main.py report     --format both                  # 4. 차트 + 리포트
python main.py export     --format excel                 # 4. 파일 내보내기

python main.py list --category IT --page 1               # (보너스) 목록 조회
python main.py show <뉴스 id>                             # (보너스) 상세 조회
```

각 커맨드의 옵션은 `python main.py <커맨드> --help` 로 확인할 수 있습니다.


## 1. 뉴스 수집

collector.py에서 뉴스 데이터를 수집합니다.

현재 다음 세 가지 소스를 지원합니다.

### Google News
 - Google News RSS 사용
 - AI 관련 뉴스 수집
 - 수집 방법: rss+crawl

### NAVER News
 - NAVER 뉴스 검색 API 사용
 - 여러 AI 관련 검색어를 이용하여 뉴스 수집
 - 검색어:
            AI
            인공지능
            생성형 AI
            LLM
            AI 반도체
 - URL 기준 중복 뉴스 제거
 - API가 주는 description은 검색어 주변만 뽑은 스니펫이라 문장이 끊기는 경우가 많아,
   Google과 동일하게 기사 원문(`originallink`)을 크롤링해 본문을 채움
 - 크롤링이 차단되는 등 실패한 경우에만 API description으로 대체 (`content_source` 필드로 구분)
 - 수집 방법: api+crawl

### 본문 크롤링 공통 로직 (Google · NAVER)
 - 기사 원문 페이지에서 본문 영역(article, 본문 전용 class/id 등)을 우선 추출
 - 본문 영역을 찾지 못한 경우에만 메타 설명(`og:description` 등)으로 대체
   (메타 설명은 사이트가 미리 짧게 잘라둔 값이라 문장이 중간에 끊기는 경우가 많아 최후 수단으로만 사용)
 - 본문 길이는 최대 3000자로 제한 (초과 시 단어 단위로 끊어 "…" 표시, `content_truncated` 필드로 확인 가능)

### GOV.UK
 - BeautifulSoup을 이용한 웹 크롤링
 - AI 관련 뉴스 목록 수집
 - 각 기사 상세 페이지에 접근하여 본문 수집
 - 과도한 요청을 방지하기 위해 요청 간 지연 적용
 - 수집 방법: crawl

## 수집 데이터 구조

수집된 뉴스는 다음과 같은 공통 구조를 사용합니다.
```text
{
  "title": "뉴스 제목",
  "content": "뉴스 본문 (최대 3000자)",
  "url": "뉴스 URL",
  "published_at": "발행 시각",
  "source": "뉴스 소스",
  "collected_at": "수집 시각",
  "collection_method": "rss+crawl | api+crawl | crawl",
  "content_truncated": "본문이 3000자 상한으로 잘렸는지 여부",
  "content_max_length": "본문 길이 상한 (3000)"
}
```

- NAVER 뉴스의 경우 수집에 사용된 검색어를 확인할 수 있도록 `search_keyword` 필드가 추가됩니다.
- NAVER 뉴스는 크롤링 성공 여부를 나타내는 `content_source`(`crawl` | `api_description`) 필드와,
  원본 API 스니펫을 보관하는 `api_description` 필드가 추가됩니다.

## Raw 데이터 저장

수집된 원본 뉴스는 JSONL 형식으로 영구 저장합니다.

```text
data/raw/
├── google_news.jsonl
├── naver_news.jsonl
└── govuk_news.jsonl
```

 - JSONL은 한 줄에 하나의 뉴스 데이터를 저장합니다.

기존 데이터가 존재하는 경우 URL을 확인하여 이미 저장된 뉴스는 건너뛰고 새로운 뉴스만 추가합니다.

## HTTP 요청 및 오류 처리

외부 뉴스 소스 요청에는 timeout을 적용합니다.

HTTP 요청 과정에서 발생할 수 있는 다음 오류를 처리합니다.

 - 요청 시간 초과
 - HTTP 요청 실패
 - RSS / JSON 응답 파싱 오류
 - 기사 본문 수집 실패

GOV.UK 상세 기사 크롤링 시 요청 사이에 지연 시간을 적용하여 과도한 요청을 방지합니다.

## Logging

Python logging 모듈을 사용하여 프로그램 실행 상태를 기록합니다.

로그 레벨:

 - INFO: 정상적인 수집 및 저장 상태
 - WARNING: timeout 등 실행 가능한 예외 상황
 - ERROR: HTTP 요청 실패 등 수집 오류

로그는 터미널에 출력되는 동시에 다음 파일에도 누적 저장됩니다.
```text
logs/collector.log
```

## 설정 파일

공개 가능한 프로그램 설정은 config.json에서 관리합니다.

설정 항목:

 - 뉴스 소스 URL
 - NAVER 뉴스 검색 키워드
 - HTTP timeout
 - GOV.UK 요청 지연 시간
 - Raw 데이터 저장 경로
 - 중복 처리 정책

API 인증정보는 config.json에 저장하지 않습니다.

NAVER API 인증정보와 같은 비밀값은 .env 파일에서 관리하며 Git 저장소에 커밋하지 않습니다.

## 뉴스 수집 실행

 - Google News:  python main.py fetch --source google --limit 20

 - NAVER News:   python main.py fetch --source naver --limit 20

 - GOV.UK:    python main.py fetch --source govuk --limit 20

## 2. 데이터 정제

cleaner.py / store.py / clean_command.py에서 raw 뉴스를 정제해 clean 저장소에 저장합니다.
자세한 내용은 [README_clean.md](README_clean.md) 참고.

정제 규칙:
 - 필수 필드 검증 (title, url, published_at)
 - 텍스트 정규화 (HTML 태그/엔티티 제거, 공백 정리)
 - 날짜 형식 통일 (한국시간 KST ISO)
 - 결측값 처리 (본문 없으면 제목으로 대체, 카테고리 기본값 적용)
 - 중복 처리 정책 적용 (skip / upsert)

실행:
```text
python main.py clean
python main.py clean --policy upsert
```

정제된 데이터는 raw와 분리된 `data/clean/news_clean.jsonl`에 저장됩니다.

## 3. AI 분석

AI 분석 담당 구현 후 작성 예정.

## 4. 시각화 및 리포트 생성

정제·분석까지 끝난 데이터를 사람이 읽는 결과물로 바꾸는 단계입니다.
모듈은 역할별로 나눠 두었습니다.

| 파일 | 역할 |
| --- | --- |
| `reporter.py` | 데이터 로드, 품질 지표·TOP N 집계, 리포트 문서(Markdown/TXT) 작성 |
| `visualizer.py` | matplotlib 차트 생성 (PNG) |
| `exporter.py` | CSV / JSONL / Excel 내보내기 |
| `report_command.py` | `report` 서브커맨드 (집계 → 차트 → 리포트) |
| `export_command.py` | `export` 서브커맨드 (필터 → 파일 저장) |

집계(`reporter`)와 그리기(`visualizer`)를 나눈 이유는, 집계 기준을 바꿔도
차트 코드를 건드릴 필요가 없게 하기 위해서입니다.

### 4-1. 리포트 실행

```text
python main.py report                                  # 차트 + 리포트(MD) 생성
python main.py report --format both                    # MD와 TXT 동시 저장
python main.py report --category IT --top 15           # IT 카테고리만, TOP 15
python main.py report --date-from 2026-08-01 --date-to 2026-08-09
python main.py report --no-charts                      # 집계·리포트만 (차트 생략)
python main.py report --date-field collected           # 수집일 기준 추이로 전환
```

주요 옵션

| 옵션 | 설명 |
| --- | --- |
| `--category` | 특정 카테고리만 집계 |
| `--date-from` / `--date-to` | 기간 지정 (YYYY-MM-DD, 양끝 포함) |
| `--top` | TOP N 집계 개수 (기본 10) |
| `--format` | `md` / `txt` / `both` (기본 md) |
| `--date-field` | 추이 기준 날짜 — `published`(발행일, 기본) / `collected`(수집일) |
| `--no-charts` | 차트 생성 생략 |
| `--quiet` | 콘솔 요약 출력 생략 |

기간·카테고리 필터를 걸면 요약 데이터도 같은 조건으로 좁혀서 집계하기 때문에,
키워드 TOP N이 필터 범위 밖의 기사까지 세는 문제가 생기지 않습니다.

### 4-2. 차트

`output/charts/` 에 PNG로 저장됩니다.

| 파일 | 내용 |
| --- | --- |
| `category_counts.png` | 카테고리별 뉴스 수 (막대) |
| `daily_trend.png` | 일자별 수집 추이 (꺾은선, 최다일 표시) |
| `top_keywords.png` | AI가 뽑은 키워드 TOP N (가로 막대) |
| `source_share.png` | 소스별 수집 비중 (원 그래프) |

한글 폰트는 실행 환경에 설치된 것을 자동으로 찾아 적용합니다.
(macOS `AppleGothic` → Windows `Malgun Gothic` → 리눅스 `NanumGothic` 순으로 탐색)
찾지 못하면 경고 로그를 남기고, 차트의 한글이 네모(□)로 보일 수 있습니다.
리눅스에서는 `sudo apt install fonts-nanum` 으로 설치할 수 있습니다.

화면이 없는 환경(GitHub Actions 등)에서도 동작하도록 matplotlib 백엔드는
파일 저장 전용(`Agg`)으로 고정했습니다.

### 4-3. 리포트 구성

`output/reports/report_날짜시각.md` (또는 `.txt`) 로 저장되고, 실행 시 콘솔에도 요약이 출력됩니다.

1. **데이터 품질 지표**
   - 요약 완료율 — 전체 뉴스 중 AI 요약이 끝난 비율
   - 본문 확보율 — 본문이 300자 이상 확보된 비율 (크롤링이 제대로 됐는지 판단)
   - 평균 본문 길이
   - 발행일 보유율 — 날짜 정제가 성공한 비율
   - 본문 잘림 비율 — 3000자 상한에 걸려 잘린 기사 비율
2. **수집 분포** — 카테고리별 / 소스별 건수, 일자별 추이 요약(집계 일수·최다일·일평균)
3. **TOP N 집계** — 키워드 TOP N, 언론사 TOP N
4. **AI 인사이트** — `data/analyzed/trend_report.json` 의 주요 트렌드·시사점·종합 요약
5. **차트** — 생성된 PNG를 리포트 기준 상대경로로 첨부 (MD 뷰어에서 바로 보입니다)

AI 분석 결과가 아직 없으면 4번 항목 자리에 안내 문구가 들어가고,
나머지 집계는 그대로 생성됩니다.

### 4-4. 데이터 내보내기

`output/exports/` 에 저장됩니다. clean 뉴스와 AI 요약을 뉴스 id 기준으로 합쳐,
한 줄에 기사 정보와 요약·키워드가 모두 담기게 만듭니다.

```text
python main.py export --format csv                     # CSV
python main.py export --format excel                   # Excel(.xlsx)
python main.py export --format jsonl                   # JSONL
python main.py export --format all                     # 세 포맷 모두
python main.py export --status summarized              # 요약 완료 건만
python main.py export --category IT --limit 50 --filename it_top50.csv
```

| 옵션 | 설명 |
| --- | --- |
| `--format` | `csv` / `jsonl` / `excel` / `all` |
| `--status` | `all`(기본) / `summarized` / `unsummarized` |
| `--category`, `--date-from`, `--date-to` | 조건 필터 |
| `--limit` | 최신순 최대 건수 |
| `--filename` | 저장 파일명 지정 |

- CSV는 `utf-8-sig`(BOM 포함)로 저장합니다. 그래야 윈도우 엑셀에서 열었을 때 한글이 깨지지 않습니다.
- Excel은 헤더 고정·열 필터가 적용된 `뉴스` 시트와, 품질 지표·카테고리·키워드가 담긴 `요약 통계` 시트로 구성됩니다.
- 파일명에 날짜시각(초 단위)이 붙어 이전 결과를 덮어쓰지 않습니다.

### 4-5. 뉴스 조회 (보너스)

```text
python main.py list                                    # 최신순 목록 (기본 20건)
python main.py list --category IT --keyword 반도체      # 조건 검색
python main.py list --status unsummarized --page 2     # 페이지 이동
python main.py show 613de6543210                       # 상세 조회
python main.py show 613de6543210 --full                # 본문 전체 보기
```

`list` 는 카테고리·기간·검색어·요약 상태 필터와 페이지네이션(`--page`, `--size`)을 지원하고,
`show` 는 기사 메타 정보 + AI 요약 + 키워드 + 본문을 함께 보여줍니다.

## 전체 파이프라인

각 단계는 앞 단계의 결과 파일을 입력으로 받습니다. 순서대로 실행하면 됩니다.

```text
python main.py fetch --source google --limit 20   # 수집  → data/raw/*.jsonl
python main.py clean                              # 정제  → data/clean/news_clean.jsonl
python main.py summarize                          # 요약  → data/analyzed/news_summary.jsonl
python main.py analyze                            # 분석  → data/analyzed/trend_report.json
python main.py report --format both               # 리포트 → output/charts, output/reports
python main.py export --format all                # 내보내기 → output/exports
```

```text
뉴스 수집
   ↓
Raw JSONL 저장
   ↓
데이터 정제 (clean JSONL)
   ↓
AI 요약 / 키워드 추출
   ↓
AI 트렌드 분석
   ↓
통계 집계 + 차트 + 리포트 + 내보내기
```


### 실행 준비

Python 3.10 이상이 필요합니다.

```text
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

차트·엑셀 기능에는 `matplotlib`, `openpyxl` 이 필요하며 requirements.txt에 포함돼 있습니다.

### 환경변수

.env 예시:
```text

NAVER_CLIENT_ID=your_client_id
NAVER_CLIENT_SECRET=your_client_secret
GOOGLE_API_KEY=your_gemini_api_key
```

- `NAVER_*` : NAVER 뉴스 검색 API (수집 단계)
- `GOOGLE_API_KEY` : Gemini API (AI 요약·분석 단계)

실제 API 키가 포함된 .env 파일은 GitHub에 업로드하지 않습니다

## 정기 실행 스케줄링

뉴스 수집을 매일 자동으로 실행하도록 예약할 수 있습니다. 환경에 따라 아래 방법 중 하나를 사용합니다.

### 방법 1. GitHub Actions (권장, 본 저장소에 적용됨)

PC를 켜두지 않아도 GitHub의 클라우드 러너가 매일 정해진 시각에 자동으로 수집을 실행하고, 결과를 저장소에 커밋합니다.

- 워크플로 정의: `.github/workflows/collect.yml`
- 스케줄: 매일 06:00 KST (cron 표현식 `0 21 * * *`, UTC 기준)
- 동작 순서: Google → NAVER → GOV.UK 순으로 각 20개씩 수집 → `data/raw/*.jsonl` 변경사항을 자동 커밋 및 푸시
- 저장소 Settings → Secrets and variables → Actions에 아래 두 값을 등록해야 NAVER 수집이 동작합니다.
  - `NAVER_CLIENT_ID`
  - `NAVER_CLIENT_SECRET`
- 예약 시각 외에도 Actions 탭에서 `Run workflow` 버튼으로 즉시 수동 실행이 가능합니다(`workflow_dispatch`).

cron 표현식은 `분 시 일 월 요일` 순서로 실행 시각을 지정합니다. 예: `0 21 * * *`는 "매일 UTC 21시 정각"을 의미합니다.

### 방법 2. Linux / macOS - cron

터미널에서 `crontab -e` 실행 후 아래와 같이 등록합니다.

```text
0 6 * * * cd /path/to/project && python main.py fetch --source google --limit 20
0 6 * * * cd /path/to/project && python main.py fetch --source naver --limit 20
0 6 * * * cd /path/to/project && python main.py fetch --source govuk --limit 20
```

위 예시는 매일 06:00에 세 소스를 각각 20개씩 수집하도록 등록한 것입니다.

### 방법 3. Windows - 작업 스케줄러(Task Scheduler)

1. `Win + R` → `taskschd.msc` 실행
2. "작업 만들기" 선택 후 트리거를 "매일 06:00"으로 설정
3. 동작으로 "프로그램 시작"을 선택하고 아래와 같이 입력
   - 프로그램/스크립트: `python`
   - 인수 추가: `main.py fetch --source google --limit 20`
   - 시작 위치: 프로젝트 루트 폴더 경로
4. NAVER, GOV.UK 소스에 대해서도 동일하게 작업을 하나씩 추가로 등록

또는 PowerShell에서 `schtasks` 명령으로 동일한 작업을 등록할 수 있습니다.

```powershell
schtasks /create /tn "AI뉴스수집_google" /tr "python C:\path\to\project\main.py fetch --source google --limit 20" /sc daily /st 06:00
```


