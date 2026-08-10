"""export 서브커맨드 (4번 파트).

역할: clean 뉴스 + AI 요약을 합쳐 CSV / JSONL / Excel 파일로 내보낸다.

main.py 에 붙이는 방법:
    from export_command import add_export_parser, cmd_export
    add_export_parser(subparsers)
    ...
    if args.command == "export":
        cmd_export(args)

단독 실행:
    python export_command.py --format csv
    python export_command.py --format excel --status summarized
"""

import os
import json
import argparse

import reporter
import exporter
from log_setup import get_logger


def load_config(path: str = "config.json") -> dict:
    """config.json 을 읽는다. 없으면 빈 설정으로 동작한다."""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def add_export_parser(subparsers) -> None:
    """argparse 서브파서에 export 커맨드와 옵션을 등록한다."""
    p = subparsers.add_parser(
        "export", help="뉴스 데이터를 CSV/JSONL/Excel 파일로 내보내기")
    p.add_argument("--format", default="csv",
                   choices=exporter.SUPPORTED_FORMATS + ["all"],
                   help="내보내기 형식 (기본: csv, all 이면 전부)")
    p.add_argument("--status", default="all",
                   choices=["all", "summarized", "unsummarized"],
                   help="요약 상태 필터 (기본: all)")
    p.add_argument("--category", default=None, help="카테고리 필터 (예: IT)")
    p.add_argument("--date-from", default=None, help="시작일 (YYYY-MM-DD, 포함)")
    p.add_argument("--date-to", default=None, help="종료일 (YYYY-MM-DD, 포함)")
    p.add_argument("--limit", type=int, default=None,
                   help="내보낼 최대 건수 (최신순)")
    p.add_argument("--filename", default=None,
                   help="저장 파일명 (기본: news_export_날짜시각.확장자)")
    p.add_argument("--output", default=None,
                   help="결과 저장 루트 폴더 (기본: output)")
    p.add_argument("--config", default="config.json", help="설정 파일 경로")


def cmd_export(args) -> list:
    """export 커맨드 본체. 생성된 파일 경로 리스트를 반환한다."""
    log = get_logger("report")
    conf = load_config(getattr(args, "config", "config.json"))
    report_conf = conf.get("report", {})

    out_root = (getattr(args, "output", None)
                or report_conf.get("output_directory", "output"))
    export_dir = os.path.join(out_root, "exports")

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
        return []

    rows = exporter.build_rows(data["clean"], data["summaries"])
    rows = exporter.filter_rows(
        rows,
        status=getattr(args, "status", "all"),
        category=getattr(args, "category", None),
        date_from=getattr(args, "date_from", None),
        date_to=getattr(args, "date_to", None),
        limit=getattr(args, "limit", None),
    )

    if not rows:
        log.warning("조건에 맞는 뉴스가 없습니다. 필터를 확인하세요.")
        return []

    # 엑셀에는 통계 시트를 함께 넣기 위해 집계 결과를 미리 구해 둔다.
    # 통계도 '실제로 내보낸 행'만 대상으로 해야 시트끼리 숫자가 어긋나지 않는다.
    exported_ids = {r["id"] for r in rows}
    stats = reporter.build_stats(
        {
            "clean": [r for r in data["clean"] if r.get("id") in exported_ids],
            "summaries": [s for s in data["summaries"]
                          if s.get("id") in exported_ids],
        },
        top_n=report_conf.get("top_n", 10),
    )

    fmt = getattr(args, "format", "csv")
    formats = exporter.SUPPORTED_FORMATS if fmt == "all" else [fmt]

    saved = []
    for f in formats:
        # --filename 은 하나만 받으므로 여러 포맷을 동시에 낼 때는 기본 이름을 쓴다
        filename = getattr(args, "filename", None) if len(formats) == 1 else None
        saved.append(exporter.export(rows, f, export_dir, filename, stats))

    print(f"내보내기 완료: {len(rows)}건")
    for path in saved:
        print(f" - {path}")
    return saved


if __name__ == "__main__":
    # 단독 실행용 진입점 (main.py 없이 내 파트만 테스트)
    import sys

    parser = argparse.ArgumentParser(description="데이터 내보내기 (export) 단독 실행")
    sub = parser.add_subparsers(dest="command")
    add_export_parser(sub)

    argv = sys.argv[1:]
    if not argv or argv[0] != "export":
        argv = ["export"] + argv
    cmd_export(parser.parse_args(argv))
