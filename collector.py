import json
import time
import os
import logging
from datetime import datetime
from math import ceil

import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


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

# --------------------------------------------------
# 공통 raw 데이터 저장
# --------------------------------------------------

def save_raw_news(news_list, file_name):
    os.makedirs("data/raw", exist_ok=True)

    file_path = f"data/raw/{file_name}"

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


def fetch_google_news(limit=20):
    rss_url = config["news_sources"]["google"]["url"]
    timeout = config["request"]["timeout"]
    request_delay = config["news_sources"]["google"].get(
        "request_delay",
        0.5
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(
            rss_url,
            headers=headers,
            timeout=timeout
        )

        response.raise_for_status()

    except requests.exceptions.Timeout:
        logger.error("Google News RSS 요청 시간이 초과되었습니다.")
        return []

    except requests.exceptions.RequestException as error:
        logger.error("Google News RSS 요청에 실패했습니다.")
        logger.error(error)
        return []

    feed = feedparser.parse(response.content)

    if feed.bozo:
        logger.error("Google News RSS 파싱 중 오류가 발생했습니다.")
        logger.error(feed.bozo_exception)
        return []

    news_list = []

    for news in feed.entries[:limit]:
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
            "published_at": news.get("published", ""),
            "source": "google",
            "collected_at": datetime.now().isoformat(),
            "collection_method": "rss+crawl",
            "content_truncated": len(content_excerpt) < len(clean_text(content)),
            "content_max_length": CONTENT_EXCERPT_MAX_LENGTH
        }

        news_list.append(news_data)

        time.sleep(request_delay)

    logger.info("수집된 Google News: %d", len(news_list))

    save_raw_news(
        news_list,
        "google_news.jsonl"
    )

    return news_list


# --------------------------------------------------
# NAVER 뉴스 검색 API 수집
# --------------------------------------------------

def fetch_naver_news(limit=20):
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

    # 검색어별로 비슷한 수량을 요청
    per_keyword_limit = max(
        1,
        ceil(limit / len(keywords)) + 2
    )

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

    logger.info("중복 제거 후 수집된 NAVER 뉴스: %d", len(news_list))

    save_raw_news(
        news_list,
        "naver_news.jsonl"
    )

    return news_list


# --------------------------------------------------
# GOV.UK AI 뉴스 크롤링
# --------------------------------------------------

def crawl_govuk(limit=20):
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

    logger.info("수집된 GOV.UK AI 뉴스: %d", len(news_list))

    save_raw_news(
        news_list,
        "govuk_news.jsonl"
    )

    return news_list

# --------------------------------------------------
# 수집 소스 선택
# --------------------------------------------------

def fetch_news(source, limit=20):
    source = source.lower()

    if source == "google":
        return fetch_google_news(limit)

    elif source == "naver":
        return fetch_naver_news(limit)

    elif source == "govuk":
        return crawl_govuk(limit)

    else:
        logger.error("지원하지 않는 뉴스 소스입니다: %s", source)
        logger.info("사용 가능한 소스: google, naver, govuk")
        return []
