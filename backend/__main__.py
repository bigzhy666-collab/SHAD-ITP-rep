import argparse
import json
import logging
import os
import socket
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

import uvicorn

from .app import create_app
from .control import DesktopControl
from .desktop import CONTROL_FILE, control_record
from .errors import ServiceError
from .locking import DataDirectoryLease
from .registry import ROOT, ModelRegistry


def main(argv=None):
    parser = argparse.ArgumentParser(description='SHAD 本机服务（仅加载已训练模型）')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--registry', type=Path, help='管理员登记的模型注册表；默认不加载示例模型')
    parser.add_argument('--model-dir', type=Path, help='管理员管理的可信模型目录；默认 ml/models')
    parser.add_argument('--dev-origin', action='append', default=[], help='允许的本机开发 Origin')
    parser.add_argument('--serve-frontend', action='store_true', help='同时提供 frontend/dist 前端资源')
    parser.add_argument('--data-dir', type=Path, help='数据库、CSV、日志目录；此开发入口默认 backend/data')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('端口必须在 1..65535')
    directory = (args.data_dir or Path(os.environ.get('SHAD_DATA_DIR', ROOT / 'backend/data'))).resolve()
    listener = socket.socket()
    lease, handler, worker, control = None, None, None, None
    record_path = directory / CONTROL_FILE
    try:
        # Reserve the port before touching the database, avoiding partial startup on conflicts.
        if os.name == 'nt':
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(('127.0.0.1', args.port))
            listener.listen(2048)
        except OSError as exc:
            raise RuntimeError(f'本机端口 {args.port} 已占用或无法使用，请停止原服务或指定其他端口。') from exc
        directory.mkdir(parents=True, exist_ok=True)
        lease = DataDirectoryLease(directory)
        lease.acquire()  # Includes migrations/registry writes; maintenance owns the same lease.
        logs = directory / 'logs'
        logs.mkdir(exist_ok=True)
        handler = RotatingFileHandler(logs / 'service.log', maxBytes=1024 * 1024, backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
        logging.getLogger('shad').addHandler(handler)
        logging.getLogger('shad').setLevel(logging.INFO)
        instance = os.environ.pop('SHAD_CONTROL_INSTANCE', '')
        token = os.environ.pop('SHAD_CONTROL_TOKEN', '')
        if instance or token:
            control = DesktopControl(instance, token, lambda: setattr(server, 'should_exit', True))
        configured = ModelRegistry(args.registry, artifact_root=args.model_dir)
        app = create_app(registry=configured, dev_origins=tuple(args.dev_origin), lease=lease, control=control,
                         frontend_dir=ROOT / 'frontend/dist' if args.serve_frontend else None, data_dir=directory)
        worker = app.state.worker
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port, proxy_headers=False, workers=1,
                                             timeout_graceful_shutdown=10))
        if control:
            pending = directory / ('.desktop-' + uuid4().hex + '.tmp')
            try:
                with pending.open('x', encoding='utf-8') as output:
                    os.chmod(pending, 0o600)
                    json.dump({'instanceId': instance, 'token': token, 'pid': os.getpid(), 'port': args.port}, output)
                    output.flush(); os.fsync(output.fileno())
                os.replace(pending, record_path)
            finally:
                pending.unlink(missing_ok=True)
        print(f'SHAD 本机服务：http://127.0.0.1:{args.port}；数据目录：{directory}', flush=True)
        server.run(sockets=[listener])
        return 0 if server.started else 2
    except (OSError, ValueError, RuntimeError, ServiceError) as exc:
        print(f'SHAD 启动失败：{exc}', file=sys.stderr)
        return 2
    finally:
        if control:
            try:
                record = control_record(directory)
                if record and record['instanceId'] == control.instance_id:
                    record_path.unlink()
            except (OSError, ValueError, RuntimeError):
                logging.getLogger('shad').warning('启动记录清理失败；下次启动会检查实际实例。')
        if lease and (worker is None or not worker.thread or not worker.thread.is_alive()):
            lease.release()
        listener.close()
        if handler:
            logging.getLogger('shad').removeHandler(handler)
            handler.close()


if __name__ == '__main__':
    raise SystemExit(main())
