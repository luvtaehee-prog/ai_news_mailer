"""blog 서브커맨드.

역할: output/reports/ 아래 가장 최근 리포트를 읽어 네이버 블로그에 발행한다.
mail 커맨드와 짝을 이루는, 같은 리포트를 블로그로 내보내는 출구다.
report 커맨드 실행 후에 이어서 쓰는 것을 전제로 한다.

단독 실행:
    python main.py blog                 # 최신 리포트를 블로그에 발행
    python main.py blog --login         # (최초 1회) 창 띄워 직접 로그인 → 세션 저장
    python main.py blog --headless      # 창 없이 발행(세션이 이미 있을 때만 권장)
"""

import os
import re
import glob
import json
import argparse

import naverblog
from cleaner import today_kst
from log_setup import get_logger


def load_config(path: str = "config.json") -> dict:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def find_latest_report_dir(out_root: str = "output") -> str:
    """output/reports/report_YYYYMMDD_HHMMSS/ 중 가장 최근 폴더를 찾는다."""
    pattern = os.path.join(out_root, "reports", "report_*")
    candidates = sorted(glob.glob(pattern))
    return candidates[-1] if candidates else None


def _strip_markdown_links(text: str) -> str:
    """남아 있는 마크다운 링크 `[제목](url)` 을 `제목 (url)` 로 편다.

    report.txt 는 대부분 평문이지만, 제목에 대괄호가 든 기사 몇 건은
    `[[제목]](url)` 형태로 남는다. 블로그 본문에서는 깔끔하게 편다.
    스마트에디터가 본문의 벌거벗은 URL 을 자동으로 링크로 걸어 준다.
    """
    return re.sub(r"\[(.+?)\]\((https?://[^)]+)\)", r"\1 (\2)", text)


def add_blog_parser(subparsers) -> None:
    """argparse 서브파서에 blog 커맨드와 옵션을 등록한다."""
    p = subparsers.add_parser("blog", help="최신 리포트를 네이버 블로그에 발행")
    p.add_argument("--login", action="store_true",
                   help="(최초 1회) 창을 띄워 직접 로그인하고 세션을 저장한다")
    p.add_argument("--blog-id", default=None,
                   help="네이버 블로그 아이디 (기본: config blog.blog_id / .env NAVER_BLOG_ID)")
    p.add_argument("--report-dir", default=None,
                   help="발행할 리포트 폴더 (기본: 가장 최근 폴더 자동 탐색)")
    p.add_argument("--require-today", action="store_true",
                   help="오늘(KST) 만든 리포트가 아니면 발행하지 않는다")
    p.add_argument("--headless", action="store_true",
                   help="창을 띄우지 않고 실행 (세션이 이미 저장돼 있을 때만 권장)")
    p.add_argument("--output", default=None, help="리포트 루트 폴더 (기본: output)")
    p.add_argument("--config", default="config.json", help="설정 파일 경로")


def cmd_blog(args) -> dict:
    """blog 커맨드 본체."""
    log = get_logger("blog")
    conf = load_config(getattr(args, "config", "config.json"))
    blog_conf = conf.get("blog", {})

    blog_id = (getattr(args, "blog_id", None)
               or blog_conf.get("blog_id")
               or os.getenv("NAVER_BLOG_ID"))
    profile_dir = blog_conf.get("profile_dir") or naverblog.DEFAULT_PROFILE_DIR

    # --login: 최초 1회 수동 로그인만 하고 끝낸다.
    if getattr(args, "login", False):
        naverblog.login(blog_id=blog_id, user_data_dir=profile_dir)
        return {"posted": None, "login": True}

    out_root = getattr(args, "output", None) or "output"
    today = today_kst()

    report_dir = getattr(args, "report_dir", None) or find_latest_report_dir(out_root)
    if not report_dir or not os.path.isdir(report_dir):
        log.error("발행할 리포트를 찾지 못했습니다. 먼저 `python main.py report` 를 실행하세요.")
        return {"posted": False}

    # 오늘 만든 리포트가 맞는지 확인 (mail 과 동일한 안전장치).
    if getattr(args, "require_today", False):
        stamp = os.path.basename(report_dir).replace("report_", "")[:8]
        if stamp != today.replace("-", ""):
            log.error("가장 최근 리포트(%s)가 오늘(%s) 것이 아닙니다. "
                      "report 단계가 실패했는지 확인하세요.", report_dir, today)
            return {"posted": False}

    # 블로그 본문은 평문 판본(report.txt)을 쓴다. 없으면 report.md.
    body_path = os.path.join(report_dir, "report.txt")
    if not os.path.exists(body_path):
        body_path = os.path.join(report_dir, "report.md")
    if not os.path.exists(body_path):
        log.error("%s 안에 report.md/report.txt 가 없습니다.", report_dir)
        return {"posted": False}

    with open(body_path, encoding="utf-8") as f:
        body_text = _strip_markdown_links(f.read())

    # 제목: 접두어 + 발행일 + 건수. (mail 커맨드와 같은 규칙으로 날짜/건수를 뽑는다)
    period = re.search(r"대상 기간\(발행일 기준\): (\d{4}-\d{2}-\d{2})"
                       r"(?: ~ (\d{4}-\d{2}-\d{2}))?", body_text)
    if period:
        start, end = period.group(1), period.group(2)
        date_label = start if not end or end == start else f"{start} ~ {end}"
    else:
        date_label = today
    match = re.search(r"뉴스 목록 \((\d+)건\)", body_text)
    count_label = f" ({match.group(1)}건)" if match else ""
    prefix = blog_conf.get("title_prefix", "AI 뉴스 리포트")
    title = f"{prefix} | {date_label}{count_label}"

    headless = getattr(args, "headless", False) or bool(blog_conf.get("headless"))

    result = naverblog.post(title, body_text, blog_id=blog_id,
                            headless=headless, user_data_dir=profile_dir)

    if result.get("posted"):
        log.info("블로그 발행 완료: %s -> blog.naver.com/%s",
                 report_dir, result.get("blog_id"))
    else:
        log.error("블로그 발행 실패: %s%s", result.get("error"),
                  f" (스크린샷: {result['screenshot']})" if result.get("screenshot") else "")
    return result


if __name__ == "__main__":
    import sys

    parser = argparse.ArgumentParser(description="리포트 네이버 블로그 발행 (blog) 단독 실행")
    sub = parser.add_subparsers(dest="command")
    add_blog_parser(sub)

    argv = sys.argv[1:]
    if not argv or argv[0] != "blog":
        argv = ["blog"] + argv
    cmd_blog(parser.parse_args(argv))
