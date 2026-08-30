<#
.SYNOPSIS
  Repairs the "Unable to establish loopback connection" failure that stops Gradle
  from running on this machine.

.DESCRIPTION
  Java NIO builds its selector on an internal socket pair. On this machine that
  creation fails intermittently, which breaks Gradle's daemon and therefore every
  Android build. The cause is a kernel-mode filter driver, so no JVM flag reaches
  it - it has to be fixed at the OS level.

  Steps run cheapest-and-most-reversible first, and the script re-tests after each
  one and STOPS as soon as Java works. So the McAfee removal only happens if the
  Defender exclusions did not already fix it.

  Everything before the uninstall is reversible; each step prints how to undo it.

.NOTES
  Must be run from an ELEVATED PowerShell (Run as administrator).
#>
[CmdletBinding()]
param(
    # Skip the confirmation prompt before removing McAfee Security Scan Plus.
    [switch]$YesToMcAfee
)

$ErrorActionPreference = 'Continue'

# --- preconditions ---------------------------------------------------------
$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "This script must run elevated." -ForegroundColor Red
    Write-Host "Right-click PowerShell -> Run as administrator, then re-run it."
    exit 1
}

$jdk = Get-ChildItem "C:\Program Files\Eclipse Adoptium" -Directory -ErrorAction SilentlyContinue |
       Sort-Object Name -Descending | Select-Object -First 1
if (-not $jdk) { Write-Host "No Temurin JDK found." -ForegroundColor Red; exit 1 }
$java = Join-Path $jdk.FullName "bin\java.exe"

# The probe is deliberately tiny: it calls only Selector.open(), which is the
# exact operation Gradle's daemon needs and the one that fails.
$probeDir = "C:\gtmp"
New-Item -ItemType Directory -Force $probeDir | Out-Null
$probe = Join-Path $probeDir "LoopProbe.java"
@'
import java.nio.channels.Selector;
public class LoopProbe {
  public static void main(String[] a) {
    int ok = 0;
    for (int i = 0; i < 5; i++) {
      try (Selector s = Selector.open()) { ok++; } catch (Throwable t) { }
    }
    System.out.println(ok == 5 ? "PASS" : ("FAIL " + ok + "/5"));
  }
}
'@ | Out-File -FilePath $probe -Encoding ascii

function Test-Loopback {
    # Repeated because the failure is intermittent - a single success proves nothing.
    $out = & $java $probe 2>&1 | Out-String
    return $out -match 'PASS'
}

function Report($step, $passed) {
    if ($passed) { Write-Host "  -> FIXED after: $step" -ForegroundColor Green }
    else         { Write-Host "  -> still failing" -ForegroundColor Yellow }
}

Write-Host "JDK under test: $($jdk.Name)" -ForegroundColor Cyan
Write-Host "Baseline check..." -NoNewline
if (Test-Loopback) {
    Write-Host " already working. Nothing to do." -ForegroundColor Green
    exit 0
}
Write-Host " failing, as expected." -ForegroundColor Yellow
Write-Host ""

# --- step 1: Defender exclusions ------------------------------------------
Write-Host "STEP 1  Defender exclusions for the Java and Android toolchain" -ForegroundColor Cyan
$paths = @(
    "C:\Program Files\Eclipse Adoptium",
    "D:\Android",
    "$env:USERPROFILE\.gradle",
    "D:\HOBBY_PROJECTS\NSE_ANALYSIS_APP"
) | Where-Object { Test-Path $_ }

foreach ($p in $paths) {
    Add-MpPreference -ExclusionPath $p -ErrorAction SilentlyContinue
    Write-Host "  excluded path    $p"
}
foreach ($proc in @("java.exe", "javaw.exe", "gradle.bat")) {
    Add-MpPreference -ExclusionProcess $proc -ErrorAction SilentlyContinue
    Write-Host "  excluded process $proc"
}
Write-Host "  (undo: Remove-MpPreference -ExclusionPath <path> / -ExclusionProcess <name>)"
Start-Sleep -Seconds 2
$passed = Test-Loopback
Report "Defender exclusions" $passed
if ($passed) { exit 0 }
Write-Host ""

# --- step 2: stop the McAfee scanner service (reversible) ------------------
Write-Host "STEP 2  Stop McAfee Security Scan service (reversible)" -ForegroundColor Cyan
$svc = Get-Service McComponentHostService -ErrorAction SilentlyContinue
if ($svc) {
    Stop-Service McComponentHostService -Force -ErrorAction SilentlyContinue
    Set-Service McComponentHostService -StartupType Disabled -ErrorAction SilentlyContinue
    Write-Host "  stopped and disabled McComponentHostService"
    Write-Host "  (undo: Set-Service McComponentHostService -StartupType Manual; Start-Service McComponentHostService)"
    Start-Sleep -Seconds 2
    $passed = Test-Loopback
    Report "stopping McAfee Security Scan" $passed
    if ($passed) { exit 0 }
} else {
    Write-Host "  service not present, skipping"
}
Write-Host ""

# --- step 3: uninstall McAfee Security Scan Plus --------------------------
Write-Host "STEP 3  Remove McAfee Security Scan Plus" -ForegroundColor Cyan
Write-Host "  This is the bundled scanner that ships with other installers, NOT a"
Write-Host "  managed endpoint agent, and not your antivirus - Windows Defender is."
Write-Host "  Unlike the steps above, this one is not reversible without reinstalling."
if (-not $YesToMcAfee) {
    $answer = Read-Host "  Remove it? [y/N]"
    if ($answer -notmatch '^[Yy]') {
        Write-Host "  skipped." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Loopback still broken. Build in GitHub Actions instead - see README." -ForegroundColor Yellow
        exit 2
    }
}
$un = "C:\Program Files (x86)\McAfee Security Scan\uninstall.exe"
if (Test-Path $un) {
    Start-Process $un -ArgumentList "/S" -Wait
    Write-Host "  uninstaller finished"
    Start-Sleep -Seconds 3
    $passed = Test-Loopback
    Report "removing McAfee Security Scan Plus" $passed
    if ($passed) { exit 0 }
} else {
    Write-Host "  uninstaller not found at $un"
}

Write-Host ""
Write-Host "Loopback is still broken after every step." -ForegroundColor Yellow
Write-Host "A reboot sometimes clears a filter driver that is still loaded in memory -"
Write-Host "try that first. If it persists, build in GitHub Actions instead; the"
Write-Host "workflow is already in .github/workflows/build-apk.yml."
exit 2
