// Only uncertain submissions retain their key. A reload can safely query/retry the same request.
export function submissionKey(scope:string,payload:unknown){
 const name=`shad-pending-${scope}`,fingerprint=JSON.stringify(payload)
 try{const raw=localStorage.getItem(name);if(raw){const saved=JSON.parse(raw);if(saved.fingerprint===fingerprint&&typeof saved.key==='string')return saved.key}
  const key=crypto.randomUUID();localStorage.setItem(name,JSON.stringify({fingerprint,key}));return key
 }catch{throw new Error('无法保存本次请求标识，请恢复浏览器存储后提交，以免重复创建任务。')}
}
export function submissionDone(scope:string){try{localStorage.removeItem(`shad-pending-${scope}`)}catch{/* The existing key safely resolves to the already created task. */}}
