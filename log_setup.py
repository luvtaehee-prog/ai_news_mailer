"""로깅 설정 모듈.

콘솔과 파일(logs/pipeline.log)에 동시에 로그를 남긴다.
INFO / WARNING / ERROR 레벨을 모두 기록한다.
"""

import logging
import os


def get_logger(name: str = "newspipe", log_dir: str = "logs") -> logging.Logger:
    """이름별 로거를 만들어 반환한다. 중복 핸들러 등록을 방지한다."""
    logger = logging.getLogger(name)
    if logger.handlers:  # 이미 설정된 로거면 그대로 재사용
        return logger

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(levelname)s] %(message)s")

    # 콘솔 출력
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    # 파일 출력
    os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.FileHandler(
        os.path.join(log_dir, "pipeline.log"), encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(file_handler)

    return logger
