"""Local data service, persisted detection queue and trusted model interface."""
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from pydantic import ValidationError
from starlette.exceptions import HTTPException
from starlette.datastructures import UploadFile
from starlette.concurrency import run_in_threadpool

from .errors import ServiceError
from .model_adapter import ModelService
from .registry import ROOT, ModelRegistry
from .schemas import ALL_FIELDS, DetectionCreate, EmptyRequest, ImportManifest, InferenceInput, InferenceOutput, OrganizationCreate, OrganizationUpdate, StationCreate, ReportCreate, ReportNote, ReportRevision
from .storage import LocalStore
from .datasets import DatasetService, MAX_CSV_BYTES, time_query
from .detections import DetectionService, DetectionWorker
from .reports import ReportService
from . import SERVICE_VERSION
from .control import DesktopControl
from .locking import DataDirectoryLease

logger = logging.getLogger("shad.api")
MAX_BODY_BYTES = 5 * 1024 * 1024
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def local_origin(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "http" and parsed.hostname in LOOPBACK
                and parsed.username is None and parsed.password is None
                and not parsed.path and not parsed.query and not parsed.fragment
                and (parsed.port is None or 1 <= parsed.port <= 65535))
    except ValueError:
        return False


class LocalBoundary:
    """ASGI boundary, including chunked bodies; no CORS or proxy header trust."""
    def __init__(self, app, dev_origins: tuple[str, ...] = ()):
        if any(not local_origin(origin) for origin in dev_origins):
            raise ValueError("开发 Origin 必须为明确的本机 HTTP 地址")
        self.app = app
        self.dev_origins = set(dev_origins)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope["headers"]}

        async def send_headers(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-content-type-options", b"nosniff"), (b"cache-control", b"no-store"),
                    (b"x-request-id", request_id.encode()), (b"cross-origin-resource-policy", b"same-origin"),
                ]
            await send(message)

        async def reject(code, message, status):
            response = JSONResponse({"requestId": request_id,
                                     "error": ServiceError(code, message, status).payload()}, status)
            await response(scope, receive, send_headers)

        host_origin = "http://" + headers.get("host", "")
        if not local_origin(host_origin):
            return await reject("LOCAL_ACCESS_REQUIRED", "仅允许本机地址访问服务。", 403)
        if scope["method"] not in ("GET", "HEAD", "OPTIONS"):
            upload = scope["path"].rstrip("/") == "/api/datasets/import"
            body_limit = MAX_CSV_BYTES + 1024 * 1024 if upload else MAX_BODY_BYTES
            origin = headers.get("origin")
            if origin is not None and origin not in {host_origin, *self.dev_origins}:
                return await reject("ORIGIN_REJECTED", "请求来源不在本机允许列表中。", 403)
            if headers.get("sec-fetch-site") == "cross-site":
                return await reject("ORIGIN_REJECTED", "不允许跨站点写入本机服务。", 403)
            try:
                content_length = int(headers.get("content-length", "0"))
                if content_length < 0:
                    raise ValueError()
            except ValueError:
                return await reject("INVALID_REQUEST", "请求长度非法。", 400)
            if content_length > body_limit:
                return await reject("REQUEST_TOO_LARGE", "请求体超过该接口允许的大小。", 413)
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > body_limit:
                    return await reject("REQUEST_TOO_LARGE", "请求体超过该接口允许的大小。", 413)
                if not message.get("more_body", False):
                    break
            sent = False
            original_receive = receive

            async def replay():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await original_receive()

            receive = replay
        await self.app(scope, receive, send_headers)


class Envelope(BaseModel):
    requestId: str
    data: dict


class InferenceEnvelope(BaseModel):
    requestId: str
    data: InferenceOutput


class FailureEnvelope(BaseModel):
    requestId: str
    error: dict


def create_app(registry_path: Path | None = None, *, registry: ModelRegistry | None = None,
               dev_origins: tuple[str, ...] = (), frontend_dir: Path | None = None,
               data_dir: Path | None = None, lease: DataDirectoryLease | None = None,
               control: DesktopControl | None = None) -> FastAPI:
    store = LocalStore(data_dir or Path(os.environ.get("SHAD_DATA_DIR", ROOT / "backend/data")))
    configured = registry or ModelRegistry(registry_path)
    store.register(configured.config)
    registry = ModelRegistry(config=store.registry_config(), artifact_root=configured.artifact_root)
    registry.cache = configured.cache
    service = ModelService(registry)
    datasets_service = DatasetService(store)
    detections_service = DetectionService(store, service)
    reports_service = ReportService(store)
    worker = DetectionWorker(detections_service, lease)

    @asynccontextmanager
    async def lifespan(app):
        worker.start()
        try:
            yield
        finally:
            await run_in_threadpool(worker.close)

    app = FastAPI(title="SHAD 本机服务", version=SERVICE_VERSION, docs_url=None, redoc_url=None, lifespan=lifespan,
                  openapi_url="/api/openapi.json",
                  description="本地数据、已训练模型、后台批次检测及版本化报告存档；原因诊断尚未启用。")
    app.add_middleware(LocalBoundary, dev_origins=dev_origins)
    app.state.model_service = service
    app.state.store = store
    app.state.detections = detections_service
    app.state.reports = reports_service
    app.state.worker = worker

    def ok(request: Request, data):
        return {"requestId": request.state.request_id, "data": data}

    def page(request: Request, values: list, page: int, size: int):
        return ok(request, {"items": values[(page - 1) * size:page * size],
                            "page": page, "pageSize": size, "total": len(values)})

    @app.exception_handler(ServiceError)
    async def service_error(request, exc):
        if exc.status >= 500:
            logger.error("%s request=%s", exc.code, request.state.request_id, exc_info=exc)
        return JSONResponse({"requestId": request.state.request_id, "error": exc.payload()}, exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        details = [{"field": ".".join(map(str, e["loc"])), "reason": e["type"]}
                   for e in exc.errors()]
        status = 400 if any(e["type"] == "json_invalid" for e in exc.errors()) else 422
        error = ServiceError("INVALID_REQUEST", "请求结构或字段格式不正确。", status, details=details)
        return JSONResponse({"requestId": request.state.request_id, "error": error.payload()}, status)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        error = ServiceError("NOT_FOUND" if exc.status_code == 404 else "INVALID_REQUEST",
                             "接口或资源不存在。" if exc.status_code == 404 else
                             "请求方法不支持。" if exc.status_code == 405 else "请求格式错误，请检查上传表单。", exc.status_code)
        return JSONResponse({"requestId": request.state.request_id, "error": error.payload()}, exc.status_code,
                            headers=exc.headers)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        logger.exception("Unhandled request=%s", request.state.request_id)
        error = ServiceError("INTERNAL_ERROR", "服务内部错误，请查看本机日志。", 500)
        return JSONResponse({"requestId": getattr(request.state, "request_id", uuid4().hex),
                             "error": error.payload()}, 500)

    @app.get("/api/runtime", response_model=Envelope)
    def runtime(request: Request):
        return ok(request, {"serviceVersion": SERVICE_VERSION, "contractVersion": "1.0", "mode": "local",
                            "desktop": control.identity() if control else {"managed": False},
                            "capabilities": {"organizationManagement": True, "dataImport": True, "anomalyDetection": worker.available,
                                             "causeDiagnosis": False, "reportPersistence": True,
                                             "offlineDetection": worker.available},
                            "storage": {"schemaVersion": 4, "datasetsPersistent": True, "detectionsPersistent": True, "reportsPersistent": True},
                            "modelInterface": {"available": True, "persisted": False, "maxSamples": 5000}})

    @app.post('/api/desktop/stop', response_model=Envelope)
    def desktop_stop(request: Request, body: EmptyRequest,
                     key: str = Header('', alias='X-SHAD-Control', max_length=128)):
        if control is None:
            raise ServiceError('DESKTOP_UNMANAGED', '此服务未通过本机启动入口运行，请在原启动窗口停止。', 409)
        if not secrets.compare_digest(key.encode('utf-8'), control.token.encode('ascii')):
            raise ServiceError('DESKTOP_CONTROL_REJECTED', '停止凭据不匹配，未执行操作。', 403)
        control.on_stop()
        return ok(request, {'stopping': True, 'instanceId': control.instance_id})

    @app.get("/api/stations", response_model=Envelope)
    def stations(request: Request, segmentId: str | None = None,
                 page_number: int = Query(1, alias="page", ge=1),
                 pageSize: int = Query(20, ge=1, le=500)):
        items = store.stations(segmentId)
        return page(request, items, page_number, pageSize)

    @app.post("/api/stations", response_model=Envelope, status_code=201)
    def create_station(request: Request, body: StationCreate):
        station = store.create_station(body)
        registry.stations[station["id"]] = station
        return ok(request, station)

    @app.get("/api/organizations", response_model=Envelope)
    def organizations(request: Request):
        return ok(request, store.organizations())

    @app.patch('/api/organizations/{kind}/{identifier}', response_model=Envelope)
    def update_organization(request: Request, kind: Literal['enterprises', 'networks', 'segments'],
                            identifier: str, body: OrganizationUpdate):
        return ok(request, store.update_organization(kind, identifier, body))

    @app.post("/api/enterprises", response_model=Envelope, status_code=201)
    def enterprise(request: Request, body: OrganizationCreate):
        return ok(request, store.create_organization("enterprises", body))

    @app.post("/api/networks", response_model=Envelope, status_code=201)
    def network(request: Request, body: OrganizationCreate):
        return ok(request, store.create_organization("networks", body))

    @app.post("/api/segments", response_model=Envelope, status_code=201)
    def segment(request: Request, body: OrganizationCreate):
        return ok(request, store.create_organization("segments", body))

    @app.get("/api/models", response_model=Envelope)
    def models(request: Request, stationId: str | None = None,
               page_number: int = Query(1, alias="page", ge=1),
               pageSize: int = Query(20, ge=1, le=500)):
        return page(request, registry.list_models(stationId), page_number, pageSize)

    @app.post("/api/model-inferences", response_model=InferenceEnvelope,
              responses={code: {"model": FailureEnvelope} for code in (400, 403, 404, 413, 422, 500, 503)})
    def infer(request: Request, body: InferenceInput):
        return ok(request, service.infer(body))

    @app.post("/api/datasets/import", response_model=Envelope, status_code=201,
              openapi_extra={"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
                  "type": "object", "required": ["file", "manifest"], "properties": {
                      "file": {"type": "string", "format": "binary"}, "manifest": {"type": "string", "description": "ImportManifest JSON"}}}}}}})
    async def import_dataset(request: Request):
        if not request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
            raise ServiceError("INVALID_REQUEST", "请通过 multipart/form-data 上传 file 和 manifest。", 400)
        form = await request.form(max_files=1, max_fields=1, max_part_size=64 * 1024)
        try:
            file, manifest = form.get("file"), form.get("manifest")
            if set(form.keys()) != {"file", "manifest"} or not isinstance(file, UploadFile) or not isinstance(manifest, str):
                raise ServiceError("INVALID_REQUEST", "上传表单必须恰好包含一个 file 和一个 manifest。", 400)
            try:
                body = ImportManifest.model_validate_json(manifest)
            except ValidationError as exc:
                raise ServiceError("INVALID_REQUEST", "导入说明格式错误，请核对字段映射、分隔符和单位。",
                                   details=[{"field": ".".join(map(str, e["loc"])), "reason": e["type"]} for e in exc.errors()]) from exc
            raw = await file.read(MAX_CSV_BYTES + 1)
            return ok(request, await run_in_threadpool(datasets_service.import_csv, raw, body))
        finally:
            await form.close()

    @app.get("/api/datasets", response_model=Envelope)
    def datasets(request: Request, stationId: str | None = None,
                 page_number: int = Query(1, alias="page", ge=1), pageSize: int = Query(20, ge=1, le=500)):
        return ok(request, store.datasets(stationId, page_number, pageSize))

    @app.get("/api/datasets/{dataset_id}", response_model=Envelope)
    def dataset(dataset_id: str, request: Request):
        return ok(request, store.dataset(dataset_id))

    @app.get("/api/datasets/{dataset_id}/samples", response_model=Envelope)
    def samples(dataset_id: str, request: Request, start: str | None = None, end: str | None = None,
                fields: str | None = None, page_number: int = Query(1, alias="page", ge=1),
                pageSize: int = Query(20, ge=1, le=500)):
        selected = fields.split(",") if fields is not None else None
        if selected is not None and (not selected or len(selected) != len(set(selected)) or not set(selected).issubset(ALL_FIELDS)):
            raise ServiceError("INVALID_REQUEST", "查询字段重复或不受支持。")
        start_us, end_us = time_query(start, end)
        return ok(request, store.samples(dataset_id, start_us, end_us, selected, page_number, pageSize))

    @app.get("/api/detections", response_model=Envelope)
    def detection_history(request: Request, stationId: str | None = None, segmentId: str | None = None,
                          status: Literal['queued', 'running', 'success', 'failed'] | None = None,
                          page_number: int = Query(1, alias='page', ge=1), pageSize: int = Query(20, ge=1, le=500)):
        return ok(request, detections_service.repo.list(stationId, segmentId, status, page_number, pageSize))

    def worker_required():
        if not worker.available:
            raise ServiceError('CAPABILITY_UNAVAILABLE', '后台检测执行器尚未运行，请启动或重启本机服务。', 503, True)

    @app.post('/api/detections', response_model=Envelope, status_code=202)
    def create_detection(request: Request, body: DetectionCreate,
                         key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9._:-]+$')):
        worker_required()
        task = detections_service.create(body, key)
        worker.wake.set()
        return ok(request, task)

    @app.get('/api/detections/{task_id}', response_model=Envelope)
    def detection_task(task_id: str, request: Request):
        return ok(request, detections_service.repo.task(task_id))

    @app.post('/api/detections/{task_id}/retry', response_model=Envelope, status_code=202)
    def retry_detection(task_id: str, request: Request, body: EmptyRequest,
                        key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9._:-]+$')):
        worker_required()
        task = detections_service.retry(task_id, key)
        worker.wake.set()
        return ok(request, task)

    @app.get('/api/detections/{task_id}/result', response_model=Envelope)
    def detection_result(task_id: str, request: Request):
        return ok(request, detections_service.repo.result(task_id))

    @app.get('/api/detections/{task_id}/points', response_model=Envelope)
    def detection_points(task_id: str, request: Request, start: str | None = None, end: str | None = None,
                         page_number: int = Query(1, alias='page', ge=1), pageSize: int = Query(20, ge=1, le=500)):
        a, b = time_query(start, end)
        return ok(request, detections_service.repo.records(task_id, 'points', a, b, page_number, pageSize))

    @app.get('/api/detections/{task_id}/events', response_model=Envelope)
    def detection_events(task_id: str, request: Request, start: str | None = None, end: str | None = None,
                         page_number: int = Query(1, alias='page', ge=1), pageSize: int = Query(20, ge=1, le=500)):
        a, b = time_query(start, end)
        return ok(request, detections_service.repo.records(task_id, 'events', a, b, page_number, pageSize))

    @app.post('/api/reports', response_model=Envelope, status_code=201)
    def create_report(request: Request, body: ReportCreate,
                      key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9._:-]+$')):
        return ok(request, reports_service.create(body, key))

    @app.get('/api/reports', response_model=Envelope)
    def report_history(request: Request, detectionId: str | None = None, archived: bool | None = None,
                       page_number: int = Query(1, alias='page', ge=1), pageSize: int = Query(20, ge=1, le=500)):
        return ok(request, reports_service.list(detectionId, archived, page_number, pageSize))

    @app.get('/api/reports/{report_id}', response_model=Envelope)
    def report_detail(report_id: str, request: Request):
        return ok(request, reports_service.get(report_id))

    @app.patch('/api/reports/{report_id}/note', response_model=Envelope)
    def report_note(report_id: str, request: Request, body: ReportNote):
        return ok(request, reports_service.note(report_id, body))

    @app.post('/api/reports/{report_id}/archive', response_model=Envelope)
    def report_archive(report_id: str, request: Request, body: ReportRevision):
        return ok(request, reports_service.archive(report_id, body))

    @app.post('/api/reports/{report_id}/versions', response_model=Envelope, status_code=201)
    def report_version(report_id: str, request: Request, body: ReportRevision,
                       key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9._:-]+$')):
        return ok(request, reports_service.version(report_id, body, key))

    # Cause diagnosis remains capability-gated.
    @app.get("/api/diagnoses", response_model=Envelope)
    def empty_history(request: Request, page_number: int = Query(1, alias="page", ge=1),
                      pageSize: int = Query(20, ge=1, le=500)):
        return page(request, [], page_number, pageSize)

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"], include_in_schema=False)
    def unimplemented(path: str, request: Request):
        if path.split("/")[0] in {"datasets", "detections", "diagnoses", "reports", "stations"}:
            raise ServiceError("CAPABILITY_UNAVAILABLE", "此业务操作尚未开放；当前可登记站点、导入与查询数据，并验证模型接口。", 503)
        raise ServiceError("NOT_FOUND", "接口不存在。", 404)

    if frontend_dir is not None:
        frontend_dir = frontend_dir.resolve()
        if not (frontend_dir / "index.html").is_file():
            raise ValueError("找不到前端构建结果，请先运行 npm run build")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str, request: Request):
            candidate = (frontend_dir / path).resolve()
            if not candidate.is_relative_to(frontend_dir):
                raise ServiceError("NOT_FOUND", "资源不存在。", 404)
            if candidate.is_file():
                return FileResponse(candidate)
            if "." not in Path(path).name and "text/html" in request.headers.get("accept", ""):
                return FileResponse(frontend_dir / "index.html")
            raise ServiceError("NOT_FOUND", "资源不存在。", 404)
    return app
