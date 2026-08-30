<#
.SYNOPSIS
  Builds the Android APK on this machine.

.DESCRIPTION
  A bare `gradle assembleDebug` fails here with "Unable to establish loopback
  connection". Java NIO builds its selector on an AF_UNIX socket pair created
  inside the directory named by the TEMP environment variable, and this
  profile's Temp directory cannot host one: bind succeeds, connect returns
  "Invalid argument", and the leftover .sock file cannot even be deleted.
  Every other directory tried works - including ones with spaces and ones of
  similar depth - so it is that directory specifically, not path length,
  spaces, or the 8.3 short name.

  The JVM's -Djava.io.tmpdir does NOT fix it, because Windows resolves the
  AF_UNIX path natively from the environment. TEMP/TMP must therefore be
  overridden before Gradle starts, which is all this script does.

.EXAMPLE
  .\devtools\build-apk.ps1
  .\devtools\build-apk.ps1 -Task lintDebug
#>
param(
    [string]$Task     = "assembleDebug",
    [string]$Jdk      = "C:\Program Files\Eclipse Adoptium\jdk-21.0.12.101-hotspot",
    [string]$Sdk      = "D:\Android\Sdk",
    [string]$GradleBin= "D:\Android\gradle\gradle-8.11.1\bin\gradle.bat",
    [string]$BuildTmp = "C:\gtmp"
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force $BuildTmp | Out-Null

$env:JAVA_HOME   = $Jdk
$env:ANDROID_HOME= $Sdk
$env:TEMP        = $BuildTmp
$env:TMP         = $BuildTmp

$appDir = Join-Path (Split-Path $PSScriptRoot -Parent) "app"
Push-Location $appDir
try {
    Write-Host "JAVA_HOME = $env:JAVA_HOME"
    Write-Host "TEMP      = $env:TEMP   (override; the default profile Temp breaks AF_UNIX)"
    Write-Host "task      = $Task`n"

    & $GradleBin $Task --console=plain
    if ($LASTEXITCODE -ne 0) { throw "gradle $Task failed with exit code $LASTEXITCODE" }

    $apk = Get-ChildItem -Recurse -Filter *.apk -ErrorAction SilentlyContinue |
           Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($apk) {
        Write-Host ""
        Write-Host ("APK: " + $apk.FullName) -ForegroundColor Green
        Write-Host ("     " + [math]::Round($apk.Length / 1MB, 1) + " MB")
    }
}
finally { Pop-Location }
