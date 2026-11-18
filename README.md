> 2026-11-14 独立桌面版 0.7.0：使用 Electron 独立窗口，启动进入管网模型，不打开浏览器；采用用户提供的 SHAD 图标。关闭即退出，检测任务/未保存备注先提示，仅停止本软件启动的服务。已有数据目录和 schema 4 保持不变，后端接口版本仍为 0.6.0。详见 [独立桌面软件说明](docs/独立桌面软件说明.md)。

> 2026-11-14 当前范围（优先于下文历史规划）：默认首页为「管网模型」，侧栏顺序为管网模型、总览、管网管理、数据监测、检测报告。模型页面为本地示意街区与演示时序，未联动真实检测，不改变本机企业/管网/管段。具体原因和解决方案诊断继续取消。详见 [管网模型说明](docs/管网模型说明.md)。本轮已重新生成 Windows 安装包；全新 Windows 虚拟机验收仍暂缓。

> 2026-11-10 实施进度：本机企业/管网/管段新增、修改、停用与三级选择已接通，服务 0.6.0、schema 4。原因及方案诊断已取消；下一步为 Windows 安装包与发布验收。详细规则见 [组织接口](docs/本机组织管理接口.md)。

> 2026-11-09 范围修订（优先于下文历史规划）：取消具体原因与解决方案的 AI 诊断能力，删除原因推理、候选原因、置信度、解决建议及等待模型的交付要求。第四入口改为「检测报告」；保留异常检测、事件证据、历史、备注、归档、版本与 Word/PDF。旧接口字段和已保存快照仅作兼容，不启用原因能力。

# SHAD 智慧供热异常检测与辅助诊断平台

V3.9 四模块前端与本地后端实施中，已完成模型接口、M1 本地数据层、M2 真实后台检测和 M3 报告持久化，支持演示模式和本机服务。使用 Vue 3、TypeScript、Pinia、Vue Router 和 ECharts，沿用已确认的图标、浅色风格与原型；本机模式使用独立 API 客户端，不在接口失败时回退演示结果。后端使用 FastAPI 和 SQLite，只接入已训练模型，不提供训练功能。

## 启动

需要 Node.js 20.19+ 或 22.12+ 及 npm。已安装依赖时直接运行第二条命令。

```sh
npm install
npm run dev
```

浏览器打开终端显示的本机地址，通常是 http://127.0.0.1:5173 。开发服务默认仅监听本机；需要手机联调时可显式添加 `--host 0.0.0.0`，不作为正式软件运行方式。

```sh
npm run build
npm run preview
```

部署时将 `dist` 作为站点目录，并将前端路由回退至 `index.html`。界面沿用参考 HTML 的系统字体，无界面字体或 Tailwind CDN 运行依赖；颜色与字体变量位于 `src/theme.css`。PDF 使用 `public/fonts/NotoSansSC.ttf`（约 10.6 MB，OFL 许可证见同目录），首次导出需读取该字体；生产部署需保持资源可访问。

已准备好 Python 环境和 dist 后，可双击根目录的 `启动SHAD.cmd`、`查看SHAD状态.cmd`、`停止SHAD.cmd`、`备份SHAD.cmd`。启动脚本默认数据在 `%LOCALAPPDATA%\SHAD\data`；**继续使用此前项目数据时运行 `.\启动SHAD.cmd --data-dir backend/data`**，其他操作同样指定该目录。恢复始终生成新目录，不覆盖原数据。详见 [本地启动与备份](docs/本地软件启动与备份.md)；当前是开发工作区入口，Windows 安装包尚未交付。

## 四模块与主要操作

| 页面 | 地址 | 可操作内容 |
|---|---|---|
| 总览 | `/overview` | 指标及时间切换、图例、缩放、异常定位、拓扑节点联动、检测与报告快捷入口 |
| 管网管理 | `/networks` | 企业→管网→管段选择、组织维护、参数与历史数据、分页、CSV、带入检测条件 |
| 数据监测 | `/detections/:id?` | 参数分类、单/多参数监测、最新采样、时间趋势、异常定位、采样明细与CSV、底部页内检测/记录、送入AI诊断 |
| AI诊断 | `/diagnosis/:id?` | 单/多选异常事件、五阶段图文证据、具体原因与处理建议、历史记录、同页报告、备注、归档、版本及 Word/PDF |

顶栏对象路径后的切换图标进入管网管理。刷新按钮和 Ctrl+R 刷新数据并保留当前路由、页面筛选及已保存记录。移动端提供折叠导航、单参数图表选择和局部表格滚动。

## 演示验收路径

1. 在管网管理保留“北方热力有限责任公司 / 城北主力供热网 / 1号二次供热管段”，点击确认选择。
2. 使用 2026-11-03 00:00–08:00 的历史数据发起检测；可选择正常、异常或失败场景。
3. 检测完成后定位或回放异常，选择需要分析的异常并送入 AI。
4. 在 AI诊断查看阶段进度、时序和关联证据，完成后查看可能原因、解决建议与复核标准；返回检测保留事件选择。
5. 诊断完成后自动生成同页报告，填写并保存备注，下载 Word/PDF，确认归档。
6. 重新生成创建新版本；刷新页面检查任务、备注和归档仍存在。

“3号末端支路”演示无参数，“西区供热支线”演示无采样。检测和 AI 的失败场景提供重试入口。存储失败显示持续提示并支持重试；PDF 字体读取或生成失败显示错误并可重新导出。

## 数据与实现边界

正式软件按**本机运行**推进：本项目同时负责前端、本地后端与模型接入，只加载已训练模型。M0/M1/M2/M3 已完成：SQLite、CSV 导入、采样、真实后台检测、异常事件、报告快照/备注/历史/归档/版本均可使用，支持幂等、冲突核对及服务重启恢复。M5 第一批已补齐本地启动/停止、备份恢复；组织维护同步现已完成；具体原因及方案诊断已取消，后续推进 Windows 安装包。实施顺序见 [本地后端实施计划](docs/本地后端实施计划.md)，启动、登记及调用见 [模型接口说明](docs/模型接口说明.md)。前端业务契约继续采用 [本机接口约定](docs/本机接口约定.md)。

```powershell
python -m venv .venv-backend
.\.venv-backend\Scripts\python.exe -m pip install -r backend/requirements-lock.txt
.\.venv-backend\Scripts\python.exe -m backend
```

默认不自动绑定模型；集成测试可显式添加 `--registry backend/config/registry.example.json --data-dir backend/data/example-check`。`POST /api/model-inferences` 接收八核心及已声明的六个可选测点并返回真实逐点结果和确认区间，推理结果暂不持久化；dataImport/anomalyDetection/offlineDetection/reportPersistence 已开启；具体原因诊断保持关闭。完整模型调用见接口说明。数据导入及本机界面操作见 [本地数据接口说明](docs/本地数据接口说明.md)。

要直接查看真实数据管理页面，执行 `npm run build` 后运行 `.\.venv-backend\Scripts\python.exe -m backend --serve-frontend`，打开 `http://127.0.0.1:8765/networks`，在右上角选择“本机服务”。默认持久化目录 `backend/data`；`--data-dir` 可更换目录。先登记换热站、由管理员登记本站适用模型，再上传 UTF-8 CSV；从数据集查看采样并创建真实检测。默认不套用示例模型，缺少本站模型时检测按钮禁用。检测接口和操作见 [本地检测任务接口说明](docs/本地检测任务接口说明.md)。

右上角可切换“本机服务”：站点绑定、CSV 映射、模型/数据集选择、检测任务、分数曲线、事件定位及报告均通过独立本机页面处理。开发代理默认 `http://127.0.0.1:8765`，可复制 `.env.example` 为 `.env.local` 修改地址。后端未启动会明确提示，不显示虚构结果。原因诊断和报告存档依据后端 capabilities 开启；未启用存档时，仍可导出明确标识未存档的 Word/PDF 阶段报告。

以下为**演示模式**边界：

- 采样窗口为北京时间 2026-11-03 00:00 至 2026-11-04 00:00。检测按参数与固定异常区间返回可复现演示结果；残差系数被保存和展示，没有运行真实算法。
- AI 的模型名、权重及关联均为示例。缺少回水温度或流量时禁用散点关联并提示局限，不补造缺失参数。
- 不连接 SCADA、真实模型或设备，不执行调控、工单派发、登录授权、数字签名和认证存证。
- 数据保存在当前浏览器 `shad-workspace-v3` 中。关闭页面期间没有后台计算；重新打开根据保存状态恢复任务。清除站点数据后恢复初始案例，没有服务端备份。
- 历史任务固定来源对象，报告保存独立检测、分析与原因快照。归档锁定当前备注，新版本保留旧记录。
- Word 使用 `docx`、PDF 使用 `pdfmake`；共享报告文本快照，导出的完整曲线不受手机参数选择或页面缩放影响。
- 构建存在图表和 PDF 库的体积提示；PDF 库仅在导出时按需加载。

## 验证与交付

```sh
npm test
npm run test:local
npx playwright install chromium
npm run test:e2e -- --workers=2
npm run build
```

Playwright 自动启动本地预览，覆盖业务闭环、失败重试、来源与选择恢复、持久化、实际文件下载和七种宽度，截图生成至 `test-results`。验收记录见 [verification/验收记录.md](verification/验收记录.md)，稳定截图入口见 [verification/index.html](verification/index.html)，导出样本见 `verification/exports`。

- [PRD.md](PRD.md)：V3.9 功能、交互、状态及本地后端范围。
- [PRODUCT.md](PRODUCT.md)、[DESIGN.md](DESIGN.md)：产品与设计上下文。
- [stitch-export/index.html](stitch-export/index.html)：已修复的五页原型截图及 HTML 入口，各页保留原始 JSON 响应。
- `src/services/demo.ts`：演示数据与校验；真实服务从服务层接入，并将任务轮询改为后台状态。
- `src/stores/workspace.ts`：对象、任务、报告关联及有版本的本地存储。
- `src/services/export.ts`：Word/PDF 共享报告内容及导出实现。
- `src/services/local`、`src/stores/integration.ts`：本机接口类型、请求、来源校验、报告导出及模式连接状态。
- [本机接入验收与截图](verification/local-integration/验收记录.md)：此前前端契约测试与截图；这些浏览器测试使用拦截数据，不代表真实业务联调。本轮模型接口测试位于 `backend/tests`，实际模型对照使用合成输入。
- `backend/`：本机服务、可信注册表、标准输入/输出模型、推理适配器及测试；执行 `.\.venv-backend\Scripts\python.exe -m pytest backend/tests -q` 验证。
- [模型接口验收](verification/backend-m0/验收记录.md)：46 项后端测试、实际 TCP 推理及现有页面托管验证；不代表本站模型准确率或完整任务业务已验收。

旧地址 `/analysis/:id?` 与 `/reports/:id?` 自动兼容至 AI诊断。原浏览器历史保留；旧记录缺少过程字段时展示标明演示性质的证据摘要。新版验证见 `verification/ai-diagnosis/验收记录.md`。

本轮数据监测修改依据《SHAD「数据监测」模块 UI》。新增截图、验收记录见 `verification/data-monitoring`。侧栏与页面标题统一为数据监测；监测时间与检测表单独立，点击“使用当前监测范围与参数”带入。当前演示缺少供水压力，不生成该参数。数据质量问题与数值异常独立分类。

- [M1 数据层验收](verification/backend-m1/验收记录.md)：真实浏览器上传/采样、实际服务重启恢复、可选字段与质量门控、桌面及手机截图。`npm run test:backend` 使用隔离测试目录和真实后端，需先构建前端；此记录为 M1 历史阶段，当前 M3 状态见下。

- [M2 后台检测验收](verification/backend-m2/验收记录.md)：真实模型逐点一致、并发幂等、任务/事件落盘、重启恢复、实际前端闭环与临时报告下载。M1 记录为历史阶段；当前 test:backend 覆盖 M1/M2/M3，新增示例站仅存在于隔离的测试启动器，不能用于现场部署。

- [M3 报告持久化验收](verification/backend-m3/验收记录.md)：保存快照、备注冲突、归档锁定、幂等新版本、实际重启及 Word/PDF。API 见 [本地报告接口](docs/本地报告接口说明.md)。原因模型尚未交付，报告明确只记录检测证据。

- [M5 第一批验收](verification/backend-m5-startup/验收记录.md)：真实后台启动/重复打开/专用凭据停止、端口冲突、离线备份、中文路径恢复及恢复后检测/报告一致性。

- [Windows 便携运行包](docs/Windows运行包.md)：已打包前端、后端与模型运行时，无需系统 Python/Node；支持本机启动、停止、备份恢复。运行包验收见 [记录](verification/windows-portable/验收记录.md)。安装向导及全新电脑离线验收尚未完成。

- [Windows 安装向导验收](verification/windows-installer/验收记录.md)：保留当前前端，已完成实际安装、升级、运行中保护与卸载保留数据；全新 Windows 离线验收尚待在干净测试机上执行。
