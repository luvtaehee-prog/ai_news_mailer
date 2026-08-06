# AI News Trend Analysis

AI 뉴스 트렌드 분석 팀 프로젝트


## 프로젝트 구조

본 프로젝트는 기능별로 모듈을 분리하여 개발합니다.

```text
project/
│
├── main.py              # CLI 실행 및 각 기능 연결
├── collector.py         # 뉴스 수집 (API/RSS, 크롤링)
├── cleaner.py           # 뉴스 데이터 정제
├── analyzer.py          # AI 뉴스 요약 및 트렌드 분석
├── reporter.py          # 시각화 및 리포트 생성
│
├── data/
│   ├── raw/             # 수집한 원본 뉴스 데이터
│   └── clean/           # 정제된 뉴스 데이터
│
├── output/              # 차트, 리포트, 내보내기 결과
├── logs/                # 실행 및 오류 로그
│
├── config.json          # 뉴스 소스, 중복 처리 정책 등 설정
├── requirements.txt     # Python 패키지 목록
└── README.md
```

### 팀 역할

| 역할            | 담당 기능                                  |
| -------------- | ------------------------------------- |
|   뉴스 수집     | RSS / API / 웹 크롤링을 통한 AI 뉴스 수집   |
|   데이터 정제   | 뉴HTML 제거, 날짜 통일, 중복 제거          |
|     AI 분석     | 뉴스 요약, 카테고리 분류, 키워드 추출         |
| 리포트 생성  | A계 집계 및 Markdown 리포트 생성      |


## 1. 뉴스 수집

collector.py에서 뉴스 데이터를 수집합니다.

현재 다음 세 가지 소스를 지원합니다.

### Google News
 - Google News RSS 사용
 - AI 관련 뉴스 수집
 - 수집 방법: rss

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
 - 수집 방법: api

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
  "content": "뉴스 본문 또는 요약",
  "url": "뉴스 URL",
  "published_at": "발행 시각",
  "source": "뉴스 소스",
  "collected_at": "수집 시각",
  "collection_method": "rss | api | crawl"
}
```

- NAVER 뉴스의 경우 수집에 사용된 검색어를 확인할 수 있도록 search_keyword 필드가 추가됩니다.

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

정제 담당 구현 후 작성 예정.

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


