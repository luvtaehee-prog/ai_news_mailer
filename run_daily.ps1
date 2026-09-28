# Daily AI news pipeline (local runner)
#
# Runs on THIS PC instead of GitHub Actions. Naver blog posting needs a trusted
# IP + a saved login session, so it must run locally, not in the cloud.
#
# Flow: fetch(google/naver/govuk) -> clean -> summarize -> analyze -> report -> blog
# (Email sending is no longer automated. Run `python main.py mail` manually if needed.)
#
# IMPORTANT (Windows Task Scheduler notes, learned the hard way):
#   * This file is ASCII-only. PowerShell 5.1 reads .ps1 as the ANSI code page
#     unless it has a UTF-8 BOM; mixing Korean/emoji made steps mis-parse.
#   * Do NOT set `$ErrorActionPreference = "Stop"`. Under Task Scheduler (no
#     console) that combined with `Start-Process` force-kills PowerShell
#     (exit 0xC000013A) the moment Python runs. The default (Continue) is fine;
#     we decide success/failure from each step's exit code + try/catch instead.
#   * Progress is written to the log FILE only (no Write-Host).
#   Korean text from the Python steps is still captured to the log as UTF-8.
#
# Manual run:
#   powershell -ExecutionPolicy Bypass -File run_daily.ps1
#   powershell -ExecutionPolicy Bypass -File run_daily.ps1 -Date 2026-09-27
#
# See README ("Windows Task Scheduler") for scheduling.

param(
    [string]$Date = ""   # empty = yesterday (KST). Local PC is already KST.
)

# Move to the script's own folder (= repo root). Relative paths (.naver_profile,
# output, data) resolve from here, so this is required.
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

# Log file (this run).
$LogDir = Join-Path $RepoRoot "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir ("run_daily_{0}.log" -f (Get-Date -Format "yyyyMMdd"))

function Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    Add-Content -Path $LogFile -Value $line -Encoding utf8
}

# Target date: default to yesterday.
if ([string]::IsNullOrWhiteSpace($Date)) {
    $Date = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")
}
Log "Target date (KST): $Date"

# Python executable. Change here if you use a virtualenv.
$Py = "python"

# Force UTF-8 for Python I/O so Korean logs don't break under the scheduler.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Run($label, $arguments) {
    Log ">> $label"
    # Run Python via Start-Process; judge success by exit code only. Python
    # output (incl. Korean logs) goes to temp files, then into the log file.
    $outFile = [System.IO.Path]::GetTempFileName()
    $errFile = [System.IO.Path]::GetTempFileName()
    $p = Start-Process -FilePath $Py -ArgumentList $arguments -NoNewWindow -Wait `
         -PassThru -RedirectStandardOutput $outFile -RedirectStandardError $errFile
    Get-Content -Path $outFile, $errFile -Encoding utf8 -ErrorAction SilentlyContinue |
        ForEach-Object { Add-Content -Path $LogFile -Value $_ -Encoding utf8 }
    Remove-Item $outFile, $errFile -ErrorAction SilentlyContinue
    if ($p.ExitCode -ne 0) {
        Log "FAIL: $label (exit $($p.ExitCode))"
        throw "$label failed"
    }
}

try {
    # 1) Collect
    Run "fetch google" @("main.py","fetch","--source","google","--limit","40","--date",$Date)
    # NAVER/GOV.UK may fail (no key / blocked); don't let that stop the pipeline.
    try { Run "fetch naver" @("main.py","fetch","--source","naver","--limit","40","--date",$Date) } catch { Log "skip naver: $_" }
    try { Run "fetch govuk" @("main.py","fetch","--source","govuk","--limit","20","--date",$Date) } catch { Log "skip govuk: $_" }

    # 2) Clean
    Run "clean" @("main.py","clean","--policy","upsert","--date",$Date)

    # 3) AI summarize/analyze (skip on missing key or failure; report still goes out)
    try { Run "summarize" @("main.py","summarize","--date",$Date) } catch { Log "skip summarize: $_" }
    try { Run "analyze" @("main.py","analyze","--date-from",$Date,"--date-to",$Date) } catch { Log "skip analyze: $_" }

    # 4) Report
    Run "report" @("main.py","report","--format","both","--date-from",$Date,"--date-to",$Date)

    # 5) Naver blog post. Runs headful (needs a saved login session).
    #    Do `python main.py blog --login` once first if there is no session.
    Run "blog post" @("main.py","blog","--require-today")

    Log "DONE"
}
catch {
    Log "ABORTED: $_"
    exit 1
}
