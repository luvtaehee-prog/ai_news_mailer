"""저장소 모듈.

raw(원본) 읽기와 clean(정제본) 영구 저장을 담당한다.
clean 저장소는 JSONL 파일(url 을 자연키로 사용)이며,
중복 정책(skip / upsert)을 여기서 적용한다.
"""

import os
import json


def read_raw(raw_dir: str) -> list:
    """raw 디렉터리 안의 .jsonl / .json 파일을 모두 읽어 레코드 리스트로 반환한다.

    - JSONL(줄마다 객체)과 JSON 배열 두 형태를 모두 지원한다.
    """
    records = []
    if not os.path.isdir(raw_dir):
        return records

    for fn in sorted(os.listdir(raw_dir)):
        if not (fn.endswith(".jsonl") or fn.endswith(".json")):
            continue
        path = os.path.join(raw_dir, fn)
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
        if not text:
            continue
        # 1) 우선 JSONL(줄 단위)로 시도
        parsed_any = False
        line_records = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                line_records.append(json.loads(line))
                parsed_any = True
            except json.JSONDecodeError:
                parsed_any = False
                break
        if parsed_any:
            records.extend(line_records)
            continue
        # 2) 실패하면 JSON 배열로 시도
        try:
            data = json.loads(text)
            if isinstance(data, list):
                records.extend(data)
            elif isinstance(data, dict):
                records.append(data)
        except json.JSONDecodeError:
            # 깨진 파일은 건너뛴다 (호출부에서 로깅)
            continue
    return records


def load_clean(clean_path: str) -> dict:
    """기존 clean 저장소를 {url: record} 딕셔너리로 불러온다. 없으면 빈 dict."""
    items = {}
    if not os.path.exists(clean_path):
        return items
    with open(clean_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = rec.get("url")
            if key:
                items[key] = rec
    return items


def write_clean(clean_path: str, items: dict) -> None:
    """{url: record} 딕셔너리를 JSONL 로 저장한다."""
    os.makedirs(os.path.dirname(clean_path) or ".", exist_ok=True)
    with open(clean_path, "w", encoding="utf-8") as f:
        for rec in items.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _norm_title(rec: dict) -> str:
    """제목 기준 중복 판별용 정규화 키 (공백 제거 + 소문자)."""
    return "".join((rec.get("title") or "").split()).lower()


def apply_dedup(existing: dict, new_records: list, policy: str,
                dedup_by_title: bool = False):
    """중복 정책을 적용해 최종 저장 대상을 만든다.

    policy = "skip"   : 이미 있는 url 은 건드리지 않음
    policy = "upsert" : 이미 있는 url 은 새 내용으로 덮어씀
    dedup_by_title=True : url 이 달라도 제목이 같으면 중복으로 간주해 제외

    반환: (merged_dict, stats)
      stats = {"added","updated","skipped","batch_dup","title_dup"}
    """
    merged = dict(existing)  # 기존 저장본 복사
    stats = {"added": 0, "updated": 0, "skipped": 0,
             "batch_dup": 0, "title_dup": 0}
    seen_in_batch = set()
    # 제목 -> 현재 채택된 url (제목 중복 판별 및 '더 나은 복사본' 교체용)
    title_index = {}
    if dedup_by_title:
        for u, r in existing.items():
            title_index[_norm_title(r)] = u

    for rec in new_records:
        url = rec.get("url")
        if not url:
            continue
        if url in seen_in_batch:      # 이번 배치 안에서의 url 중복
            stats["batch_dup"] += 1
            continue
        seen_in_batch.add(url)

        if url in merged:             # 기존 저장소에 이미 존재 (url 기준)
            if policy == "upsert":
                merged[url] = rec
                stats["updated"] += 1
            else:                     # skip
                stats["skipped"] += 1
            continue

        # 신규 url 이지만 제목이 이미 있으면 중복 처리 (선택)
        ntitle = _norm_title(rec)
        if dedup_by_title and ntitle and ntitle in title_index:
            kept_url = title_index[ntitle]
            kept = merged.get(kept_url, {})
            # 내용이 더 풍부한(긴) 복사본을 남긴다
            if len(rec.get("content", "")) > len(kept.get("content", "")):
                merged.pop(kept_url, None)
                merged[url] = rec
                title_index[ntitle] = url
            stats["title_dup"] += 1
            continue

        merged[url] = rec
        stats["added"] += 1
        if dedup_by_title and ntitle:
            title_index[ntitle] = url

    return merged, stats
