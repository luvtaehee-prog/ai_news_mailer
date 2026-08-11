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
├── analyzer.py          # AI 뉴스 요약 / 감성 분석 / 트렌드 분석
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
├── .github/workflows/   # 정기 실행 자동화 (보너스)
│   ├── collect.yml      #   매일 - 수집 + 정제
│   └── analyze.yml      #   매월 14일 - 전체 파이프라인 (AI 분석·리포트 포함)
├── config.json          # 뉴스 소스, 정제 설정, 중복 처리 정책 등
├── requirements.txt     # Python 패키지 목록
└── README.md
```

### 팀 역할

| 파트 | 담당자 | 담당 기능 | 주요 파일 |
| --- | --- | --- | --- |
| 1. 뉴스 수집 | 박수진 | RSS / API / 웹 크롤링을 통한 AI 뉴스 수집 | `collector.py` |
| 2. 데이터 정제 | 강민주 | HTML 제거, 날짜 통일, 결측·중복 처리 | `cleaner.py`, `store.py`, `clean_command.py` |
| 3. AI 분석 | 김태희 | 뉴스 요약, 키워드 추출, 감성 분석, 트렌드 분석 | `analyzer.py`, `analyze_command.py` |
| 4. 시각화·리포트 | 전지영 | 차트 생성, 집계·리포트, CSV/Excel 내보내기 | `reporter.py`, `visualizer.py`, `exporter.py`, `report_command.py`, `export_command.py` |

공통 모듈은 `main.py`(CLI 연결), `log_setup.py`(로깅), `query_command.py`(보너스 조회 CLI)입니다.


## CLI 한눈에 보기

모든 기능은 `main.py` 의 서브커맨드로 실행합니다.

```text
python main.py fetch      --source google --limit 20     # 1. 뉴스 수집
python main.py clean      --policy skip                  # 2. 데이터 정제
python main.py summarize  --unsummarized                 # 3. AI 요약 + 감성 분석
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
logs/collector.log    # 1. 뉴스 수집 단계
logs/pipeline.log     # 2~4. 정제 / AI 분석 / 리포트 단계
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

정제된 뉴스를 AI로 요약하고, 그 요약들을 모아 트렌드를 분석하는 단계입니다.
`summarize`(기사 단위)와 `analyze`(전체 단위) 두 서브커맨드로 나뉩니다.

| 파일 | 역할 |
| --- | --- |
| `analyzer.py` | OpenAI 호출, 요약·감성·트렌드 분석 로직, 키워드·카테고리 집계 |
| `analyze_command.py` | `summarize` / `analyze` 서브커맨드 (옵션 처리 → analyzer 호출) |

사용 모델은 `config.json`의 `ai.model`에서 바꿀 수 있고(기본 `gpt-5.4`),
API 키는 `.env`의 `OPENAI_API_KEY`에서 읽습니다.

### 3-1. AI 요약

기사 본문을 3문장 이내로 요약하고 핵심 키워드 3개를 뽑습니다.

```text
python main.py summarize                     # 아직 요약되지 않은 뉴스 전체
python main.py summarize --unsummarized      # 위와 동일 (기본값을 명시)
python main.py summarize --all               # 전체 뉴스 대상 (이미 요약된 건은 스킵)
python main.py summarize --limit 20          # 최대 20건만
python main.py summarize --id 606b1d302cef   # 특정 뉴스 1건만
python main.py summarize --batch-size 3      # 한 번의 호출에 묶을 기사 수 (기본 5)
```

기사를 여러 건씩 묶어 한 번에 호출합니다. 호출 수가 줄어 비용과 시간이 함께 줄어듭니다.

이미 요약된 뉴스는 기본적으로 건너뜁니다. 결과를 한 줄씩 이어 붙이는(append) 방식이라
중간에 끊겨도 다시 실행하면 남은 건부터 이어서 처리합니다.

### 3-2. 감성 분석 (보너스)

각 뉴스의 논조를 **긍정 / 부정 / 중립** 중 하나로 분류합니다.
분류 기준은 프롬프트에 명시해 두었습니다.

- 긍정: 성장·성과·호재·기대를 다루는 기사
- 부정: 위기·규제·손실·우려를 다루는 기사
- 중립: 사실 전달 위주이거나 긍정·부정이 뚜렷하지 않은 기사

```text
python main.py summarize                     # 요약과 감성을 한 번에
python main.py summarize --sentiment-only    # 감성만 채우기
```

요약과 감성을 한 호출에서 함께 받기 때문에 평소에는 추가 비용이 없습니다.
`--sentiment-only`는 **이미 요약이 끝난 기사에 감성만 뒤늦게 채울 때** 쓰는 경로로,
본문 대신 제목과 요약만 보내므로 요약을 다시 돌리는 것보다 훨씬 쌉니다.

결과는 `news_summary.jsonl`의 `sentiment` 필드에 저장되고,
막대 차트(`output/charts/sentiment.png`)와 리포트의 "감성 분포" 표로 시각화됩니다.
내보내기(CSV/Excel)에도 `sentiment` 컬럼으로 포함됩니다.

### 3-3. 트렌드 분석

요약본 전체를 한 번에 넣고 주요 트렌드와 시사점을 뽑습니다.

```text
python main.py analyze                                   # 전체 기간·전체 카테고리
python main.py analyze --category IT                     # 특정 카테고리만
python main.py analyze --date-from 2026-08-01 --date-to 2026-08-11
```

키워드 빈도와 카테고리 분포는 **AI가 아니라 코드가 직접 집계**해서 프롬프트에 넣어 줍니다.
AI에게 숫자를 세게 하면 틀리기 때문에, 세는 일은 `Counter`가 하고 AI는 해석만 맡습니다.

> 조건을 걸고 실행해도 결과는 같은 `trend_report.json`에 저장되므로, 조건별로 돌린 뒤에는
> 마지막에 조건 없이 한 번 더 실행해 전체 기준 결과로 되돌려 놓아야 리포트가 어긋나지 않습니다.

### 3-4. 산출물

**`data/analyzed/news_summary.jsonl`** — 기사 1건당 1줄

| 필드 | 설명 |
| --- | --- |
| `id` | clean 데이터와 동일한 id (조인 키) |
| `title` / `category` / `source` / `published_date` | clean에서 그대로 가져온 메타 정보 |
| `summary` | 3문장 이내 요약 |
| `keywords` | 핵심 키워드 3개 |
| `sentiment` | 감성 (긍정 / 부정 / 중립) |

**`data/analyzed/trend_report.json`** — 전체 분석 결과 1개

| 필드 | 설명 |
| --- | --- |
| `trends` | 주요 트렌드 3~6개 (`title`, `description`) |
| `implications` | 시사점 3~5개 |
| `overall_summary` | 전체 흐름 3~4문장 요약 |
| `keyword_frequency` | 키워드 빈도 상위 15개 (`keyword`, `count`) |
| `category_distribution` | 카테고리별 건수 |
| `article_count` | 분석에 사용된 기사 수 |

### 3-5. 다른 파트와의 연결

- `news_summary.jsonl`의 `id`로 clean 데이터와 조인할 수 있습니다.
- 4번 파트(시각화·리포트)는 `trend_report.json`의 트렌드·시사점·종합 요약을
  그대로 가져다 씁니다.
- 다만 키워드 빈도와 카테고리 분포는 `reporter.py`가 `news_summary.jsonl`에서
  다시 집계합니다. `report --category IT` 처럼 조건을 걸었을 때 집계도 함께
  좁혀져야 하기 때문입니다. (`trend_report.json`의 통계는 `analyze` 실행 시점의
  전체 기준 값이라 필터를 따라가지 못합니다.)

### 3-6. 안정성 처리

- **응답 형식 고정** — structured outputs(strict)로 JSON 스키마를 API 쪽에서 강제합니다.
  모델이 형식을 어기거나 코드펜스를 붙일 수 없어 파싱이 실패하지 않습니다.
- **호출 한도·서버 오류** — 429나 5xx는 SDK가 지수 백오프로 자동 재시도합니다(최대 5회).
- **실패 시 스킵** — 재시도로도 실패한 배치는 `logs/pipeline.log`에 ERROR로 남기고
  다음 배치로 넘어갑니다. 한 배치가 실패해도 전체가 멈추지 않습니다.
- **잘림·거부 감지** — 응답이 토큰 한도에서 잘리거나 안전 정책으로 거부되면
  정상 응답으로 착각하지 않도록 따로 확인합니다.

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
| `sentiment.png` | 뉴스 감성 분포 (가로 막대, 보너스) |

`sentiment.png` 는 감성 분석이 끝난 기사가 있을 때만 생성됩니다.

한글 폰트는 실행 환경에 설치된 것을 자동으로 찾아 적용합니다.
(macOS `AppleGothic` → Windows `Malgun Gothic` → 리눅스 `NanumGothic` 순으로 탐색)
찾지 못하면 경고 로그를 남기고, 차트의 한글이 네모(□)로 보일 수 있습니다.
리눅스에서는 `sudo apt install fonts-nanum` 으로 설치할 수 있습니다.

화면이 없는 환경(GitHub Actions 등)에서도 동작하도록 matplotlib 백엔드는
파일 저장 전용(`Agg`)으로 고정했습니다.

### 4-3. 리포트 구성

`output/reports/report_날짜시각.md` (또는 `.txt`) 로 저장되고, 실행 시 콘솔에도 요약이 출력됩니다.

1. **데이터 품질 지표** (각 지표의 의미를 표에 함께 표기)
   - 요약 완료율 — 전체 뉴스 중 AI 요약이 끝난 비율
   - 본문 확보율 — 본문이 300자 이상 확보된 비율. 미만은 크롤링이 본문 영역을
     찾지 못해 메타 설명(150~200자)으로 대체된 경우
   - 평균 본문 길이
   - 본문 잘림 비율 — 3000자 상한에 걸려 뒷부분이 잘린 비율. 잘린 기사는
     AI가 원문 일부만 보고 요약하게 되므로 요약 신뢰도 판단에 쓴다
2. **수집 분포** — 카테고리별 / 소스별 건수, **수집 방식별 비교**, 일자별 추이 요약
   - 수집 방식별 비교는 `rss+crawl` / `api+crawl` / `crawl` 각각의 건수·평균 본문
     길이·본문 확보율을 나란히 보여준다. API·RSS 방식과 크롤링 방식의 장단점을
     숫자로 확인할 수 있다
3. **TOP N 집계** — AI가 추출한 키워드 TOP N
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
OPENAI_API_KEY=your_openai_api_key
```

- `NAVER_*` : NAVER 뉴스 검색 API (수집 단계)
- `OPENAI_API_KEY` : OpenAI API (AI 요약·분석 단계)

AI 모델은 `config.json` 의 `ai.model` 에서 바꿀 수 있습니다.

실제 API 키가 포함된 .env 파일은 GitHub에 업로드하지 않습니다

## 정기 실행 스케줄링 (보너스)

> **보너스 과제**: "cron 또는 작업 스케줄러를 이용한 정기 수집 방법을 README.md에 문서화한다."
> 본 저장소는 문서화에 그치지 않고 **GitHub Actions로 실제 자동화까지 적용**했습니다.

파이프라인은 비용과 주기가 다른 두 워크플로로 나눠 예약해 두었습니다.

| 워크플로 | 주기 | 하는 일 | 비용 |
| --- | --- | --- | --- |
| `collect.yml` | **매일** 06:00 KST | 수집(3소스) → 정제 | 무료 (외부 API만 사용) |
| `analyze.yml` | **매월 14일** 06:30 KST | 수집 → 정제 → AI 요약·감성 → 트렌드 분석 → 리포트 → 내보내기 | OpenAI API 과금 |

나눈 이유는 **비용** 입니다. 뉴스는 매일 쌓여야 추이 분석이 의미가 있지만, AI 단계까지 매일 돌리면
호출 비용이 계속 발생합니다. 그래서 무료인 수집·정제만 매일 돌리고, 과금되는 AI 단계는 2주에 한 번
몰아서 처리합니다. 요약은 아직 처리되지 않은 기사만 골라 실행하므로 그동안 쌓인 분량이 한 번에 정리됩니다.

### 방법 1. GitHub Actions (권장, 본 저장소에 적용됨)

PC를 켜두지 않아도 GitHub의 클라우드 러너가 정해진 시각에 자동 실행하고, 결과를 저장소에 커밋합니다.

**매일 수집 — `.github/workflows/collect.yml`**

- 스케줄: 매일 06:00 KST (cron `0 21 * * *`, UTC 기준)
- 동작: Google → NAVER → GOV.UK 각 20개씩 수집 → 정제 → 변경사항 자동 커밋·푸시

**전체 파이프라인 — `.github/workflows/analyze.yml`**

- 스케줄: 매월 14일 06:30 KST (cron `30 21 14 * *`, UTC 기준)
- 동작: 수집 → 정제 → AI 요약·감성 분석 → 트렌드 분석 → 리포트·차트 → 내보내기
- 매일 수집(21:00 UTC)이 먼저 푸시하므로 30분 뒤에 실행하고, 푸시 전 `git pull --rebase`로 최신 상태에 얹습니다.
- `output/exports/`는 `.gitignore` 대상이라 커밋되지 않으므로, 워크플로 아티팩트로 업로드해 30일간 내려받을 수 있게 했습니다.

**필요한 Secrets** — 저장소 Settings → Secrets and variables → Actions에 등록합니다.

| 이름 | 쓰이는 곳 |
| --- | --- |
| `NAVER_CLIENT_ID` | NAVER 뉴스 수집 (두 워크플로 공통) |
| `NAVER_CLIENT_SECRET` | NAVER 뉴스 수집 (두 워크플로 공통) |
| `OPENAI_API_KEY` | AI 요약·감성·트렌드 분석 (`analyze.yml` 전용) |

두 워크플로 모두 Actions 탭의 `Run workflow` 버튼으로 즉시 수동 실행할 수 있습니다(`workflow_dispatch`).

cron 표현식은 `분 시 일 월 요일` 순서입니다. `0 21 * * *`는 "매일 UTC 21시 정각",
`30 21 14 * *`는 "매월 14일 UTC 21시 30분"을 뜻합니다.

> cron은 달력 기준이라 "N일마다"를 직접 표현할 수 없습니다. 예를 들어 `*/14`는
> 1·15·29일에 걸린 뒤 다음 달 1일로 넘어가 마지막 간격만 2~3일이 됩니다.
> 그래서 날짜를 고정하는 방식(`14 * *`)을 썼습니다.

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


