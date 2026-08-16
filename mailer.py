"""이메일 발송 모듈.

Gmail SMTP(smtp.gmail.com:465, SSL)로 리포트를 발송한다.
인증 정보는 .env 의 GMAIL_ADDRESS / GMAIL_APP_PASSWORD 에서 읽는다.
(수신 비밀번호가 아니라 앱 비밀번호를 사용해야 한다.)
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def get_credentials():
    """.env 에서 발신 계정 정보를 읽는다. 없으면 명확한 에러를 낸다."""
    address = os.getenv("GMAIL_ADDRESS")
    password = os.getenv("GMAIL_APP_PASSWORD")
    if not address or not password:
        raise RuntimeError(
            ".env 에 GMAIL_ADDRESS 와 GMAIL_APP_PASSWORD 가 없습니다. "
            "프로젝트 루트의 .env 에 두 값을 추가하세요."
        )
    return address, password


def build_message(subject: str, body_text: str, to_addr: str,
                   from_addr: str, attachments=None) -> MIMEMultipart:
    """제목/본문/수신자로 MIME 메시지를 만든다. attachments 는 파일 경로 리스트."""
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    for path in attachments or []:
        if not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        filename = os.path.basename(path)
        part.add_header("Content-Disposition",
                         f'attachment; filename="{filename}"')
        msg.attach(part)

    return msg


def send_email(subject: str, body_text: str, to_addr: str = None,
                attachments=None) -> None:
    """이메일을 발송한다. to_addr 를 생략하면 본인 계정으로 보낸다."""
    from_addr, app_password = get_credentials()
    to_addr = to_addr or from_addr

    msg = build_message(subject, body_text, to_addr, from_addr, attachments)

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(from_addr, app_password)
        server.sendmail(from_addr, [to_addr], msg.as_string())
