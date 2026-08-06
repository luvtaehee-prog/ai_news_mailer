from collector import fetch_news
import argparse
from collector import fetch_news


def main():
    parser = argparse.ArgumentParser(
        description="AI 뉴스 트렌드 분석 프로젝트"
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True
    )

    fetch_parser = subparsers.add_parser(
        "fetch",
        help="뉴스 수집"
    )

    fetch_parser.add_argument(
        "--source",
        default="google",
        help="뉴스 소스"
    )

    fetch_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="수집할 뉴스 개수"
    )

    args = parser.parse_args()

    if args.command == "fetch":
        fetch_news(
            source=args.source,
            limit=args.limit
        )


if __name__ == "__main__":
    main()