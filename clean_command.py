"""clean 서브커맨드 (2번 파트).

역할: raw 저장소 뉴스를 정제 규칙에 따라 다듬고,
중복 정책을 적용해 clean 저장소(JSONL)에 저장한다.

main.py 에 붙이는 방법 (리더의 main.py):
    from clean_command import add_clean_parser, cmd_clean
    add_clean_parser(subparsers)          # 서브파서 등록
    ...
    if args.command == "clean":
        cmd_clean(args)

단독 실행 (내 파트만 테스트):
    python clean_command.py --limit 100
    python clean_command.py --policy upsert
"""

import os
import json
import argparse

from cleaner import clean_record, today_kst
from store import read_raw, load_clean, write_clean, apply_dedup
from log_setup import get_logger


def load_config(path: str = "config.json") -> dict:
    """config.json 을 읽는다. 없으면 빈 설정으로 동작한다."""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def add_clean_parser(subparsers) -> None:
    """argparse 서브파서에 clean 커맨드와 옵션을 등록한다."""
    p = subparsers.add_parser("clean", help="raw 뉴스를 정제해 clean 저장소에 저장")
    p.add_argument("--limit", type=int, default=None,
                   help="정제할 최대 건수 (기본: 전체)")
    p.add_argument("--policy", choices=["skip", "upsert"], default=None,
                   help="중복 처리 정책 (기본: config.json 값)")
    p.add_argument("--date", default=None,
                   help="이 발행일(YYYY-MM-DD)의 기사만 정제한다")
    p.add_argument("--today", action="store_true",
                   help="오늘(KST) 발행 기사만 정제한다 (--date 오늘 과 동일)")
    p.add_argument("--config", default="config.json", help="설정 파일 경로")


def cmd_clean(args) -> dict:
    """clean 커맨드 본체. 정제 파이프라인을 실행하고 요약 통계를 반환한다."""
    log = get_logger("clean")
    conf = load_config(getattr(args, "config", "config.json"))

    paths = conf.get("paths", {})
    raw_dir = paths.get("raw", "data/raw")
    clean_dir = paths.get("clean", "data/clean")
    clean_path = os.path.join(clean_dir, "news_clean.jsonl")
    clean_conf = conf.get("clean", {})
    policy = getattr(args, "policy", None) or conf.get("duplicate_policy", "skip")

    log.info("정제 시작: raw=%s, 정책=%s", raw_dir, policy)

    # 1) raw 읽기
    raw_records = read_raw(raw_dir)
    if getattr(args, "limit", None):
        raw_records = raw_records[: args.limit]
    log.info("raw 로드: %d건", len(raw_records))

    # 2) 레코드별 정제 + 필수 필드 검증
    cleaned, dropped = [], 0
    for raw in raw_records:
        rec, reason = clean_record(raw, clean_conf)
        if rec is None:
            dropped += 1
            log.warning("검증 실패로 제외: %s | 제목=%r", reason, raw.get("title", "")[:30])
        else:
            cleaned.append(rec)
    log.info("정제 통과: %d건, 제외: %d건", len(cleaned), dropped)

    # 2-1) 기준일 필터
    #
    # raw 폴더에는 지금까지 모은 기사가 그대로 쌓여 있다. 매일 돌리는
    # 당일 리포트에서는 오늘 발행분만 손대면 되므로, 여기서 좁혀 둔다.
    # (clean 저장소 자체는 계속 누적되는 보관용이라 과거 기사는 남는다.)
    only_date = args.date or (today_kst() if getattr(args, "today", False) else None)
    if only_date:
        before = len(cleaned)
        cleaned = [r for r in cleaned if r.get("published_date") == only_date]
        log.info("기준일 %s 필터: %d건 -> %d건", only_date, before, len(cleaned))

    # 3) 중복 정책 적용 후 저장
    existing = load_clean(clean_path)
    dedup_by_title = clean_conf.get("dedup_by_title", True)
    merged, stats = apply_dedup(existing, cleaned, policy, dedup_by_title)
    write_clean(clean_path, merged)

    log.info(
        "저장 완료: 신규 %d, 갱신 %d, 스킵 %d, 배치중복 %d, 제목중복 %d -> 총 %d건 (%s)",
        stats["added"], stats["updated"], stats["skipped"],
        stats["batch_dup"], stats["title_dup"], len(merged), clean_path,
    )
    return {"dropped": dropped, "total": len(merged),
            "date": only_date, **stats}


if __name__ == "__main__":
    # 단독 실행용 진입점 (리더 main.py 없이 내 파트만 테스트)
    parser = argparse.ArgumentParser(description="뉴스 정제 (clean) 단독 실행")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--policy", choices=["skip", "upsert"], default=None)
    parser.add_argument("--date", default=None)
    parser.add_argument("--today", action="store_true")
    parser.add_argument("--config", default="config.json")
    cmd_clean(parser.parse_args())
