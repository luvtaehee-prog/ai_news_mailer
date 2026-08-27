"""report 서브커맨드 (4번 파트).

역할: 저장된 데이터를 집계해 차트(PNG)를 그리고,
품질 지표·TOP N·AI 인사이트가 담긴 리포트를 콘솔과 파일로 낸다.

main.py 에 붙이는 방법:
    from report_command import add_report_parser, cmd_report
    add_report_parser(subparsers)
    ...
    if args.command == "report":
        cmd_report(args)

단독 실행 (내 파트만 테스트):
    python report_command.py
    python report_command.py --format both --top 15
    python report_command.py --category IT --date-from 2026-08-01
"""

import os
import json
import argparse
from datetime import datetime

import reporter
import visualizer
from cleaner import today_kst
from log_setup import get_logger


def load_config(path: str = "config.json") -> dict:
    """config.json 을 읽는다. 없으면 빈 설정으로 동작한다."""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def add_report_parser(subparsers) -> None:
    """argparse 서브파서에 report 커맨드와 옵션을 등록한다."""
    p = subparsers.add_parser(
        "report", help="집계·차트·AI 인사이트를 묶은 리포트 생성")
    p.add_argument("--category", default=None,
                   help="특정 카테고리만 집계 (예: IT)")
    p.add_argument("--date-from", default=None,
                   help="시작일 (YYYY-MM-DD, 포함)")
    p.add_argument("--date-to", default=None,
                   help="종료일 (YYYY-MM-DD, 포함)")
    p.add_argument("--today", action="store_true",
                   help="오늘(KST) 발행 기사만 집계 (--date-from/--date-to 오늘)")
    p.add_argument("--articles", type=int, default=None,
                   help="리포트에 싣는 기사 목록 개수 (0 이면 전부, "
                        "기본: config.json report.article_limit 또는 30)")
    p.add_argument("--top", type=int, default=None,
                   help="TOP N 집계 개수 (기본: config.json 값 또는 10)")
    p.add_argument("--format", choices=["md", "txt", "both"], default="md",
                   help="리포트 저장 형식 (기본: md)")
    p.add_argument("--date-field", choices=["published", "collected"],
                   default=None,
                   help="추이 차트 기준 날짜 (기본: config.json 값 또는 published)")
    p.add_argument("--no-charts", action="store_true",
                   help="차트 생성을 건너뛴다")
    p.add_argument("--quiet", action="store_true",
                   help="콘솔 요약 출력을 생략한다")
    p.add_argument("--output", default=None,
                   help="결과 저장 루트 폴더 (기본: output)")
    p.add_argument("--config", default="config.json", help="설정 파일 경로")


def cmd_report(args) -> dict:
    """report 커맨드 본체. 생성된 파일 경로들을 반환한다."""
    log = get_logger("report")
    conf = load_config(getattr(args, "config", "config.json"))
    report_conf = conf.get("report", {})

    out_root = (getattr(args, "output", None)
                or report_conf.get("output_directory", "output"))

    # 실행 한 번을 폴더 하나로 묶는다.
    #
    #   output/reports/report_20260811_162309/
    #   ├── report.md
    #   ├── report.txt
    #   └── charts/*.png
    #
    # 차트를 output/charts 에 고정 이름으로 두면 실행할 때마다 덮어써져,
    # 과거 리포트가 최신 차트를 가리키게 된다(본문은 203건인데 차트는 239건).
    # 리포트가 자기 차트를 갖고 다니게 해서 시점별로 일관되게 남긴다.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = os.path.join(out_root, "reports", f"report_{stamp}")
    chart_dir = os.path.join(report_dir, "charts")

    top_n = getattr(args, "top", None) or report_conf.get("top_n", 10)

    # 기간 조건. --today 는 '오늘 하루'를 뜻하는 지름길이다.
    date_from = getattr(args, "date_from", None)
    date_to = getattr(args, "date_to", None)
    if getattr(args, "today", False):
        date_from = date_to = today_kst()

    article_limit = getattr(args, "articles", None)
    if article_limit is None:
        article_limit = report_conf.get("article_limit", 30)
    date_field = (getattr(args, "date_field", None)
                  or report_conf.get("date_field", "published"))

    # 1) 데이터 로드 (clean / 요약 / 트렌드 분석 결과)
    paths = conf.get("paths", {})
    data = reporter.load_all({
        "clean": os.path.join(paths.get("clean", "data/clean"),
                              "news_clean.jsonl"),
        "summary": os.path.join(paths.get("analyzed", "data/analyzed"),
                                "news_summary.jsonl"),
        "trend": os.path.join(paths.get("analyzed", "data/analyzed"),
                              "trend_report.json"),
    })

    if not data["clean"]:
        log.error("clean 데이터가 비어 있습니다. "
                  "먼저 `python main.py clean` 을 실행하세요.")
        return {"charts": [], "reports": []}

    # AI 인사이트(trend_report.json)는 analyze 를 마지막으로 돌린 시점의
    # 기간 기준이다. 오늘치 리포트에 지난주 분석을 그대로 붙이면 사실과
    # 어긋나므로, 기간이 겹치지 않으면 싣지 않는다.
    if (date_from or date_to) and data["trend"]:
        trend_period = data["trend"].get("period") or {}
        trend_from = trend_period.get("from", "")
        trend_to = trend_period.get("to", "")
        overlaps = bool(trend_from and trend_to) and not (
            (date_from and trend_to < date_from)
            or (date_to and trend_from > date_to)
        )
        if not overlaps:
            log.warning(
                "AI 인사이트(기간 %s)가 이번 리포트 기간(%s ~ %s)과 달라 제외합니다.",
                f"{trend_from} ~ {trend_to}" if trend_from else "기록 없음",
                date_from or "-", date_to or "-")
            data["trend"] = None

    # 2) 조건 필터 적용 (카테고리 / 기간)
    before = len(data["clean"])
    data["clean"] = reporter.filter_records(
        data["clean"],
        category=getattr(args, "category", None),
        date_from=date_from,
        date_to=date_to,
    )
    if len(data["clean"]) != before:
        log.info("필터 적용: %d건 -> %d건", before, len(data["clean"]))

    if not data["clean"]:
        # 리포트를 아예 안 만들면 메일 단계가 어제 폴더를 집어 들고
        # 같은 내용을 또 보낸다. 빈 날에도 빈 리포트를 남긴다.
        log.warning("조건에 맞는 뉴스가 없습니다 (기간 %s ~ %s).",
                    date_from or "-", date_to or "-")
        markdown = reporter.build_empty_report(date_from, date_to)
        fmt = getattr(args, "format", "md")
        formats = ["md", "txt"] if fmt == "both" else [fmt]
        report_paths = [reporter.save_report(markdown, report_dir, f,
                                             filename=f"report.{f}")
                        for f in formats]
        return {"charts": [], "reports": report_paths, "stats": None,
                "empty": True}

    # 요약도 필터 결과에 맞춰 좁혀야 키워드 TOP N 이 어긋나지 않는다
    target_ids = {r.get("id") for r in data["clean"]}
    data["summaries"] = [s for s in data["summaries"]
                         if s.get("id") in target_ids]

    # 3) 집계
    stats = reporter.build_stats(data, top_n=top_n, date_field=date_field)

    # 4) 차트
    chart_paths = []
    if not getattr(args, "no_charts", False):
        chart_paths = visualizer.render_all(stats, out_dir=chart_dir)

    # 5) 리포트 문서 생성 및 저장
    # 필터를 걸면 집계는 좁아지지만 AI 인사이트(trend_report.json)는 그대로라
    # 두 기준이 어긋난다. 리포트에 그 사실을 밝히도록 알려 준다.
    filtered = bool(getattr(args, "category", None) or date_from or date_to)
    markdown = reporter.build_report(stats, data["trend"], chart_paths,
                                     report_dir=report_dir, filtered=filtered,
                                     article_limit=article_limit)
    fmt = getattr(args, "format", "md")
    formats = ["md", "txt"] if fmt == "both" else [fmt]
    # 폴더 이름이 이미 시각을 담고 있으므로 파일명은 report.md / report.txt 로 고정한다
    report_paths = [reporter.save_report(markdown, report_dir, f,
                                         filename=f"report.{f}")
                    for f in formats]

    # 6) 콘솔 출력
    if not getattr(args, "quiet", False):
        print(reporter.console_summary(stats, data["trend"]))
        for path in report_paths:
            print(f" 리포트 파일 : {path}")
        for path in chart_paths:
            print(f" 차트 파일   : {path}")

    return {"charts": chart_paths, "reports": report_paths, "stats": stats}


if __name__ == "__main__":
    # 단독 실행용 진입점 (main.py 없이 내 파트만 테스트)
    # 옵션 정의를 한 곳에서만 관리하려고 add_report_parser 를 그대로 재사용한다.
    import sys

    parser = argparse.ArgumentParser(description="리포트 생성 (report) 단독 실행")
    sub = parser.add_subparsers(dest="command")
    add_report_parser(sub)

    argv = sys.argv[1:]
    if not argv or argv[0] != "report":
        argv = ["report"] + argv  # 단독 실행 시 커맨드 이름 생략 허용
    cmd_report(parser.parse_args(argv))
