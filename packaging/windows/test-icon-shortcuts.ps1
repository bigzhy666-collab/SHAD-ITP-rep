param(
    [Parameter(Mandatory=$true)][string]$PackageDir,
    [Parameter(Mandatory=$true)][string]$Compiler
)
$ErrorActionPreference='Stop'
$projectPath=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$packagePath=(Resolve-Path -LiteralPath $PackageDir).Path
$compilerPath=(Resolve-Path -LiteralPath $Compiler).Path
$testKey='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{DB55E893-59E0-4219-92CE-E5D31CE0741B}_is1'
if (Test-Path -LiteralPath $testKey) { throw '已有图标验收安装记录，停止以免覆盖。' }
$work=Join-Path $projectPath ('build/icon-installer-checks/'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
$install=Join-Path $work '安装目录 空格'
New-Item -ItemType Directory -Path $install -Force | Out-Null
# Confine every test shortcut to the test directory. The production installer
# keeps its actual desktop/Start menu paths and its real running-app protection.
$source=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'setup.iss') -Raw
$source=$source.Replace('Local\SHAD.LocalService','Local\SHAD.IconAcceptance')
$source=$source.Replace('Local\SHAD.Setup','Local\SHAD.IconAcceptanceSetup')
$source=$source.Replace('{autodesktop}', '{app}').Replace('{group}', '{app}\菜单')
$source=$source.Replace('..\..\desktop\icon.ico',(Join-Path $projectPath 'desktop/icon.ico'))
$source=$source.Replace('InfoBeforeFile=installer-info.txt','InfoBeforeFile='+(Join-Path $PSScriptRoot 'installer-info.txt'))
$script=Join-Path $work 'icon-check.iss'
[IO.File]::WriteAllText($script,$source,[Text.UTF8Encoding]::new($false))
& $compilerPath /Qp "/DPackageDir=$packagePath" "/DOutputDir=$work" '/DAppIdValue={{DB55E893-59E0-4219-92CE-E5D31CE0741B}' $script
if ($LASTEXITCODE -ne 0) { throw '图标验收安装包编译失败。' }
$shell=New-Object -ComObject WScript.Shell
$shortcutPath=Join-Path $install 'SHAD.lnk'
$legacy=$shell.CreateShortcut($shortcutPath)
$legacy.TargetPath=Join-Path $env:WINDIR 'System32/cmd.exe'
$legacy.Save()
$setup=Join-Path $work 'SHAD-Setup-0.7.3-x64.exe'
$uninstaller=Join-Path $install 'unins000.exe'
try {
    # No /TASKS override: verify that the corrected shortcut is selected by default.
    & $setup /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- "/DIR=$install" "/LOG=$work/setup.log" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw '图标验收安装失败。' }
    $checks=@()
    foreach ($file in @($shortcutPath,(Join-Path $install '菜单/启动 SHAD.lnk'))) {
        $link=$shell.CreateShortcut($file)
        $target=Join-Path $install 'SHAD.exe'
        $icon=Join-Path $install 'resources/shad-0.7.3.ico'
        if ($link.TargetPath -ne $target) { throw '快捷方式未指向桌面程序。' }
        if ($link.IconLocation -ne "$icon,0") { throw "快捷方式未显式使用新版图标：$($link.IconLocation)" }
        if (-not (Test-Path -LiteralPath $icon)) { throw '快捷方式图标文件缺失。' }
        $folder=(New-Object -ComObject Shell.Application).Namespace((Split-Path $file))
        $appId=$folder.ParseName((Split-Path $file -Leaf)).ExtendedProperty('System.AppUserModel.ID')
        if ($appId -ne 'SHAD.Desktop') { throw '快捷方式与窗口的任务栏分组标识不同。' }
        $checks+=@{shortcut=(Split-Path $file -Leaf);target='SHAD.exe';icon='resources/shad-0.7.3.ico,0';appId=$appId}
    }
    $out=Join-Path $projectPath 'verification/desktop-icon/shortcut-check.json'
    @{passed=$true;replacedLegacyShortcut=$true;defaultDesktopTask=$true;checks=$checks;scope='isolated icon installation; production install untouched'} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $out -Encoding utf8
    Write-Output 'Passed: default task replaces a legacy shortcut; desktop and Start menu links use the full-size icon and SHAD.Desktop ID.'
} finally {
    if (Test-Path -LiteralPath $uninstaller) {
        & $uninstaller /VERYSILENT /SUPPRESSMSGBOXES /NORESTART | Out-Null
        if ($LASTEXITCODE -ne 0) { throw '验收安装未能卸载，请检查临时安装记录。' }
    }
}
