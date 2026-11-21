// @ts-nocheck
// Geometry adapted from repository prototype d22938b. DOM is instance-scoped.
import heat from './heat.json'

// 未导入数据时使用空时序：指标显示 --，不判异常、不显示异常角标
if ((globalThis as any).__SHAD_NO_DEMO__) {
  Object.keys(heat as any).forEach(k => {
    if (Array.isArray((heat as any)[k])) (heat as any)[k] = []
  })
}
import {NETS,TREE,alarmRule} from './config'
export interface SceneController {setIndex:(i:number)=>void; count:number; times:string[]; firstAlarm:number; dispose:()=>void}
export function mountScene(root:HTMLElement,onTime:(i:number)=>void):SceneController{
const abort=new AbortController(), timers=new Set<ReturnType<typeof setTimeout>>();
const listenWindow=(type,fn,opts={})=>window.addEventListener(type,fn,{...opts,signal:abort.signal});
const listenDocument=(type,fn,opts={})=>root.addEventListener(type,fn,{...opts,signal:abort.signal});
const document={getElementById:(id)=>id==='app'?root:root.querySelector('#'+id),querySelector:(s)=>root.querySelector(s),querySelectorAll:(s)=>root.querySelectorAll(s),createElement:(t)=>globalThis.document.createElement(t),createTextNode:(t)=>globalThis.document.createTextNode(t)};
const later=(fn,delay)=>{const id=setTimeout(()=>{timers.delete(id);fn()},delay);timers.add(id);return id};
const listenCanvas=(type,fn,opts={})=>root.querySelector('canvas').addEventListener(type,fn,{...opts,signal:abort.signal});
const marks=globalThis.document.createElement('div');marks.className='alarm-overlay';root.append(marks);
const markButtons=new Map();
const stationButtons=new Map();
let focusFrame=0;
let centerX=0,centerY=0;
function stopFocus(){cancelAnimationFrame(focusFrame);focusFrame=0;}
function updateAlarms(){
 updateStationTargets();
 const objects=alarm?NET.city.stations.filter(s=>alarmRule.stations.includes(s.id)).map(s=>({key:s.id,kind:'station',obj:s,point:{x:s.x,y:s.h+8,z:s.z}})):[];
 const keys=new Set(objects.map(o=>o.key));for(const [key,button] of markButtons)if(!keys.has(key)){button.remove();markButtons.delete(key)}
 const placed=[];
 for(const o of objects){let button=markButtons.get(o.key);if(!button){button=globalThis.document.createElement('button');button.className='model-alarm';button.type='button';button.textContent='● 异常';button.title='点击查看站点及关联管线的演示异常';button.setAttribute('aria-label','演示异常 '+o.key);marks.append(button);markButtons.set(o.key,button)}button.onclick=()=>selectObject(o);const p=P(o.point.x,o.point.y,o.point.z);button.hidden=!p;if(p){let y=p.y;while(placed.some(q=>Math.abs(q.x-p.x)<70&&Math.abs(q.y-y)<28))y-=30;placed.push({x:p.x,y});button.style.left=p.x+'px';button.style.top=y+'px';button.style.setProperty('--stem',(p.y-y)+'px')}}
}


/* ---------- 基础工具 ---------- */
const clamp = (v, a, b) => v < a ? a : v > b ? b : v;
const lerp = (a, b, t) => a + (b - a) * t;
function mulberry32(a) {
  return function () {
    a |= 0; a = a + 0x6D2B79F5 | 0;
    let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}
function hexToRgb(h) {
  const n = parseInt(h.slice(1), 16);
  return [n >> 16 & 255, n >> 8 & 255, n & 255];
}
function shade(hex, f) {
  const [r, g, b] = hexToRgb(hex);
  return 'rgb(' + clamp(Math.round(r * f), 0, 255) + ',' + clamp(Math.round(g * f), 0, 255) + ',' + clamp(Math.round(b * f), 0, 255) + ')';
}
function rgba(hex, a) {
  const [r, g, b] = hexToRgb(hex);
  return 'rgba(' + r + ',' + g + ',' + b + ',' + a + ')';
}

/* ---------- 画布与相机 ---------- */
const cv = document.getElementById('c');
const ctx = cv.getContext('2d', { alpha: false });
if(!ctx)throw new Error('此设备不支持 Canvas 渲染');
let W = 0, H = 0, DPR = 1, FOCAL = 900;
const cam = { yaw: -0.52, pitch: 0.64, dist: 1020, tx: 0, tz: 0, ty: 0 };
let eye = { x: 0, y: 0, z: 0 }, mRight = { x: 1, y: 0, z: 0 }, mUp = { x: 0, y: 1, z: 0 }, mFwd = { x: 0, y: 0, z: 1 };

function resize() {
  DPR = Math.min(window.devicePixelRatio || 1, 2);
  W = cv.clientWidth; H = cv.clientHeight;
  cv.width = Math.round(W * DPR); cv.height = Math.round(H * DPR);
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  FOCAL = Math.max(H * 0.92, 620);
  render();
}
listenWindow('resize', resize);

function updateCamera() {
  const cp = Math.cos(cam.pitch), sp = Math.sin(cam.pitch);
  eye.x = cam.tx + cam.dist * cp * Math.sin(cam.yaw);
  eye.y = cam.ty + cam.dist * sp;
  eye.z = cam.tz + cam.dist * cp * Math.cos(cam.yaw);
  let fx = cam.tx - eye.x, fy = cam.ty - eye.y, fz = cam.tz - eye.z;
  let l = Math.hypot(fx, fy, fz) || 1; fx /= l; fy /= l; fz /= l;
  mFwd = { x: fx, y: fy, z: fz };
  // right = fwd × up(0,1,0) = (-fz, 0, fx)
  let rx = -fz, rz = fx;
  l = Math.hypot(rx, rz) || 1; rx /= l; rz /= l;
  mRight = { x: rx, y: 0, z: rz };
  // up = right × fwd
  mUp = {
    x: mRight.y * mFwd.z - mRight.z * mFwd.y,
    y: mRight.z * mFwd.x - mRight.x * mFwd.z,
    z: mRight.x * mFwd.y - mRight.y * mFwd.x
  };
}

/** 世界坐标 -> 屏幕；返回 null 表示在相机后方 */
function P(x, y, z) {
  const vx = x - eye.x, vy = y - eye.y, vz = z - eye.z;
  const cz = vx * mFwd.x + vy * mFwd.y + vz * mFwd.z;
  if (cz < 30) return null;
  const cx = vx * mRight.x + vy * mRight.y + vz * mRight.z;
  const cy = vx * mUp.x + vy * mUp.y + vz * mUp.z;
  const s = FOCAL / cz;
  return { x: centerX + cx * s, y: centerY - cy * s, z: cz, s: s };
}

/* ---------- 场景状态 ---------- */
let NET = null;              // 当前管网
let layers = { buildings: true, roads: true, pipes: true, labels: true };
let mode = 'ground';         // ground | under | clear | cut
let selected = null;         // 选中对象
let hover = null;
let alarm = false;

/* ---------- 管网配置 ---------- */
function buildCity(cfg) {
  const rnd = mulberry32(cfg.seed);
  const halfW = cfg.gw / 2, halfD = cfg.gd / 2;

  // ---------- 热源厂 / 换热站（先定位置，水系与建筑都要避让） ----------
  const plant = {
    x: cfg.plant.x, z: cfg.plant.z, name: cfg.plant.name,
    boxes: [
      { dx: 0, dz: 0, w: 116, d: 74, h: 27, roof: '#C3CDD9', side: '#93A6BA' },
      { dx: -72, dz: 26, w: 44, d: 38, h: 17, roof: '#D6DEE7', side: '#A6B6C6' },
      { dx: 62, dz: -26, w: 34, d: 34, h: 50, roof: '#AEBBCA', side: '#8496A9' }
    ],
    stacks: [{ dx: 26, dz: 20, r: 5.6, h: 98 }, { dx: 43, dz: 20, r: 4.2, h: 80 }]
  };
  const stations = cfg.stations.map((s, k) => ({
    id: 'S' + (k + 1), x: s.x, z: s.z, name: s.name, w: 15, d: 11, h: 6.5, r: 4
  }));

  // ---------- 绿地：几块街心公园 ----------
  const parks = [];
  const rndP = mulberry32(cfg.seed + 31);
  for (let i = 0; i < 4; i++) {
    const w = 80 + rndP() * 110, dd = 60 + rndP() * 80;
    const px = (rndP() - 0.5) * (cfg.gw - w - 200);
    const pz = (rndP() - 0.5) * (cfg.gd - dd - 200);
    if (stations.some(s => Math.abs(s.x - px) < w / 2 + 40 && Math.abs(s.z - pz) < dd / 2 + 40)) continue;
    parks.push({ x0: px - w / 2, z0: pz - dd / 2, x1: px + w / 2, z1: pz + dd / 2 });
  }

  // ---------- 路网 ----------
  const roads = [], blocks = [], buildings = [];
  const xs = [], zs = [];
  for (let x = -halfW; x <= halfW + 1; x += cfg.step) xs.push(x);
  for (let z = -halfD; z <= halfD + 1; z += cfg.step) zs.push(z);
  xs.push(0); zs.push(0);
  xs.sort((a, b) => a - b); zs.sort((a, b) => a - b);
  const mainRoad = (v) => Math.abs(v) < 1;
  xs.forEach(x => roads.push({ x1: x, z1: -halfD, x2: x, z2: halfD, w: mainRoad(x) ? cfg.mainW : cfg.roadW, major: mainRoad(x) }));
  zs.forEach(z => roads.push({ x1: -halfW, z1: z, x2: halfW, z2: z, w: mainRoad(z) ? cfg.mainW * 0.85 : cfg.roadW, major: mainRoad(z) }));

  const inPark = (x, z) => parks.some(q => x > q.x0 - 6 && x < q.x1 + 6 && z > q.z0 - 6 && z < q.z1 + 6);

  // ---------- 街区与建筑 ----------
  for (let i = 0; i < xs.length - 1; i++) {
    for (let j = 0; j < zs.length - 1; j++) {
      const x0 = xs[i] + cfg.roadW * 0.75, x1 = xs[i + 1] - cfg.roadW * 0.75;
      const z0 = zs[j] + cfg.roadW * 0.75, z1 = zs[j + 1] - cfg.roadW * 0.75;
      if (x1 - x0 < 34 || z1 - z0 < 34) continue;
      const block = { x0, z0, x1, z1, tone: rnd() };
      blocks.push(block);
      const nx = (x1 - x0) > 118 ? 3 : 2, nz = (z1 - z0) > 118 ? 2 : 1;
      const gw = (x1 - x0) / nx, gd = (z1 - z0) / nz;
      for (let a2 = 0; a2 < nx; a2++) {
        for (let b2 = 0; b2 < nz; b2++) {
          if (rnd() < 0.16) continue;
          const pad = 3 + rnd() * 5;
          const bw = Math.min(gw * (0.55 + rnd() * 0.34), gw - pad * 2);
          const bd = Math.min(gd * (0.55 + rnd() * 0.34), gd - pad * 2);
          if (bw < 9 || bd < 9) continue;
          const cx = x0 + gw * a2 + gw / 2 + (rnd() - 0.5) * 6;
          const cz = z0 + gd * b2 + gd / 2 + (rnd() - 0.5) * 6;
          if (inPark(cx, cz)) continue;
          let h = 7 + rnd() * 16;
          const r = rnd();
          if (r > 0.945) h = 42 + rnd() * 30;
          else if (r > 0.80) h = 22 + rnd() * 16;
          else if (r > 0.62) h = 14 + rnd() * 8;
          const tone = rnd();
          buildings.push({
            x: cx, z: cz, w: bw, d: bd, h: h,
            roof: tone > 0.72 ? '#F2F5F9' : tone > 0.4 ? '#FBFBF8' : '#E9EEF3',
            side: tone > 0.6 ? '#D8E0E8' : '#CFD8E2',
            rot: 0
          });
        }
      }
    }
  }

  // 站 / 厂 / 水面周边清空普通建筑
  const keepOut = stations.map(s => ({ x: s.x, z: s.z, r: 46 }));
  keepOut.push({ x: plant.x, z: plant.z, rx: 96, rz: 76 });
  const kept = buildings.filter(b => {
    for (const k of keepOut) {
      if (k.r) { if ((b.x - k.x) ** 2 + (b.z - k.z) ** 2 < k.r * k.r) return false; }
      else if (Math.abs(b.x - k.x) < k.rx + b.w / 2 && Math.abs(b.z - k.z) < k.rz + b.d / 2) return false;
    }
    return true;
  });

  return { roads, blocks, buildings: kept, plant, stations, parks, bounds: { halfW, halfD } };
}

/* ---------- 管线拓扑 ---------- */
function pickBuilding(city, st, dir, lenMax) {
  let best = null, bestScore = 1e9;
  city.buildings.forEach(b => {
    if (b.served) return;
    const vx = b.x - st.x, vz = b.z - st.z;
    const along = vx * dir[0] + vz * dir[1];
    const perp = Math.abs(vx * dir[1] - vz * dir[0]);
    if (along < 26 || along > lenMax) return;
    if (perp > 46) return;
    const score = perp * 1.6 + along * 0.25;
    if (score < bestScore) { bestScore = score; best = b; }
  });
  return best;
}

function buildPipes(net, city) {
  const pipes = [];
  const P0 = city.plant;
  const st = city.stations;
  const cfg = net.cfg;
  const hw = cfg.gw / 2, hd = cfg.gd / 2, step = cfg.step;
  // 吸附到最近的道路中心线，避免管线横穿街区
  const snap = (v, half) => {
    if (Math.abs(v) < step * 0.38) return 0;
    const k = Math.round((v + half) / step);
    return k * step - half;
  };
  const snapX = v => snap(v, hw);
  const snapZ = v => snap(v, hd);

  let bIdx = 0;
  const minX = Math.min(...st.map(s => s.x));
  const maxX = Math.max(...st.map(s => s.x));
  const hz = snapZ(P0.z);
  const OFF = 9;

  // 一次网母管：沿热源厂出线方向的道路
  const header = [[Math.min(minX, P0.x) - 60, hz], [Math.max(maxX, P0.x) + 60, hz]];
  pipes.push({ id: 'P-MAIN-1', type: 'p1s', pts: header, dn: 600, station: null, name: '一次网供水母管' });
  pipes.push({ id: 'P-MAIN-2', type: 'p1r', pts: header.map(p => [p[0], p[1] + OFF]), dn: 600, station: null, name: '一次网回水母管' });

  st.forEach(s => {
    const rx = snapX(s.x);                 // 立管走在站旁的道路上
    const sup = [[rx, hz], [rx, s.z], [s.x, s.z]];
    const ret = [[rx + OFF, hz + OFF], [rx + OFF, s.z + OFF], [s.x, s.z + OFF]];
    if (Math.abs(s.z - hz) > 6) {
      pipes.push({ id: 'P1S-' + s.id, type: 'p1s', pts: sup, dn: 250, station: s.id, name: s.name + ' · 一次供水' });
      pipes.push({ id: 'P1R-' + s.id, type: 'p1r', pts: ret, dn: 250, station: s.id, name: s.name + ' · 一次回水' });
    }

    // 二次侧：站内向两个方向，末端落到楼栋（入户）
    const dirs = [[1, 0], [0, 1]];
    dirs.forEach((d, k) => {
      const lenMax = 230;
      const target = pickBuilding(city, s, d, lenMax);
      const a2 = [s.x + d[0] * 12, s.z + d[1] * 12];
      let b2;
      if (target) {
        const half = (Math.abs(d[0]) ? target.w : target.d) / 2;
        b2 = [target.x - d[0] * (half + 3), target.z - d[1] * (half + 3)];
        if (!target.served) { target.served = true; target.tag = (++bIdx) + '#楼'; }
      } else {
        b2 = [s.x + d[0] * (64 + k * 20), s.z + d[1] * (64 + k * 20)];
      }
      const ox = d[1] ? 7.5 : 0, oz = d[0] ? 7.5 : 0;
      pipes.push({ id: 'P2S-' + s.id + '-' + k, type: 'p2s', pts: [a2, b2], dn: 150, station: s.id, name: s.name + ' · 二次供水 ' + (k + 1) });
      pipes.push({ id: 'P2R-' + s.id + '-' + k, type: 'p2r', pts: [[a2[0] + ox, a2[1] + oz], [b2[0] + ox, b2[1] + oz]], dn: 150, station: s.id, name: s.name + ' · 二次回水 ' + (k + 1) });
    });
  });
  return pipes;
}

/* ---------- 颜色 ---------- */
const PIPE_COLOR = { p1s: '#EE8B37', p1r: '#8E4212', p2s: '#37B3C6', p2r: '#0F5560' };
const PIPE_LABEL = { p1s: '一次网供水', p1r: '一次网回水', p2s: '二次网供水', p2r: '二次网回水' };

/* ---------- 渲染 ---------- */
let faceBuf = [];
function render() {
  if (!NET) return;
  updateFocusViewport();
  updateCamera();
  const c = NET.city;
  ctx.save();
  const bgg = ctx.createLinearGradient(0, 0, 0, H);
  bgg.addColorStop(0, '#F6F5F0'); bgg.addColorStop(.55, '#F1F0EA'); bgg.addColorStop(1, '#E9E8E1');
  ctx.fillStyle = bgg; ctx.fillRect(0, 0, W, H);

  /* 地面 */
  drawGround(c);
  /* 绿地（压在道路下面） */
  drawGreens(c);

  /* 道路 */
  if (layers.roads) drawRoads(c);


  /* 管线（地下模式先画） */
  const pipeY = mode === 'under' ? -7 : 0.5;
  if (layers.pipes && mode === 'under') drawPipes(pipeY);

  /* 建筑 */
  if (layers.buildings) drawBuildings(c);

  /* 管线（地面/透明/剖切模式画在上面） */
  if (layers.pipes && mode !== 'under') drawPipes(0.5);

  /* 热源厂与换热站 */
  drawPlant(c);
  drawStations(c);

  /* 选中高亮（画在设施之上，保证可见） */
  if (selected) {
    if (selected.kind === 'station') {
      const bad = alarm && alarmRule.stations.includes(selected.id);
      drawHalo(selected.x, selected.z, 32, 22, 12, bad ? '#dc2626' : '#2563eb');
    } else if (selected.kind === 'plant') {
      drawHalo(c.plant.x, c.plant.z, 116, 74, 27, '#2563eb');
    }
  }

  /* 标注 */
  if (layers.labels) drawLabels(c);

  /* 选中高亮 */
  drawSelection();

  updateAlarms();
  ctx.restore();
}

function drawGround(c) {
  const b = c.bounds;
  const EX = 1400;
  const q = [
    P(-b.halfW - EX, 0, -b.halfD - EX), P(b.halfW + EX, 0, -b.halfD - EX),
    P(b.halfW + EX, 0, b.halfD + EX), P(-b.halfW - EX, 0, b.halfD + EX)
  ];
  if (q.every(p => p)) {
    ctx.beginPath(); ctx.moveTo(q[0].x, q[0].y);
    for (let i = 1; i < 4; i++) ctx.lineTo(q[i].x, q[i].y);
    ctx.closePath();
    ctx.fillStyle = 'rgba(242,241,236,.9)'; ctx.fill();
  }
  // 街区底色（略深一点的台面）
  if (mode === 'under' || mode === 'clear') {
    ctx.globalAlpha = mode === 'under' ? 0.35 : 0.55;
  }
  c.blocks.forEach(bl => {
    const p = [P(bl.x0, 0.02, bl.z0), P(bl.x1, 0.02, bl.z0), P(bl.x1, 0.02, bl.z1), P(bl.x0, 0.02, bl.z1)];
    if (!p.every(Boolean)) return;
    ctx.beginPath(); ctx.moveTo(p[0].x, p[0].y);
    for (let i = 1; i < 4; i++) ctx.lineTo(p[i].x, p[i].y);
    ctx.closePath();
    ctx.fillStyle = bl.tone > 0.5 ? '#EBE9E0' : '#EDEBE2';
    ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,.55)'; ctx.lineWidth = 1; ctx.stroke();
  });
  ctx.globalAlpha = 1;
}

function drawGreens(c) {
  const alpha = mode === 'under' ? 0.55 : 1;
  ctx.globalAlpha = alpha;
  c.parks.forEach(p => {
    const q = [P(p.x0, 0.035, p.z0), P(p.x1, 0.035, p.z0), P(p.x1, 0.035, p.z1), P(p.x0, 0.035, p.z1)];
    if (!q.every(Boolean)) return;
    ctx.beginPath(); ctx.moveTo(q[0].x, q[0].y);
    for (let i = 1; i < 4; i++) ctx.lineTo(q[i].x, q[i].y);
    ctx.closePath();
    ctx.fillStyle = '#D7E8C8'; ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,.45)'; ctx.lineWidth = 1; ctx.stroke();
  });
  ctx.globalAlpha = 1;
}

function drawRoads(c) {
  const alpha = mode === 'under' ? 0.45 : 1;
  ctx.globalAlpha = alpha;
  c.roads.forEach(r => {
    const dx = r.x2 - r.x1, dz = r.z2 - r.z1;
    const len = Math.hypot(dx, dz) || 1;
    const nx = -dz / len * r.w / 2, nz = dx / len * r.w / 2;
    const pts = [
      P(r.x1 + nx, 0.06, r.z1 + nz), P(r.x2 + nx, 0.06, r.z2 + nz),
      P(r.x2 - nx, 0.06, r.z2 - nz), P(r.x1 - nx, 0.06, r.z1 - nz)
    ];
    if (!pts.every(Boolean)) return;
    ctx.beginPath(); ctx.moveTo(pts[0].x, pts[0].y);
    for (let i = 1; i < 4; i++) ctx.lineTo(pts[i].x, pts[i].y);
    ctx.closePath();
    ctx.fillStyle = r.major ? '#CFC8B4' : '#D9D3C2';
    ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,.95)'; ctx.lineWidth = r.major ? 1.6 : 1.1;
    ctx.stroke();
  });
  ctx.globalAlpha = 1;
}

/* 建筑：画家算法（远 -> 近） */
let _order = [];
function drawBuildings(c) {
  const list = c.buildings;
  const alpha = mode === 'under' ? 0.18 : mode === 'clear' ? 0.55 : 1;
  _order.length = 0;
  for (let i = 0; i < list.length; i++) {
    const b = list[i];
    if (mode === 'cut' && b.x > 40) continue;
    const dx = b.x - eye.x, dz = b.z - eye.z;
    _order.push({ b: b, d: dx * dx + dz * dz });
  }
  _order.sort((a, b) => b.d - a.d);
  // 阴影
  if (mode === 'ground') {
    ctx.fillStyle = 'rgba(36,48,62,.085)';
    for (let i = 0; i < _order.length; i++) {
      const b = _order[i].b;
      const ox = b.h * 0.34, oz = b.h * 0.22;
      const q = [P(b.x - b.w / 2 + ox, 0.04, b.z - b.d / 2 + oz), P(b.x + b.w / 2 + ox, 0.04, b.z - b.d / 2 + oz),
                 P(b.x + b.w / 2 + ox, 0.04, b.z + b.d / 2 + oz), P(b.x - b.w / 2 + ox, 0.04, b.z + b.d / 2 + oz)];
      if (!q.every(Boolean)) continue;
      ctx.beginPath(); ctx.moveTo(q[0].x, q[0].y);
      for (let k = 1; k < 4; k++) ctx.lineTo(q[k].x, q[k].y);
      ctx.closePath(); ctx.fill();
    }
  }
  ctx.globalAlpha = alpha;
  for (let i = 0; i < _order.length; i++) drawBuilding(_order[i].b);
  ctx.globalAlpha = 1;
}

function drawBuilding(b) {
  const x0 = b.x - b.w / 2, x1 = b.x + b.w / 2;
  const z0 = b.z - b.d / 2, z1 = b.z + b.d / 2;
  const h = b.h;
  const faces = [];

  // 侧面：只画朝向相机的两面
  const sideA = [[x0, 0, z0], [x1, 0, z0], [x1, h, z0], [x0, h, z0]];
  const sideB = [[x1, 0, z0], [x1, 0, z1], [x1, h, z1], [x1, h, z0]];
  const sideC = [[x1, 0, z1], [x0, 0, z1], [x0, h, z1], [x1, h, z1]];
  const sideD = [[x0, 0, z1], [x0, 0, z0], [x0, h, z0], [x0, h, z1]];

  const toCam = (pts) => {
    let cx = 0, cz = 0;
    pts.forEach(p => { cx += p[0]; cz += p[2]; });
    return (cx / pts.length - eye.x) * 0 + (cz / pts.length - eye.z);
  };
  // 用面法线判断可见性（简单：比较面中心与相机）
  const vis = (pts) => {
    let mx = 0, mz = 0;
    pts.forEach(p => { mx += p[0]; mz += p[2]; });
    mx /= pts.length; mz /= pts.length;
    return ((mx - b.x) * (mx - eye.x) + (mz - b.z) * (mz - eye.z)) < 0;
  };
  if (vis(sideA)) faces.push({ pts: sideA, col: shade(b.side, 0.90) });
  if (vis(sideB)) faces.push({ pts: sideB, col: shade(b.side, 0.98) });
  if (vis(sideC)) faces.push({ pts: sideC, col: shade(b.side, 0.84) });
  if (vis(sideD)) faces.push({ pts: sideD, col: shade(b.side, 0.88) });
  faces.push({ pts: [[x0, h, z0], [x1, h, z0], [x1, h, z1], [x0, h, z1]], col: b.roof, roof: true });

  for (const f of faces) {
    const pp = f.pts.map(p => P(p[0], p[1], p[2]));
    if (!pp.every(Boolean)) continue;
    ctx.beginPath(); ctx.moveTo(pp[0].x, pp[0].y);
    for (let i = 1; i < pp.length; i++) ctx.lineTo(pp[i].x, pp[i].y);
    ctx.closePath();
    ctx.fillStyle = f.col; ctx.fill();
    if (f.roof) { ctx.strokeStyle = 'rgba(255,255,255,.95)'; ctx.lineWidth = .9; ctx.stroke(); }
  }
}

/* 管线 */
function drawPipes(y, overlay) {
  const pipes = NET.pipes;
  ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  for (const p of pipes) {
    const isHot = alarm && alarmRule.stations.includes(p.station);
    const base = isHot ? '#E23B3B' : PIPE_COLOR[p.type];
    const pts = p.pts.map(q => P(q[0], y, q[1]));
    if (pts.some(v => !v)) continue;
    const isReturn = p.type.endsWith('r');
    const wWorld = clamp(p.dn / 150, 1.4, 4.6);
    const avgZ = pts.reduce((a, v) => a + v.z, 0) / pts.length;
    let lw = clamp(wWorld * (FOCAL / avgZ) * 0.58, 2.0, 13);
    const path = () => {
      ctx.beginPath(); ctx.moveTo(pts[0].x, pts[0].y);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
    };
    // 柔和投影（只一次，不要白边）
    if (!overlay) {
      ctx.beginPath(); ctx.moveTo(pts[0].x, pts[0].y + 2);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y + 2);
      ctx.strokeStyle = 'rgba(20,30,45,.07)'; ctx.lineWidth = lw + 1.5; ctx.stroke();
    }
    ctx.globalAlpha = overlay ? 0.30 : 1;
    ctx.strokeStyle = base; ctx.lineWidth = lw;
    // 回水：虚线（供实回虚）；线宽越细虚线段越短
    ctx.setLineDash(isReturn ? [Math.max(4, lw * 3.0), Math.max(3, lw * 2.0)] : []);
    path(); ctx.stroke();
    ctx.setLineDash([]);
    if (isHot) {
      ctx.globalAlpha = 0.22; ctx.strokeStyle = '#FF4D4D'; ctx.lineWidth = lw + 7; ctx.setLineDash([]); path(); ctx.stroke();
    }
    if (selected && selected.id === p.id) {
      ctx.globalAlpha = 0.55; ctx.strokeStyle = '#fff'; ctx.lineWidth = lw + 6; ctx.setLineDash([]); path(); ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }
}

/* 热源厂 */
function drawPlant(c) {
  const pl = c.plant;
  // 厂区地面
  const yard = [P(pl.x - 92, 0.12, pl.z - 62), P(pl.x + 92, 0.12, pl.z - 62), P(pl.x + 92, 0.12, pl.z + 62), P(pl.x - 92, 0.12, pl.z + 62)];
  if (yard.every(Boolean)) {
    ctx.beginPath(); ctx.moveTo(yard[0].x, yard[0].y);
    for (let i = 1; i < 4; i++) ctx.lineTo(yard[i].x, yard[i].y);
    ctx.closePath(); ctx.fillStyle = '#E7E4DA'; ctx.fill();
  }
  pl.boxes.forEach(bx => {
    drawBuilding({ x: pl.x + bx.dx, z: pl.z + bx.dz, w: bx.w, d: bx.d, h: bx.h, roof: bx.roof, side: bx.side });
  });
  // 烟囱
  pl.stacks.forEach(s => {
    const cx = pl.x + s.dx, cz = pl.z + s.dz, rr = s.r * 2;
    drawBuilding({ x: cx, z: cz, w: rr, d: rr, h: s.h, roof: '#C0453C', side: '#B7BFC9' });
    drawBuilding({ x: cx, z: cz, w: rr * 1.25, d: rr * 1.25, h: 2.2, roof: '#C3CAD3', side: '#C3CAD3' });
  });
  // 厂界围栏
  const ring = [P(pl.x - 92, 0.3, pl.z - 62), P(pl.x + 92, 0.3, pl.z - 62), P(pl.x + 92, 0.3, pl.z + 62), P(pl.x - 92, 0.3, pl.z + 62)];
  if (ring.every(Boolean)) {
    ctx.beginPath(); ctx.moveTo(ring[0].x, ring[0].y);
    for (let i = 1; i < 4; i++) ctx.lineTo(ring[i].x, ring[i].y);
    ctx.closePath(); ctx.strokeStyle = 'rgba(224,122,47,.6)'; ctx.lineWidth = 1.6; ctx.setLineDash([7, 5]); ctx.stroke(); ctx.setLineDash([]);
  }
}

/* 换热站 */
function drawStations(c) {
  c.stations.forEach(s => {
    const isBad = alarm && alarmRule.stations.includes(s.id);
    const main = { roof: isBad ? '#EFC7C2' : '#F0C39C', side: isBad ? '#DDB4AF' : '#B9C6D4' };
    // 站区底板
    const plate = [P(s.x - 30, 0.14, s.z - 22), P(s.x + 36, 0.14, s.z - 22), P(s.x + 36, 0.14, s.z + 22), P(s.x - 30, 0.14, s.z + 22)];
    if (plate.every(Boolean)) {
      ctx.beginPath(); ctx.moveTo(plate[0].x, plate[0].y);
      for (let i = 1; i < 4; i++) ctx.lineTo(plate[i].x, plate[i].y);
      ctx.closePath(); ctx.fillStyle = isBad ? '#F3E1DF' : '#E6EEF0'; ctx.fill();
    }
    // 站房主体（两层，带设备间）
    drawBuilding({ x: s.x, z: s.z, w: 32, d: 22, h: 12, roof: main.roof, side: main.side });
    // 附属间
    drawBuilding({ x: s.x + 24, z: s.z + 4, w: 13, d: 14, h: 7.5, roof: '#F2F5F7', side: '#C6D0DA' });
    // 排风管
    drawBuilding({ x: s.x - 11, z: s.z - 6, w: 3.2, d: 3.2, h: 18, roof: '#B9C2CC', side: '#C9D1DA' });
    // 站区围栏
    const rq = [P(s.x - 26, 0.3, s.z - 18), P(s.x + 32, 0.3, s.z - 18), P(s.x + 32, 0.3, s.z + 18), P(s.x - 26, 0.3, s.z + 18)];
    if (rq.every(Boolean)) {
      ctx.beginPath(); ctx.moveTo(rq[0].x, rq[0].y);
      for (let i = 1; i < 4; i++) ctx.lineTo(rq[i].x, rq[i].y);
      ctx.closePath();
      ctx.setLineDash([5, 4]); ctx.strokeStyle = isBad ? 'rgba(224,59,59,.65)' : 'rgba(45,159,176,.55)';
      ctx.lineWidth = 1.4; ctx.stroke(); ctx.setLineDash([]);
    }
    const p = P(s.x, s.h + 2.5, s.z);
    if (!p) return;
    // 站点标记
    const r = clamp(26 * (FOCAL / 900) / (p.z / 600 + 1), 9, 16);
    ctx.beginPath(); ctx.arc(p.x, p.y - r * 0.6, r * 0.62, 0, Math.PI * 2);
    ctx.fillStyle = isBad ? 'rgba(224,59,59,.16)' : 'rgba(45,159,176,.16)'; ctx.fill();
    ctx.beginPath(); ctx.arc(p.x, p.y - r * 0.6, r * 0.3, 0, Math.PI * 2);
    ctx.fillStyle = isBad ? '#E23B3B' : '#2D9FB0'; ctx.fill();
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.6; ctx.stroke();
  });
}

/* 标注 */
function drawLabels(c) {
  ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
  const items = [];
  const pl = P(c.plant.x, 70, c.plant.z);
  if (pl) items.push({ p: pl, t: c.plant.name, hot: true, sel: !!(selected && selected.kind === 'plant') });
  c.stations.forEach(s => {
    const p = P(s.x, s.h + 4, s.z);
    if (p) items.push({ p: p, t: s.name, hot: alarm && alarmRule.stations.includes(s.id), sel: !!(selected && selected.kind === 'station' && selected.id === s.id) });
  });
  // 入户楼栋（脱敏名称：1#楼 / 2#楼 …），仅近景显示
  if (cam.dist < 1600) {
    c.buildings.forEach(b => {
      if (!b.served || !b.tag) return;
      const p = P(b.x, b.h + 1.5, b.z);
      if (p) items.push({ p: p, t: b.tag, small: true, hot: false });
    });
  }
  items.sort((a, b) => a.p.z - b.p.z);
  items.forEach(it => {
    if (it.small) {
      const fs2 = 10;
      ctx.font = '500 ' + fs2 + 'px "Microsoft YaHei",sans-serif';
      const w2 = ctx.measureText(it.t).width + 10;
      const x2 = it.p.x, y2 = it.p.y - 8;
      ctx.beginPath();
      roundRect(ctx, x2 - w2 / 2, y2 - fs2 - 4, w2, fs2 + 8, 3);
      ctx.fillStyle = 'rgba(245,246,248,.92)'; ctx.fill();
      ctx.strokeStyle = 'rgba(120,132,148,.55)'; ctx.lineWidth = .8; ctx.stroke();
      ctx.fillStyle = '#3C4655'; ctx.fillText(it.t, x2, y2);
      return;
    }
    const fs = it.hot ? 12 : 11;
    ctx.font = '600 ' + fs + 'px "Microsoft YaHei",sans-serif';
    const w = ctx.measureText(it.t).width + 14;
    const x = it.p.x, y = it.p.y - 16;
    ctx.beginPath();
    roundRect(ctx, x - w / 2, y - fs - 6, w, fs + 12, 4);
    if (it.sel) {
      ctx.fillStyle = it.hot ? '#dc2626' : '#2563eb'; ctx.fill();
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();
      ctx.fillStyle = '#fff';
    } else {
      ctx.fillStyle = it.hot ? 'rgba(220,38,38,.94)' : 'rgba(255,255,255,.95)';
      ctx.fill();
      if (!it.hot) { ctx.strokeStyle = 'rgba(15,23,42,.14)'; ctx.lineWidth = 1; ctx.stroke(); }
      ctx.fillStyle = it.hot ? '#fff' : '#1e293b';
    }
    ctx.fillText(it.t, x, y - 1);
  });
}
function roundRect(ctx, x, y, w, h, r) {
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

/* 选中高亮 */
function drawSelection() {
  if (!selected) return;
  if (selected.kind === 'pipe') {
    // 已在 drawPipes 内处理
  }
}


/* ============================================================
   数据 / 交互 / UI
   ============================================================ */
const DATA = heat;
const S = DATA.v;
const N = DATA.t.length;
let idx = 0, playing = false, speed = 12, lastTick = 0;

const $ = (s) => document.querySelector(s);
const kpiCard = $('#kpiCard');
const info = $('#info'), infoTag = $('#infoTag'), infoName = $('#infoName'), infoSub = $('#infoSub'),
  infoDl = $('#infoDl'), infoState = $('#infoState');

/* ---------- KPI ---------- */
const KPIS = [
  { key: 'outdoor_temperature', label: '室外温度', unit: '℃', cls: 'cold', min: -12, max: 22 },
  { key: 'p_net_supply_temperature', label: '一次侧供水', unit: '℃', cls: 'hot', min: 70, max: 120 },
  { key: 'p_net_return_temperature', label: '一次侧回水', unit: '℃', cls: '', min: 20, max: 90 },
  { key: 'p_net_meter_heat_power', label: '瞬时热功率', unit: 'kW', cls: '', min: 0, max: 620 },
  { key: 'p_net_meter_flow', label: '瞬时流量', unit: 'L/h', cls: '', min: 0, max: 11000 },
  { key: 's_hc1_supply_temperature', label: '二次侧供水', unit: '℃', cls: 'hot', min: 30, max: 110 }
];
const kpiEls = {};
KPIS.forEach(k => {
  const d = document.createElement('div');
  d.className = 'kpi ' + k.cls;
  d.innerHTML = '<div class="k"><span>' + k.label + '</span></div>' +
    '<div class="v"><span class="num">--</span><small>' + k.unit + '</small></div><div class="bar"><i></i></div>';
  kpiCard.appendChild(d);
  kpiEls[k.key] = { root: d, num: d.querySelector('.num'), bar: d.querySelector('.bar i'), def: k };
});

function fmt(v, digits) {
  if (v === null || v === undefined || isNaN(v)) return '--';
  if (Math.abs(v) >= 1000) return Math.round(v).toLocaleString('en-US');
  return v.toFixed(digits);
}
function updateKPIs() {
  KPIS.forEach(k => {
    const v = S[k.key][idx];
    const e = kpiEls[k.key];
    e.num.textContent = fmt(v, k.key.includes('flow') || k.key.includes('power') ? 0 : 1);
    const p = clamp((v - k.min) / (k.max - k.min), 0, 1);
    e.bar.style.width = (p * 100).toFixed(1) + '%';
    if (k.key === 's_hc1_supply_temperature') {
      e.root.classList.toggle('bad', v > 80);
      e.bar.style.background = v > 80 ? 'linear-gradient(90deg,#B3402F,#E23B3B)' : '';
    }
  });
}

/* ---------- 固定快照（时间轴已移除） ---------- */
const SNAP_FALLBACK = 1120;   // 11-26 08:00，处在故障段内
function setIdx(i) {
  idx = clamp(Math.round(i), 0, N - 1);
  alarm = S[alarmRule.metric][idx] > alarmRule.threshold;
  onTime(idx);
  updateKPIs();
  render();
  if (selected) renderInfo();
}

/* ---------- 企业 / 管网 / 管段 三级切换 ---------- */
const entSel = $('#entSel'), netSel = $('#netSel'), segSel = $('#segSel');
let cur = { ent: null, net: null, seg: null };

TREE.forEach(e => {
  const o = document.createElement('option');
  o.value = e.id; o.textContent = e.name; entSel.appendChild(o);
});

function fillNets(entId, keep) {
  const ent = TREE.find(e => e.id === entId) || TREE[0];
  netSel.innerHTML = '';
  ent.nets.forEach(n => {
    const o = document.createElement('option');
    o.value = n.id; o.textContent = n.name; netSel.appendChild(o);
  });
  netSel.value = keep && ent.nets.some(n => n.id === keep) ? keep : ent.nets[0].id;
  fillSegs(entId, netSel.value, null);
}
function fillSegs(entId, netId, keep) {
  const ent = TREE.find(e => e.id === entId) || TREE[0];
  const net = ent.nets.find(n => n.id === netId) || ent.nets[0];
  segSel.innerHTML = '';
  net.segs.forEach(sid => {
    const cfg = NETS.find(n => n.id === sid);
    const o = document.createElement('option');
    o.value = sid; o.textContent = cfg ? cfg.name : sid; segSel.appendChild(o);
  });
  segSel.value = keep && net.segs.includes(keep) ? keep : net.segs[0];
  loadSeg(segSel.value);
}
entSel.onchange = () => { fillNets(entSel.value, null); };
netSel.onchange = () => { fillSegs(entSel.value, netSel.value, null); };
segSel.onchange = () => { loadSeg(segSel.value); };

function loadSeg(segId) {
  const i = NETS.findIndex(n => n.id === segId);
  if (i < 0) return;
  stopFocus();
  const cfg = NETS[i];
  cur = { ent: cfg.ent, net: cfg.net, seg: cfg.id };
  NET = { cfg, city: buildCity(cfg), pipes: [] };
  NET.pipes = buildPipes(NET, NET.city);
  cam.yaw = cfg.cam.yaw; cam.pitch = cfg.cam.pitch; cam.dist = cfg.cam.dist * 0.78;
  const xs = cfg.stations.map(s => s.x).concat([cfg.plant.x]);
  const zs = cfg.stations.map(s => s.z).concat([cfg.plant.z]);
  cam.tx = (Math.min(...xs) + Math.max(...xs)) / 2;
  cam.tz = (Math.min(...zs) + Math.max(...zs)) / 2;
  cam.ty = 0;
  selected = null; info.classList.remove('show');
  alarm = S[alarmRule.metric][idx] > alarmRule.threshold;
  entSel.value = cfg.ent; netSel.value = cfg.net; segSel.value = cfg.id;
  render();
}

/* ---------- 图层菜单 ---------- */
$('#btnLayers').onclick = (e) => {
  e.stopPropagation();
  const btn = e.currentTarget;
  let pop = document.getElementById('layerPop');
  if (pop) { pop.remove(); btn.classList.remove('on'); return; }
  btn.classList.add('on');
  pop = document.createElement('div');
  pop.id = 'layerPop';
  pop.onclick = e => e.stopPropagation();
  pop.style.cssText = 'position:absolute;top:52px;right:110px;z-index:25;background:rgba(20,25,32,.97);border:1px solid #2A303B;border-radius:6px;padding:6px;min-width:132px;box-shadow:0 12px 32px rgba(0,0,0,.45)';
  [['buildings', '建筑'], ['roads', '道路'], ['pipes', '供热管线'], ['labels', '站点标注']].forEach(([k, t]) => {
    const row = document.createElement('label');
    row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 8px;font-size:11.5px;color:#C6CEDB;cursor:pointer;border-radius:4px';
    row.onmouseenter = () => row.style.background = '#262E3A';
    row.onmouseleave = () => row.style.background = 'transparent';
    const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = layers[k];
    cb.onchange = () => { layers[k] = cb.checked; render(); };
    row.appendChild(cb); row.appendChild(document.createTextNode(t));
    pop.appendChild(row);
  });
  document.getElementById('app').appendChild(pop);
  listenDocument('click', () => { pop.remove(); btn.classList.remove('on'); }, { once: true });
};

/* ---------- 模式 ---------- */
document.querySelectorAll('#modeSeg button').forEach(b => {
  b.onclick = () => {
    document.querySelectorAll('#modeSeg button').forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    mode = b.dataset.mode;
    $('#gridOv').classList.toggle('on', mode === 'cut');
    render();
  };
});
$('#btnReset').onclick = () => {
  stopFocus();selected=null;info.classList.remove('show');cam.ty=0;
  const c = NET.cfg.cam;
  cam.yaw = c.yaw; cam.pitch = c.pitch; cam.dist = c.dist; cam.tx = 0; cam.tz = 0;
  render();
};

/* ---------- 相机交互 ---------- */
let drag = null;
listenCanvas('contextmenu', e => e.preventDefault());
listenCanvas('pointerdown', e => {
  stopFocus();
  cv.setPointerCapture(e.pointerId);
  drag = { x: e.clientX, y: e.clientY, yaw: cam.yaw, pitch: cam.pitch, tx: cam.tx, tz: cam.tz, pan: e.button === 2 || e.shiftKey, moved: 0 };
  cv.classList.add('dragging');
});
listenCanvas('pointermove', e => {
  if (!drag) { updateHover(e); return; }
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  drag.moved += Math.abs(dx) + Math.abs(dy);
  if (drag.pan) {
    const k = cam.dist * 0.0014;
    cam.tx = drag.tx - dx * mRight.x * k + dy * mFwd.x * k;
    cam.tz = drag.tz - dx * mRight.z * k + dy * mFwd.z * k;
  } else {
    cam.yaw = drag.yaw - dx * 0.005;
    cam.pitch = clamp(drag.pitch + dy * 0.004, 0.32, 1.35);
  }
  render();
});
listenCanvas('pointerup', e => {
  cv.classList.remove('dragging');
  const wasDrag = drag && drag.moved > 6;
  drag = null;
  if (!wasDrag) pick(e.clientX - cv.getBoundingClientRect().left, e.clientY - cv.getBoundingClientRect().top);
});
listenCanvas('wheel', e => {
  stopFocus();
  e.preventDefault();
  cam.dist = clamp(cam.dist * (1 + Math.sign(e.deltaY) * 0.12), 200, 2800);
  render();
}, { passive: false });
listenCanvas('dblclick', e => {
  const o = hitTest(e.clientX - cv.getBoundingClientRect().left, e.clientY - cv.getBoundingClientRect().top);
  if (!o) return;
  if(o.kind==='station'||o.kind==='plant'){selectObject(o);return;}
  stopFocus();
  const p = midOf(o.obj);
  cam.tx=p.x;cam.tz=p.z;cam.dist=clamp(cam.dist*0.6,220,1600);render();
});

function midOf(p) {
  const a = p.pts[Math.floor(p.pts.length / 2) - 1] || p.pts[0];
  const b = p.pts[Math.floor(p.pts.length / 2)] || p.pts[0];
  return { x: (a[0] + b[0]) / 2, z: (a[1] + b[1]) / 2 };
}

/* ---------- 拾取 ---------- */
function quadPts(x, z, w, d, y, expand) {
  const x0 = x - w / 2 - expand, x1 = x + w / 2 + expand;
  const z0 = z - d / 2 - expand, z1 = z + d / 2 + expand;
  return [P(x0, y, z0), P(x1, y, z0), P(x1, y, z1), P(x0, y, z1)];
}
function pointInQuad(mx, my, q) {
  if (!q || !q.every(Boolean)) return false;
  let sign = 0;
  for (let i = 0; i < 4; i++) {
    const a = q[i], b = q[(i + 1) % 4];
    const cr = (b.x - a.x) * (my - a.y) - (b.y - a.y) * (mx - a.x);
    if (Math.abs(cr) < 0.001) continue;
    const sg = cr > 0 ? 1 : -1;
    if (sign === 0) sign = sg; else if (sg !== sign) return false;
  }
  return true;
}
function fillQuad(q, fill, stroke, dash, lw) {
  if (!q || !q.every(Boolean)) return;
  ctx.beginPath(); ctx.moveTo(q[0].x, q[0].y);
  for (let i = 1; i < 4; i++) ctx.lineTo(q[i].x, q[i].y);
  ctx.closePath();
  if (fill) { ctx.fillStyle = fill; ctx.fill(); }
  if (stroke) {
    ctx.strokeStyle = stroke; ctx.lineWidth = lw || 2;
    if (dash) ctx.setLineDash(dash);
    ctx.stroke(); ctx.setLineDash([]);
  }
}
function drawHalo(x, z, w, d, h, color) {
  const c = color || '#2563eb';
  // 地面光晕
  fillQuad(quadPts(x, z, w, d, 0.22, 11), c === '#2563eb' ? 'rgba(37,99,235,.13)' : 'rgba(220,38,38,.12)', c, [7, 5], 2);
  // 顶部描边
  fillQuad(quadPts(x, z, w, d, h + 0.5, 2.5), null, c, null, 1.8);
}

function hitTest(mx, my) {
  // 1) 换热站优先：楼体轮廓命中，或靠近站体 28px 内
  let stBest = null, stD = 1e9;
  NET.city.stations.forEach(s => {
    const g = quadPts(s.x, s.z, 32, 22, 0.2, 8);
    const t = quadPts(s.x, s.z, 32, 22, s.h, 2);
    const p = P(s.x, s.h * 0.6, s.z);
    if (!p) return;
    const d = Math.hypot(p.x - mx, p.y - my);
    if (pointInQuad(mx, my, g) || pointInQuad(mx, my, t) || d < 28) {
      if (d < stD) { stD = d; stBest = { kind: 'station', obj: s }; }
    }
  });
  if (stBest) return stBest;

  // 2) 热源厂
  const pl = NET.city.plant;
  if (pointInQuad(mx, my, quadPts(pl.x, pl.z, 116, 74, 0.2, 6)) ||
      pointInQuad(mx, my, quadPts(pl.x, pl.z, 116, 74, 26, 4))) {
    return { kind: 'plant', obj: pl };
  }

  // 3) 管线
  const y = mode === 'under' ? -7 : 0.5;
  let best = null, bd = 10;
  NET.pipes.forEach(p => {
    const pts = p.pts.map(q => P(q[0], y, q[1]));
    for (let i = 1; i < pts.length; i++) {
      if (!pts[i - 1] || !pts[i]) continue;
      const d = distSeg(mx, my, pts[i - 1].x, pts[i - 1].y, pts[i].x, pts[i].y);
      if (d < bd) { bd = d; best = { kind: 'pipe', obj: p }; }
    }
  });
  return best;
}
function distSeg(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1, dy = y2 - y1;
  const l2 = dx * dx + dy * dy;
  if (!l2) return Math.hypot(px - x1, py - y1);
  let t = ((px - x1) * dx + (py - y1) * dy) / l2;
  t = clamp(t, 0, 1);
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}
function updateHover(e) {
  const o = hitTest(e.clientX - cv.getBoundingClientRect().left, e.clientY - cv.getBoundingClientRect().top);
  cv.style.cursor = o ? 'pointer' : 'grab';
  hover = o;
}
// Keep the selected station clear of the surrounding controls and details.
function updateFocusViewport(){
  const focused=selected&&(selected.kind==='station'||selected.kind==='plant')&&info.classList.contains('show');
  root.classList.toggle('has-station-focus',!!focused);
  centerX=W/2;centerY=H/2;
  if(!focused)return;
  const top=root.querySelector('.top').offsetHeight+16;
  if(W<=700){centerY=(top+H-info.offsetHeight-16)/2;}
  else{
    const left=root.querySelector('.left');
    const minX=getComputedStyle(left).display==='none'?16:left.getBoundingClientRect().right-cv.getBoundingClientRect().left+16;
    centerX=(minX+info.offsetLeft-16)/2;
    centerY=(top+H-36)/2;
  }
}
function updateStationTargets(){
  const objects=NET.city.stations.map(obj=>({kind:'station',obj})).concat([{kind:'plant',obj:NET.city.plant}]);
  const keys=new Set(objects.map(o=>o.kind+o.obj.id));
  for(const [key,button] of stationButtons)if(!keys.has(key)){button.remove();stationButtons.delete(key);}
  for(const o of objects){
    const key=o.kind+o.obj.id;
    let button=stationButtons.get(key);
    if(!button){button=globalThis.document.createElement('button');button.className='station-target';button.type='button';marks.prepend(button);stationButtons.set(key,button);}
    button.setAttribute('aria-label','聚焦'+o.obj.name);
    button.setAttribute('aria-pressed',String(selected?.kind===o.kind&&selected?.id===o.obj.id));
    button.title='点击居中并拉近：'+o.obj.name;
    button.onclick=()=>selectObject(o);
    const p=P(o.obj.x,o.kind==='station'?o.obj.h:20,o.obj.z);
    button.hidden=!p;
    if(p){button.style.left=p.x+'px';button.style.top=p.y+'px';}
  }
}
function focusStation(o){
  stopFocus();
  const start={tx:cam.tx,tz:cam.tz,ty:cam.ty,dist:cam.dist};
  const target={tx:o.obj.x,tz:o.obj.z,ty:o.kind==='station'?o.obj.h:20,dist:Math.min(cam.dist,Math.max(400,NET.cfg.cam.dist*0.6))};
  const begin=performance.now();
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function step(now){
    const t=reduced?1:clamp((now-begin)/400,0,1),ease=1-Math.pow(1-t,3);
    for(const key of Object.keys(target))cam[key]=lerp(start[key],target[key],ease);
    render();
    focusFrame=t<1?requestAnimationFrame(step):0;
  }
  step(begin);
}
function selectObject(o){
  stopFocus();
  selected={kind:o.kind,...o.obj};
  renderInfo();info.classList.add('show');
  if(o.kind==='station'||o.kind==='plant')focusStation(o);
  else render();
}
function pick(mx, my) {
  const o = hitTest(mx, my);
  if (!o) { stopFocus();selected = null; info.classList.remove('show'); render(); return; }
  selectObject(o);
}

/* ---------- 信息面板 ---------- */
function pipeLen(p) {
  let L = 0;
  for (let i = 1; i < p.pts.length; i++) L += Math.hypot(p.pts[i][0] - p.pts[i - 1][0], p.pts[i][1] - p.pts[i - 1][1]);
  return L;
}
function renderInfo() {
  const s = selected;
  if (!s) return;
  if (s.kind === 'pipe') {
    const st = NET.city.stations.find(x => x.id === s.station);
    const bad = alarm && alarmRule.stations.includes(s.station);
    infoTag.textContent = PIPE_LABEL[s.type];
    infoTag.style.background = PIPE_COLOR[s.type];
    infoTag.style.color = '#fff';
    infoName.textContent = s.id;
    infoSub.textContent = s.name + ' · ' + NET.cfg.name;
    infoDl.innerHTML = [
      ['管线编号', s.id],
      ['管线类型', PIPE_LABEL[s.type]],
      ['管径', 'DN' + s.dn],
      ['长度', pipeLen(s).toFixed(0) + ' m'],
      ['所属管网', NET.cfg.name],
      ['关联换热站', st ? st.name : '—'],
      ['映射指标', s.type === 'p1s' ? '一次侧供水温度' : s.type === 'p1r' ? '一次侧回水温度' : '二次侧供水温度'],
      ['当前值', fmt(S[s.type === 'p1r' ? 'p_net_return_temperature' : s.type === 'p2r' ? 'p_hc1_return_temperature' : s.type === 'p1s' ? 'p_net_supply_temperature' : 's_hc1_supply_temperature'][idx], 1) + ' ℃']
    ].map(([k, v]) => '<dt>' + k + '</dt><dd>' + v + '</dd>').join('');
    infoState.className = 'state ' + (bad ? 'bad' : 'ok');
    infoState.textContent = bad ? '异常：该管段处于超温告警（演示）' : '未触发演示阈值（非真实检测）';
  } else if (s.kind === 'station') {
    const cnt = NET.pipes.filter(p => p.station === s.id).length;
    const bad = alarm && alarmRule.stations.includes(s.id);
    infoTag.textContent = '换热站'; infoTag.style.background = '#2D9FB0'; infoTag.style.color = '#fff';
    infoName.textContent = s.name;
    infoSub.textContent = NET.cfg.name + ' · ' + s.id;
    infoDl.innerHTML = [
      ['换热站编号', s.id],
      ['所属管网', NET.cfg.name],
      ['关联管线', cnt + ' 段'],
      ['一次供水', fmt(S.p_net_supply_temperature[idx], 1) + ' ℃'],
      ['二次供水', fmt(S.s_hc1_supply_temperature[idx], 1) + ' ℃'],
      ['二次回水', fmt(S.p_hc1_return_temperature[idx], 1) + ' ℃'],
      ['热功率', fmt(S.p_net_meter_heat_power[idx], 0) + ' kW'],
      ['流量', fmt(S.p_net_meter_flow[idx], 0) + ' L/h']
    ].map(([k, v]) => '<dt>' + k + '</dt><dd>' + v + '</dd>').join('');
    infoState.className = 'state ' + (bad ? 'bad' : 'ok');
    infoState.textContent = bad ? '异常：二次供水超温（演示映射）' : '未触发演示阈值（非真实检测）';
  } else {
    const cnt = NET.pipes.filter(p => !p.station).length;
    infoTag.textContent = '热源厂'; infoTag.style.background = '#E07A2F'; infoTag.style.color = '#fff';
    infoName.textContent = s.name;
    infoSub.textContent = NET.cfg.name + ' · 热源';
    infoDl.innerHTML = [
      ['热源厂', s.name],
      ['所属管网', NET.cfg.name],
      ['出口干管', cnt + ' 段'],
      ['一次供水', fmt(S.p_net_supply_temperature[idx], 1) + ' ℃'],
      ['一次回水', fmt(S.p_net_return_temperature[idx], 1) + ' ℃'],
      ['总热功率', fmt(S.p_net_meter_heat_power[idx], 0) + ' kW'],
      ['总流量', fmt(S.p_net_meter_flow[idx], 0) + ' L/h']
    ].map(([k, v]) => '<dt>' + k + '</dt><dd>' + v + '</dd>').join('');
    infoState.className = 'state ok';
    infoState.textContent = '正常：热源出力跟随室外温度';
  }
}
const originalRenderInfo=renderInfo; renderInfo=()=>{originalRenderInfo();if(selected){const rule=alarm && (alarmRule.stations.includes(selected.id)||alarmRule.stations.includes(selected.station));if(rule&&selected.kind==='station')infoDl.insertAdjacentHTML('beforeend','<dt>关联异常管线</dt><dd>'+NET.pipes.filter(p=>p.station===selected.id).map(p=>p.id).join('、')+'</dd>');infoDl.insertAdjacentHTML('beforeend','<dt>演示时间</dt><dd>'+heat.t[idx]+'</dd><dt>演示触发条件</dt><dd>二次供水温度 &gt; 80 ℃</dd>');if(rule)infoState.textContent='演示异常：当前 '+fmt(S[alarmRule.metric][idx],1)+' ℃；未联动真实检测';}};
$('#infoClose').onclick = () => { stopFocus();info.classList.remove('show'); selected = null; render(); };

/* ---------- toast ---------- */
let toastTimer = null;
function toast(t) {
  const el = $('#toast');
  el.textContent = t; el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = later(() => el.classList.remove('show'), 3200);
}

/* ---------- 启动 ---------- */
listenWindow('keydown', e => {
  if (e.key === 'r' || e.key === 'R') $('#btnReset').click();
});
function boot() {
  resize();
  const q = new URLSearchParams(location.search);
  const segQ = q.get('seg') || 'seg-5';
  const segCfg = NETS.find(n => n.id === segQ) || NETS[NETS.length - 1];
  entSel.value = segCfg.ent;
  fillNets(segCfg.ent, segCfg.net);
  segSel.value = segCfg.id;
  loadSeg(segCfg.id);
  const m = q.get('mode');
  if (m && ['ground', 'under', 'clear', 'cut'].includes(m)) {
    mode = m;
    document.querySelectorAll('#modeSeg button').forEach(x => x.classList.toggle('on', x.dataset.mode === m));
    $('#gridOv').classList.toggle('on', m === 'cut');
  }
  const ti = parseInt(q.get('t') || '', 10);
  setIdx(Number.isFinite(ti) ? ti : SNAP_FALLBACK);
  const sel = q.get('sel');
  if (sel) {
    const st = NET.city.stations.find(s => s.id === sel);
    if (st) selectObject({kind:'station',obj:st});
  }
  later(() => { $('#hint').style.opacity = '0'; }, 6000);
}
boot();

const observer=new ResizeObserver(resize);observer.observe(root);
return {setIndex:setIdx,count:N,times:heat.t,firstAlarm:heat.v[alarmRule.metric].findIndex(v=>v>alarmRule.threshold),dispose(){stopFocus();abort.abort();observer.disconnect();timers.forEach(clearTimeout);marks.remove();root.querySelectorAll('*').forEach(el=>{el.onclick=null;el.onchange=null});}};
}
