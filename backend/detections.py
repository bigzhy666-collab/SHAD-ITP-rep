"""Persisted batch detection; one worker, no training and no invented causes."""
import hashlib
import json
import logging
import threading
from statistics import median
from uuid import uuid4

from .datasets import DatasetService, instant, split_ranges, time_query
from .errors import ServiceError
from .locking import DataDirectoryLease
from .model_adapter import ModelService, blocks, prepare_frame
from .schemas import ALL_UNITS, FIELDS, PREPROCESSING_VERSION, DetectionCreate, InferenceInput
from .storage import LocalStore, now
from .task_repository import TaskRepository

logger = logging.getLogger('shad.detections')
SNAPSHOT_FIELDS = ('id', 'version', 'name', 'artifactChecksum', 'stationId', 'isDemo', 'trainingTimezone',
                   'featureMode', 'scoreKind', 'cyclic', 'adaptive', 'cThr', 'quantile')
DATASET_FIELDS = ('id', 'version', 'name', 'sourceChecksum', 'timezone', 'preprocessingVersion')


def digest(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def warnings_unique(items):
    return list({(w['code'], w['message']): {'code': w['code'], 'message': w['message']} for w in items}.values())


class DetectionService:
    def __init__(self, store: LocalStore, models: ModelService):
        self.store, self.models = store, models
        self.repo = TaskRepository(store)

    def validate(self, body: DetectionCreate, frozen=None):
        station = self.store.station(body.context.stationId)
        if any(station[f] != getattr(body.context, f) for f in ('enterpriseId', 'networkId', 'segmentId')):
            raise ServiceError('SOURCE_MISMATCH', '检测对象与换热站所属企业、管网、管段不一致。')
        if frozen is None:
            self.store.require_active_path(station)
        dataset = self.store.dataset(body.datasetId)
        if dataset['stationId'] != station['id']:
            raise ServiceError('SOURCE_MISMATCH', '数据集不属于当前换热站。')
        if dataset['status'] != 'ready':
            raise ServiceError('DATA_QUALITY_BLOCKED', '数据集存在阻断问题，请修正后重新导入。')
        registry = self.models.registry
        entry = registry.entries.get((body.modelId, body.modelVersion))
        if entry is None:
            raise ServiceError('NOT_FOUND', '模型版本未登记。', 404)
        if entry.stationId != station['id']:
            raise ServiceError('SOURCE_MISMATCH', '所选模型不适用于当前换热站。')
        if station['timezone'] != entry.trainingTimezone or dataset['timezone'] != station['timezone']:
            raise ServiceError('TIMEZONE_MISMATCH', '站点、数据集与模型训练时区必须一致。')
        start_us, end_us = time_query(body.range.start, body.range.end)
        if start_us < instant(dataset['start']).value // 1000 or end_us > instant(dataset['end']).value // 1000:
            raise ServiceError('TIME_RANGE_INVALID', '检测范围必须在数据集的首末采样之间。')
        records = self.store.samples(body.datasetId, start_us, end_us, None, 1, 5001)
        if not records['total']:
            raise ServiceError('DATA_EMPTY', '检测范围内没有标准化采样，请重新选择时间。')
        if records['total'] > 5000:
            raise ServiceError('DETECTION_LIMIT_EXCEEDED', '首版一次检测最多 5000 点，请缩小范围；不能未经验证地独立拆批拼接。')
        rows = records['items']
        columns = set(rows[0]['values'])
        units = {c['field']: c['unit'] for c in dataset['columns'] if c['field'] in columns}
        if any(ALL_UNITS.get(f) != unit for f, unit in units.items()):
            raise ServiceError('UNIT_UNSUPPORTED', '数据集标准单位与当前模型接口不匹配。')
        payload = InferenceInput.model_validate({
            'stationId': station['id'], 'modelId': body.modelId, 'modelVersion': body.modelVersion,
            'timezone': station['timezone'], 'units': units,
            'samples': [{'timestamp': r['timestamp'], 'values': r['values']} for r in rows]})
        frame, index = prepare_frame(payload)
        if len(index) > 1 and median((b.value - a.value) / 60e9 for a, b in zip(index, index[1:])) > 30.000001:
            raise ServiceError('SAMPLING_INTERVAL_UNSUPPORTED', '所选范围内采样过于稀疏，不兼容当前半小时持续性模型。')
        chunks = list(blocks(frame, index))  # Includes the selected range's core-missing gate.
        for a, b in [(0, len(rows)), *split_ranges(index)]:
            bad_fields = [f for f in FIELDS if sum(r['quality'].get(f, 'missing') != 'valid' for r in rows[a:b]) / (b - a) > .8]
            if bad_fields:
                raise ServiceError('DATA_QUALITY_BLOCKED', '所选范围或连续块内核心测点质量无效/缺失超过 80%，不能可靠检测。',
                                   details=[{'field': f, 'reason': '质量标记无效或缺失超过 80%'} for f in bad_fields])
        range_issues = []
        health_frame = frame.copy()
        health_frame.index = index
        DatasetService._sensor_report(health_frame, split_ranges(index),
                                      lambda code, field, count, message, blocking=False:
                                      range_issues.append({'code': code, 'field': field, 'message': message, 'blocking': blocking}))
        if any(i['blocking'] for i in range_issues):
            raise ServiceError('DATA_QUALITY_BLOCKED', '所选范围内室外测点质量异常，请核查并重新导入。',
                               details=[{'field': i['field'], 'reason': i['message']} for i in range_issues if i['blocking']])
        entry, model = registry.resolve(body.modelId, body.modelVersion)
        metadata = registry.metadata(entry, model)
        model_snapshot = {f: metadata[f] for f in SNAPSHOT_FIELDS}
        dataset_snapshot = {f: dataset[f] for f in DATASET_FIELDS}
        tree = self.store.organizations()
        context = {kind: {'id': obj['id'], 'name': obj['name']}
                   for kind, collection, key in (('enterprise', 'enterprises', 'enterpriseId'),
                                                 ('network', 'networks', 'networkId'), ('segment', 'segments', 'segmentId'))
                   for obj in tree[collection] if obj['id'] == station[key]}
        context['station'] = {f: station[f] for f in ('id', 'name', 'timezone')}
        selected_range = {key: instant(getattr(body.range, key)).tz_convert(station['timezone']).isoformat() for key in ('start', 'end')}
        if frozen:
            if frozen['datasetSnapshot'] != dataset_snapshot or frozen['modelSnapshot'] != model_snapshot or frozen['range'] != selected_range:
                raise ServiceError('SOURCE_SNAPSHOT_CHANGED', '任务冻结的数据或模型配置已变化，不能用新来源覆盖原结果。')
            context = frozen['contextSnapshot']
        warnings = [{'code': i['code'], 'message': '数据集提示：' + i['message']} for i in dataset['issues'] if not i['blocking']]
        warnings.extend({'code': i['code'], 'message': i['message']} for i in range_issues)
        if any(len(chunk) < model.c_thr for _, chunk, _ in chunks):
            warnings.append({'code': 'CONFIRMATION_CONTEXT_SHORT', 'message': '部分连续块不足持续性确认所需点数，无确认事件不等于状态正常。'})
        return {'contextSnapshot': context, 'datasetSnapshot': dataset_snapshot, 'modelSnapshot': model_snapshot,
                'range': selected_range, 'warnings': warnings_unique(warnings), 'payload': payload,
                'qualityIssueCount': sum(q != 'valid' for r in rows for q in r['quality'].values())}

    def create(self, body: DetectionCreate, key, retry_of=None):
        operation = f'retry:{retry_of}' if retry_of else 'create-detection'
        content = body.model_dump()
        checksum = digest(content)
        existing = self.repo.lookup(operation, key, checksum)
        if existing:
            return existing
        previous = self.repo.task(retry_of) if retry_of else None
        if previous and (previous['status'] != 'failed' or not previous['error']['retryable']):
            raise ServiceError('TASK_NOT_RETRYABLE', '只有可重试的失败任务可以创建重试。', 409)
        validated = self.validate(body, previous)
        task = {f: validated[f] for f in ('contextSnapshot', 'datasetSnapshot', 'modelSnapshot', 'range', 'warnings')}
        task.update(id='det-' + uuid4().hex, name=body.name, status='queued', phase='queued', progress=None,
                    createdAt=now(), startedAt=None, finishedAt=None, error=None, retryOf=retry_of)
        return self.repo.create(task, content, operation, key, checksum)

    def retry(self, task_id, key):
        body = DetectionCreate.model_validate(self.repo.input(task_id))
        return self.create(body, key, task_id)

    def execute(self, task, stop):
        body = DetectionCreate.model_validate(self.repo.input(task['id']))
        validated = self.validate(body, task)
        self.repo.phase(task['id'], 'detecting')
        while not stop.is_set():
            try:
                output = self.models.infer(validated['payload'])
                break
            except ServiceError as exc:
                if exc.code != 'MODEL_BUSY':
                    raise
                stop.wait(.1)
        else:
            raise ServiceError('TASK_INTERRUPTED', '软件关闭，检测未完成，可以创建重试。', retryable=True)
        if stop.is_set():
            raise ServiceError('TASK_INTERRUPTED', '软件关闭时检测尚未保存，可以创建重试。', retryable=True)
        if any(output['modelSnapshot'][f] != task['modelSnapshot'][f] for f in SNAPSHOT_FIELDS):
            raise ServiceError('SOURCE_SNAPSHOT_CHANGED', '模型执行配置与任务快照不一致。')
        events = [{**e, 'id': f"event-{task['id']}-{i:03d}", 'detectionId': task['id'],
                   'stationId': body.context.stationId} for i, e in enumerate(output['segments'], 1)]
        for event in events:
            at_start = instant(event['start']) == instant(task['range']['start'])
            at_end = instant(event['end']) == instant(task['range']['end'])
            event['boundary'] = ('touches_both' if at_start and at_end else 'touches_range_start' if at_start else
                                 'touches_range_end' if at_end else 'within_range')
        summary = {**output['summary'], 'qualityIssueCount': validated['qualityIssueCount']}
        result = {f: task[f] for f in ('contextSnapshot', 'datasetSnapshot', 'modelSnapshot', 'range')}
        result.update(detectionId=task['id'], computedAt=now(), preprocessingVersion=PREPROCESSING_VERSION, sampleRange=output['range'],
                      summary=summary, warnings=warnings_unique([*validated['warnings'], *output['warnings']]),
                      links={kind: f"/api/detections/{task['id']}/{kind}" for kind in ('points', 'events')})
        self.repo.phase(task['id'], 'saving')
        self.repo.complete(task['id'], result, output['points'], events)


class DetectionWorker:
    def __init__(self, service: DetectionService, lease: DataDirectoryLease | None = None):
        self.service = service
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.lease = lease or DataDirectoryLease(service.store.directory)
        if self.lease.path.resolve() != (service.store.directory / 'service.lock').resolve():
            raise ValueError('服务锁与数据目录不一致。')

    @property
    def available(self):
        return self.thread is not None and self.thread.is_alive() and not self.stop.is_set()

    def start(self):
        if self.thread and self.thread.is_alive():
            raise RuntimeError('检测执行器仍在运行，不能重复启动。')
        if self.lease.handle is None:
            self.lease.acquire()
        try:
            self.service.repo.recover()
            self.stop.clear()
            self.thread = threading.Thread(target=self.run, daemon=True, name='shad-detection-worker')
            self.thread.start()
        except BaseException:
            self.lease.release()
            raise

    def close(self):
        self.stop.set(); self.wake.set()
        if self.thread:
            self.thread.join(timeout=10)
        # The thread retains the lease until it exits, even if a model ignores shutdown.
        if not self.thread or not self.thread.is_alive():
            self.lease.release()

    def run(self):
        try:
            while not self.stop.is_set():
                task = None
                try:
                    task = self.service.repo.claim()
                    if task:
                        self.service.execute(task, self.stop)
                        continue
                except Exception as exc:
                    logger.exception('Detection execution failed')
                    if task:
                        error = exc if isinstance(exc, ServiceError) else ServiceError(
                            'TASK_EXECUTION_FAILED', '检测执行失败，请按任务编号查看日志并重试。', 500, True)
                        try:
                            self.service.repo.fail(task['id'], error)
                        except Exception:
                            logger.exception('Unable to persist task failure; restart recovery required')
                self.wake.wait(.25)
                self.wake.clear()
        finally:
            self.lease.release()
