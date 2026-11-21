<script setup lang="ts">
import {ref} from 'vue'
const sections = [
      {key:"一、总览",title:"总览：一眼看全局",blocks:[
        {h:"",p:"这是进软件后的第一屏，左边是导航，中间是三维管网，下面是记录。"},
        {h:"三维管网场景",p:"画的是示意街区（不是真实图纸），用来表示\"管网怎么走、换热站在哪\"。操作：按住左键拖动可旋转，滚轮缩放（上划放大、下划缩小），右键拖动平移，双击管网或换热站可选中。"},
        {h:"左上指标卡",p:"选中换热站后出现，显示该站最近一次导入数据的六个读数：室外温度、一次侧供水/回水、瞬时热功率、瞬时流量、二次侧供水。拖动底部进度条，读数会随时间变化。没选站或该站没导数据时显示\"无\"。"},
        {h:"右上图例与\"异常\"标签",p:"图例说明四种管线颜色与建筑/道路。出现\"● 异常\"标签，表示某个换热站最近一次数据的二次供水超过 80 ℃；没有导入数据的站不会被判异常。"},
        {h:"当前管段检测记录",p:"只显示当前管段的检测任务，换个管段记录就换一批。没有任何记录时这块是空的，不会显示占位文字。"},
        {h:"本机运行状态",p:"服务版本、当前管段、检测与报告能力是否可用。"},
        {h:"左侧\"受析管段\"卡片",p:"全局的\"当前工作对象\"（企业/管网/管段）。四个模块都围着它转，要改它请去\"管网管理\"。"},
        {h:"右上工具条",p:"运行模式（导入模式=真实本机数据；实时模式暂未接入）、连接状态、当前时间、刷新按钮（Ctrl/⌘+R）。"}
      ]},
      {key:"二、管网管理",title:"管网管理：把站点和数据接进来",blocks:[
        {h:"",p:"相当于在系统里登记\"我要分析哪个公司的哪条管线\"。这一步做一次，后面都能用。"},
        {h:"企业 / 供热管网 / 管段",p:"三个下拉按层级选，选完点\"确认选择\"才生效。生效后左侧\"受析管段\"会同步变。"},
        {h:"管段关联换热站",p:"把换热站挂到当前管段上；下拉里带编码（如 1#换热站 · ST-P01-S1），同名也能区分。必须先选换热站，才能导入该站数据、做检测。"},
        {h:"本站运行数据导入",p:"上传 CSV 文件：要求 30 分钟一个点、包含 8 个必需字段。系统会检查字段、时间轴、缺测，通过后进入下面的历史数据集；不通过会直接告诉你哪一项不合格。"},
        {h:"历史数据集",p:"列出这个站已导入的数据：名称、标准化行数、质量问题。出现\"需修正\"时，下面会写原因。"},
        {h:"组织维护",p:"新增/停用企业、管网、管段。编码唯一；停用不会删历史，但停用上级后，它下面的对象不能再建新检测。"}
      ]},
      {key:"三、数据监测",title:"数据监测：看曲线、跑检测",blocks:[
        {h:"",p:"这一页几乎不用点按钮：选好换热站，系统自己把剩下的做完。"},
        {h:"本站检测配置",p:"选换热站后自动完成四件事：选好该站的数据集 → 填好起止时间 → 读取采样 → 提交检测。中途会出现\"正在加载数据并运行检测…\"的提示（至少 0.5 秒），切换换热站会重新跑一遍。"},
        {h:"监测采样与趋势",p:"显示原始数据曲线。右上\"曲线参数\"可切换看哪个测点；红点是异常分数最高的 20 个时刻；滚轮上划放大、下划缩小，按住拖动平移；下方采样表每页 6 行，可导出监测 CSV。"},
        {h:"加入待处理异常集",p:"把这次检测的\"确认告警\"打包收起，放到\"检测报告\"页去处理。没有确认告警时按钮是灰的，点不动。"},
        {h:"本站检测历史",p:"这个站以前的检测，每页 3 条，可点\"查看检测\"复查。"},
        {h:"小提示",p:"刷新页面后，上次选的换热站、数据集、时间会自动恢复；第一次使用需要手动选一次。"}
      ]},
      {key:"四、检测报告",title:"检测报告：出结论、存证",blocks:[
        {h:"选择待处理异常集",p:"列出你在数据监测里\"加入\"的异常集合（名称、条数、加入时间）。点\"载入处理\"把对应检测载进来；不需要的点\"移除\"，或右上\"清空全部\"。指向已删除检测的记录会被自动清理。"},
        {h:"检测任务与结果",p:"任务信息 + 事件表（起止时间、持续小时、峰值/计数），只读、不需要挑选。点\"定位区间\"看该段时间的曲线；\"查看异常分数曲线\"弹出曲线浮窗，里面同时给出四个指标（有效点/超阈点/确认告警/质量问题）与数据质量提示；可导出逐点或事件 CSV。"},
        {h:"查看报告（全部事件）",p:"报告固定包含本次检测的全部确认告警，不用勾选。点按钮弹出报告浮窗：对象与来源、异常检测与证据、备注与适用边界三段。"},
        {h:"报告浮窗里的按钮",p:"保存报告与备注（存到本机）、保存并归档（归档后备注锁定）、创建新版本、导出 Word、导出 PDF。"},
        {h:"报告历史与归档",p:"历史报告列表，可按全部/已归档/未归档筛选，点\"查看报告\"重新打开。"}
      ]},
      {key:"五、完整流程",title:"完整流程：从头走一遍",blocks:[
        {h:"",p:"照着顺序走，第一次大约 10 分钟。"},
        {h:"",p:"打开软件：双击启动器后浏览器自动打开；右上确认\"导入模式 · 已连接\"。"},
        {h:"",p:"定对象：管网管理 → 企业/管网/管段 → 点\"确认选择\"。"},
        {h:"",p:"挂站点：管段关联换热站 → 选一个换热站。"},
        {h:"",p:"导数据：本站运行数据导入 → 上传 CSV（30 分钟对齐、8 个字段）→ 校验通过后出现在\"历史数据集\"。"},
        {h:"",p:"跑检测：数据监测 → 选同一个换热站 → 系统自动读采样并提交检测，等状态变\"已完成\"。"},
        {h:"",p:"看曲线：监测采样与趋势里看原始曲线和红点；想看分数细节就去\"检测报告 → 查看异常分数曲线\"。"},
        {h:"",p:"入池：点\"加入待处理异常集\"。"},
        {h:"",p:"载入：检测报告 → 选择待处理异常集 → 载入处理。"},
        {h:"",p:"出报告：点\"查看报告（全部 N 项事件）\"→ 核对内容 → 填备注 → 保存/归档 → 导出 Word 或 PDF。"},
        {h:"",p:"常见卡点：① 没点\"确认选择\"→ 后面全是空的；② 没选换热站 → 不能导数据；③ 站没导入数据 → 曲线显示\"无\"、也不判异常；④ 看到\"示例模型\"字样说明当前用的是演示模型，结果只用于跑通流程。"}
      ]},
      {key:"六、名词解释",title:"名词解释",blocks:[
        {h:"换热站",p:"把一次网的高温水换成二次网低温水、再送给居民楼的站点。本系统检测的对象就是它。"},
        {h:"一次网 / 二次网",p:"一次网是热源到换热站的主干管（温度高、流量大）；二次网是换热站到小区楼栋的支线。"},
        {h:"数据集",p:"你导入的那份 CSV，系统把它整理成 30 分钟一个点的标准格式，叫\"标准化数据集\"。"},
        {h:"异常分数",p:"某一时刻多个测点整体偏离\"该站正常水平\"的程度。越大越异常，不是概率，也不是百分比。"},
        {h:"超阈点 / 确认告警",p:"分数超过当刻阈值叫\"超阈点\"；连续足够多个点（默认 11 个，约 5.5 小时）都超阈，才升级为一段\"确认告警\"，用来压掉偶发抖动。"},
        {h:"待处理异常集",p:"你自己攒的一个\"待办箱\"：在数据监测里把某次告警加进去，到检测报告里逐条处理。"},
        {h:"示例模型",p:"用公开数据集训练、仅供跑通流程的模型，界面上会明确标注。它不代表你导入那家企业的真实水平。"},
        {h:"归档",p:"报告定稿后\"封存\"：证据与备注锁定，不能再改；需要修改就创建新版本。"}
      ]}
  ]
const props=defineProps<{open:boolean}>()
const emit=defineEmits<{(e:'close'):void}>()
const active=ref(0)
</script>

<template>
<Teleport to="body">
  <div v-if="open" class="help-backdrop" @click.self="emit('close')">
    <div class="help-dialog" role="dialog" aria-label="使用说明与帮助">
      <header class="help-hd">
        <strong>使用说明与帮助</strong>
        <button class="help-x" aria-label="关闭" @click="emit('close')">×</button>
      </header>

      <div class="help-body">
        <aside class="help-toc">
          <button v-for="(s,i) in sections" :key="s.key"
                  :class="['help-toc-item',{on:i===active}]" @click="active=i">{{s.key}}</button>
        </aside>

        <article class="help-content">
          <h3>{{sections[active].title}}</h3>
          <template v-for="(b,i) in sections[active].blocks" :key="i">
            <h4 v-if="b.h">{{b.h}}</h4>
            <p v-if="b.p">{{b.p}}</p>
          </template>
        </article>
      </div>
    </div>
  </div>
</Teleport>
</template>

<style scoped>
.help-backdrop{position:fixed;inset:0;background:rgba(15,23,42,.38);z-index:120;display:flex;align-items:center;justify-content:center;padding:28px}
.help-dialog{width:1040px;max-width:96vw;max-height:88vh;display:flex;flex-direction:column;background:#fff;border:1px solid #e2e8f0;border-radius:12px;box-shadow:0 20px 60px rgba(15,23,42,.22);overflow:hidden}
.help-hd{display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid #e2e8f0;background:#fff}
.help-hd strong{font-size:15px;color:#1e293b}
.help-x{border:0;background:transparent;font-size:20px;line-height:1;color:#64748b;cursor:pointer}
.help-body{display:grid;grid-template-columns:190px minmax(0,1fr);min-height:0;flex:1}
.help-toc{display:flex;flex-direction:column;gap:2px;padding:12px;border-right:1px solid #e2e8f0;background:#f8fafc;overflow:auto}
.help-toc-item{text-align:left;border:1px solid transparent;background:transparent;padding:8px 10px;border-radius:7px;font-size:13px;color:#1e293b;cursor:pointer}
.help-toc-item:hover{background:#eef2f7}
.help-toc-item.on{background:#e8f0ff;border-color:#c7dbff;color:#2563eb;font-weight:600}
.help-content{padding:20px 24px;overflow:auto}
.help-content h3{margin:0 0 12px;font-size:16px;color:#1e293b}
.help-content h4{margin:16px 0 6px;font-size:13.5px;color:#1e293b}
.help-content p{margin:0 0 10px;font-size:13px;line-height:1.9;color:#334155}
</style>
