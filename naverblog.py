"""네이버 블로그 자동 포스팅 모듈 (Playwright).

네이버 공식 '글쓰기 API' 는 2020년에 종료됐다. 그래서 이 모듈은 브라우저를
직접 몰아서(스마트에디터 ONE) 글을 올린다.

핵심 전제 두 가지:

1) 본인 PC에서, 눈에 보이는 창(headful)으로 돈다.
   네이버는 낯선 IP(예: GitHub Actions 같은 클라우드)나 봇스러운 접근을
   캡차·기기인증으로 강하게 막는다. 본인 PC에서 돌려야 막히지 않는다.

2) 로그인 세션을 폴더에 저장해 재사용한다(user_data_dir).
   최초 1회만 사람이 직접 로그인하면(캡차도 그때 사람이 푼다), 그 세션이
   폴더에 남아 이후 실행은 로그인 없이 바로 글쓰기로 들어간다.
   세션이 만료되면 다시 `python main.py blog --login` 한 번만 해 주면 된다.

인증 정보(.env, 선택):
    NAVER_ID          네이버 아이디  (자동 로그인 시도에 사용, 없어도 됨)
    NAVER_PW          네이버 비밀번호(자동 로그인 시도에 사용, 없어도 됨)
    NAVER_BLOG_ID     내 블로그 아이디(주소 blog.naver.com/<여기>). 없으면 config 나 인자로.

자동 로그인은 캡차가 뜨면 실패할 수 있다. 그래서 '세션 재사용'이 정공법이고,
자동 로그인은 세션이 없을 때의 보조 수단일 뿐이다.
"""

import os
import time

from dotenv import load_dotenv

load_dotenv()

# 로그인 세션을 저장할 브라우저 프로필 폴더. 여기에 쿠키가 남아 재사용된다.
DEFAULT_PROFILE_DIR = os.path.join(".naver_profile")
# 실패했을 때 화면을 캡처해 둘 폴더. 셀렉터가 바뀌었을 때 원인 파악용.
DEBUG_DIR = os.path.join("output", "blog_debug")

LOGIN_URL = "https://nid.naver.com/nidlogin.login"
# ?Redirect=Write 를 붙이면 로그인 상태에서 곧장 글쓰기(스마트에디터)로 들어간다.
WRITE_URL_TMPL = "https://blog.naver.com/{blog_id}?Redirect=Write"


def _screenshot(page, name: str) -> str:
    """디버그용 스크린샷을 남기고 경로를 돌려준다."""
    os.makedirs(DEBUG_DIR, exist_ok=True)
    path = os.path.join(DEBUG_DIR, f"{name}_{int(time.time())}.png")
    try:
        page.screenshot(path=path, full_page=True)
    except Exception:
        return ""
    return path


def _paste(page, text: str) -> None:
    """클립보드를 거쳐 붙여넣는다.

    네이버 로그인은 키 입력(type)을 봇으로 잘 잡아내므로, 아이디·비번은
    클립보드 복사 후 Ctrl+V 로 넣는 편이 안전하다. 본문에도 같은 방식을 쓴다.
    """
    import pyperclip
    pyperclip.copy(text)
    page.keyboard.press("Control+V")


def _get_editor_frame(page, timeout_ms: int = 20000):
    """스마트에디터 ONE 은 name="mainFrame" iframe 안에서 돈다. 그 프레임을 잡는다."""
    page.wait_for_selector("iframe#mainFrame", timeout=timeout_ms)
    frame = page.frame(name="mainFrame")
    if frame is None:
        raise RuntimeError("에디터 프레임(mainFrame)을 찾지 못했습니다.")
    return frame


def _dismiss_popups(frame) -> None:
    """글쓰기 진입 직후 뜨는 팝업들을 닫는다.

    - '작성 중이던 글이 있습니다' (임시저장 불러오기): [취소] 를 눌러 새 글로 시작.
    - 도움말/공지 레이어: 닫기 버튼이 있으면 닫는다.
    이 팝업들을 안 닫으면 제목/본문 클릭이 팝업에 가로막힌다.
    """
    for label in ("취소", "닫기"):
        try:
            btn = frame.get_by_role("button", name=label)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click(timeout=2000)
                frame.page.wait_for_timeout(500)
        except Exception:
            pass
    # 임시저장 팝업 전용 셀렉터(버전에 따라 다름) 보조 처리
    for sel in (".se-popup-button-cancel", "button.se-popup-button-cancel"):
        try:
            el = frame.locator(sel)
            if el.count() > 0 and el.first.is_visible():
                el.first.click(timeout=2000)
                frame.page.wait_for_timeout(300)
        except Exception:
            pass


def _write_title(frame, title: str) -> None:
    """제목 영역을 클릭하고 제목을 입력한다."""
    candidates = [
        ".se-section-documentTitle .se-placeholder",
        ".se-section-documentTitle",
        ".se-documentTitle",
        "span.se-placeholder",  # 최후: 첫 placeholder 가 제목인 경우
    ]
    for sel in candidates:
        try:
            el = frame.locator(sel).first
            if el.count() > 0 and el.is_visible():
                el.click(timeout=3000)
                frame.page.keyboard.type(title, delay=20)
                return
        except Exception:
            continue
    raise RuntimeError("제목 입력 영역을 찾지 못했습니다.")


def _write_body(frame, body_text: str) -> None:
    """본문 영역을 클릭하고 본문을 붙여넣는다.

    본문에는 기사 URL 이 그대로 들어 있는데, 스마트에디터가 붙여넣은 URL 을
    자동으로 클릭 가능한 링크로 바꿔 준다. 그래서 평문으로 넣어도 링크가 산다.
    """
    candidates = [
        ".se-section-text .se-text-paragraph",
        ".se-component.se-text",
        ".se-section-documentContent",
        "div.se-text-paragraph",
    ]
    clicked = False
    for sel in candidates:
        try:
            el = frame.locator(sel).first
            if el.count() > 0 and el.is_visible():
                el.click(timeout=3000)
                clicked = True
                break
        except Exception:
            continue
    if not clicked:
        # 제목 입력 후 Tab/Enter 로 본문으로 내려가는 경우
        frame.page.keyboard.press("Enter")
    _paste(frame.page, body_text)


def _publish(frame) -> None:
    """발행 버튼을 눌러 글을 게시한다.

    두 단계다: (1) 우상단 '발행' → 발행 옵션 레이어가 뜬다.
              (2) 레이어 안의 '발행' 확정 버튼.
    스마트에디터는 클래스명이 해시로 자주 바뀌므로 텍스트/역할 기반으로 찾는다.
    """
    # (1) 발행 레이어 열기
    opened = False
    for sel in ("button:has-text('발행')", "[data-click-area='tpb.publish']",
                ".publish_btn__m9KHH"):
        try:
            btn = frame.locator(sel).first
            if btn.count() > 0 and btn.is_visible():
                btn.click(timeout=3000)
                opened = True
                break
        except Exception:
            continue
    if not opened:
        raise RuntimeError("발행 버튼을 찾지 못했습니다.")

    frame.page.wait_for_timeout(1000)

    # (2) 레이어 안의 발행 확정 버튼
    for sel in ("[data-testid='seOnePublishBtn']",
                ".layer_btn_area button:has-text('발행')",
                ".btn_area button:has-text('발행')",
                "button.confirm_btn__WEaBq",
                "button:has-text('발행')"):
        try:
            btn = frame.locator(sel).last
            if btn.count() > 0 and btn.is_visible():
                btn.click(timeout=3000)
                return
        except Exception:
            continue
    raise RuntimeError("발행 확정 버튼을 찾지 못했습니다.")


def _try_auto_login(page) -> bool:
    """.env 의 NAVER_ID/PW 로 자동 로그인을 시도한다. 캡차가 뜨면 실패할 수 있다."""
    nid = os.getenv("NAVER_ID")
    npw = os.getenv("NAVER_PW")
    if not nid or not npw:
        return False
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        page.click("#id")
        _paste(page, nid)
        page.click("#pw")
        _paste(page, npw)
        page.click("#log\\.login")
        page.wait_for_timeout(3000)
        # 로그인 성공하면 nid.naver.com 을 벗어난다
        return "nidlogin" not in page.url
    except Exception:
        return False


def login(blog_id: str = None, user_data_dir: str = DEFAULT_PROFILE_DIR) -> None:
    """최초 1회 수동 로그인용. 창을 띄우고 사람이 직접 로그인하도록 기다린다.

    로그인(및 캡차)을 사람이 끝내면 세션이 user_data_dir 에 저장되어,
    이후 post() 는 로그인 없이 바로 글을 쓸 수 있다.
    """
    from playwright.sync_api import sync_playwright

    blog_id = blog_id or os.getenv("NAVER_BLOG_ID") or ""
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir, headless=False)
        page = context.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        print("\n[안내] 열린 창에서 네이버에 직접 로그인하세요. "
              "(캡차가 나오면 직접 풀어 주세요)")
        print("      로그인 후 네이버 메인/블로그로 넘어가면 자동으로 세션을 저장하고 닫습니다.")
        # 로그인 페이지를 벗어날 때까지(=로그인 완료) 최대 3분 대기
        for _ in range(180):
            if "nidlogin" not in page.url and "nid.naver.com" not in page.url:
                break
            time.sleep(1)
        page.wait_for_timeout(1500)
        context.close()
        print("[완료] 로그인 세션을 저장했습니다:", user_data_dir)


def post(title: str, body_text: str, blog_id: str = None,
         headless: bool = False, user_data_dir: str = DEFAULT_PROFILE_DIR) -> dict:
    """네이버 블로그에 글 하나를 발행한다.

    성공하면 {"posted": True}, 실패하면 {"posted": False, "error": ...} 를 돌려준다.
    """
    from playwright.sync_api import sync_playwright

    blog_id = blog_id or os.getenv("NAVER_BLOG_ID")
    if not blog_id:
        return {"posted": False,
                "error": "블로그 아이디가 없습니다. config.json 의 blog.blog_id "
                         "또는 .env 의 NAVER_BLOG_ID 를 설정하세요."}

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir, headless=headless)
        page = context.new_page()
        try:
            page.goto(WRITE_URL_TMPL.format(blog_id=blog_id),
                      wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)

            # 로그인 세션이 없으면 로그인 화면으로 튕긴다. 자동 로그인 한번 시도.
            if "nid.naver.com" in page.url or "nidlogin" in page.url:
                if not _try_auto_login(page):
                    _screenshot(page, "login_required")
                    return {"posted": False,
                            "error": "로그인 세션이 없습니다. `python main.py blog --login` 을 "
                                     "한 번 실행해 직접 로그인해 주세요."}
                # 로그인 후 다시 글쓰기로 진입
                page.goto(WRITE_URL_TMPL.format(blog_id=blog_id),
                          wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)

            frame = _get_editor_frame(page)
            frame.page.wait_for_timeout(1500)
            _dismiss_popups(frame)
            _write_title(frame, title)
            frame.page.wait_for_timeout(500)
            _write_body(frame, body_text)
            frame.page.wait_for_timeout(1000)
            _publish(frame)
            # 발행 처리 시간을 준다
            page.wait_for_timeout(4000)
            return {"posted": True, "blog_id": blog_id}
        except Exception as error:
            shot = _screenshot(page, "post_failed")
            return {"posted": False, "error": str(error), "screenshot": shot}
        finally:
            context.close()
