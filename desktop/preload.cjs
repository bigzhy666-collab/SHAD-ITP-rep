const {contextBridge, ipcRenderer} = require('electron');
contextBridge.exposeInMainWorld('shadDesktop', Object.freeze({
  setDirty(id, dirty) {
    if (typeof id === 'string' && id.length < 100 && typeof dirty === 'boolean') {
      ipcRenderer.send('shad:dirty', {id, dirty});
    }
  },
}));
ipcRenderer.on('shad:refresh', () => window.dispatchEvent(new KeyboardEvent('keydown', {key:'r',ctrlKey:true,cancelable:true})));
window.addEventListener('DOMContentLoaded', () => {
  if (!document.getElementById('desktop-startup')) return;
  document.getElementById('retry').addEventListener('click', () => ipcRenderer.send('shad:retry'));
  ipcRenderer.on('shad:state', (_event, value) => {
    document.getElementById('message').textContent = value.message;
    document.getElementById('details').textContent = value.details || '';
    document.getElementById('retry').hidden = !value.retry;
    document.getElementById('desktop-startup').setAttribute('aria-busy', String(!value.retry));
  });
  ipcRenderer.send('shad:shell-ready');
});
