# AI News Trend Analysis

AI 뉴스 트렌드 분석 팀 프로젝트


## 프로젝트 구조

본 프로젝트는 기능별로 모듈을 분리하여 개발합니다.

```text
project/
│
├── main.py              # CLI 실행 (현재 fetch 서브커맨드만 연결됨)
├── collector.py         # 뉴스 수집 (API/RSS, 크롤링)
├── cleaner.py           # 정제 핵심 로직 (필드 검증, 텍스트 정규화, 날짜 통일, 결측값 처리)
├── store.py             # raw 읽기 / clean 저장 / 중복 처리(skip·upsert)
├── clean_command.py     # clean 서브커맨드 진입점 (main.py 미연결, 단독 실행)
├── log_setup.py         # clean 파이프라인 로깅 설정
├── analyzer.py          # AI 뉴스 요약 및 트렌드 분석 (예정, 미구현)
├── reporter.py          # 시각화 및 리포트 생성 (예정, 미구현)
│
├── data/
│   ├── raw/             # 수집한 원본 뉴스 데이터 (google/naver/govuk_news.jsonl)
│   └── clean/           # 정제된 뉴스 데이터 (news_clean.jsonl)
│
├── output/              # 차트, 리포트, 내보내기 결과 (예정, 미구현)
├── logs/                # 실행 로그 (collector.log 등)
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
| 리포트 생성  | A계 집계 및 Markdown 리포트 생성      |


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

실행 (아직 main.py에는 연결되지 않아 단독 실행):
```text
python clean_command.py
python clean_command.py --policy upsert
```

정제된 데이터는 raw와 분리된 `data/clean/news_clean.jsonl`에 저장됩니다.

## 3. AI 분석

AI 분석 담당 구현 후 작성 예정.

## 4. 리포트 생성

리포트 담당 구현 후 작성 예정.

전체 파이프라인

모든 모듈 구현 완료 후 다음 명령으로 전체 파이프라인을 실행합니다.

python main.py run --source google --limit 20

최종 파이프라인:

```text
뉴스 수집
   ↓
Raw JSONL 저장
   ↓
데이터 정제
   ↓
AI 요약 / 분류 / 키워드 추출
   ↓
통계 집계
   ↓
Markdown 리포트 생성
```


### 환경변수

.env 예시:
```text

NAVER_CLIENT_ID=your_client_id
NAVER_CLIENT_SECRET=your_client_secret
```

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


