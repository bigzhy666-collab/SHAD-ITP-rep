# Windows 本地运行包

当前提供 Windows x64 便携包和安装向导，不依赖系统安装 Python 或 Node.js。服务仅监听本机，界面在本机浏览器打开。本机安装/升级/卸载已验证，代码签名和全新电脑的离线验收尚未完成。

## 使用

保留整个 `SHAD` 文件夹，双击 `启动SHAD.cmd`。关闭浏览器后服务仍运行，需要双击 `停止SHAD.cmd`。`查看状态.cmd` 查询本程序管理的实例，`备份数据.cmd` 在停止服务后备份。

默认业务数据位于 `%LOCALAPPDATA%\SHAD\data`，程序目录与数据分开。已有工作区用户应明确指定原数据目录，程序不会自动搬迁开发数据：

```powershell
.\SHAD.exe start --data-dir 'D:\SHAD 数据'
.\SHAD.exe status --data-dir 'D:\SHAD 数据'
.\SHAD.exe stop --data-dir 'D:\SHAD 数据'
.\SHAD.exe backup --data-dir 'D:\SHAD 数据' --output 'D:\备份\业务.shad-backup.zip'
.\SHAD.exe restore --archive 'D:\备份\业务.shad-backup.zip' --data-dir 'D:\恢复后的数据'
```

恢复目标必须是不存在的新目录。更新前停止并备份，将新包解压到新程序目录，继续使用原数据目录。不要用旧程序打开新版数据库；当前 schema 为 4。

## 模型与数据

模型登记、CSV 导入、检测、报告备注/归档/版本与 Word/PDF 沿用现有业务。包内 `M1_s7.pkl` 是仓库历史示例，只用于软件通路验证，默认不绑定站点。现场使用需管理员登记适用本站的模型及版本，不能将历史示例的结果视为本站有效结论。

`examples/registry.example.json` 可通过启动参数 `--registry` 显式启用，仅供合成数据验收。外部可信模型目录通过 `--model-dir` 指定，启动、备份、恢复应使用同一目录；业务备份不打包模型文件，需另外保留对应模型。具体原因及解决方案的 AI 诊断已取消。

## 开发者构建

在仓库根目录准备前后端环境及打包工具：

```powershell
npm ci
python -m venv .venv-backend
.\.venv-backend\Scripts\python.exe -m pip install -r backend/requirements-lock.txt
.\.venv-backend\Scripts\python.exe -m pip install -r packaging/windows/requirements-build.txt
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/windows/build.ps1
```

脚本构建前端，将前端静态文件、后端、模型适配代码、示例模型及 Python 运行时打成同一文件夹。每次输出到独立的 `release/windows/时间戳/SHAD`，中间文件写入 `build/windows/时间戳`，均不提交 Git。仅在前端构建已为当前版本时使用 `-SkipFrontend`。

将**整个 SHAD 文件夹**压缩后分发，不单独分发 EXE。构建机器需联网准备依赖；运行包不依赖在线 CDN。

## 验收

```powershell
.\.venv-backend\Scripts\python.exe -m pytest backend/tests -q
.\.venv-backend\Scripts\python.exe -m backend.tests.desktop_http_smoke --exe 'release/windows/时间戳/SHAD/SHAD.exe' --out verification/windows-portable/frozen-backup-restore.json
```

第二项使用实际打包程序、隔离数据目录、真实 TCP 与示例模型，覆盖启动、停止、CSV 检测、报告、备份和恢复。子程序环境移除 Python/Node 查找路径。它仍是本机构建环境下的验收，不能替代全新 Windows 电脑离线安装测试。记录见 [运行包验收](../verification/windows-portable/验收记录.md)。

## 安装向导构建

先重新构建本轮便携包（含安装保护），再用官方 Inno Setup 7.1.1 x64 编译。不要使用旧便携包制作安装程序，旧 EXE 没有运行中安装保护。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/windows/build-installer.ps1 -PackageDir 'release/windows/时间戳/SHAD' -Compiler 'Inno Setup 7/ISCC.exe'
```

安装到当前用户 Programs/SHAD，默认不要求管理员权限；支持可选桌面入口及开始菜单启动/停止/状态/备份/卸载。AppMutex 在程序、后台服务或维护操作存在时阻止更新卸载；不强制结束任务。卸载仅移除安装文件，保留 AppData 下业务数据与外部备份。不要把业务数据存放在程序安装目录。

官方依据：[AppMutex](https://jrsoftware.org/ishelp/topic_setup_appmutex.htm)、[关闭应用行为](https://jrsoftware.org/ishelp/topic_setup_closeapplications.htm)。

本机安装生命周期可通过 `packaging/windows/test-installer.py --setup 安装包路径` 验证；脚本发现已有 SHAD 安装记录会拒绝覆盖。请仅用于隔离测试环境。全新机器步骤见 [离线验收](全新Windows离线验收.md)。
