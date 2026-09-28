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


def _esc(text: str) -> str:
    """HTML 텍스트 이스케이프."""
    import html
    return html.escape(text, quote=True)


def _markdown_to_html(md_text: str) -> str:
    """리포트 마크다운(report.md)을 블로그 본문용 HTML 로 직접 변환한다.

    마크다운 라이브러리는 `1. [제목](url)` + 들여쓴 `- 출처` 를 중첩 목록으로
    제대로 못 묶어, 제목과 출처가 각각 번호 항목으로 쪼개지고 "- "가 노출된다.
    그래서 리포트의 알려진 형식을 직접 파싱해 기사 한 건을 문단 하나로 만든다:
        <p><a href=url>제목</a><br><span>출처 · 분류 · 시각</span></p>
    평문 기호(#, -, >, 1.)를 출력에 남기지 않아 스마트에디터의 마크다운
    재해석도 피한다.
    """
    lines = md_text.splitlines()
    out = []
    i = 0
    n = len(lines)
    item_re = re.compile(r"^\s*\d+\.\s+\[(.+?)\]\((https?://[^)]+)\)\s*$")
    meta_re = re.compile(r"^\s*-\s*(.+?)\s*$")
    table_buf = []

    def flush_table():
        # 표는 각 행의 셀을 ' · ' 로 이어 문단으로 (구분선 행은 버린다)
        for row in table_buf:
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            text = " · ".join(c for c in cells if c)
            if text:
                out.append(f'<p style="color:#555;">{_esc(text)}</p>')
        table_buf.clear()

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("|"):
            table_buf.append(line)
            i += 1
            continue
        elif table_buf:
            flush_table()

        if not stripped:
            i += 1
            continue

        m = item_re.match(line)
        if m:
            title, url = m.group(1), m.group(2)
            meta = ""
            if i + 1 < n:
                mm = meta_re.match(lines[i + 1])
                if mm:
                    meta = mm.group(1)
                    i += 1
            meta_html = (f'<br><span style="color:#888;font-size:13px;">'
                         f'{_esc(meta)}</span>') if meta else ""
            out.append(f'<p><a href="{_esc(url)}" target="_blank">'
                       f'{_esc(title)}</a>{meta_html}</p>')
        elif stripped.startswith("## "):
            out.append(f'<h3>{_esc(stripped[3:].strip())}</h3>')
        elif stripped.startswith("# "):
            # 최상단 문서 제목은 글 제목과 겹치므로 생략
            pass
        elif stripped.startswith(">"):
            out.append(f'<p style="color:#888;">{_esc(stripped.lstrip("> ").strip())}</p>')
        elif stripped.startswith("- "):
            out.append(f'<p style="color:#555;">{_esc(stripped[2:].strip())}</p>')
        else:
            out.append(f'<p>{_esc(stripped)}</p>')
        i += 1

    if table_buf:
        flush_table()
    return "\n".join(out)


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

    # 블로그 본문은 마크다운 판본(report.md)을 HTML 로 변환해 쓴다.
    # (report.txt 평문을 붙여넣으면 서식이 깨져서 md 를 우선한다)
    body_path = os.path.join(report_dir, "report.md")
    if not os.path.exists(body_path):
        body_path = os.path.join(report_dir, "report.txt")
    if not os.path.exists(body_path):
        log.error("%s 안에 report.md/report.txt 가 없습니다.", report_dir)
        return {"posted": False}

    with open(body_path, encoding="utf-8") as f:
        md_text = f.read()
    body_html = _markdown_to_html(md_text)

    # 제목: 접두어 + 발행일 + 건수. (mail 커맨드와 같은 규칙으로 날짜/건수를 뽑는다)
    period = re.search(r"대상 기간\(발행일 기준\): (\d{4}-\d{2}-\d{2})"
                       r"(?: ~ (\d{4}-\d{2}-\d{2}))?", md_text)
    if period:
        start, end = period.group(1), period.group(2)
        date_label = start if not end or end == start else f"{start} ~ {end}"
    else:
        date_label = today
    match = re.search(r"뉴스 목록 \((\d+)건\)", md_text)
    count_label = f" ({match.group(1)}건)" if match else ""
    prefix = blog_conf.get("title_prefix", "AI 뉴스 리포트")
    title = f"{prefix} | {date_label}{count_label}"

    headless = getattr(args, "headless", False) or bool(blog_conf.get("headless"))

    result = naverblog.post(title, body_html, blog_id=blog_id,
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
