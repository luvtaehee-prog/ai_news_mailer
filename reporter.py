"""리포트 모듈 (4번 파트).

역할:
  1) clean / summary / trend 데이터를 읽어온다 (load_all)
  2) 품질 지표와 TOP N 집계를 계산한다 (build_stats)
  3) AI 인사이트를 합쳐 사람이 읽는 리포트 문서를 만든다 (build_report)

차트 그리기는 visualizer.py, 파일 내보내기는 exporter.py 가 담당한다.

단독 실행 (리포트만 다시 생성):
    python reporter.py
"""

import os
import json
from collections import Counter
from datetime import datetime

from log_setup import get_logger

log = get_logger("report")

DEFAULT_PATHS = {
    "clean": "data/clean/news_clean.jsonl",
    "summary": "data/analyzed/news_summary.jsonl",
    "trend": "data/analyzed/trend_report.json",
    "output": "output",
}

# 본문이 이 길이 미만이면 '본문 확보 실패'로 본다.
# 크롤링이 기사 본문 영역을 못 찾으면 메타 설명(og:description)으로 대체되는데,
# 그 값이 보통 150~200자다. 그보다 넉넉히 잡아 진짜 본문인지 가르는 기준으로 쓴다.
MIN_USABLE_CONTENT = 300

# 지표 이름만으로는 뜻이 통하지 않아 리포트에 함께 싣는 설명
QUALITY_DESC = {
    "총 뉴스 수": "정제를 통과해 저장된 기사 수",
    "요약 완료율": "AI 요약이 끝난 기사 비율",
    "본문 확보율": f"본문이 {MIN_USABLE_CONTENT}자 이상 확보된 비율. "
               "미만은 크롤링이 본문을 못 찾아 메타 설명으로 대체된 경우",
    "평균 본문 길이": "기사 한 건당 평균 본문 글자 수",
    "본문 잘림 비율": "본문 길이 상한을 넘어 뒷부분이 잘린 비율. "
                "잘린 기사는 AI가 원문 일부만 보고 요약하게 됨",
}

# 수집 방식별 비교 표 아래에 붙는 해설
METHOD_NOTE = (
    "> `rss+crawl` / `api+crawl` 은 RSS·API 로 기사 목록을 받은 뒤 원문을 "
    "크롤링한 방식이고, `crawl` 은 목록부터 본문까지 모두 크롤링한 방식입니다.\n"
    ">\n"
    "> RSS·API 는 목록을 빠르고 안정적으로 받아오지만 본문은 주지 않아 결국 "
    "크롤링이 필요하고, 실패하면 짧은 메타 설명으로 대체되어 본문 확보율이 "
    "떨어집니다. 반면 전체 크롤링은 본문 확보율이 높은 대신 사이트 구조에 "
    "맞춘 코드가 따로 필요하고 요청 간 지연을 둬야 해 느립니다."
)


def load_jsonl(path: str) -> list:
    """JSONL 파일을 레코드 리스트로 읽는다. 파일이 없으면 빈 리스트."""
    records = []
    if not os.path.exists(path):
        log.warning("파일 없음: %s", path)
        return records

    broken = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                broken += 1  # 깨진 줄은 건너뛰고 개수만 남긴다
    if broken:
        log.warning("%s: 파싱 실패 %d줄 건너뜀", path, broken)
    return records


def load_json(path: str) -> dict:
    """단일 JSON 파일을 읽는다. 없거나 깨졌으면 빈 dict."""
    if not os.path.exists(path):
        log.warning("파일 없음: %s", path)
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        log.error("JSON 파싱 실패: %s", path)
        return {}


def load_all(paths: dict = None) -> dict:
    """리포트에 필요한 세 종류 데이터를 한 번에 읽는다."""
    p = {**DEFAULT_PATHS, **(paths or {})}
    data = {
        "clean": load_jsonl(p["clean"]),
        "summaries": load_jsonl(p["summary"]),
        "trend": load_json(p["trend"]),
    }
    log.info("데이터 로드: clean %d건, 요약 %d건, 트렌드 %s",
             len(data["clean"]), len(data["summaries"]),
             "있음" if data["trend"] else "없음")
    return data


def filter_records(records: list, category: str = None,
                   date_from: str = None, date_to: str = None) -> list:
    """카테고리/기간 조건으로 뉴스를 걸러낸다. 조건이 없으면 전체를 그대로 반환."""
    out = []
    for r in records:
        if category and r.get("category") != category:
            continue
        pub = r.get("published_date", "")
        if date_from and pub < date_from:
            continue
        if date_to and pub > date_to:
            continue
        out.append(r)
    return out


def build_stats(data: dict, top_n: int = 10,
                date_field: str = "published") -> dict:
    """집계와 품질 지표를 계산한다.

    date_field = "published" : 기사 발행일 기준 추이
    date_field = "collected" : 우리가 수집한 날짜 기준 추이
    """
    clean = data.get("clean", [])
    summaries = data.get("summaries", [])
    total = len(clean)

    # --- 분포 집계 ---------------------------------------------------
    category_counts = dict(
        Counter(r.get("category") or "미분류" for r in clean).most_common())
    source_counts = dict(
        Counter(r.get("source") or "unknown" for r in clean).most_common())

    # 수집 방식별 비교 (API/RSS 와 크롤링의 차이를 숫자로 확인하기 위한 집계)
    method_groups = {}
    for r in clean:
        method_groups.setdefault(r.get("collection_method") or "미상", []).append(r)

    method_stats = []
    for method, records in sorted(method_groups.items(),
                                  key=lambda kv: -len(kv[1])):
        sizes = [r.get("content_length") or len(r.get("content") or "")
                 for r in records]
        method_stats.append({
            "method": method,
            "count": len(records),
            "sources": ", ".join(sorted({r.get("source", "?")
                                         for r in records})),
            "avg_length": round(sum(sizes) / len(sizes)) if sizes else 0,
            "usable_pct": round(
                sum(1 for n in sizes if n >= MIN_USABLE_CONTENT)
                / len(sizes) * 100, 1) if sizes else 0.0,
        })

    key = "published_date" if date_field == "published" else "collected_at"
    day_counter = Counter()
    for r in clean:
        value = (r.get(key) or "")[:10]  # ISO 문자열 앞 10글자 = YYYY-MM-DD
        if value:
            day_counter[value] += 1
    daily_counts = sorted(day_counter.items())

    # --- TOP N 집계 --------------------------------------------------
    keyword_counter = Counter()
    for s in summaries:
        for kw in s.get("keywords", []):
            kw = (kw or "").strip()
            if kw:
                keyword_counter[kw] += 1
    top_keywords = keyword_counter.most_common(top_n)

    # --- 감성 분포 (보너스) ------------------------------------------
    # 값이 비어 있는 레코드(감성 분석 전에 요약된 건)는 세지 않는다.
    sentiment_counter = Counter()
    for s in summaries:
        label = (s.get("sentiment") or "").strip()
        if label:
            sentiment_counter[label] += 1
    # 건수 순이 아니라 긍정 → 중립 → 부정 순으로 고정해 읽기 쉽게 둔다
    order = ["긍정", "중립", "부정"]
    sentiment_counts = {k: sentiment_counter[k] for k in order
                        if sentiment_counter.get(k)}
    for k, v in sentiment_counter.most_common():   # 예상 밖 라벨이 와도 누락 방지
        sentiment_counts.setdefault(k, v)
    sentiment_total = sum(sentiment_counts.values())

    # --- 품질 지표 ---------------------------------------------------
    summarized_ids = {s.get("id") for s in summaries if s.get("id")}
    clean_ids = {r.get("id") for r in clean if r.get("id")}
    summarized_in_clean = len(clean_ids & summarized_ids)

    lengths = [r.get("content_length") or len(r.get("content") or "")
               for r in clean]
    usable = sum(1 for n in lengths if n >= MIN_USABLE_CONTENT)
    truncated = sum(1 for r in clean if r.get("truncated"))

    def pct(part: int, whole: int) -> float:
        """0으로 나누는 상황을 막으면서 백분율을 계산한다."""
        return round(part / whole * 100, 1) if whole else 0.0

    quality = {
        "총 뉴스 수": f"{total}건",
        "요약 완료율": f"{pct(summarized_in_clean, total)}% "
                   f"({summarized_in_clean}/{total}건)",
        "본문 확보율": f"{pct(usable, total)}% ({usable}/{total}건)",
        "평균 본문 길이": f"{round(sum(lengths) / total) if total else 0}자",
        "본문 잘림 비율": f"{pct(truncated, total)}% ({truncated}/{total}건)",
    }

    period = ""
    if daily_counts:
        period = f"{daily_counts[0][0]} ~ {daily_counts[-1][0]}"

    return {
        "total": total,
        "summarized": summarized_in_clean,
        "period": period,
        "date_field": date_field,
        "category_counts": category_counts,
        "source_counts": source_counts,
        "method_stats": method_stats,
        "daily_counts": daily_counts,
        "top_keywords": top_keywords,
        "sentiment_counts": sentiment_counts,
        "sentiment_total": sentiment_total,
        "quality": quality,
    }


def _md_table(headers: list, rows: list) -> str:
    """Markdown 표 문자열을 만든다."""
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def build_report(stats: dict, trend: dict, chart_paths: list = None,
                 report_dir: str = "output/reports") -> str:
    """집계 + AI 인사이트를 합쳐 Markdown 리포트 본문을 만든다."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    label = "발행일" if stats["date_field"] == "published" else "수집일"
    parts = []

    parts.append("# AI 뉴스 트렌드 리포트\n")
    parts.append(f"- 생성 시각: {now}")
    parts.append(f"- 대상 기간({label} 기준): {stats['period'] or '데이터 없음'}")
    parts.append(f"- 분석 대상: 총 {stats['total']}건 "
                 f"(AI 요약 완료 {stats['summarized']}건)\n")
    parts.append("> 항목마다 세는 대상이 다릅니다. 수집·정제 현황은 정제 완료 "
                 f"{stats['total']}건 전체를, 키워드와 AI 인사이트는 요약이 끝난 "
                 f"{stats['summarized']}건을 기준으로 합니다. "
                 "키워드는 AI가 추출하는 값이라 요약 전 기사에는 존재하지 않습니다.\n")

    # 1. 품질 지표
    parts.append(f"## 1. 데이터 품질 지표 (정제 완료 {stats['total']}건 기준)\n")
    parts.append(_md_table(
        ["지표", "값", "의미"],
        [[k, v, QUALITY_DESC.get(k, "")] for k, v in stats["quality"].items()]))
    parts.append("")

    # 2. 분포 집계
    parts.append(f"## 2. 수집 분포 (정제 완료 {stats['total']}건 기준)\n")
    parts.append("### 카테고리별 뉴스 수\n")
    parts.append(_md_table(
        ["카테고리", "건수"],
        list(stats["category_counts"].items()) or [["-", 0]]))
    parts.append("")
    parts.append("### 소스별 수집 건수\n")
    parts.append(_md_table(
        ["소스", "건수"],
        list(stats["source_counts"].items()) or [["-", 0]]))
    parts.append("")

    methods = stats.get("method_stats") or []
    if methods:
        parts.append("### 수집 방식별 비교\n")
        parts.append(_md_table(
            ["수집 방식", "소스", "건수", "평균 본문", "본문 확보율"],
            [[m["method"], m["sources"], f"{m['count']}건",
              f"{m['avg_length']}자", f"{m['usable_pct']}%"]
             for m in methods]))
        parts.append("")
        parts.append(METHOD_NOTE)
        parts.append("")

    daily = stats["daily_counts"]
    if daily:
        peak_day, peak_count = max(daily, key=lambda kv: kv[1])
        parts.append(f"### {label}별 추이\n")
        parts.append(f"- 집계된 일자 수: {len(daily)}일")
        parts.append(f"- 최다 수집일: {peak_day} ({peak_count}건)")
        parts.append(f"- 일평균: {round(stats['total'] / len(daily), 1)}건\n")

    # 3. TOP N
    parts.append("## 3. TOP N 집계\n")
    parts.append(f"### AI 추출 키워드 TOP {len(stats['top_keywords'])} "
                 f"(AI 요약 완료 {stats['summarized']}건 기준)\n")
    parts.append(_md_table(
        ["순위", "키워드", "등장 기사 수"],
        [[i, kw, c] for i, (kw, c) in enumerate(stats["top_keywords"], 1)]
        or [["-", "-", 0]]))
    parts.append("")

    # 4. AI 인사이트 (analyzer.py 가 만든 trend_report.json 활용)
    parts.append("## 4. AI 인사이트 분석 "
                 f"(AI 요약 완료 {stats['summarized']}건 기준)\n")

    # 감성 분포도 AI 가 뽑은 값이라 이 절에 함께 둔다.
    # trend_report.json 이 아니라 요약 레코드에서 직접 집계한다.
    sentiment = stats.get("sentiment_counts") or {}
    if sentiment:
        s_total = stats.get("sentiment_total", 0) or 1
        parts.append(f"### 감성 분포 (감성 분석 완료 "
                     f"{stats.get('sentiment_total', 0)}건 기준)\n")
        parts.append(_md_table(
            ["감성", "기사 수", "비중"],
            [[k, v, f"{v / s_total * 100:.1f}%"] for k, v in sentiment.items()]))
        parts.append("")

    if trend:
        overall = trend.get("overall_summary")
        if overall:
            parts.append("### 종합 요약\n")
            parts.append(f"{overall}\n")

        trends = trend.get("trends") or []
        if trends:
            parts.append("### 주요 트렌드\n")
            for i, t in enumerate(trends, 1):
                parts.append(f"**{i}. {t.get('title', '(제목 없음)')}**\n")
                parts.append(f"{t.get('description', '')}\n")

        implications = trend.get("implications") or []
        if implications:
            parts.append("### 시사점\n")
            for imp in implications:
                parts.append(f"- {imp}")
            parts.append("")
    else:
        parts.append("AI 분석 결과가 없습니다. "
                     "`python main.py analyze` 를 먼저 실행하세요.\n")

    # 5. 차트
    if chart_paths:
        parts.append("## 5. 차트\n")
        for path in chart_paths:
            name = os.path.splitext(os.path.basename(path))[0]
            # 리포트 파일 기준 상대 경로로 적어야 Markdown 뷰어에서 이미지가 보인다
            rel = os.path.relpath(path, report_dir)
            parts.append(f"### {name}\n")
            parts.append(f"![{name}]({rel})\n")

    return "\n".join(parts)


def to_plain_text(markdown: str) -> str:
    """Markdown 리포트를 TXT 용 평문으로 바꾼다 (표/헤더 기호 정리)."""
    lines = []
    for line in markdown.splitlines():
        stripped = line.strip()
        # 표 구분선(| --- | --- |)은 평문에서 의미가 없으므로 버린다
        if stripped.startswith("|") and set(stripped) <= set("|- :"):
            continue
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            lines.append("")
            lines.append(title)
            lines.append("-" * (len(title) + 4))
            continue
        if stripped.startswith("!["):
            continue  # 이미지 링크는 평문에서 제외
        line = line.replace("**", "")
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            line = "  " + "\t".join(cells)
        lines.append(line)
    return "\n".join(lines)


def save_report(markdown: str, out_dir: str = "output/reports",
                fmt: str = "md", filename: str = None) -> str:
    """리포트를 파일로 저장하고 경로를 반환한다. fmt = md | txt"""
    os.makedirs(out_dir, exist_ok=True)
    # 초 단위까지 붙여 같은 분에 두 번 실행해도 이전 리포트를 덮어쓰지 않게 한다
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = filename or f"report_{stamp}.{fmt}"
    path = os.path.join(out_dir, name)

    content = markdown if fmt == "md" else to_plain_text(markdown)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    log.info("리포트 저장: %s", path)
    return path


def console_summary(stats: dict, trend: dict) -> str:
    """터미널에 바로 뿌릴 짧은 요약본을 만든다 (전체 리포트는 파일로)."""
    lines = []
    lines.append("=" * 52)
    lines.append(" AI 뉴스 트렌드 리포트 요약")
    lines.append("=" * 52)
    lines.append(f" 기간      : {stats['period'] or '-'}")
    lines.append(f" 뉴스 수   : {stats['total']}건 "
                 f"(요약 완료 {stats['summarized']}건)")
    lines.append("-" * 52)
    lines.append(" [품질 지표]")
    for k, v in stats["quality"].items():
        lines.append(f"  - {k}: {v}")
    lines.append("-" * 52)
    lines.append(f" [키워드 TOP 5] (요약 완료 {stats['summarized']}건 기준)")
    for i, (kw, c) in enumerate(stats["top_keywords"][:5], 1):
        lines.append(f"  {i}. {kw} ({c}건)")
    if not stats["top_keywords"]:
        lines.append("  (AI 요약 데이터 없음)")
    sentiment = stats.get("sentiment_counts") or {}
    if sentiment:
        s_total = stats.get("sentiment_total", 0) or 1
        lines.append("-" * 52)
        lines.append(f" [감성 분포] (감성 분석 완료 "
                     f"{stats.get('sentiment_total', 0)}건 기준)")
        for label, c in sentiment.items():
            lines.append(f"  - {label}: {c}건 ({c / s_total * 100:.1f}%)")
    lines.append("-" * 52)
    lines.append(" [수집 방식별]")
    for m in stats.get("method_stats", []):
        lines.append(f"  - {m['method']}: {m['count']}건 "
                     f"(평균 {m['avg_length']}자, 본문확보 {m['usable_pct']}%)")
    lines.append("-" * 52)
    lines.append(" [카테고리 분포]")
    for cat, c in list(stats["category_counts"].items())[:5]:
        lines.append(f"  - {cat}: {c}건")
    if trend and trend.get("overall_summary"):
        lines.append("-" * 52)
        lines.append(" [AI 종합 요약]")
        lines.append(f"  {trend['overall_summary']}")
    lines.append("=" * 52)
    return "\n".join(lines)


if __name__ == "__main__":
    # 단독 실행: 저장된 데이터로 콘솔 요약만 출력한다.
    _data = load_all()
    print(console_summary(build_stats(_data), _data["trend"]))
