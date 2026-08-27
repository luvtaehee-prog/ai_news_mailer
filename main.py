"""CLI 진입점.

서브커맨드 하나가 파이프라인 한 단계에 대응한다.

    fetch     뉴스 수집          (1번 파트: collector.py)
    clean     데이터 정제        (2번 파트: clean_command.py)
    summarize AI 요약            (3번 파트: analyzer.py)
    analyze   AI 트렌드 분석     (3번 파트: analyzer.py)
    report    시각화·리포트 생성 (4번 파트: report_command.py)
    export    CSV/JSONL/Excel    (4번 파트: export_command.py)
    list/show 저장된 뉴스 조회    (보너스: query_command.py)
    mail      최신 리포트 이메일 발송 (mail_command.py)

각 파트는 자기 모듈에 add_*_parser(서브파서 등록)와 cmd_*(실행 본체)를 두고,
main.py 는 그것들을 모아 연결하기만 한다. 그래야 파트별로 따로 작업해도
main.py 에서 충돌이 나지 않는다.

전체 흐름:
    fetch -> clean -> summarize -> analyze -> report / export -> mail
"""

import argparse

from cleaner import today_kst
from clean_command import add_clean_parser, cmd_clean
from analyze_command import (add_analyze_parser, add_summarize_parser,
                             cmd_analyze, cmd_summarize)
from report_command import add_report_parser, cmd_report
from export_command import add_export_parser, cmd_export
from query_command import (add_list_parser, add_show_parser,
                           cmd_list, cmd_show)
from mail_command import add_mail_parser, cmd_mail


def add_fetch_parser(subparsers) -> None:
    """fetch 커맨드와 옵션을 등록한다."""
    p = subparsers.add_parser("fetch", help="뉴스 수집")
    p.add_argument("--source", default="google",
                   choices=["google", "naver", "govuk"],
                   help="뉴스 소스 (기본: google)")
    p.add_argument("--limit", type=int, default=20,
                   help="수집할 뉴스 개수 (기본: 20)")
    # 이 프로젝트는 '매일 당일 뉴스'를 보내는 것이 목적이라 날짜 필터가 기본이다.
    # 과거 기사까지 모으고 싶을 때만 --all-dates 로 끈다.
    p.add_argument("--date", default=None,
                   help="수집할 발행일 (YYYY-MM-DD, 기본: 오늘 KST)")
    p.add_argument("--all-dates", action="store_true",
                   help="발행일 필터를 끄고 피드에 있는 기사를 모두 수집")
    p.add_argument("--keyword", action="append", default=None, metavar="말",
                   help="검색어 (여러 번 쓸 수 있음). 생략하면 "
                        "config.json 의 keywords 를 쓴다")


def cmd_fetch(args):
    """fetch 커맨드 본체.

    collector 는 함수 안에서 import 한다. 모듈 상단에서 불러오면
    수집용 패키지가 없는 환경에서 report/export 같은 다른 커맨드까지
    함께 실행되지 않기 때문이다.
    """
    from collector import fetch_news

    only_date = None if args.all_dates else (args.date or today_kst())

    return fetch_news(source=args.source, limit=args.limit,
                      only_date=only_date, keywords=args.keyword)


def build_parser() -> argparse.ArgumentParser:
    """서브커맨드가 모두 등록된 argparse 파서를 만든다."""
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="AI 뉴스 트렌드 분석 파이프라인",
        epilog="예) python main.py fetch --source google --limit 30",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_fetch_parser(subparsers)      # 1번 파트
    add_clean_parser(subparsers)      # 2번 파트
    add_summarize_parser(subparsers)  # 3번 파트
    add_analyze_parser(subparsers)    # 3번 파트
    add_report_parser(subparsers)     # 4번 파트
    add_export_parser(subparsers)     # 4번 파트
    add_list_parser(subparsers)       # 보너스: 조회 CLI
    add_show_parser(subparsers)       # 보너스: 조회 CLI
    add_mail_parser(subparsers)       # 최신 리포트 이메일 발송
    return parser


# 커맨드 이름과 실행 함수 연결표
COMMANDS = {
    "fetch": cmd_fetch,
    "clean": cmd_clean,
    "summarize": cmd_summarize,
    "analyze": cmd_analyze,
    "report": cmd_report,
    "export": cmd_export,
    "list": cmd_list,
    "show": cmd_show,
    "mail": cmd_mail,
}


def main():
    args = build_parser().parse_args()
    result = COMMANDS[args.command](args)

    # 실패를 조용히 넘기지 않는다. 종료 코드가 0 이면 GitHub Actions 가
    # 성공으로 표시해서, 메일이 안 온 것을 한참 뒤에야 알게 된다.
    if isinstance(result, dict) and result.get("sent") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()