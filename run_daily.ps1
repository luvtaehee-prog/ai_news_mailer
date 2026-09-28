# 일일 AI 뉴스 파이프라인 (로컬 실행판)
#
# GitHub Actions 대신 '내 PC'에서 매일 도는 스크립트다.
# 네이버 블로그 발행은 본인 PC(신뢰된 IP) + 저장된 로그인 세션이 있어야 하므로,
# 클라우드가 아니라 여기서 돌린다. 메일 발송도 그대로 함께 나간다.
#
# 흐름: fetch(google/naver/govuk) -> clean -> summarize -> analyze -> report -> mail -> blog
#
# 수동 실행:
#   powershell -ExecutionPolicy Bypass -File run_daily.ps1
#   powershell -ExecutionPolicy Bypass -File run_daily.ps1 -Date 2026-09-27   # 특정일
#
# Windows 작업 스케줄러 등록은 README 의 '매일 자동 실행(작업 스케줄러)' 참고.

param(
    [string]$Date = ""   # 비우면 어제(KST). 로컬 PC가 한국시간이면 그냥 어제.
)

$ErrorActionPreference = "Stop"

# 스크립트가 있는 폴더(=저장소 루트)로 이동. 상대경로(.naver_profile 등)가 여기 기준이라 필수.
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

# 실행 로그를 파일로도 남긴다.
$LogDir = Join-Path $RepoRoot "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir ("run_daily_{0}.log" -f (Get-Date -Format "yyyyMMdd"))

function Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding utf8
}

# 기준일 결정: 인자가 없으면 어제.
if ([string]::IsNullOrWhiteSpace($Date)) {
    $Date = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")
}
Log "기준일(KST): $Date"

# python 실행 파일. 가상환경을 쓰면 여기서 경로를 바꾸면 된다.
$Py = "python"

function Run($label, $arguments) {
    Log "▶ $label"
    & $Py $arguments 2>&1 | ForEach-Object { Add-Content -Path $LogFile -Value $_ -Encoding utf8; Write-Host $_ }
    if ($LASTEXITCODE -ne 0) {
        Log "✖ 실패: $label (exit $LASTEXITCODE)"
        throw "$label 실패"
    }
}

try {
    # 1) 수집
    Run "Google 수집"  @("main.py","fetch","--source","google","--limit","40","--date",$Date)
    # NAVER/GOV.UK 는 키가 없거나 접속이 막혀도 전체를 세우면 안 되므로 실패를 흘려보낸다.
    try { Run "NAVER 수집" @("main.py","fetch","--source","naver","--limit","40","--date",$Date) } catch { Log "△ NAVER 수집 건너뜀: $_" }
    try { Run "GOV.UK 수집" @("main.py","fetch","--source","govuk","--limit","20","--date",$Date) } catch { Log "△ GOV.UK 수집 건너뜀: $_" }

    # 2) 정제
    Run "정제" @("main.py","clean","--policy","upsert","--date",$Date)

    # 3) AI 요약/분석 (키 없거나 실패해도 리포트는 나가야 하므로 흘려보낸다)
    try { Run "AI 요약·감성분석" @("main.py","summarize","--date",$Date) } catch { Log "△ 요약 건너뜀: $_" }
    try { Run "AI 트렌드 분석" @("main.py","analyze","--date-from",$Date,"--date-to",$Date) } catch { Log "△ 분석 건너뜀: $_" }

    # 4) 리포트
    Run "리포트·차트 생성" @("main.py","report","--format","both","--date-from",$Date,"--date-to",$Date)

    # 5) 메일 발송 (기존 유지). --require-today: 리포트가 오늘 것이 아니면 안 보냄.
    try { Run "메일 발송" @("main.py","mail","--attach-charts","--require-today") } catch { Log "△ 메일 발송 실패: $_" }

    # 6) 네이버 블로그 발행. 창을 띄워 진행(헤드풀)해야 안정적이다.
    #    세션이 없으면 실패하니, 최초 1회 `python main.py blog --login` 을 먼저 해 둘 것.
    Run "네이버 블로그 발행" @("main.py","blog","--require-today")

    Log "✔ 완료"
}
catch {
    Log "✖ 파이프라인 중단: $_"
    exit 1
}
