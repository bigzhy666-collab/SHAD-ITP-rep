const NETS = [
  {
    id: 'seg-1', name: '1号二次供热管段', ent: 'ent-1', net: 'net-1', seed: 20121, gw: 1500, gd: 1180, mainW: 26, roadW: 13, step: 148,
    plant: { x: -470, z: -330, name: '1#能源站' },
    stations: [
      { x: -300, z: -250, name: '1#换热站' }, { x: -300, z: -110, name: '2#换热站' },
      { x: -300, z: 40, name: '3#换热站' }, { x: -300, z: 190, name: '4#换热站' },
      { x: 10, z: 190, name: '5#换热站' }, { x: 10, z: -110, name: '6#换热站' }
    ],
    cam: { yaw: -0.62, pitch: 0.70, dist: 1250 }
  },
  {
    id: 'seg-2', name: '2号一次供热管段', ent: 'ent-1', net: 'net-1', seed: 3307, gw: 1320, gd: 1050, mainW: 22, roadW: 12, step: 132,
    plant: { x: 380, z: 330, name: '2#能源站' },
    stations: [
      { x: 210, z: 250, name: '1#换热站' }, { x: 210, z: 120, name: '2#换热站' },
      { x: 210, z: -10, name: '3#换热站' }, { x: 60, z: -10, name: '4#换热站' },
      { x: 60, z: 250, name: '5#换热站' }, { x: -110, z: 120, name: '6#换热站' }
    ],
    cam: { yaw: 2.35, pitch: 0.70, dist: 1180 }
  },
  {
    id: 'seg-3', name: '3号末端支路', ent: 'ent-1', net: 'net-1', seed: 9911, gw: 980, gd: 820, mainW: 18, roadW: 11, step: 118,
    plant: { x: -330, z: 250, name: '3#能源站' },
    stations: [
      { x: -140, z: 190, name: '1#换热站' }, { x: 60, z: 190, name: '2#换热站' },
      { x: 60, z: 20, name: '3#换热站' }, { x: -140, z: 20, name: '4#换热站' }
    ],
    cam: { yaw: -0.9, pitch: 0.72, dist: 900 }
  },
  {
    id: 'seg-4', name: '西区供热支线', ent: 'ent-1', net: 'net-2', seed: 5150, gw: 1560, gd: 1220, mainW: 28, roadW: 13, step: 162,
    plant: { x: -520, z: 0, name: '4#能源站' },
    stations: [
      { x: -300, z: -300, name: '1#换热站' }, { x: 100, z: -300, name: '2#换热站' },
      { x: 380, z: -60, name: '3#换热站' }, { x: 100, z: 260, name: '4#换热站' },
      { x: -300, z: 260, name: '5#换热站' }, { x: -300, z: -60, name: '6#换热站' }
    ],
    cam: { yaw: -1.1, pitch: 0.74, dist: 1420 }
  },
  {
    id: 'seg-5', name: '高新供热管段', ent: 'ent-2', net: 'net-3', seed: 8811, gw: 1420, gd: 1100, mainW: 24, roadW: 14, step: 156,
    plant: { x: 0, z: -400, name: '5#能源站' },
    stations: [
      { x: -260, z: -230, name: '1#换热站' }, { x: 40, z: -230, name: '2#换热站' },
      { x: 320, z: -230, name: '3#换热站' }, { x: -260, z: 30, name: '4#换热站' },
      { x: 40, z: 30, name: '5#换热站' }, { x: 320, z: 30, name: '6#换热站' }
    ],
    cam: { yaw: -0.05, pitch: 0.72, dist: 1320 }
  }
];

const TREE = [
  { id: 'ent-1', name: '北方热力有限责任公司', nets: [
    { id: 'net-1', name: '城北主力供热网', segs: ['seg-1', 'seg-2', 'seg-3'] },
    { id: 'net-2', name: '城西供热网', segs: ['seg-4'] }
  ]},
  { id: 'ent-2', name: '城东热力分公司', nets: [
    { id: 'net-3', name: '高新片区热网', segs: ['seg-5'] }
  ]}
];

/* ---------- 生成示意街区 ---------- */

export {NETS,TREE};
export const alarmRule={metric:"s_hc1_supply_temperature",threshold:80,stations:["S3"]} as const;
