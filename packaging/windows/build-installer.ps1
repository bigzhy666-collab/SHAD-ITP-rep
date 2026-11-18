param(
    [Parameter(Mandatory=$true)][string]$PackageDir,
    [Parameter(Mandatory=$true)][string]$Compiler
)
$ErrorActionPreference = 'Stop'
$packagePath = (Resolve-Path -LiteralPath $PackageDir).Path
$compilerPath = (Resolve-Path -LiteralPath $Compiler).Path
if (-not (Test-Path -LiteralPath (Join-Path $packagePath 'SHAD.exe'))) { throw 'PackageDir 必须指向本轮构建的 SHAD 文件夹。' }
if (-not (Test-Path -LiteralPath (Join-Path $packagePath 'resources/backend/SHAD.exe')) -or
    -not (Test-Path -LiteralPath (Join-Path $packagePath 'resources/app.asar'))) { throw '0.7.3 安装包必须使用独立桌面运行包，不能使用旧后端运行包。' }
$projectPath = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$desktopVersion = (Get-Content -LiteralPath (Join-Path $projectPath 'desktop/package.json') -Raw | ConvertFrom-Json).version
if (-not (Test-Path -LiteralPath (Join-Path $packagePath "resources/shad-$desktopVersion.ico"))) { throw '桌面包缺少当前版本的快捷方式图标，请重新构建桌面包。' }
$outputPath = Join-Path $projectPath ('release/installers/' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $outputPath | Out-Null
& $compilerPath "/DPackageDir=$packagePath" "/DOutputDir=$outputPath" (Join-Path $PSScriptRoot 'setup.iss')
if ($LASTEXITCODE -ne 0) { throw '安装包编译失败。' }
Write-Output "安装包已生成：$outputPath"
