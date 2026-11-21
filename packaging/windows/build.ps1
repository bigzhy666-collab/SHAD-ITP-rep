param([switch]$SkipFrontend)
$ErrorActionPreference = 'Stop'
$projectPath = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location $projectPath
try {
    $pythonPath = Join-Path $projectPath '.venv-backend/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先准备后端环境。' }
    if (-not $SkipFrontend) {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' }
    }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $outputPath = Join-Path $projectPath "release/windows/$stamp"
    $workPath = Join-Path $projectPath "build/windows/$stamp"
    New-Item -ItemType Directory -Path $outputPath,$workPath | Out-Null
    & $pythonPath -m PyInstaller --noconfirm --name SHAD --onedir --console --icon (Join-Path $projectPath 'desktop/icon.ico') `
        --distpath $outputPath --workpath $workPath --specpath $workPath `
        --paths $projectPath --paths (Join-Path $projectPath 'ml') `
        --hidden-import src.inference --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto `
        --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.lifespan.on `
        --collect-data tzdata --collect-data sklearn --collect-submodules scipy._external `
        --add-data "${projectPath}/ml/src;ml/src" `
        --add-data "${projectPath}/frontend/dist;dist" --add-data "${projectPath}/ml/models/M1_s7.pkl;ml/models" `
        packaging/windows/entry.py
    if ($LASTEXITCODE -ne 0) { throw '打包失败。' }
    $packagePath = Join-Path $outputPath 'SHAD'
    Copy-Item -LiteralPath 'packaging/windows/使用说明.txt' -Destination $packagePath
    New-Item -ItemType Directory -Path (Join-Path $packagePath 'examples') | Out-Null
    Copy-Item -LiteralPath 'backend/config/registry.example.json' -Destination (Join-Path $packagePath 'examples')
    foreach ($entry in @(@('启动SHAD','start'),@('停止SHAD','stop'),@('查看状态','status'),@('备份数据','backup'))) {
        $content = "@echo off`r`nchcp 65001 >nul`r`ncd /d `"%~dp0`"`r`nSHAD.exe $($entry[1]) %*`r`npause`r`n"
        [IO.File]::WriteAllText((Join-Path $packagePath ($entry[0]+'.cmd')), $content, [Text.UTF8Encoding]::new($false))
    }
    Write-Output "已生成：$packagePath"
} finally { Pop-Location }
