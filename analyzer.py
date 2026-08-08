import json
import os
import time
from collections import Counter
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

MODEL_NAMES = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview",
]

_model_cache = {}


def get_model(index):
    name = MODEL_NAMES[index]
    if name not in _model_cache:
        _model_cache[name] = genai.GenerativeModel(name)
    return _model_cache[name]


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


def summarize_batch(batch, model):
    articles_text = "\n\n".join(
        f"[id: {r['id']}]\n제목: {r['title']}\n본문: {r['content'][:1200]}"
        for r in batch
    )
    prompt = f"""아래는 여러 개의 뉴스 기사입니다. 각 기사마다 3문장 이내 요약과 핵심 키워드 3개를 추출하세요.
반드시 아래 JSON 배열 형식으로만 응답하세요. 각 기사의 id를 정확히 그대로 포함하세요. 다른 설명은 붙이지 마세요.

[
  {{"id": "기사id", "summary": "요약", "keywords": ["키워드1", "키워드2", "키워드3"]}}
]

{articles_text}
"""
    response = model.generate_content(prompt)
    return response.text.strip()


def parse_batch_response(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


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


def is_quota_error(e):
    msg = str(e)
    return "429" in msg or "quota" in msg.lower() or "ResourceExhausted" in type(e).__name__


def summarize_all(records, output_path="data/analyzed/news_summary.jsonl", batch_size=5, delay=8):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    done_ids = load_done_ids(output_path)
    todo = [r for r in records if r["id"] not in done_ids]
    print(f"이미 완료: {len(done_ids)}건 / 남은 작업: {len(todo)}건")

    batches = [todo[i:i + batch_size] for i in range(0, len(todo), batch_size)]
    model_idx = 0

    with open(output_path, "a", encoding="utf-8") as f:
        for i, batch in enumerate(batches, 1):
            while True:
                if model_idx >= len(MODEL_NAMES):
                    print(f"모든 모델({len(MODEL_NAMES)}개) 할당량 소진. {i}/{len(batches)} 배치에서 중단.")
                    print(f"지금까지 저장된 결과: {output_path}")
                    return

                model_name = MODEL_NAMES[model_idx]
                print(f"[배치 {i}/{len(batches)}] {len(batch)}건 처리 중... (모델: {model_name})")
                try:
                    raw = summarize_batch(batch, get_model(model_idx))
                    parsed_list = parse_batch_response(raw)
                    break  # 성공 시 while 탈출
                except Exception as e:
                    if is_quota_error(e):
                        print(f"  {model_name} 할당량 초과. 다음 모델로 전환합니다.")
                        model_idx += 1
                        continue  # 같은 배치를 다음 모델로 재시도
                    else:
                        print(f"  배치 실패(할당량 문제 아님): {e}")
                        parsed_list = None
                        break

            if not parsed_list:
                continue

            by_id = {r["id"]: r for r in batch}
            for item in parsed_list:
                rid = item.get("id")
                rec = by_id.get(rid)
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
                }
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
            f.flush()
            time.sleep(delay)

    print(f"완료: {output_path}")


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

    prompt = f"""아래는 최근 수집된 AI 관련 뉴스 {len(summaries)}건의 요약 목록과, 실제 집계된 키워드·카테고리 통계입니다.

[실제 키워드 빈도 (상위 {len(keyword_stats)}개)]
{kw_lines}

[카테고리 분포]
{cat_lines}

[뉴스 요약 목록]
{summary_lines}

위 데이터를 바탕으로 주요 트렌드와 시사점을 분석하세요.
반드시 아래 JSON 형식으로만 응답하세요. 다른 설명은 붙이지 마세요. 숫자나 빈도는 위에 제시된 실제 통계만 참고하고 새로 추정하지 마세요.

{{
  "trends": [
    {{"title": "트렌드 제목", "description": "트렌드 설명 (2~3문장, 관련 키워드나 기사 근거 포함)"}}
  ],
  "implications": [
    "시사점 1 (뉴스 흐름이 시사하는 산업적/기술적 의미)"
  ],
  "overall_summary": "전체 뉴스 흐름을 요약하는 3~4문장"
}}

trends는 3~6개, implications는 3~5개 작성하세요.
"""
    return prompt


def analyze_trends(summaries, output_path="data/analyzed/trend_report.json"):
    keyword_stats = compute_keyword_stats(summaries)
    category_stats = compute_category_stats(summaries)

    model_idx = 0
    parsed = None
    while model_idx < len(MODEL_NAMES):
        model_name = MODEL_NAMES[model_idx]
        print(f"트렌드 분석 중... (모델: {model_name})")
        try:
            prompt = build_trend_prompt(summaries, keyword_stats, category_stats)
            response = get_model(model_idx).generate_content(prompt)
            parsed = parse_batch_response(response.text.strip())
            break
        except Exception as e:
            if is_quota_error(e):
                print(f"  {model_name} 할당량 초과. 다음 모델로 전환합니다.")
                model_idx += 1
                continue
            else:
                print(f"  트렌드 분석 실패: {e}")
                return None

    if parsed is None:
        print("모든 모델 할당량 소진. 트렌드 분석 실패.")
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

    print(f"완료: {output_path}")
    return result


if __name__ == "__main__":
    data = load_clean_news()
    print(f"로드된 레코드 수: {len(data)}")

    summarize_all(data)

    summaries = load_summaries()
    analyze_trends(summaries)