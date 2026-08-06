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

### 모듈별 역할

| 파일             | 역할                                    |
| -------------- | ------------------------------------- |
| `main.py`      | CLI 명령을 받아 각 모듈의 기능을 실행               |
| `collector.py` | 뉴스 API/RSS 및 크롤링을 이용한 뉴스 수집           |
| `cleaner.py`   | 원본 데이터 검증, 중복 처리, 텍스트 및 날짜 정제         |
| `analyzer.py`  | AI API를 이용한 개별 뉴스 요약 및 종합 트렌드 분석      |
| `reporter.py`  | 통계 집계, matplotlib 시각화, 리포트 및 결과 파일 생성 |

### 데이터 처리 흐름

```text
뉴스 API / RSS / 웹 크롤링
            │
            ▼
      collector.py
            │
            ▼
       data/raw/
            │
            ▼
       cleaner.py
            │
            ▼
      data/clean/
            │
            ▼
       analyzer.py
            │
            ▼
 AI 요약 및 트렌드 분석 결과
            │
            ▼
       reporter.py
            │
            ▼
   차트 / 리포트 / CSV·Excel
```

각 담당자는 자신의 모듈을 중심으로 개발하고, 모듈 사이에서는 공통된 뉴스 데이터 구조를 사용합니다.

### 공통 뉴스 데이터 구조 예시

```json
{
  "title": "뉴스 제목",
  "content": "뉴스 본문",
  "url": "https://example.com/news",
  "published_at": "2026-08-06",
  "source": "뉴스 출처",
  "collected_at": "2026-08-06T10:30:00",
  "collection_method": "rss"
}
```

`collection_method`에는 뉴스가 어떤 방식으로 수집되었는지 구분할 수 있도록 `rss`, `api`, `crawl` 등의 값을 저장합니다.
