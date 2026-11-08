import type {Report} from './types'
import {time,download} from '../../utils'
export function assertReportSource(report:Report):Report {
 const {task,result,events,diagnosis}=report.snapshot
 const same=(a:string[],b:string[])=>new Set(a).size===a.length&&JSON.stringify([...a].sort())===JSON.stringify([...b].sort())
 if(report.detectionId!==task.id||result.detectionId!==task.id||result.contextSnapshot.station.id!==task.contextSnapshot.station.id||!same(report.eventIds,events.map(e=>e.id))||events.some(e=>e.detectionId!==task.id||e.stationId!==task.contextSnapshot.station.id)||!!diagnosis&&(diagnosis.detectionId!==task.id||diagnosis.id!==report.diagnosisId||!same(report.eventIds,diagnosis.eventIds)))throw new Error('报告快照与来源任务或事件不一致，已停止展示和导出。')
 return report
}
export function localReportText(report:Report){
 const {task,result,events,diagnosis}=report.snapshot,c=task.contextSnapshot
 return [
  {heading:'对象与来源',lines:[`报告：${report.id} / V${report.version}`,`生成时间：${time(report.createdAt)}`,`企业 / 管网 / 管段：${c.enterprise.name} / ${c.network.name} / ${c.segment.name}`,`模型作用站点：${c.station.name}（${c.station.id}）`,`来源检测：${task.id}`,`检测范围：${time(task.range.start)} — ${time(task.range.end)}`,`数据集：${task.datasetSnapshot.name} / ${task.datasetSnapshot.version}`,`数据校验值：${task.datasetSnapshot.sourceChecksum}`,`模型：${task.modelSnapshot.name} / ${task.modelSnapshot.version}`,`模型校验值：${task.modelSnapshot.artifactChecksum}`,`预处理：${result.preprocessingVersion}`,`来源标识：${task.modelSnapshot.isDemo?'示例模型结果，不适用于本站运行判断':'本机后端模型结果'}`]},
  {heading:'异常检测与证据',lines:[`检测点 ${result.summary.pointCount}，点级超阈 ${result.summary.alarmPointCount}，全部确认事件 ${result.summary.eventCount} 段。`,`本报告选择事件 ${events.length} 项。`,...events.map(e=>`${e.id}：${e.title}；${time(e.start)} — ${time(e.end)}；持续 ${e.hours} 小时；峰值分数 ${e.peak_score}；最大持续性计数 ${e.max_criticality}；${({within_range:'事件位于检测范围内',touches_range_start:'触及检测开始边界',touches_range_end:'触及检测结束边界，不能据此判断已恢复',touches_both:'触及检测起止边界'})[e.boundary]}。`),...result.warnings.map(w=>`检测提示：${w.message}`)]},
  {heading:'原因诊断与核查建议',lines:diagnosis?.status==='success'?[...diagnosis.observations.map(t=>'观测：'+t),...diagnosis.hypotheses.map(h=>`可能原因：${h.title}；依据：${h.evidence}；置信度：${h.confidence===null?'未提供':h.confidence}`),...diagnosis.recommendations.map(r=>`建议：${r.title}；措施：${r.action}；复核：${r.verification}`),...diagnosis.limitations.map(t=>'局限：'+t)]:['原因诊断能力尚未接入或未完成。本报告仅记录运行状态异常，未确定具体故障原因或解决方案。']},
  {heading:'分析过程证据',lines:diagnosis?.steps.length?diagnosis.steps.flatMap(s=>[`${s.title}：${s.summary}`,...s.evidence]):['仅提供实际检测结果，没有生成原因分析过程。']},
  {heading:'备注、版本与适用边界',lines:[`备注：${report.note||'无'}`,`归档状态：${report.archivedAt?'已归档 '+time(report.archivedAt):report.version===0?'临时导出，未保存到本机后端':'已保存，未归档'}`,'异常事件表示偏离正常行为，不等同于已确认的设备故障；健康度不代表故障概率。','该模型用于换热站设备与控制状态，不覆盖埋地管道腐蚀、裂纹和泄漏点定位。']},
 ]
}
export async function exportLocalReport(report:Report,format:'docx'|'pdf',image:string){
 assertReportSource(report)
 const sections=localReportText(report),filename=`${report.id}-V${report.version}`,subtitle=report.snapshot.task.modelSnapshot.isDemo?'示例模型检测报告':'本机运行数据检测报告'
 if(format==='docx'){
  const {Document,Packer,Paragraph,TextRun,HeadingLevel,ImageRun}=await import('docx')
  const children=[new Paragraph({text:report.title,heading:HeadingLevel.TITLE}),new Paragraph(subtitle)]
  sections.forEach((section,i)=>{children.push(new Paragraph({text:section.heading,heading:HeadingLevel.HEADING_1}));for(const line of section.lines)children.push(new Paragraph({children:[new TextRun({text:line,font:'Noto Sans SC',size:21})],spacing:{after:120}}));if(i===1&&image)children.push(new Paragraph({children:[new ImageRun({data:Uint8Array.from(atob(image.split(',')[1]!),c=>c.charCodeAt(0)),type:'png',transformation:{width:600,height:240}})]}))})
  download(await Packer.toBlob(new Document({sections:[{children}],styles:{default:{document:{run:{font:'Noto Sans SC'}}}}})),filename+'.docx');return
 }
 const {default:pdf}=await import('pdfmake/build/pdfmake'),response=await fetch('/fonts/NotoSansSC.ttf')
 if(!response.ok)throw new Error('本地中文字体读取失败，请检查安装资源后重试。')
 const bytes=new Uint8Array(await response.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768))
 pdf.vfs={'NotoSansSC.ttf':btoa(binary)};pdf.fonts={Noto:{normal:'NotoSansSC.ttf',bold:'NotoSansSC.ttf',italics:'NotoSansSC.ttf',bolditalics:'NotoSansSC.ttf'}}
 const content:unknown[]=[{text:report.title,fontSize:20,bold:true},{text:subtitle,margin:[0,12,0,12]}]
 sections.forEach((s,i)=>{content.push({text:s.heading,fontSize:14,bold:true,margin:[0,15,0,8]});s.lines.forEach(t=>content.push({text:t,margin:[0,0,0,6]}));if(i===1&&image)content.push({image,width:490})})
 await new Promise<void>((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('PDF 生成超时，请重试。')),120000);try{pdf.createPdf({content,defaultStyle:{font:'Noto',fontSize:10,lineHeight:1.4},pageSize:'A4',pageMargins:[42,42,42,42]}).getBlob(blob=>{clearTimeout(timer);download(blob,filename+'.pdf');resolve()})}catch(e){clearTimeout(timer);reject(e)}})
}
