"""mail 서브커맨드.

역할: output/reports/ 아래 가장 최근 리포트(report.md 또는 report.txt)를
읽어 이메일로 발송한다. report 커맨드 실행 후에 이어서 쓰는 것을 전제로 한다.

main.py 에 붙이는 방법:
    from mail_command import add_mail_parser, cmd_mail
    add_mail_parser(subparsers)
    ...
    COMMANDS["mail"] = cmd_mail

단독 실행 (내 파트만 테스트):
    python mail_command.py
    python mail_command.py --to someone@example.com --attach-charts
"""

import os
import re
import glob
import json
import argparse

import mailer
from cleaner import today_kst
from log_setup import get_logger


def load_config(path: str = "config.json") -> dict:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def find_latest_report_dir(out_root: str = "output") -> str:
    """output/reports/report_YYYYMMDD_HHMMSS/ 중 가장 최근 폴더를 찾는다.

    폴더 이름에 시각이 들어 있으므로 이름순 정렬이 곧 시각순 정렬이다.
    """
    pattern = os.path.join(out_root, "reports", "report_*")
    candidates = sorted(glob.glob(pattern))
    return candidates[-1] if candidates else None


def add_mail_parser(subparsers) -> None:
    """argparse 서브파서에 mail 커맨드와 옵션을 등록한다."""
    p = subparsers.add_parser("mail", help="최신 리포트를 이메일로 발송")
    p.add_argument("--to", default=None,
                   help="수신자 이메일 (기본: config.json email.to, "
                        "없으면 발신 계정 본인)")
    p.add_argument("--report-dir", default=None,
                   help="발송할 리포트 폴더 (기본: 가장 최근 폴더 자동 탐색)")
    p.add_argument("--attach-charts", action="store_true",
                   help="charts/ 폴더의 PNG 를 첨부파일로 함께 보낸다")
    p.add_argument("--require-today", action="store_true",
                   help="오늘(KST) 만든 리포트가 아니면 보내지 않는다")
    p.add_argument("--output", default=None,
                   help="리포트 루트 폴더 (기본: output)")
    p.add_argument("--config", default="config.json", help="설정 파일 경로")


def cmd_mail(args) -> dict:
    """mail 커맨드 본체."""
    log = get_logger("mail")
    conf = load_config(getattr(args, "config", "config.json"))
    out_root = getattr(args, "output", None) or "output"

    today = today_kst()

    report_dir = getattr(args, "report_dir", None) or find_latest_report_dir(out_root)
    if not report_dir or not os.path.isdir(report_dir):
        log.error("보낼 리포트를 찾지 못했습니다. 먼저 `python main.py report` 를 실행하세요.")
        return {"sent": False}

    # 오늘 만든 리포트가 맞는지 확인한다.
    # report 단계가 실패하면 '가장 최근 폴더'가 어제 것이라, 확인 없이 보내면
    # 어제 뉴스를 오늘 제목으로 다시 보내게 된다.
    if getattr(args, "require_today", False):
        stamp = os.path.basename(report_dir).replace("report_", "")[:8]
        if stamp != today.replace("-", ""):
            log.error("가장 최근 리포트(%s)가 오늘(%s) 것이 아닙니다. "
                      "report 단계가 실패했는지 확인하세요.", report_dir, today)
            return {"sent": False}

    # 평문 메일이라 report.txt 를 우선 쓴다 (표·링크가 평문으로 정리된 판본).
    # 없으면 report.md 로 대체한다.
    body_path = os.path.join(report_dir, "report.txt")
    if not os.path.exists(body_path):
        body_path = os.path.join(report_dir, "report.md")
    if not os.path.exists(body_path):
        log.error("%s 안에 report.md/report.txt 가 없습니다.", report_dir)
        return {"sent": False}

    with open(body_path, encoding="utf-8") as f:
        body_text = f.read()

    to_addr = getattr(args, "to", None) or conf.get("email", {}).get("to")

    attachments = []
    if getattr(args, "attach_charts", False):
        attachments = sorted(glob.glob(os.path.join(report_dir, "charts", "*.png")))

    # 제목에 건수를 넣어 두면 메일함에서 열지 않고도 오늘 수확을 알 수 있다
    match = re.search(r"뉴스 목록 \((\d+)건\)", body_text)
    count_label = f" · {match.group(1)}건" if match else ""
    subject = f"[AI 뉴스 리포트] {today}{count_label}"

    try:
        mailer.send_email(subject, body_text, to_addr=to_addr,
                          attachments=attachments)
    except Exception as error:
        log.error("이메일 발송 실패: %s", error)
        return {"sent": False, "error": str(error)}

    log.info("이메일 발송 완료: %s -> %s (첨부 %d건)",
             report_dir, to_addr or "(본인 계정)", len(attachments))
    return {"sent": True, "report_dir": report_dir, "to": to_addr,
            "attachments": attachments}


if __name__ == "__main__":
    import sys

    parser = argparse.ArgumentParser(description="리포트 이메일 발송 (mail) 단독 실행")
    sub = parser.add_subparsers(dest="command")
    add_mail_parser(sub)

    argv = sys.argv[1:]
    if not argv or argv[0] != "mail":
        argv = ["mail"] + argv
    cmd_mail(parser.parse_args(argv))
