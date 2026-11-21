"""Integration-only server. Explicit synthetic station; never a deployment registry."""
import argparse
import json
from pathlib import Path

import uvicorn

from backend.app import create_app
from backend.registry import ROOT, ModelRegistry
from backend.schemas import RegistryConfig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads((ROOT / 'backend/config/registry.example.json').read_text(encoding='utf-8'))
    # Deliberate UI integration fixture: synthetic input and an explicitly demo model.
    # This does not assert a Chinese deployment/training timezone for the real artifact.
    station = config['stations'][0]
    station.update(id='station-browser-fixture', name='合成输入验收站（仅测试）', code='BROWSER-TEST',
                   enterpriseId='ent-1', networkId='net-1', segmentId='seg-2', timezone='Asia/Shanghai')
    config['models'][0].update(id='model-browser-fixture', stationId=station['id'], name='接口验收示例模型',
                               trainingTimezone='Asia/Shanghai', isDemo=True,
                               description='仅验证前后端连接的合成样例，不能用于国内站点运行判断。')
    config['organizations'] = {}
    app = create_app(registry=ModelRegistry(config=RegistryConfig.model_validate(config)),
                     data_dir=args.data_dir, frontend_dir=ROOT / 'frontend/dist')
    uvicorn.run(app, host='127.0.0.1', port=args.port, proxy_headers=False)


if __name__ == '__main__':
    main()
