"""AI 요약·트렌드 분석 (3번 파트).

OpenAI API 를 사용한다.
모델은 config.json 의 ai.model 로 바꿀 수 있고,
API 키는 .env 의 OPENAI_API_KEY 에서 읽는다.

응답은 structured outputs(response_format 의 json_schema, strict 모드)로 받는다.
JSON 스키마를 API 쪽에서 강제하므로 모델이 ```json 코드펜스를 붙이거나
형식을 어길 일이 없어 파싱이 안정적이다.

호출 한도(429)·서버 오류(5xx)는 SDK 가 지수 백오프로 자동 재시도하므로
직접 재시도 루프를 만들지 않는다 (MAX_RETRIES 로 횟수만 지정).
"""

import json
import os
import time
from collections import Counter

from dotenv import load_dotenv
from openai import OpenAI

from log_setup import get_logger

load_dotenv()

# 요구사항: API 실패는 로깅 후 스킵. print 가 아니라 로거로 남겨야
# logs/pipeline.log 에 기록이 남아 사후 확인이 된다.
log = get_logger("analyze")

DEFAULT_MODEL = "gpt-5.4"
MAX_RETRIES = 5       # 429·5xx 자동 재시도 횟수 (SDK 기본값은 2)
MAX_TOKENS = 16000    # 응답 상한. gpt-5 계열은 내부 추론 토큰도 이 한도를 함께 쓴다

_client = None
_config_cache = None


def load_config(path="config.json"):
    """config.json 의 ai 설정을 읽는다. 파일이 없거나 ai 항목이 없으면 기본값."""
    global _config_cache
    if _config_cache is None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                _config_cache = json.load(f).get("ai", {})
        except (FileNotFoundError, json.JSONDecodeError):
            _config_cache = {}
    return _config_cache


def get_model_name():
    return load_config().get("model", DEFAULT_MODEL)


def get_client():
    """OpenAI 클라이언트를 만든다(한 번만).

    모듈 상단이 아니라 함수 안에서 만드는 이유: 키가 없는 환경에서도
    `import analyzer` 자체는 성공해야 한다. 그래야 analyze_command 가
    안내 문구를 대신 띄울 수 있다.
    """
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                ".env 에 OPENAI_API_KEY 가 없습니다. "
                "프로젝트 루트의 .env 에 OPENAI_API_KEY=sk-... 형태로 추가하세요."
            )
        _client = OpenAI(api_key=api_key, max_retries=MAX_RETRIES)
    return _client


def call_model(prompt, schema_name, schema):
    """프롬프트를 보내고 스키마에 맞는 dict 를 돌려준다.

    strict 모드 structured outputs 라 응답이 반드시 이 스키마 형태로 온다.
    실패 시에는 예외를 올려 호출한 쪽에서 로깅·스킵하게 한다.
    """
    response = get_client().chat.completions.create(
        model=get_model_name(),
        # gpt-5 계열은 max_tokens 를 거부한다(400). max_completion_tokens 를 써야 한다.
        max_completion_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        },
    )

    choice = response.choices[0]
    # 안전 정책상 거부하면 content 대신 refusal 이 채워진다. 먼저 확인한다.
    if getattr(choice.message, "refusal", None):
        raise RuntimeError(f"모델이 응답을 거부했습니다: {choice.message.refusal}")
    if choice.finish_reason == "length":
        raise RuntimeError(f"응답이 max_tokens({MAX_TOKENS})에서 잘렸습니다")
    if not choice.message.content:
        raise RuntimeError("응답이 비어 있습니다")

    return json.loads(choice.message.content)


# ── 응답 형식 정의 ──────────────────────────────────────────────
# strict 모드는 모든 객체에 additionalProperties: false 와 required 를 요구한다.
# 개수 제한(3~6개 등)은 스키마가 지원하지 않으므로 프롬프트 문장으로 지시한다.

SENTIMENT_LABELS = ["긍정", "부정", "중립"]

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "summary": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "sentiment": {"type": "string", "enum": SENTIMENT_LABELS},
                },
                "required": ["id", "summary", "keywords", "sentiment"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

# 이미 요약된 기사에 감성만 뒤늦게 채울 때 쓰는 스키마.
# 본문 대신 제목+요약만 보내므로 요약 재실행보다 훨씬 싸다.
SENTIMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "sentiment": {"type": "string", "enum": SENTIMENT_LABELS},
                },
                "required": ["id", "sentiment"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

TREND_SCHEMA = {
    "type": "object",
    "properties": {
        "trends": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["title", "description"],
                "additionalProperties": False,
            },
        },
        "implications": {"type": "array", "items": {"type": "string"}},
        "overall_summary": {"type": "string"},
    },
    "required": ["trends", "implications", "overall_summary"],
    "additionalProperties": False,
}


def load_clean_news(path="data/clean/news_clean.jsonl"):
    records = []
    if not os.path.exists(path):
        raise FileNotFoundError(f"clean 데이터 없음: {path}")

    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # 파싱 실패 라인 skip

            required = ["id", "title", "content", "published_date", "category"]
            if not all(rec.get(k) for k in required):
                continue  # 필수 필드 결측 시 skip

            records.append(rec)

    return records


def summarize_batch(batch):
    articles_text = "\n\n".join(
        f"[id: {r['id']}]\n제목: {r['title']}\n본문: {r['content'][:1200]}"
        for r in batch
    )
    prompt = f"""아래는 여러 개의 뉴스 기사입니다. 각 기사마다 아래 세 가지를 뽑으세요.

1. 3문장 이내 요약
2. 핵심 키워드 3개
3. 기사 논조의 감성: 긍정 / 부정 / 중립 중 하나
   - 긍정: 성장·성과·호재·기대를 다루는 기사
   - 부정: 위기·규제·손실·우려를 다루는 기사
   - 중립: 사실 전달 위주이거나 긍정·부정이 뚜렷하지 않은 기사

기사 하나당 결과 하나씩, 총 {len(batch)}개를 results 에 담으세요. 각 기사의 id를 정확히 그대로 포함하세요.

{articles_text}
"""
    return call_model(prompt, "news_summaries", SUMMARY_SCHEMA)["results"]


def load_done_ids(output_path):
    if not os.path.exists(output_path):
        return set()
    done = set()
    with open(output_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                done.add(json.loads(line)["id"])
    return done


def summarize_all(records, output_path="data/analyzed/news_summary.jsonl",
                  batch_size=5, delay=0):
    # 키가 없으면 배치마다 같은 오류를 반복하지 않도록 먼저 한 번만 확인한다
    try:
        get_client()
    except RuntimeError as e:
        log.error("%s", e)
        return

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    done_ids = load_done_ids(output_path)
    todo = [r for r in records if r["id"] not in done_ids]
    log.info("이미 완료: %d건 / 남은 작업: %d건", len(done_ids), len(todo))

    batches = [todo[i:i + batch_size] for i in range(0, len(todo), batch_size)]
    model = get_model_name()
    ok_count = fail_count = 0

    with open(output_path, "a", encoding="utf-8") as f:
        for i, batch in enumerate(batches, 1):
            log.info("[배치 %d/%d] %d건 처리 중... (모델: %s)", i, len(batches), len(batch), model)
            try:
                parsed_list = summarize_batch(batch)
            except Exception as e:
                # 요구사항: API 실패 시 로깅 후 스킵
                log.error("배치 %d 실패, %d건 스킵: %s: %s", i, len(batch), type(e).__name__, e)
                fail_count += len(batch)
                continue

            by_id = {r["id"]: r for r in batch}
            for item in parsed_list:
                rec = by_id.get(item.get("id"))
                if not rec:
                    continue
                result = {
                    "id": rec["id"],
                    "title": rec["title"],
                    "category": rec["category"],
                    "source": rec["source"],
                    "published_date": rec["published_date"],
                    "summary": item.get("summary", ""),
                    "keywords": item.get("keywords", []),
                    "sentiment": item.get("sentiment", ""),
                }
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
                ok_count += 1
            f.flush()

            if delay and i < len(batches):
                time.sleep(delay)

    log.info("요약 완료: %d건 성공, %d건 실패 -> %s", ok_count, fail_count, output_path)


def classify_sentiment_batch(batch):
    """요약 레코드 묶음의 감성을 분류한다(제목+요약만 사용)."""
    items_text = "\n\n".join(
        f"[id: {r['id']}]\n제목: {r.get('title','')}\n요약: {r.get('summary','')}"
        for r in batch
    )
    prompt = f"""아래 뉴스들의 논조를 긍정 / 부정 / 중립 중 하나로 분류하세요.

- 긍정: 성장·성과·호재·기대를 다루는 기사
- 부정: 위기·규제·손실·우려를 다루는 기사
- 중립: 사실 전달 위주이거나 긍정·부정이 뚜렷하지 않은 기사

뉴스 하나당 결과 하나씩, 총 {len(batch)}개를 results 에 담으세요. id를 정확히 그대로 포함하세요.

{items_text}
"""
    return call_model(prompt, "news_sentiments", SENTIMENT_SCHEMA)["results"]


def backfill_sentiment(output_path="data/analyzed/news_summary.jsonl",
                       batch_size=10):
    """감성 값이 비어 있는 요약 레코드를 채운다.

    요약을 먼저 끝낸 뒤 감성 분석을 추가했기 때문에, 기존 레코드에는
    sentiment 가 없다. 요약을 다시 돌리면 비싸므로 제목+요약만 보내
    감성만 채우고 파일을 다시 쓴다.
    """
    try:
        get_client()
    except RuntimeError as e:
        log.error("%s", e)
        return

    records = load_summaries(output_path)
    todo = [r for r in records if not r.get("sentiment")]
    if not todo:
        log.info("감성 분석: 채울 레코드가 없습니다 (전체 %d건 완료)", len(records))
        return

    log.info("감성 분석 대상: %d건 / 전체 %d건", len(todo), len(records))
    batches = [todo[i:i + batch_size] for i in range(0, len(todo), batch_size)]
    by_id = {r["id"]: r for r in records}
    ok_count = fail_count = 0

    for i, batch in enumerate(batches, 1):
        log.info("[감성 %d/%d] %d건 처리 중...", i, len(batches), len(batch))
        try:
            parsed_list = classify_sentiment_batch(batch)
        except Exception as e:
            log.error("감성 배치 %d 실패, %d건 스킵: %s: %s",
                      i, len(batch), type(e).__name__, e)
            fail_count += len(batch)
            continue

        for item in parsed_list:
            rec = by_id.get(item.get("id"))
            if rec is not None and item.get("sentiment"):
                rec["sentiment"] = item["sentiment"]
                ok_count += 1

    # 중간에 실패해도 원본이 날아가지 않도록 임시 파일에 먼저 쓰고 교체한다
    tmp_path = output_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp_path, output_path)

    log.info("감성 분석 완료: %d건 성공, %d건 실패 -> %s",
             ok_count, fail_count, output_path)


def load_summaries(path="data/analyzed/news_summary.jsonl"):
    if not os.path.exists(path):
        raise FileNotFoundError(f"요약 데이터 없음: {path}")
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def compute_keyword_stats(summaries, top_n=15):
    counter = Counter()
    for r in summaries:
        for kw in r.get("keywords", []):
            counter[kw] += 1
    return counter.most_common(top_n)


def compute_category_stats(summaries):
    return dict(Counter(r.get("category", "") for r in summaries))


def build_trend_prompt(summaries, keyword_stats, category_stats):
    kw_lines = "\n".join(f"- {kw}: {count}건" for kw, count in keyword_stats)
    cat_lines = "\n".join(f"- {cat}: {count}건" for cat, count in category_stats.items())
    summary_lines = "\n".join(
        f"- [{r.get('published_date','')}] {r.get('title','')}: {r.get('summary','')}"
        for r in summaries
    )

    return f"""아래는 최근 수집된 AI 관련 뉴스 {len(summaries)}건의 요약 목록과, 실제 집계된 키워드·카테고리 통계입니다.

[실제 키워드 빈도 (상위 {len(keyword_stats)}개)]
{kw_lines}

[카테고리 분포]
{cat_lines}

[뉴스 요약 목록]
{summary_lines}

위 데이터를 바탕으로 주요 트렌드와 시사점을 분석하세요.
숫자나 빈도는 위에 제시된 실제 통계만 참고하고 새로 추정하지 마세요.

trends 는 3~6개를 작성하되 각 항목의 description 은 2~3문장으로 관련 키워드나 기사 근거를 포함하세요.
implications 는 뉴스 흐름이 시사하는 산업적·기술적 의미를 3~5개 작성하세요.
overall_summary 는 전체 뉴스 흐름을 3~4문장으로 요약하세요.
"""


def analyze_trends(summaries, output_path="data/analyzed/trend_report.json"):
    try:
        get_client()
    except RuntimeError as e:
        log.error("%s", e)
        return None

    keyword_stats = compute_keyword_stats(summaries)
    category_stats = compute_category_stats(summaries)
    model = get_model_name()

    log.info("트렌드 분석 중... (모델: %s, 대상 %d건)", model, len(summaries))
    try:
        prompt = build_trend_prompt(summaries, keyword_stats, category_stats)
        parsed = call_model(prompt, "trend_report", TREND_SCHEMA)
    except Exception as e:
        log.error("트렌드 분석 실패: %s: %s", type(e).__name__, e)
        return None

    result = {
        "keyword_frequency": [{"keyword": kw, "count": c} for kw, c in keyword_stats],
        "category_distribution": category_stats,
        "article_count": len(summaries),
        **parsed,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    log.info("완료: %s", output_path)
    return result


if __name__ == "__main__":
    data = load_clean_news()
    print(f"로드된 레코드 수: {len(data)}")

    summarize_all(data)

    summaries = load_summaries()
    analyze_trends(summaries)
