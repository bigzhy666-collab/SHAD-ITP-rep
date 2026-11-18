import {afterEach,expect,it,vi} from 'vitest'
import {allPages,ApiError,localApi,query,request} from './api'
import {eventIdsFromQuery,fields,parseCsv,validRange,zoned} from './fields'
import {submissionDone,submissionKey} from './submission'
afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers()})
it('请求按本机相对路径发送，编码查询中的时区和 ID',async()=>{
 const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify({data:{items:[],page:1,pageSize:500,total:0}})))
 vi.stubGlobal('fetch',fetcher);await localApi.samples('a/b','2026-11-08T00:00:00+08:00','2026-11-08T01:00:00+08:00',['a'])
 expect(fetcher.mock.calls[0]![0]).toContain('/api/datasets/a%2Fb/samples?');expect(fetcher.mock.calls[0]![0]).toContain('%2B08%3A00');expect(query({a:'',b:undefined,c:0})).toBe('?c=0')
})
it('创建任务保留幂等键，导入 multipart 不手工覆盖 boundary',async()=>{
 const fetcher=vi.fn().mockImplementation(async()=>new Response(JSON.stringify({data:{}})));vi.stubGlobal('fetch',fetcher)
 await request('/detections',{method:'POST',body:{name:'test'},headers:{'Idempotency-Key':'same'}})
 expect(fetcher.mock.calls[0]![1].headers.get('Idempotency-Key')).toBe('same');expect(fetcher.mock.calls[0]![1].headers.get('Content-Type')).toBe('application/json')
 const body=new FormData();body.append('manifest','{}');await request('/datasets/import',{method:'POST',body});expect(fetcher.mock.calls[1]![1].headers.has('Content-Type')).toBe(false)
})
it('保留后端错误编号、字段和可重试性',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({requestId:'req-1',error:{code:'SOURCE_MISMATCH',message:'来源不一致',retryable:false,details:[{field:'stationId',reason:'不同站点'}]}}),{status:422})))
 await expect(request('/detections')).rejects.toMatchObject({code:'SOURCE_MISMATCH',requestId:'req-1',details:[{field:'stationId',reason:'不同站点'}]})
})
it('HTML 回退和缺失 data 不被误认为成功',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(new Response('<html>Vite</html>')).mockResolvedValueOnce(new Response('{}')))
 await expect(request('/runtime')).rejects.toMatchObject({code:'INVALID_RESPONSE'});await expect(request('/runtime')).rejects.toBeInstanceOf(ApiError)
})
it('中断与超时区分，不改变任务状态',async()=>{
 vi.useFakeTimers();vi.stubGlobal('fetch',vi.fn((_url,options)=>new Promise((_resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new Error('abort'))))))
 const timeout=request('/runtime',{timeout:50});const assertion=expect(timeout).rejects.toMatchObject({code:'TIMEOUT'});await vi.advanceTimersByTimeAsync(60);await assertion
 const controller=new AbortController(),cancel=request('/runtime',{signal:controller.signal});controller.abort();await expect(cancel).rejects.toMatchObject({name:'AbortError'})
})
it('全量结果遍历所有分页，并阻止遗漏与读取期间数量变化',async()=>{
 expect(await allPages(async page=>({items:[page],page,pageSize:1,total:3}))).toEqual([1,2,3])
 await expect(allPages(async page=>({items:page===1?[1]:[],page,pageSize:1,total:3}))).rejects.toMatchObject({code:'INCOMPLETE_RESULT'})
 await expect(allPages(async page=>({items:[page],page,pageSize:1,total:page===1?3:4}))).rejects.toMatchObject({code:'RESULT_CHANGED'})
})
it('CSV 支持 BOM、分隔符、引号转义和引号内换行，拒绝坏表头和坏列数',()=>{
 expect(parseCsv('\uFEFF时间,说明\r\n2026,"a,""b""\nc"')).toEqual([['时间','说明'],['2026','a,"b"\nc']])
 expect(parseCsv('时间;温度\n1;2',';')[1]).toEqual(['1','2'])
 for(const value of ['a,a\n1,2','a,b\n1','a,b\n1,"2'])expect(()=>parseCsv(value)).toThrow()
 expect(fields).toHaveLength(8);expect(validRange(zoned('2026-11-08T01:00'),zoned('2026-11-08T02:00'))).toBe(true)
 expect(eventIdsFromQuery(JSON.stringify(['opaque,id','second']))).toEqual(['opaque,id','second']);expect(eventIdsFromQuery('legacy-1,legacy-2')).toHaveLength(2)
})
it('不确定提交跨页面复用键；成功后下一次操作使用新键；存储失败阻止提交',()=>{
 const saved=new Map<string,string>();vi.stubGlobal('localStorage',{getItem:(k:string)=>saved.get(k)??null,setItem:(k:string,v:string)=>saved.set(k,v),removeItem:(k:string)=>saved.delete(k)})
 const a=submissionKey('test',{id:'same'});expect(submissionKey('test',{id:'same'})).toBe(a);submissionDone('test');expect(submissionKey('test',{id:'same'})).not.toBe(a)
 vi.stubGlobal('localStorage',{getItem:()=>{throw new Error('storage unavailable')}});expect(()=>submissionKey('test',{})).toThrow('无法保存本次请求标识')
})
