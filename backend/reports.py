"""Immutable detection evidence snapshots, editable notes and versioned archives."""
import hashlib
import json
from uuid import uuid4

from .errors import ServiceError
from .storage import LocalStore, json_text, now
from .task_repository import TaskRepository


class ReportService:
    def __init__(self, store: LocalStore):
        self.store = store

    @staticmethod
    def _get(db, report_id):
        row = db.execute('SELECT report_json FROM reports WHERE id=?', (report_id,)).fetchone()
        if row is None:
            raise ServiceError('NOT_FOUND', '报告不存在。', 404)
        return json.loads(row[0])

    @staticmethod
    def _revision(report, expected):
        if report['revision'] != expected:
            raise ServiceError('REVISION_CONFLICT', '报告已在其他窗口更新。请核对最新版本后再保存，当前输入尚未覆盖。', 409)

    @staticmethod
    def _put(db, report, insert=False):
        if insert:
            db.execute('INSERT INTO reports VALUES(?,?,?,?,?,?,?)',
                       (report['id'], report['seriesId'], report['version'], report['detectionId'],
                        report['createdAt'], report['archivedAt'], json_text(report)))
        else:
            db.execute('UPDATE reports SET archived_at=?,report_json=? WHERE id=?',
                       (report['archivedAt'], json_text(report), report['id']))

    def _submit(self, operation, key, body, build):
        digest = hashlib.sha256(json_text(body).encode('utf-8')).hexdigest()
        with self.store.connection(write=True) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT digest,report_id FROM report_submissions WHERE operation=? AND key=?',
                             (operation, key)).fetchone()
            if row:
                if row['digest'] != digest:
                    raise ServiceError('IDEMPOTENCY_CONFLICT', '此提交编号已用于其他报告配置，请重新发起保存。', 409)
                return self._get(db, row['report_id'])
            report = build(db)
            self._put(db, report, insert=True)
            db.execute('INSERT INTO report_submissions VALUES(?,?,?,?)', (operation, key, digest, report['id']))
            return report

    def create(self, body, key):
        def build(db):
            task = TaskRepository._task(db, body.detectionId)
            if task['status'] != 'success':
                raise ServiceError('RESULT_NOT_READY', '仅成功完成的检测可以保存报告。', 409)
            if body.diagnosisId is not None:
                raise ServiceError('CAPABILITY_UNAVAILABLE', '原因诊断尚未接入，请保存不含原因诊断的阶段报告。', 503)
            row = db.execute('SELECT payload FROM detection_results WHERE detection_id=?', (task['id'],)).fetchone()
            if row is None:
                raise ServiceError('RESULT_UNAVAILABLE', '来源检测结果不完整，不能保存报告。', 503)
            result = json.loads(row[0])
            all_events = [json.loads(r[0]) for r in db.execute(
                'SELECT payload FROM detection_events WHERE detection_id=? ORDER BY start_us,id', (task['id'],))]
            selected = set(body.eventIds)
            station_id = task['contextSnapshot']['station']['id']
            events = [e for e in all_events if e['id'] in selected]
            if len(events) != len(body.eventIds) or any(
                    e['detectionId'] != task['id'] or e['stationId'] != station_id for e in events):
                raise ServiceError('SOURCE_MISMATCH', '所选事件必须全部来自当前成功检测和换热站。')
            points = [json.loads(r[0]) for r in db.execute(
                'SELECT payload FROM detection_points WHERE detection_id=? ORDER BY position', (task['id'],))]
            if (result['detectionId'] != task['id']
                    or any(result[f] != task[f] for f in ('contextSnapshot', 'modelSnapshot', 'datasetSnapshot', 'range'))
                    or len(points) != result['summary']['pointCount'] or len(all_events) != result['summary']['eventCount']):
                raise ServiceError('RESULT_UNAVAILABLE', '来源检测证据不完整或不一致，不能保存报告。', 503)
            report_id = uuid4().hex
            return {'id': report_id, 'seriesId': report_id, 'sourceReportId': None,
                    'title': task['contextSnapshot']['station']['name'] + '运行状态异常检测报告',
                    'detectionId': task['id'], 'diagnosisId': None, 'eventIds': [e['id'] for e in events],
                    'version': 1, 'revision': 1, 'createdAt': now(), 'archivedAt': None, 'note': '',
                    'snapshot': {'task': task, 'result': result, 'events': events, 'points': points, 'diagnosis': None}}
        return self._submit('create', key, body.model_dump(), build)

    def get(self, report_id):
        with self.store.connection() as db:
            return self._get(db, report_id)

    def list(self, detection_id, archived, page, size):
        terms, args = [], []
        if detection_id is not None:
            terms.append('detection_id=?'); args.append(detection_id)
        if archived is not None:
            terms.append('archived_at IS NOT NULL' if archived else 'archived_at IS NULL')
        where = ' WHERE ' + ' AND '.join(terms) if terms else ''
        with self.store.connection() as db:
            db.execute('BEGIN')
            total = db.execute('SELECT count(*) FROM reports' + where, args).fetchone()[0]
            # History never transfers thousands of curve points for every report.
            rows = db.execute("SELECT json_remove(report_json,'$.snapshot') FROM reports" + where +
                              ' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?', [*args, size, (page - 1) * size])
            return {'items': [json.loads(r[0]) for r in rows], 'page': page, 'pageSize': size, 'total': total}

    def note(self, report_id, body):
        with self.store.connection(write=True) as db:
            db.execute('BEGIN IMMEDIATE')
            report = self._get(db, report_id)
            self._revision(report, body.expectedRevision)
            if report['archivedAt']:
                raise ServiceError('REPORT_ARCHIVED', '归档版本不可修改备注，请创建新版本。', 409)
            if report['note'] != body.note:
                report.update(note=body.note, revision=report['revision'] + 1)
                self._put(db, report)
            return report

    def archive(self, report_id, body):
        with self.store.connection(write=True) as db:
            db.execute('BEGIN IMMEDIATE')
            report = self._get(db, report_id)
            # A lost success response may be retried with the immediately preceding revision.
            if report['archivedAt'] and body.expectedRevision in (report['revision'], report['revision'] - 1):
                return report
            self._revision(report, body.expectedRevision)
            if report['archivedAt']:
                raise ServiceError('REPORT_ARCHIVED', '报告已经归档。', 409)
            report.update(archivedAt=now(), revision=report['revision'] + 1)
            self._put(db, report)
            return report

    def version(self, report_id, body, key):
        def build(db):
            previous = self._get(db, report_id)
            self._revision(previous, body.expectedRevision)
            version = db.execute('SELECT max(version)+1 FROM reports WHERE series_id=?', (previous['seriesId'],)).fetchone()[0]
            # Carry the stored evidence and note forward; old versions remain byte-for-byte unchanged.
            return {**previous, 'id': uuid4().hex, 'sourceReportId': previous['id'], 'version': version,
                    'revision': 1, 'createdAt': now(), 'archivedAt': None}
        return self._submit('version:' + report_id, key, body.model_dump(), build)
