"""summarize / analyze 서브커맨드 어댑터.

AI 요약·트렌드 분석 로직 자체는 3번 파트의 analyzer.py 에 있다.
이 파일은 그 함수들을 CLI 에 연결하기만 하는 얇은 어댑터다.
(analyzer.py 를 수정하지 않으려고 따로 뒀다. 3번 담당자가 직접 CLI 를 만들면
 이 파일은 지우고 그쪽 것으로 교체하면 된다.)

analyzer 모듈은 함수 안에서 import 한다.
모듈 상단에서 import 하면 openai 패키지나 API 키가 없는 환경에서
`python main.py report` 같은 무관한 커맨드까지 함께 죽기 때문이다.
"""

import argparse

from log_setup import get_logger


def _load_analyzer(log):
    """analyzer 모듈을 불러온다. 준비가 안 됐으면 안내 문구를 남기고 None 을 반환한다.

    openai 패키지가 없으면 파이썬 기본 오류 메시지(ModuleNotFoundError)가
    그대로 튀어나와 원인을 알기 어렵다. 무엇을 설치해야 하는지 짚어 준다.
    """
    try:
        import analyzer
        return analyzer
    except ImportError as e:
        log.error("AI 관련 패키지를 불러오지 못했습니다: %s", e)
        log.error("설치 후 다시 시도하세요: pip install -r requirements.txt")
        log.error("(요약·분석 기능에만 필요합니다. "
                  "report / export / list 는 이것 없이도 동작합니다.)")
        return None


def add_summarize_parser(subparsers) -> None:
    """argparse 서브파서에 summarize 커맨드와 옵션을 등록한다."""
    p = subparsers.add_parser("summarize", help="AI로 뉴스 본문 요약")
    target = p.add_mutually_exclusive_group()
    target.add_argument("--all", action="store_true",
                        help="전체 뉴스를 대상으로 (이미 요약된 건은 스킵)")
    target.add_argument("--unsummarized", action="store_true",
                        help="아직 요약되지 않은 뉴스만 (기본값)")
    target.add_argument("--id", default=None, help="특정 뉴스 id 하나만 요약")
    p.add_argument("--limit", type=int, default=None,
                   help="요약할 최대 건수")
    p.add_argument("--batch-size", type=int, default=5,
                   help="한 번의 API 호출에 묶을 기사 수 (기본: 5)")
    p.add_argument("--sentiment-only", action="store_true",
                   help="요약은 건너뛰고 감성(긍정/부정/중립)만 채운다")
    p.add_argument("--delay", type=int, default=0,
                   help="배치 사이 대기 시간(초). 기본 0 — 호출 한도 초과는 "
                        "SDK 가 알아서 재시도하므로 보통 필요 없다")


def cmd_summarize(args):
    """summarize 커맨드 본체."""
    log = get_logger("analyze")
    analyzer = _load_analyzer(log)  # 지연 import (위 모듈 설명 참고)
    if analyzer is None:
        return

    # 감성만 채우는 모드: 이미 요약된 레코드만 손대면 되므로 clean 로드가 필요 없다
    if getattr(args, "sentiment_only", False):
        analyzer.backfill_sentiment()
        return

    records = analyzer.load_clean_news()
    log.info("clean 데이터 %d건 로드", len(records))

    target_id = getattr(args, "id", None)
    if target_id:
        records = [r for r in records if r.get("id") == target_id]
        if not records:
            log.error("해당 id의 뉴스를 찾지 못했습니다: %s", target_id)
            return

    if getattr(args, "limit", None):
        # 이미 요약된 건을 먼저 걸러낸 뒤에 limit 을 적용한다.
        # 순서를 바꾸면 앞쪽 기요약분만 잘려나가 신규 건이 하나도 안 잡힌다.
        done = analyzer.load_done_ids("data/analyzed/news_summary.jsonl")
        records = [r for r in records if r.get("id") not in done][: args.limit]

    # --all / --unsummarized 모두 analyzer 가 기존 요약분을 건너뛴다.
    # (요구사항: 이미 요약된 뉴스는 기본 스킵)
    analyzer.summarize_all(
        records,
        batch_size=getattr(args, "batch_size", 5),
        delay=getattr(args, "delay", 0),
    )

    # 감성 값이 빠진 레코드를 이어서 채운다.
    # (요약보다 감성 분석을 나중에 추가했기 때문에 기존 레코드에는 값이 없다)
    #
    # --id 나 --limit 으로 범위를 좁혀 실행했다면 감성도 그 범위만 채운다.
    # 안 그러면 1건만 요약하려고 실행했는데 감성은 전체를 훑어 과금된다.
    scoped = target_id or getattr(args, "limit", None)
    analyzer.backfill_sentiment(
        only_ids={r.get("id") for r in records} if scoped else None)


def add_analyze_parser(subparsers) -> None:
    """argparse 서브파서에 analyze 커맨드와 옵션을 등록한다."""
    p = subparsers.add_parser("analyze", help="AI 트렌드·키워드·시사점 분석")
    p.add_argument("--category", default=None, help="특정 카테고리만 분석")
    p.add_argument("--date-from", default=None, help="시작일 (YYYY-MM-DD, 포함)")
    p.add_argument("--date-to", default=None, help="종료일 (YYYY-MM-DD, 포함)")


def cmd_analyze(args):
    """analyze 커맨드 본체."""
    log = get_logger("analyze")
    analyzer = _load_analyzer(log)  # 지연 import (위 모듈 설명 참고)
    if analyzer is None:
        return

    summaries = analyzer.load_summaries()

    # 기간/카테고리 조건은 요약 결과를 걸러서 적용한다
    category = getattr(args, "category", None)
    date_from = getattr(args, "date_from", None)
    date_to = getattr(args, "date_to", None)
    if category or date_from or date_to:
        before = len(summaries)
        summaries = [
            s for s in summaries
            if (not category or s.get("category") == category)
            and (not date_from or s.get("published_date", "") >= date_from)
            and (not date_to or s.get("published_date", "") <= date_to)
        ]
        log.info("분석 대상 필터: %d건 -> %d건", before, len(summaries))

    if not summaries:
        log.error("분석할 요약 데이터가 없습니다. 먼저 summarize 를 실행하세요.")
        return

    analyzer.analyze_trends(summaries)


if __name__ == "__main__":
    import sys

    parser = argparse.ArgumentParser(description="AI 요약/분석 단독 실행")
    sub = parser.add_subparsers(dest="command", required=True)
    add_summarize_parser(sub)
    add_analyze_parser(sub)

    parsed = parser.parse_args(sys.argv[1:])
    if parsed.command == "summarize":
        cmd_summarize(parsed)
    else:
        cmd_analyze(parsed)
