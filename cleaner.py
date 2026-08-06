"""데이터 정제 모듈 (2번 파트 핵심 로직).

수집(raw) 단계에서 넘어온 뉴스 한 건을 받아,
분석하기 좋은 형태의 clean 레코드로 변환한다.

정제 규칙:
  1) 필수 필드 검증  : title, url, published_at 이 비어 있으면 버림
  2) 텍스트 정규화    : HTML 태그 제거, 엔티티 복원(&nbsp; 등), 공백 정리
  3) 날짜 형식 통일   : "Thu, 06 Aug 2026 00:40:23 GMT" -> 한국시간(KST) ISO
  4) 결측값 처리      : content 없으면 title 로 대체, category 없으면 기본값
"""

import re
import html
import hashlib
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

KST = timezone(timedelta(hours=9))  # 한국 표준시(UTC+9)

_TAG_RE = re.compile(r"<[^>]+>")     # 모든 HTML 태그
_WS_RE = re.compile(r"\s+")          # 연속 공백
# 줄바꿈/문단 구분 태그는 공백으로 바꿔 단어가 붙지 않게 한다.
_BLOCK_RE = re.compile(r"</?(?:br|p|div|li|tr|h[1-6]|section|article)\b[^>]*>",
                       re.IGNORECASE)


def strip_html(text: str) -> str:
    """HTML 태그와 엔티티를 제거하고 공백을 정리한 순수 텍스트를 반환한다.

    - 문단/줄바꿈 태그(<p>, <br> 등)는 공백으로 치환 (단어 붙음 방지)
    - <b>, <a>, <font> 같은 인라인 태그는 그냥 제거 (AI시대 -> AI시대 유지)
    """
    if not text:
        return ""
    text = _BLOCK_RE.sub(" ", text)  # 블록 태그 -> 공백
    text = _TAG_RE.sub("", text)     # 나머지 인라인 태그 -> 제거
    text = html.unescape(text)       # &nbsp; &quot; &amp; 등 -> 실제 문자
    text = _WS_RE.sub(" ", text)     # 연속 공백/개행 -> 공백 하나
    return text.strip()


def split_title_press(title: str):
    """'제목 - 언론사' 형태를 (제목, 언론사) 로 분리한다.

    구분자가 없으면 언론사는 빈 문자열로 둔다.
    """
    title = strip_html(title)
    if " - " in title:
        head, _, tail = title.rpartition(" - ")  # 마지막 ' - ' 기준으로 분리
        head, tail = head.strip(), tail.strip()
        if head and tail:
            return head, tail
    return title, ""


def normalize_date(raw_date: str):
    """다양한 형식의 날짜 문자열을 한국시간(KST) datetime 으로 변환한다.

    지원 형식:
      - RFC822       : "Thu, 06 Aug 2026 00:40:23 GMT"  (google)
      - RFC822+오프셋 : "Thu, 06 Aug 2026 11:33:00 +0900" (naver)
      - 사람용 표기   : "3 August 2026", "03 Aug 2026"     (gov.uk)
      - ISO          : "2026-08-06T11:35:15"
    실패하면 None 을 반환한다.
    """
    if not raw_date:
        return None
    raw_date = raw_date.strip()

    # 1) RFC822 형식 (google, naver)
    try:
        dt = parsedate_to_datetime(raw_date)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(KST)
    except (TypeError, ValueError):
        pass

    # 2) 사람용 날짜 표기 (gov.uk 등, 시간 없음 -> 00:00 처리)
    #    뒤에 잡다한 문구가 붙는 경우가 있어 'D Month YYYY' 부분만 뽑아낸다.
    #    예: "13 July 2026 First published during ..." -> "13 July 2026"
    m = re.search(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})", raw_date)
    date_part = m.group(1) if m else raw_date
    for fmt in ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_part, fmt)
            return dt.replace(tzinfo=KST)  # 시간 없는 날짜는 KST 자정으로 간주
        except ValueError:
            continue

    # 3) ISO 형식
    try:
        dt = datetime.fromisoformat(raw_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(KST)
    except ValueError:
        return None


def make_id(url: str) -> str:
    """url 을 기반으로 짧고 고유한 id 를 만든다 (중복 판별의 자연키)."""
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:12]


def cap_content(text: str, limit: int):
    """본문이 너무 길면 limit 글자로 자른다 (단어 중간이 잘리지 않게 보정).

    반환: (본문, 잘렸는지 여부)
    """
    if not limit or len(text) <= limit:
        return text, False
    cut = text[:limit]
    sp = cut.rfind(" ")            # 마지막 공백에서 끊어 단어 잘림 방지
    if sp > limit * 0.6:
        cut = cut[:sp]
    return cut.rstrip() + "…", True


def clean_record(raw: dict, clean_conf: dict):
    """raw 레코드 한 건을 정제한다.

    반환: (clean_dict, None)          정제 성공
          (None, "사유 문자열")        검증 실패로 버림
    """
    clean_conf = clean_conf or {}
    min_title_len = clean_conf.get("min_title_length", 2)
    category_map = clean_conf.get("category_by_source", {})
    default_category = clean_conf.get("default_category", "미분류")
    # 제목 끝에 '- 언론사'가 붙는 소스만 분리 (google RSS 관례). 기본 ["google"]
    press_sources = clean_conf.get("press_in_title_sources", ["google"])
    max_content = clean_conf.get("max_content_length", 3000)  # 본문 길이 상한

    # --- 1) 필수 필드 검증 ---
    source = raw.get("source", "") or ""
    if source in press_sources:
        title, press = split_title_press(raw.get("title", ""))
    else:
        title, press = strip_html(raw.get("title", "")), ""
    url = (raw.get("url") or "").strip()
    published_dt = normalize_date(raw.get("published_at", ""))

    if len(title) < min_title_len:
        return None, "제목 없음/너무 짧음"
    if not url:
        return None, "url 없음"
    if published_dt is None:
        return None, "발행일 파싱 실패"

    # --- 2) 텍스트 정규화 ---
    content = strip_html(raw.get("content", ""))

    # --- 4) 결측값 처리 ---
    if not content:
        content = title  # 본문이 비면 제목으로 대체
    # 카테고리 우선순위: 명시적 category -> search_keyword(naver 등) -> 소스 기본값
    category = (
        raw.get("category")
        or raw.get("search_keyword")
        or category_map.get(source, default_category)
    )

    # 본문 길이 상한 적용 (긴 gov.uk 기사 등)
    content, truncated = cap_content(content, max_content)

    # --- 3) 날짜 통일 + clean 레코드 조립 ---
    clean = {
        "id": make_id(url),
        "title": title,
        "press": press,
        "content": content,
        "content_length": len(content),
        "truncated": truncated,
        "url": url,
        "category": category,
        "source": source,
        "collection_method": raw.get("collection_method", ""),
        "published_at": published_dt.isoformat(),          # 예: 2026-08-06T09:40:23+09:00
        "published_date": published_dt.strftime("%Y-%m-%d"),  # 예: 2026-08-06
        "collected_at": raw.get("collected_at", ""),
        "cleaned_at": datetime.now(KST).isoformat(),
    }
    return clean, None
