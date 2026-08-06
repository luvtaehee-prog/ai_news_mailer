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
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logger = logging.getLogger(__name__)

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
                for line in file:
                    line = line.strip()

                    if not line:
                        continue

                    news = json.loads(line)

                    if news.get("url"):
                        existing_urls.add(news["url"])

        except (json.JSONDecodeError, OSError) as error:
            logger.error("기존 raw 파일을 읽는 중 오류가 발생했습니다.")
            logger.error(error)

    added_count = 0

    # 새로운 뉴스만 JSONL 파일 뒤에 추가
    with open(file_path, "a", encoding="utf-8") as file:
        for news in news_list:
            url = news.get("url")

            if url and url in existing_urls:
                continue

            file.write(
                json.dumps(
                    news,
                    ensure_ascii=False
                ) + "\n"
            )

            if url:
                existing_urls.add(url)

            added_count += 1

    logger.info("저장 완료: %s", file_path)
    logger.info("새로 추가된 뉴스: %d", added_count)

# --------------------------------------------------
# Google News RSS 수집
# --------------------------------------------------

def fetch_google_news(limit=20):
    rss_url = (
        "https://news.google.com/rss/search"
        "?q=AI&hl=ko&gl=KR&ceid=KR:ko"
    )

    try:
        response = requests.get(
            rss_url,
            timeout=10
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
        news_data = {
            "title": news.get("title", ""),
            "content": news.get("summary", ""),
            "url": news.get("link", ""),
            "published_at": news.get("published", ""),
            "source": "google",
            "collected_at": datetime.now().isoformat(),
            "collection_method": "rss"
        }

        news_list.append(news_data)

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

    url = "https://naverapihub.apigw.ntruss.com/search/v1/news"

    headers = {
        "X-NCP-APIGW-API-KEY-ID": client_id,
        "X-NCP-APIGW-API-KEY": client_secret
    }

    keywords = [
        "AI",
        "인공지능",
        "생성형 AI",
        "LLM",
        "AI 반도체"
    ]

    news_list = []
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
                timeout=10
            )

            logger.info(
                "검색어 '%s' 응답 코드: %d",
                keyword,
                response.status_code
            )

            response.raise_for_status()

        except requests.exceptions.Timeout:
            print(
                f"네이버 뉴스 요청 시간이 초과되었습니다: {keyword}"
            )
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

            news_data = {
                "title": item.get("title", ""),
                "content": item.get("description", ""),
                "url": article_url,
                "published_at": item.get("pubDate", ""),
                "source": "naver",
                "collected_at": datetime.now().isoformat(),
                "collection_method": "api",
                "search_keyword": keyword
            }

            news_list.append(news_data)

    # --limit 값을 최종 뉴스 개수로 사용
    news_list = news_list[:limit]

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
    url = (
        "https://www.gov.uk/search/news-and-communications"
        "?parent=%2Fbusiness-and-industry%2Fartificial-intelligence"
        "&topic=7a4fba0a-f8d5-4aed-9d73-8a455c6ba7ac"
    )

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=10
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
                timeout=10
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
        time.sleep(1)

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