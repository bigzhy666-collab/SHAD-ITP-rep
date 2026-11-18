param([string]$BackendDir)
$ErrorActionPreference='Stop'
$projectPath=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location $projectPath
try {
    if (-not $BackendDir) {
        & ./packaging/windows/build.ps1
        if ($LASTEXITCODE -ne 0) { throw '后端打包失败。' }
        $latestBuild=Get-ChildItem -LiteralPath release/windows -Directory | Sort-Object Name -Descending | Select-Object -First 1
        $BackendDir=Join-Path $latestBuild.FullName 'SHAD'
    }
    $backendPath=(Resolve-Path -LiteralPath $BackendDir).Path
    if (-not (Test-Path -LiteralPath (Join-Path $backendPath 'SHAD.exe'))) { throw '后端程序不存在。' }
    & node packaging/windows/build-desktop.mjs $backendPath
    if ($LASTEXITCODE -ne 0) { throw '桌面窗口打包失败。' }
} finally { Pop-Location }
