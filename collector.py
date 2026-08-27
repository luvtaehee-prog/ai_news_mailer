import json
import re
import time
import os
import logging
from datetime import datetime
from math import ceil

import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from cleaner import normalize_date


load_dotenv()

with open("config.json", "r", encoding="utf-8") as file:
    config = json.load(file)

# 로그 폴더 생성
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        # 로그 파일에 저장
        logging.FileHandler(
            "logs/collector.log",
            encoding="utf-8"
        ),

        # 터미널에도 출력
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

ARTICLE_CONTENT_SELECTORS = [
    "article",
    "[itemprop='articleBody']",
    ".article-body",
    ".article_body",
    ".article-content",
    ".article_content",
    ".article-view-content",
    ".articleView",
    ".article_view",
    ".entry-content",
    ".post-content",
    ".news-content",
    ".news_content",
    ".newsct_article",
    ".view_text",
    ".view_con",
    ".view_content",
    "#articleBody",
    "#articleBodyContents",
    "#article-view-content-div",
    "#dic_area"
]

ARTICLE_DESCRIPTION_SELECTORS = [
    "meta[property='og:description']",
    "meta[name='description']",
    "meta[name='twitter:description']"
]

GOOGLE_NEWS_BATCH_URL = (
    "https://news.google.com/_/DotsSplashUi/data/batchexecute"
)

CONTENT_EXCERPT_MAX_LENGTH = 3000

# 본문 셀렉터가 기사와 함께 긁어오는 페이지 부가 텍스트(저작권 안내, 기자 이메일,
# 공유/댓글 UI 문구 등)의 시작 지점을 찾기 위한 패턴. 완벽한 커버리지는 아니고
# 흔한 패턴 위주의 휴리스틱이라, 언론사에 따라 못 걸러내는 경우가 있을 수 있다.
TRAILING_BOILERPLATE_PATTERNS = [
    r"저작권자\s*[ⓒ©]",
    r"무단\s*전재",
    r"재배포\s*금지",
    r"AI\s*학습\s*및\s*활용\s*금지",
    r"이 기사를 공유합니다",
    r"다른\s*기사\s*보기",
    r"기자\s*[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}",
    r"구독하기",
    r"기사의 본문 내용은 이 글자크기로 변경됩니다",
]

_TRAILING_BOILERPLATE_RE = re.compile(
    "|".join(TRAILING_BOILERPLATE_PATTERNS)
)

# --------------------------------------------------
# 발행일 필터 (당일 뉴스만 수집)
# --------------------------------------------------

def published_date_kst(raw_date):
    """기사 발행일 문자열을 KST 기준 'YYYY-MM-DD' 로 바꾼다. 실패하면 None."""
    parsed = normalize_date(raw_date)

    return parsed.strftime("%Y-%m-%d") if parsed else None


def is_target_date(raw_date, only_date):
    """only_date 에 해당하는 기사인지 판단한다.

    only_date 가 None 이면(=--all-dates) 전부 통과시킨다.
    발행일을 못 읽는 기사는 당일 여부를 확인할 수 없으므로 제외한다.
    (어차피 clean 단계에서도 '발행일 파싱 실패'로 버려진다.)
    """
    if not only_date:
        return True

    return published_date_kst(raw_date) == only_date


# --------------------------------------------------
# 공통 raw 데이터 저장
# --------------------------------------------------

def save_raw_news(news_list, file_name):
    # 저장 경로는 config.json 의 paths.raw 를 따른다.
    # 정제·리포트 단계도 같은 키를 보고 있어, 한 곳만 바꾸면 전체가 함께 움직인다.
    raw_dir = config.get("paths", {}).get("raw", "data/raw")
    os.makedirs(raw_dir, exist_ok=True)

    file_path = os.path.join(raw_dir, file_name)

    existing_urls = set()

    # 기존 JSONL 파일이 있으면 저장된 URL 확인
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                for line_number, line in enumerate(file, start=1):
                    line = line.strip()

                    if not line:
                        continue

                    try:
                        news = json.loads(line)

                    except json.JSONDecodeError as error:
                        logger.warning(
                            "JSONL line skipped: %s:%d (%s)",
                            file_path,
                            line_number,
                            error
                        )
                        continue

                    for url_key in ("url", "google_news_url"):
                        if news.get(url_key):
                            existing_urls.add(news[url_key])

        except (json.JSONDecodeError, OSError) as error:
            logger.error("기존 raw 파일을 읽는 중 오류가 발생했습니다.")
            logger.error(error)

    added_count = 0

    # 새로운 뉴스만 JSONL 파일 뒤에 추가
    with open(file_path, "a", encoding="utf-8") as file:
        for news in news_list:
            url = news.get("url")
            google_news_url = news.get("google_news_url")

            if (
                url
                and url in existing_urls
            ) or (
                google_news_url
                and google_news_url in existing_urls
            ):
                continue

            file.write(
                json.dumps(
                    news,
                    ensure_ascii=False
                ) + "\n"
            )

            if url:
                existing_urls.add(url)

            if google_news_url:
                existing_urls.add(google_news_url)

            added_count += 1

    logger.info("저장 완료: %s", file_path)
    logger.info("새로 추가된 뉴스: %d", added_count)

# --------------------------------------------------
# Google News RSS 수집
# --------------------------------------------------

def clean_text(text):
    return " ".join(
        text.split()
    )


def make_content_excerpt(text, max_length=CONTENT_EXCERPT_MAX_LENGTH):
    text = clean_text(text)

    if len(text) <= max_length:
        return text

    suffix = "..."
    excerpt = text[:max_length - len(suffix)].rstrip()

    last_space = excerpt.rfind(" ")

    if last_space >= max_length * 0.75:
        excerpt = excerpt[:last_space].rstrip()

    return excerpt + suffix


def html_to_text(html):
    if not html:
        return ""

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    return clean_text(
        soup.get_text(
            " ",
            strip=True
        )
    )


def strip_trailing_boilerplate(text, min_keep=200, search_window=1200):
    # 기사 앞부분(바이라인 등)에도 비슷한 문구가 있을 수 있어, 끝부분 구간에서만 찾는다
    window_start = max(0, len(text) - search_window)
    match = _TRAILING_BOILERPLATE_RE.search(text, window_start)

    if not match:
        return text

    trimmed = text[:match.start()].rstrip()

    # 오탐으로 본문 앞부분까지 잘려나가면 원본을 그대로 둔다
    if len(trimmed) < min_keep:
        return text

    return trimmed


def extract_article_content(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # 메타 설명(og:description 등)은 사이트가 미리 짧게 잘라둔 값이라
    # 문장이 중간에 끊기는 경우가 많다. 그래서 실제 본문 셀렉터를 먼저 시도하고,
    # 본문을 못 찾을 때만 메타 설명으로 폴백한다.
    for tag in soup(
        [
            "script",
            "style",
            "noscript",
            "nav",
            "header",
            "footer",
            "aside",
            "form"
        ]
    ):
        tag.decompose()

    candidates = []

    for selector in ARTICLE_CONTENT_SELECTORS:
        for tag in soup.select(selector):
            text = clean_text(
                tag.get_text(
                    " ",
                    strip=True
                )
            )

            if text:
                candidates.append(text)

    if not candidates:
        paragraphs = [
            clean_text(
                paragraph.get_text(
                    " ",
                    strip=True
                )
            )
            for paragraph in soup.find_all("p")
        ]

        paragraphs = [
            paragraph
            for paragraph in paragraphs
            if len(paragraph) >= 30
        ]

        if paragraphs:
            candidates.append(
                clean_text(
                    " ".join(paragraphs)
                )
            )

    if not candidates and soup.body:
        candidates.append(
            clean_text(
                soup.body.get_text(
                    " ",
                    strip=True
                )
            )
        )

    content = max(candidates, key=len) if candidates else ""
    content = strip_trailing_boilerplate(content)

    if len(content) >= 200:
        return content

    # 본문 셀렉터로 못 찾았을 때만 메타 설명으로 폴백
    for selector in ARTICLE_DESCRIPTION_SELECTORS:
        meta_tag = soup.select_one(selector)

        if not meta_tag:
            continue

        description = clean_text(
            meta_tag.get("content", "")
        )

        if len(description) >= 30:
            return description

    return ""


def is_google_news_url(url):
    return (
        "://news.google.com/" in url
        and "/rss/articles/" in url
    )


def resolve_google_news_url(google_news_url, timeout, headers):
    if not is_google_news_url(google_news_url):
        return google_news_url

    try:
        response = requests.get(
            google_news_url,
            headers=headers,
            timeout=timeout
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )
        data_tag = soup.select_one("c-wiz[data-p]")

        if not data_tag:
            return google_news_url

        request_data = json.loads(
            data_tag.get("data-p").replace(
                '%.@.',
                '["garturlreq",'
            )
        )
        payload = {
            "f.req": json.dumps(
                [
                    [
                        [
                            "Fbv4je",
                            json.dumps(
                                request_data[:-6] + request_data[-2:]
                            ),
                            None,
                            "generic"
                        ]
                    ]
                ]
            )
        }
        resolve_headers = {
            **headers,
            "Content-Type": (
                "application/x-www-form-urlencoded;charset=UTF-8"
            ),
            "Referer": "https://news.google.com/"
        }

        resolve_response = requests.post(
            GOOGLE_NEWS_BATCH_URL,
            headers=resolve_headers,
            data=payload,
            timeout=timeout
        )

        resolve_response.raise_for_status()

        response_text = resolve_response.text

        if response_text.startswith(")]}'"):
            response_text = response_text[4:]

        array_string = json.loads(response_text)[0][2]
        article_url = json.loads(array_string)[1]

        return article_url or google_news_url

    except (
        AttributeError,
        IndexError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        requests.exceptions.RequestException
    ) as error:
        logger.warning("Google News URL resolve failed: %s", google_news_url)
        logger.warning(error)

    return google_news_url


def fetch_article_content(article_url, timeout, headers):
    if not article_url:
        return "", ""

    article_url = resolve_google_news_url(
        article_url,
        timeout,
        headers
    )

    try:
        response = requests.get(
            article_url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True
        )

        response.raise_for_status()

        if not response.encoding:
            response.encoding = response.apparent_encoding

        content = extract_article_content(response.text)

        return content, response.url

    except requests.exceptions.Timeout:
        logger.error("Article request timed out: %s", article_url)

    except requests.exceptions.RequestException as error:
        logger.error("Article content fetch failed: %s", article_url)
        logger.error(error)

    return "", article_url


def fetch_google_news(limit=20, only_date=None):
    rss_url = config["news_sources"]["google"]["url"]
    timeout = config["request"]["timeout"]
    request_delay = config["news_sources"]["google"].get(
        "request_delay",
        0.5
    )
    max_retries = config["news_sources"]["google"].get(
        "max_retries",
        3
    )
    retry_delay = config["news_sources"]["google"].get(
        "retry_delay",
        5
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )
    }

    response = None

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(
                rss_url,
                headers=headers,
                timeout=timeout
            )

            response.raise_for_status()
            break

        except requests.exceptions.Timeout:
            logger.error(
                "Google News RSS 요청 시간이 초과되었습니다. (%d/%d회 시도)",
                attempt,
                max_retries
            )
            response = None

        except requests.exceptions.RequestException as error:
            logger.error(
                "Google News RSS 요청에 실패했습니다. (%d/%d회 시도)",
                attempt,
                max_retries
            )
            logger.error(error)
            response = None

        if attempt < max_retries:
            time.sleep(retry_delay)

    if response is None:
        logger.error(
            "Google News RSS 요청이 %d회 모두 실패했습니다.",
            max_retries
        )
        return []

    feed = feedparser.parse(response.content)

    if feed.bozo:
        logger.error("Google News RSS 파싱 중 오류가 발생했습니다.")
        logger.error(feed.bozo_exception)
        return []

    news_list = []
    skipped_by_date = 0

    # entries[:limit] 로 미리 자르지 않는다. 날짜로 걸러내고 나면 limit 을
    # 못 채우기 때문에, 피드 전체를 훑으면서 조건에 맞는 것만 limit 만큼 모은다.
    for news in feed.entries:
        if len(news_list) >= limit:
            break

        published_at = news.get("published", "")

        # 날짜 판정은 본문 크롤링보다 먼저 한다. 순서를 바꾸면 버릴 기사까지
        # 원문 페이지를 받아오느라 실행 시간이 몇 배로 늘어난다.
        if not is_target_date(published_at, only_date):
            skipped_by_date += 1
            continue

        google_news_url = news.get("link", "")
        content, article_url = fetch_article_content(
            google_news_url,
            timeout,
            headers
        )
        content_excerpt = make_content_excerpt(content)

        news_data = {
            "title": news.get("title", ""),
            "content": content_excerpt,
            "url": article_url or google_news_url,
            "google_news_url": google_news_url,
            "published_at": published_at,
            "source": "google",
            "collected_at": datetime.now().isoformat(),
            "collection_method": "rss+crawl",
            "content_truncated": len(content_excerpt) < len(clean_text(content)),
            "content_max_length": CONTENT_EXCERPT_MAX_LENGTH
        }

        news_list.append(news_data)

        time.sleep(request_delay)

    logger.info(
        "수집된 Google News: %d건 (기준일 %s, 날짜 불일치로 제외 %d건)",
        len(news_list),
        only_date or "전체",
        skipped_by_date
    )

    save_raw_news(
        news_list,
        "google_news.jsonl"
    )

    return news_list


# --------------------------------------------------
# NAVER 뉴스 검색 API 수집
# --------------------------------------------------

def fetch_naver_news(limit=20, only_date=None):
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")

    if not client_id or not client_secret:
        logger.error("NAVER API 인증정보가 없습니다.")
        logger.error(".env 파일의 NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET을 확인하세요.")
        return []

    url = config["news_sources"]["naver"]["url"]

    headers = {
        "X-NCP-APIGW-API-KEY-ID": client_id,
        "X-NCP-APIGW-API-KEY": client_secret
    }

    keywords = config["news_sources"]["naver"]["keywords"]
    timeout = config["request"]["timeout"]
    request_delay = config["news_sources"]["naver"].get("request_delay", 0.5)
    items_found = []
    seen_urls = set()

    skipped_by_date = 0

    # 검색어별로 비슷한 수량을 요청
    per_keyword_limit = max(
        1,
        ceil(limit / len(keywords)) + 2
    )

    # 당일치만 남기면 대부분 걸러지므로 넉넉히 받아 온다.
    # sort=date(최신순)라 앞쪽에 오늘 기사가 몰려 있다.
    if only_date:
        per_keyword_limit = max(per_keyword_limit, 30)

    for keyword in keywords:
        params = {
            "query": keyword,
            "display": min(per_keyword_limit, 100),
            "start": 1,
            "sort": "date",
            "format": "json"
        }

        try:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=timeout
            )

            logger.info(
                "검색어 '%s' 응답 코드: %d",
                keyword,
                response.status_code
            )

            response.raise_for_status()

        except requests.exceptions.Timeout:
            logger.error("네이버 뉴스 요청 시간이 초과되었습니다: %s", keyword)
            continue

        except requests.exceptions.RequestException as error:
            logger.error("네이버 뉴스 요청에 실패했습니다: %s", keyword)
            logger.error(error)
            continue

        try:
            data = response.json()

        except requests.exceptions.JSONDecodeError:
            logger.error("네이버 뉴스 JSON 응답을 읽지 못했습니다: %s", keyword)
            continue

        for item in data.get("items", []):
            if not is_target_date(item.get("pubDate", ""), only_date):
                skipped_by_date += 1
                continue

            article_url = (
                item.get("originallink")
                or item.get("link", "")
            )

            if not article_url:
                continue

            if article_url in seen_urls:
                continue

            seen_urls.add(article_url)
            items_found.append((item, article_url, keyword))

    # --limit 값을 최종 뉴스 개수로 사용 (크롤링은 이 개수만큼만 수행)
    items_found = items_found[:limit]

    news_list = []

    # naver API의 description은 검색어 주변만 뽑은 스니펫이라 문맥이 끊기므로,
    # google과 동일하게 원문 페이지를 크롤링해 본문을 채운다.
    # 크롤링 실패 시에는 API description으로 대체한다.
    for item, article_url, keyword in items_found:
        api_description = item.get("description", "")

        content, resolved_url = fetch_article_content(
            article_url,
            timeout,
            headers
        )

        if content:
            content_excerpt = make_content_excerpt(content)
            content_truncated = len(content_excerpt) < len(clean_text(content))
            content_source = "crawl"
        else:
            content_excerpt = html_to_text(api_description)
            content_truncated = False
            content_source = "api_description"

        news_data = {
            "title": item.get("title", ""),
            "content": content_excerpt,
            "api_description": html_to_text(api_description),
            "url": article_url,
            "published_at": item.get("pubDate", ""),
            "source": "naver",
            "collected_at": datetime.now().isoformat(),
            "collection_method": "api+crawl",
            "search_keyword": keyword,
            "content_source": content_source,
            "content_truncated": content_truncated,
            "content_max_length": CONTENT_EXCERPT_MAX_LENGTH
        }

        news_list.append(news_data)

        time.sleep(request_delay)

    logger.info(
        "중복 제거 후 수집된 NAVER 뉴스: %d건 (기준일 %s, 날짜 불일치로 제외 %d건)",
        len(news_list),
        only_date or "전체",
        skipped_by_date
    )

    save_raw_news(
        news_list,
        "naver_news.jsonl"
    )

    return news_list


# --------------------------------------------------
# GOV.UK AI 뉴스 크롤링
# --------------------------------------------------

def crawl_govuk(limit=20, only_date=None):
    url = config["news_sources"]["govuk"]["url"]
    request_delay = config["news_sources"]["govuk"]["request_delay"]
    timeout = config["request"]["timeout"]

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=timeout
        )

        logger.info("GOV.UK 응답 코드: %d", response.status_code)

        response.raise_for_status()

    except requests.exceptions.Timeout:
        logger.error("GOV.UK 요청 시간이 초과되었습니다.")
        return []

    except requests.exceptions.RequestException as error:
        logger.error("GOV.UK 뉴스 수집에 실패했습니다.")
        logger.error(error)
        return []

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    results = soup.select("li")

    news_list = []
    skipped_by_date = 0

    for item in results:
        link_tag = item.find("a")
        text = item.get_text(" ", strip=True)

        if not link_tag:
            continue

        if "Updated:" not in text:
            continue

        href = link_tag.get("href", "")

        if not href.startswith("/government/"):
            continue

        title = (
            link_tag.string.strip()
            if link_tag.string
            else link_tag.get_text(
                " ",
                strip=True
            )
        )

        published_at = (
            text.split("Updated:")[-1].strip()
        )

        # 상세 페이지를 받아오기 전에 날짜부터 본다 (기사마다 1초씩 쉬므로
        # 뒤에서 거르면 버릴 기사에 그 시간을 다 쓰게 된다)
        if not is_target_date(published_at, only_date):
            skipped_by_date += 1
            continue

        article_url = "https://www.gov.uk" + href

        # 기사 상세 페이지 본문 수집
        content = ""

        try:
            article_response = requests.get(
                article_url,
                headers=headers,
                timeout=timeout
            )

            article_response.raise_for_status()

            article_soup = BeautifulSoup(
                article_response.text,
                "html.parser"
            )

            # GOV.UK 기사 본문 영역
            content_tag = article_soup.select_one(
                ".govspeak"
            )

            if content_tag:
                content = content_tag.get_text(
                    " ",
                    strip=True
                )

        except requests.exceptions.Timeout:
            logger.error("기사 본문 요청 시간 초과: %s", article_url)

        except requests.exceptions.RequestException as error:
            logger.error("기사 본문 수집 실패: %s", article_url)
            logger.error(error)

        news_data = {
            "title": title,
            "content": content,
            "url": article_url,
            "published_at": published_at,
            "source": "gov.uk",
            "collected_at": datetime.now().isoformat(),
            "collection_method": "crawl"
        }

        news_list.append(news_data)

        # 과도한 요청 방지
        time.sleep(request_delay)

        if len(news_list) >= limit:
            break

    logger.info(
        "수집된 GOV.UK AI 뉴스: %d건 (기준일 %s, 날짜 불일치로 제외 %d건)",
        len(news_list),
        only_date or "전체",
        skipped_by_date
    )

    save_raw_news(
        news_list,
        "govuk_news.jsonl"
    )

    return news_list

# --------------------------------------------------
# 수집 소스 선택
# --------------------------------------------------

def fetch_news(source, limit=20, only_date=None):
    """뉴스를 수집한다.

    only_date : "YYYY-MM-DD" 를 주면 그 날짜에 발행된 기사만 남긴다.
                None 이면 발행일과 무관하게 수집한다.
    """
    source = source.lower()

    if source == "google":
        return fetch_google_news(limit, only_date)

    elif source == "naver":
        return fetch_naver_news(limit, only_date)

    elif source == "govuk":
        return crawl_govuk(limit, only_date)

    else:
        logger.error("지원하지 않는 뉴스 소스입니다: %s", source)
        logger.info("사용 가능한 소스: google, naver, govuk")
        return []
