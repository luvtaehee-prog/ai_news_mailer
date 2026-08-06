# 데이터 정제 (clean) 파트 — 2번 담당

raw 저장소의 뉴스를 정제 규칙에 따라 다듬어 clean 저장소(JSONL)에 저장합니다.
프로젝트 스펙의 `clean` 서브커맨드에 해당합니다.

## 파일 구성 (모듈 분리)

| 파일 | 역할 |
|------|------|
| `cleaner.py` | 정제 핵심 로직 (HTML 제거 · 제목/언론사 분리 · 날짜 통일 · 필드 검증) |
| `store.py` | raw 읽기, clean 저장, 중복(skip/upsert) 처리 |
| `log_setup.py` | 로깅 설정 (INFO/WARNING/ERROR, 콘솔+파일) |
| `clean_command.py` | `clean` 서브커맨드 진입점 (단독 실행도 가능) |

## 실행 방법

내 파트만 단독으로 테스트:

```bash
python clean_command.py                 # config.json의 정책 사용
python clean_command.py --limit 100     # 최대 100건만
python clean_command.py --policy upsert # 기존 데이터 덮어쓰기
```

## 리더의 main.py에 붙이기

main.py 상단과 서브파서 등록부에 아래를 추가하면 `python main.py clean`으로 동작합니다.

```python
from clean_command import add_clean_parser, cmd_clean

# argparse 서브파서를 만든 뒤:
add_clean_parser(subparsers)

# 커맨드 분기부에:
if args.command == "clean":
    cmd_clean(args)
```

## config.json에서 읽는 값

정제 단계는 아래 키를 사용합니다. (없으면 기본값으로 동작)

```json
{
  "duplicate_policy": "skip",
  "paths": { "raw": "data/raw", "clean": "data/clean" },
  "clean": {
    "min_title_length": 2,
    "max_content_length": 3000,
    "dedup_by_title": true,
    "press_in_title_sources": ["google"],
    "category_by_source": { "google": "IT", "naver": "IT", "gov.uk": "정책/정부" },
    "default_category": "미분류"
  }
}
```

- `max_content_length`: 본문 최대 글자 수 (긴 gov.uk 기사 절단, 0이면 무제한)
- `dedup_by_title`: url이 달라도 제목이 같으면 중복 제거 (같은 기사 재게재 방지).
  제목이 겹치면 본문이 더 긴 복사본을 남김.

## clean 레코드 스키마 (3번·4번 담당에게 넘어가는 형태)

`data/clean/news_clean.jsonl` — 한 줄에 뉴스 1건(JSONL)

| 필드 | 설명 |
|------|------|
| `id` | url 기반 고유 id (중복 판별 키) |
| `title` | 언론사명을 뗀 순수 제목 |
| `press` | 언론사명 |
| `content` | HTML 제거된 본문 (비면 제목으로 대체, 최대 3000자로 절단) |
| `content_length` | 본문 글자 수 (품질 지표용) |
| `truncated` | 본문이 길이 상한으로 잘렸는지 여부 |
| `url` | 기사 링크 |
| `category` | 카테고리 (없으면 source 기준/기본값) |
| `source` | 수집처 (google, naver 등) |
| `collection_method` | 수집 방식 (rss, crawl 등) |
| `published_at` | 발행일시 KST ISO (예: 2026-08-06T09:40:23+09:00) |
| `published_date` | 발행일 (예: 2026-08-06) — 일자별 추이용 |
| `collected_at` | 수집 시각 |
| `cleaned_at` | 정제 시각 |

## 소스별 데이터 특성 (실제 확인됨)

| 소스 | 본문(content) | 날짜 형식 | 특이사항 |
|------|--------------|----------|---------|
| google (rss) | **없음** — 제목+언론사 반복만 | `Thu, 06 Aug 2026 00:40:23 GMT` | 제목 끝 `- 언론사` 분리함 |
| naver (api) | **요약 있음** | `Thu, 06 Aug 2026 11:33:00 +0900` | `<b>`, `&quot;` 정리함 |
| gov.uk (crawl) | **전체 본문** | `3 August 2026` (+뒤에 잡문구) | 영문, 날짜만 추출 |

세 소스 모두 정제 통과(193건, 제외 0). 날짜는 전부 한국시간 ISO로 통일됨.

## 팀에 확인할 점

- **google 본문 부재**: 구글 RSS만 실제 본문이 없고 제목만 있음. 3번(AI 요약)이
  구글 기사를 제목만으로 요약할지, 원문 크롤링을 추가할지 리더와 협의 필요.
  (naver·gov.uk는 본문이 있어 요약 가능)
- **카테고리**: naver는 `search_keyword`(AI/생성형 AI/AI 반도체/인공지능/LLM)를
  카테고리로 활용함. google·gov.uk는 해당 정보가 없어 source 기준으로 채움
  (google→IT, gov.uk→정책/정부). 최종 7개 카테고리.
  google/gov.uk도 세분화하려면 수집 단계에서 주제 태깅이 필요함.
