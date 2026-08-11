"""list / show 서브커맨드 (보너스 과제: 데이터 조회 CLI).

역할: 저장된 뉴스를 터미널에서 바로 찾아보고(list), 하나를 골라
본문·요약·키워드까지 자세히 확인한다(show).

main.py 에 붙이는 방법:
    from query_command import add_list_parser, add_show_parser, cmd_list, cmd_show

단독 실행:
    python query_command.py list --category IT --page 2
    python query_command.py show 613de6543210
"""

import os
import json
import argparse
import unicodedata

import reporter
from log_setup import get_logger


def _display_width(text: str) -> int:
    """터미널에서 차지하는 칸 수를 센다.

    한글·한자 같은 전각 문자는 영문 한 글자의 두 칸을 차지하므로
    len() 으로 폭을 재면 표가 어긋난다.
    """
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1
               for ch in text)


def _pad(text: str, width: int) -> str:
    """전각 문자를 고려해 오른쪽 공백을 채운다."""
    text = str(text)
    return text + " " * max(0, width - _display_width(text))


def _cut(text: str, width: int) -> str:
    """표시 폭 기준으로 문자열을 자르고 넘치면 말줄임표를 붙인다."""
    if _display_width(text) <= width:
        return text
    out = ""
    for ch in text:
        if _display_width(out + ch) > width - 1:
            break
        out += ch
    return out + "…"


def load_config(path: str = "config.json") -> dict:
    """config.json 을 읽는다. 없으면 빈 설정으로 동작한다."""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _load(args) -> dict:
    """조회에 필요한 clean 뉴스와 요약을 읽는다."""
    conf = load_config(getattr(args, "config", "config.json"))
    paths = conf.get("paths", {})
    return reporter.load_all({
        "clean": os.path.join(paths.get("clean", "data/clean"),
                              "news_clean.jsonl"),
        "summary": os.path.join(paths.get("analyzed", "data/analyzed"),
                                "news_summary.jsonl"),
        "trend": os.path.join(paths.get("analyzed", "data/analyzed"),
                              "trend_report.json"),
    })


def add_list_parser(subparsers) -> None:
    """argparse 서브파서에 list 커맨드와 옵션을 등록한다."""
    p = subparsers.add_parser("list", help="저장된 뉴스 목록 조회")
    p.add_argument("--category", default=None, help="카테고리 필터 (예: IT)")
    p.add_argument("--date-from", default=None, help="시작일 (YYYY-MM-DD, 포함)")
    p.add_argument("--date-to", default=None, help="종료일 (YYYY-MM-DD, 포함)")
    p.add_argument("--keyword", default=None,
                   help="제목·본문에 포함된 검색어")
    p.add_argument("--status", default="all",
                   choices=["all", "summarized", "unsummarized"],
                   help="요약 상태 필터 (기본: all)")
    p.add_argument("--page", type=int, default=1, help="페이지 번호 (기본: 1)")
    p.add_argument("--size", type=int, default=20,
                   help="한 페이지에 보여줄 건수 (기본: 20)")
    p.add_argument("--config", default="config.json", help="설정 파일 경로")


def cmd_list(args) -> list:
    """list 커맨드 본체. 조건에 맞는 뉴스를 페이지 단위로 출력한다."""
    log = get_logger("query")
    data = _load(args)

    summarized_ids = {s.get("id") for s in data["summaries"] if s.get("id")}
    records = reporter.filter_records(
        data["clean"],
        category=getattr(args, "category", None),
        date_from=getattr(args, "date_from", None),
        date_to=getattr(args, "date_to", None),
    )

    keyword = getattr(args, "keyword", None)
    if keyword:
        kw = keyword.lower()
        records = [r for r in records
                   if kw in (r.get("title") or "").lower()
                   or kw in (r.get("content") or "").lower()]

    status = getattr(args, "status", "all")
    if status != "all":
        want = status == "summarized"
        records = [r for r in records
                   if (r.get("id") in summarized_ids) == want]

    records.sort(key=lambda r: r.get("published_date", ""), reverse=True)

    total = len(records)
    if total == 0:
        log.warning("조건에 맞는 뉴스가 없습니다.")
        return []

    size = max(1, getattr(args, "size", 20))
    last_page = (total + size - 1) // size
    page = min(max(1, getattr(args, "page", 1)), last_page)
    start = (page - 1) * size
    page_items = records[start:start + size]

    print(f"\n총 {total}건 중 {start + 1}~{start + len(page_items)}번째 "
          f"(페이지 {page}/{last_page})")
    print("-" * 100)
    print(_pad("id", 14) + _pad("발행일", 13) + _pad("카테고리", 12)
          + _pad("요약", 7) + "제목")
    print("-" * 100)
    for r in page_items:
        mark = "O" if r.get("id") in summarized_ids else "-"
        print(_pad(r.get("id", ""), 14)
              + _pad(r.get("published_date", ""), 13)
              + _pad(r.get("category", ""), 12)
              + _pad(mark, 7)
              + _cut(r.get("title") or "", 52))
    print("-" * 100)
    if page < last_page:
        print(f"다음 페이지: --page {page + 1}")
    print("상세 보기: python main.py show <id>\n")
    return page_items


def add_show_parser(subparsers) -> None:
    """argparse 서브파서에 show 커맨드와 옵션을 등록한다."""
    p = subparsers.add_parser("show", help="뉴스 한 건 상세 조회")
    p.add_argument("id", help="조회할 뉴스 id (list 커맨드로 확인)")
    p.add_argument("--full", action="store_true",
                   help="본문을 자르지 않고 전부 출력")
    p.add_argument("--config", default="config.json", help="설정 파일 경로")


def cmd_show(args) -> dict:
    """show 커맨드 본체. 기사 원문과 AI 요약을 함께 보여준다."""
    log = get_logger("query")
    data = _load(args)

    record = next((r for r in data["clean"] if r.get("id") == args.id), None)
    if not record:
        log.error("해당 id의 뉴스를 찾지 못했습니다: %s", args.id)
        return {}

    summary = next((s for s in data["summaries"]
                    if s.get("id") == args.id), {})

    print("\n" + "=" * 80)
    print(record.get("title", ""))
    print("=" * 80)
    print(f" id        : {record.get('id', '')}")
    print(f" 발행일    : {record.get('published_date', '')}")
    print(f" 언론사    : {record.get('press', '')}")
    print(f" 카테고리  : {record.get('category', '')}")
    print(f" 소스      : {record.get('source', '')} "
          f"({record.get('collection_method', '')})")
    print(f" 원문 링크 : {record.get('url', '')}")
    print("-" * 80)

    if summary:
        print(" [AI 요약]")
        print(f" {summary.get('summary', '')}")
        keywords = summary.get("keywords") or []
        if keywords:
            print(f" 키워드: {', '.join(keywords)}")
        sentiment = summary.get("sentiment")
        if sentiment:
            print(f" 감성: {sentiment}")
    else:
        print(" [AI 요약] 아직 요약되지 않은 기사입니다.")
    print("-" * 80)

    content = record.get("content", "")
    if not getattr(args, "full", False) and len(content) > 600:
        content = content[:600] + f"\n … (총 {len(content)}자, 전체는 --full)"
    print(" [본문]")
    print(f" {content}")
    print("=" * 80 + "\n")
    return record


if __name__ == "__main__":
    import sys

    parser = argparse.ArgumentParser(description="뉴스 조회 단독 실행")
    sub = parser.add_subparsers(dest="command", required=True)
    add_list_parser(sub)
    add_show_parser(sub)

    parsed = parser.parse_args(sys.argv[1:])
    if parsed.command == "list":
        cmd_list(parsed)
    else:
        cmd_show(parsed)
