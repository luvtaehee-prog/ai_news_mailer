"""시각화 모듈 (4번 파트).

역할: 집계된 통계를 matplotlib 차트(PNG)로 그려 output/charts 에 저장한다.

이 모듈은 '그리기'만 담당한다. 데이터 로딩과 집계는 reporter.py 가 맡고,
여기서는 이미 계산된 딕셔너리/리스트를 받아 그림만 그린다.
(그래야 집계 로직을 고쳐도 차트 코드를 건드릴 필요가 없다.)

단독 실행 (차트만 다시 그리기):
    python visualizer.py
"""

import os

import matplotlib

# 서버/CI 환경에는 화면이 없으므로 파일 저장 전용 백엔드를 강제한다.
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager

from log_setup import get_logger

log = get_logger("report")

# 운영체제별 기본 한글 폰트 후보 (앞에서부터 설치된 것을 사용)
KOREAN_FONT_CANDIDATES = [
    "AppleGothic",           # macOS 기본
    "Apple SD Gothic Neo",   # macOS
    "Malgun Gothic",         # Windows 기본
    "NanumGothic",           # 리눅스/공용 (fonts-nanum)
    "NanumBarunGothic",
    "Noto Sans CJK KR",      # 리눅스
    "Noto Sans KR",
]

# 차트 공통 색상 (한 프로젝트 안에서 톤을 통일하기 위해 상수로 관리)
COLOR_MAIN = "#3B6FD4"
COLOR_SUB = "#F2A03D"
COLOR_PALETTE = ["#3B6FD4", "#F2A03D", "#5FB98C", "#E4685D",
                 "#8C7AE6", "#4FB0C6", "#C7A15A", "#9AA3AF"]

# 감성은 색 자체가 의미를 가지므로 팔레트 순서가 아니라 라벨에 고정한다
SENTIMENT_COLORS = {"긍정": "#5FB98C", "중립": "#9AA3AF", "부정": "#E4685D"}


def setup_korean_font() -> str:
    """설치된 한글 폰트를 찾아 matplotlib 기본 폰트로 설정한다.

    반환값: 실제로 적용된 폰트 이름 (못 찾으면 빈 문자열)
    """
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in KOREAN_FONT_CANDIDATES:
        if name in installed:
            plt.rcParams["font.family"] = name
            # 한글 폰트는 마이너스 기호가 깨지는 경우가 있어 아스키 마이너스를 쓴다.
            plt.rcParams["axes.unicode_minus"] = False
            log.info("한글 폰트 적용: %s", name)
            return name

    log.warning(
        "한글 폰트를 찾지 못했습니다. 차트의 한글이 네모(□)로 보일 수 있습니다. "
        "설치 예: macOS는 기본 제공, Windows는 맑은 고딕, 리눅스는 fonts-nanum"
    )
    return ""


def _prepare(out_path: str):
    """저장 폴더를 만들고 새 figure 를 연다."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)


def _base_note(fig, text: str) -> None:
    """차트 우측 하단에 '무엇을 기준으로 센 수치인지'를 적는다.

    차트를 리포트에서 떼어내 발표 자료 등에 단독으로 붙여도
    모집단을 오해하지 않도록 그림 안에 함께 남긴다.
    """
    if text:
        fig.text(0.99, 0.01, text, ha="right", va="bottom",
                 fontsize=9, color="#888888")


def _finish(fig, out_path: str) -> str:
    """공통 마무리: 여백 정리 → 저장 → figure 닫기(메모리 누수 방지)."""
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    log.info("차트 저장: %s", out_path)
    return out_path


def _empty_notice(title: str, out_path: str) -> str:
    """그릴 데이터가 없을 때도 빈 차트를 남겨 파이프라인이 멈추지 않게 한다."""
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.set_title(title)
    ax.text(0.5, 0.5, "표시할 데이터가 없습니다",
            ha="center", va="center", fontsize=13, color="#888888")
    ax.axis("off")
    return _finish(fig, out_path)


def chart_category_counts(counts: dict, out_path: str,
                          base_note: str = "") -> str:
    """카테고리별 뉴스 수 (세로 막대)."""
    _prepare(out_path)
    if not counts:
        return _empty_notice("카테고리별 뉴스 수", out_path)

    items = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    labels = [k for k, _ in items]
    values = [v for _, v in items]

    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.bar(labels, values, color=COLOR_MAIN, width=0.6)
    ax.set_title("카테고리별 뉴스 수", fontsize=15, pad=14)
    ax.set_xlabel("카테고리")
    ax.set_ylabel("뉴스 수 (건)")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.set_axisbelow(True)
    ax.set_ylim(0, max(values) * 1.15)

    # 막대 위에 실제 건수를 적어 눈금을 읽지 않아도 값을 알 수 있게 한다.
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + max(values) * 0.02,
                str(value), ha="center", va="bottom", fontsize=10)

    if len(labels) > 6:
        plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    _base_note(fig, base_note)
    return _finish(fig, out_path)


def chart_daily_trend(daily: list, out_path: str,
                      date_label: str = "발행일", base_note: str = "") -> str:
    """일자별 수집 추이 (꺾은선).

    daily: [(날짜문자열, 건수), ...] — 날짜 오름차순으로 정렬되어 있다고 가정한다.
    date_label: x축 기준이 발행일인지 수집일인지 표시
    """
    _prepare(out_path)
    if not daily:
        return _empty_notice(f"{date_label}별 뉴스 추이", out_path)

    labels = [d for d, _ in daily]
    values = [c for _, c in daily]

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(labels, values, marker="o", markersize=5,
            linewidth=2, color=COLOR_MAIN)
    ax.fill_between(range(len(values)), values, alpha=0.12, color=COLOR_MAIN)
    ax.set_title(f"{date_label}별 뉴스 수집 추이", fontsize=15, pad=14)
    ax.set_xlabel(f"{date_label} (YYYY-MM-DD)")
    ax.set_ylabel("뉴스 수 (건)")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.set_axisbelow(True)
    ax.set_ylim(0, max(values) * 1.2)

    # 날짜가 많으면 x축 라벨이 겹치므로 일정 간격으로 솎아낸다.
    step = max(1, len(labels) // 12)
    ax.set_xticks(range(0, len(labels), step))
    ax.set_xticklabels(labels[::step], rotation=45, ha="right", fontsize=9)

    peak = max(range(len(values)), key=lambda i: values[i])
    ax.annotate(f"최다 {values[peak]}건",
                xy=(peak, values[peak]),
                xytext=(0, 12), textcoords="offset points",
                ha="center", fontsize=10, color=COLOR_SUB)
    _base_note(fig, base_note)
    return _finish(fig, out_path)


def chart_top_keywords(keywords: list, out_path: str, top_n: int = 10,
                       base_note: str = "") -> str:
    """AI가 뽑은 키워드 TOP N (가로 막대).

    keywords: [(키워드, 빈도), ...]
    """
    _prepare(out_path)
    if not keywords:
        return _empty_notice(f"키워드 TOP {top_n}", out_path)

    items = sorted(keywords, key=lambda kv: kv[1], reverse=True)[:top_n]
    items.reverse()  # barh 는 아래에서 위로 그리므로 뒤집어야 1위가 맨 위에 온다
    labels = [k for k, _ in items]
    values = [v for _, v in items]

    fig, ax = plt.subplots(figsize=(9, max(4.5, len(items) * 0.45)))
    ax.barh(labels, values, color=COLOR_SUB, height=0.6)
    ax.set_title(f"AI 추출 키워드 TOP {len(items)}", fontsize=15, pad=14)
    ax.set_xlabel("등장 기사 수 (건)")
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    ax.set_axisbelow(True)
    ax.set_xlim(0, max(values) * 1.15)

    for y, value in enumerate(values):
        ax.text(value + max(values) * 0.015, y, str(value),
                va="center", fontsize=10)
    _base_note(fig, base_note)
    return _finish(fig, out_path)


def chart_source_share(counts: dict, out_path: str,
                       base_note: str = "") -> str:
    """수집 소스별 비중 (원 그래프)."""
    _prepare(out_path)
    if not counts:
        return _empty_notice("소스별 수집 비중", out_path)

    items = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    labels = [k for k, _ in items]
    values = [v for _, v in items]

    fig, ax = plt.subplots(figsize=(7, 6))
    ax.pie(
        values,
        labels=labels,
        autopct=lambda p: f"{p:.1f}%\n({round(p * sum(values) / 100)}건)",
        colors=COLOR_PALETTE[: len(values)],
        startangle=90,
        counterclock=False,
        wedgeprops={"edgecolor": "white", "linewidth": 1.5},
        textprops={"fontsize": 11},
    )
    ax.set_title("소스별 수집 비중", fontsize=15, pad=14)
    ax.axis("equal")
    _base_note(fig, base_note)
    return _finish(fig, out_path)


def chart_sentiment(counts: dict, out_path: str,
                    base_note: str = "") -> str:
    """뉴스 감성 분포 (가로 막대). 보너스 과제."""
    _prepare(out_path)
    if not counts:
        return _empty_notice("뉴스 감성 분포", out_path)

    labels = list(counts.keys())
    values = [counts[k] for k in labels]
    total = sum(values)
    colors = [SENTIMENT_COLORS.get(k, COLOR_MAIN) for k in labels]

    fig, ax = plt.subplots(figsize=(8, 4.2))
    # 위에서부터 긍정 → 중립 → 부정 순으로 읽히도록 뒤집어 그린다
    ypos = range(len(labels))
    ax.barh(list(ypos), values, color=colors, height=0.6)
    ax.set_yticks(list(ypos))
    ax.set_yticklabels(labels, fontsize=12)
    ax.invert_yaxis()

    for y, v in zip(ypos, values):
        ax.text(v + max(values) * 0.015, y,
                f"{v}건 ({v / total * 100:.1f}%)",
                va="center", fontsize=11)

    ax.set_xlabel("기사 수 (건)", fontsize=11)
    ax.set_xlim(0, max(values) * 1.22)
    ax.set_title("뉴스 감성 분포", fontsize=15, pad=14)
    ax.grid(axis="x", linestyle=":", alpha=0.5)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)

    _base_note(fig, base_note)
    return _finish(fig, out_path)


def render_all(stats: dict, out_dir: str = "output/charts") -> list:
    """리포트에 들어갈 차트를 한 번에 그린다.

    stats: reporter.build_stats() 결과
    반환값: 생성된 PNG 경로 리스트
    """
    setup_korean_font()
    date_label = "발행일" if stats.get("date_field") == "published" else "수집일"

    # 차트마다 모집단이 다르다. 수집·정제 현황은 전체 뉴스를 세지만,
    # 키워드는 AI가 뽑는 값이라 요약이 끝난 기사에만 존재한다.
    # 차트를 따로 떼어 봐도 알 수 있도록 기준을 그림 안에 적어 둔다.
    all_note = f"정제 완료 {stats['total']}건 기준"
    ai_note = f"AI 요약 완료 {stats['summarized']}건 기준"

    paths = [
        chart_category_counts(
            stats["category_counts"],
            os.path.join(out_dir, "category_counts.png"), all_note),
        chart_daily_trend(
            stats["daily_counts"], os.path.join(out_dir, "daily_trend.png"),
            date_label, all_note),
        chart_top_keywords(
            stats["top_keywords"], os.path.join(out_dir, "top_keywords.png"),
            base_note=ai_note),
        chart_source_share(
            stats["source_counts"],
            os.path.join(out_dir, "source_share.png"), all_note),
    ]

    # 감성 차트는 감성 분석이 끝난 기사가 있을 때만 그린다
    sentiment_counts = stats.get("sentiment_counts") or {}
    if sentiment_counts:
        paths.append(chart_sentiment(
            sentiment_counts, os.path.join(out_dir, "sentiment.png"),
            f"감성 분석 완료 {stats.get('sentiment_total', 0)}건 기준"))

    return paths


if __name__ == "__main__":
    # 단독 실행: 저장된 데이터를 읽어 차트만 다시 그린다.
    from reporter import build_stats, load_all

    data = load_all()
    for path in render_all(build_stats(data)):
        print(path)
