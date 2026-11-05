import type { Report } from '../domain'
import { metricInfo } from '../domain'
import { download, time } from '../utils'
export function reportText(r: Report): { heading: string; lines: string[] }[] {
 return [
  { heading: '基本信息与工况边界', lines: [`报告编号：${r.id} / V${r.version}`, `所属企业：${r.context.enterprise.name}`, `供热管网：${r.context.network.name}`, `管段：${r.context.segment.name}（${r.context.segment.code}，DN${r.context.segment.diameter}）`, `生成时间：${time(r.createdAt)}`, `检测范围：${time(r.detection.start)} — ${time(r.detection.end)}`, `来源检测：${r.detectionId}`, `来源分析：${r.analysisId ?? '未提供（阶段性检测报告）'}`] },
  { heading: '异常检测概况与数据证据', lines: [`算法：${r.detection.algorithm} / 残差系数 ${r.detection.threshold} σ`, `监测参数：${r.detection.metrics.map(m => metricInfo[m].label).join('、')}`, ...r.detection.anomalies.map(a => `${a.title}：${time(a.start)} — ${a.end ? time(a.end) : '持续中'}；观测 ${a.value} ${metricInfo[a.metric].unit}，基准 ${a.baseline} ${metricInfo[a.metric].unit}；${a.evidence}`), ...(r.detection.anomalies.length ? [] : ['当前检测范围未检出异常。'])] },
  { heading: 'AI 辅助诊断与核查建议', lines: r.analysis ? [`模型：${r.analysis.model}`, `分析异常：${r.detection.anomalies.filter(a=>r.analysis!.anomalyIds.includes(a.id)).map(a=>a.title).join('、')}`,  ...r.causes.flatMap(c => [`可能原因：${c.title} / 示例权重 ${c.weight}%`, `依据：${c.evidence}`, `核查：${c.check}`])] : ['本报告未包含 AI 分析，不提供模型原因判断。'] },
  { heading: '完整性与演示说明', lines: ['本报告为 SHAD 前端交互演示产物。数据、检测及模型权重均为示例，未连接真实设备或算法服务，不构成实际运行诊断。', '事实、算法示例结果和原因推测分别呈现；现场处置须由专业人员核验。', `归档状态：${r.archivedAt ? '已归档 · ' + time(r.archivedAt) : '待归档'}`, `备注：${r.note || '无'}`] },
 ]
}
export async function exportDocx(r: Report, image?: string) {
 const { Document, Packer, Paragraph, TextRun, HeadingLevel, ImageRun } = await import('docx')
 const sections = reportText(r)
 const children = [new Paragraph({ text: r.title, heading: HeadingLevel.TITLE }), new Paragraph('演示报告 · 不连接真实设备')]
 sections.forEach((s,i) => { children.push(new Paragraph({ text: s.heading, heading: HeadingLevel.HEADING_1, keepNext:true })); s.lines.forEach(t => children.push(new Paragraph({ children: [new TextRun({ text:t, font:'Noto Sans SC', size:21 })], spacing:{after:130} }))); if(i===1&&image){ const raw=atob(image.split(',')[1]!); const bytes=Uint8Array.from(raw,c=>c.charCodeAt(0));children.push(new Paragraph({ children:[new ImageRun({data:bytes,type:'png',transformation:{width:600,height:257}})] })) } })
 const doc = new Document({ sections:[{ properties:{}, children }], styles:{ default:{document:{run:{font:'Noto Sans SC',size:21}}} } })
 download(await Packer.toBlob(doc), `${r.id}-V${r.version}.docx`)
}
export async function exportPdf(r: Report, image?: string) {
 const mod = await import('pdfmake/build/pdfmake')
 const pdf = mod.default
 const response = await fetch('/fonts/NotoSansSC.ttf'); if(!response.ok)throw new Error('中文字体加载失败，请重试。')
 const buffer = new Uint8Array(await response.arrayBuffer()); let binary=''; for(let i=0;i<buffer.length;i+=32768)binary+=String.fromCharCode(...buffer.subarray(i,i+32768))
 pdf.vfs = {'NotoSansSC.ttf':btoa(binary)}
 pdf.fonts = { Noto:{normal:'NotoSansSC.ttf',bold:'NotoSansSC.ttf',italics:'NotoSansSC.ttf',bolditalics:'NotoSansSC.ttf'} }
 const content: unknown[] = [{text:r.title,fontSize:20,bold:true,margin:[0,0,0,12]},{text:'演示报告 · 不连接真实设备',color:'#a34d08',margin:[0,0,0,14]}]
 reportText(r).forEach((s,i)=>{content.push({text:s.heading,fontSize:14,bold:true,margin:[0,15,0,8]});s.lines.forEach(t=>content.push({text:t,margin:[0,0,0,7]}));if(i===1&&image)content.push({image,width:490,margin:[0,8,0,12]})})
 await new Promise<void>((resolve,reject)=>{try{pdf.createPdf({content,defaultStyle:{font:'Noto',fontSize:10,lineHeight:1.4},pageSize:'A4',pageMargins:[42,42,42,42],footer:(page:number,total:number)=>({text:`SHAD 演示报告 · ${page} / ${total}`,alignment:'center',fontSize:8,color:'#666666'})}).getBlob((blob:Blob)=>{download(blob,`${r.id}-V${r.version}.pdf`);resolve()})}catch(e){reject(e)}})
}
