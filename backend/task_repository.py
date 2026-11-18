"""Durable detection state. Publishing success and all results is one transaction."""
import json

from .datasets import instant
from .errors import ServiceError
from .storage import LocalStore, json_text, now


class TaskRepository:
    def __init__(self, store: LocalStore):
        self.store = store

    @staticmethod
    def _task(db, task_id):
        row = db.execute('SELECT task_json FROM detections WHERE id=?', (task_id,)).fetchone()
        if row is None:
            raise ServiceError('NOT_FOUND', '检测任务不存在。', 404)
        return json.loads(row[0])

    @staticmethod
    def _put(db, task):
        db.execute('UPDATE detections SET status=?,task_json=? WHERE id=?',
                   (task['status'], json_text(task), task['id']))

    def task(self, task_id):
        with self.store.connection() as db:
            return self._task(db, task_id)

    def input(self, task_id):
        with self.store.connection() as db:
            self._task(db, task_id)
            return json.loads(db.execute('SELECT input_json FROM detections WHERE id=?', (task_id,)).fetchone()[0])

    def lookup(self, operation, key, digest, db=None):
        if db is None:
            with self.store.connection() as connection:
                return self.lookup(operation, key, digest, connection)
        row = db.execute('SELECT digest,detection_id FROM idempotency_keys WHERE operation=? AND key=?', (operation, key)).fetchone()
        if row is None:
            return None
        if row['digest'] != digest:
            raise ServiceError('IDEMPOTENCY_CONFLICT', '此提交编号已用于其他配置，请重新发起检测。', 409)
        return self._task(db, row['detection_id'])

    def create(self, task, body, operation, key, digest):
        with self.store.connection(write=True) as db:
            db.execute('BEGIN IMMEDIATE')
            existing = self.lookup(operation, key, digest, db)
            if existing:
                return existing
            db.execute('INSERT INTO detections VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (task['id'], body['context']['stationId'], body['context']['segmentId'], body['datasetId'],
                        body['modelId'], body['modelVersion'], task['status'], task['createdAt'], json_text(task), json_text(body)))
            db.execute('INSERT INTO idempotency_keys VALUES(?,?,?,?)', (operation, key, digest, task['id']))
        return task

    def list(self, station_id, segment_id, status, page, size):
        terms, args = [], []
        for field, value in (('station_id', station_id), ('segment_id', segment_id), ('status', status)):
            if value is not None:
                terms.append(field + '=?'); args.append(value)
        where = ' WHERE ' + ' AND '.join(terms) if terms else ''
        with self.store.connection() as db:
            db.execute('BEGIN')
            total = db.execute('SELECT count(*) FROM detections' + where, args).fetchone()[0]
            rows = db.execute('SELECT task_json FROM detections' + where + ' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',
                              [*args, size, (page - 1) * size])
            return {'items': [json.loads(r[0]) for r in rows], 'page': page, 'pageSize': size, 'total': total}

    def recover(self):
        with self.store.connection(write=True) as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute("SELECT task_json FROM detections WHERE status='running'").fetchall():
                task = json.loads(row[0])
                task.update(status='failed', phase='failed', finishedAt=now(), progress=None,
                            error=ServiceError('TASK_INTERRUPTED', '上次软件退出时检测尚未完成，可以创建重试任务。', retryable=True).payload())
                self._put(db, task)

    def claim(self):
        with self.store.connection(write=True) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT task_json FROM detections WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchone()
            if row is None:
                return None
            task = json.loads(row[0])
            task.update(status='running', phase='validating', startedAt=now())
            self._put(db, task)
            return task

    def phase(self, task_id, phase):
        with self.store.connection(write=True) as db:
            db.execute('BEGIN IMMEDIATE')
            task = self._task(db, task_id)
            if task['status'] != 'running':
                raise ServiceError('TASK_STATE_CONFLICT', '任务已经结束，不能修改阶段。', 409)
            task['phase'] = phase
            self._put(db, task)

    def fail(self, task_id, error):
        with self.store.connection(write=True) as db:
            db.execute('BEGIN IMMEDIATE')
            task = self._task(db, task_id)
            if task['status'] != 'running':
                return
            task.update(status='failed', phase='failed', finishedAt=now(), error=error.payload(), progress=None)
            self._put(db, task)

    def complete(self, task_id, result, points, events):
        with self.store.connection(write=True) as db:
            db.execute('BEGIN IMMEDIATE')
            task = self._task(db, task_id)
            if task['status'] != 'running':
                raise ServiceError('TASK_STATE_CONFLICT', '任务已经结束，不能覆盖结果。', 409)
            db.execute('INSERT INTO detection_results VALUES(?,?)', (task_id, json_text(result)))
            db.executemany('INSERT INTO detection_points VALUES(?,?,?,?)',
                           [(task_id, i, instant(p['timestamp']).value // 1000, json_text(p)) for i, p in enumerate(points)])
            db.executemany('INSERT INTO detection_events VALUES(?,?,?,?,?)',
                           [(e['id'], task_id, instant(e['start']).value // 1000, instant(e['end']).value // 1000, json_text(e)) for e in events])
            task.update(status='success', phase='completed', finishedAt=now(), error=None, warnings=result['warnings'])
            self._put(db, task)

    def result(self, task_id):
        with self.store.connection() as db:
            task = self._task(db, task_id)
            if task['status'] != 'success':
                raise ServiceError('RESULT_NOT_READY', '检测尚未成功完成，请先查看任务状态。', 409)
            row = db.execute('SELECT payload FROM detection_results WHERE detection_id=?', (task_id,)).fetchone()
            if row is None:
                raise ServiceError('RESULT_UNAVAILABLE', '已完成任务的结果无法读取，请检查本地存储。', 503, True)
            return json.loads(row[0])

    def records(self, task_id, kind, start_us, end_us, page, size):
        self.result(task_id)
        table = {'points': 'detection_points', 'events': 'detection_events'}[kind]
        terms, args = ['detection_id=?'], [task_id]
        if start_us is not None:
            terms.append('time_us>=?' if kind == 'points' else 'end_us>=?'); args.append(start_us)
        if end_us is not None:
            terms.append('time_us<=?' if kind == 'points' else 'start_us<=?'); args.append(end_us)
        where = ' AND '.join(terms)
        order = 'time_us,position' if kind == 'points' else 'start_us,id'
        with self.store.connection() as db:
            total = db.execute(f'SELECT count(*) FROM {table} WHERE {where}', args).fetchone()[0]
            rows = db.execute(f'SELECT payload FROM {table} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?',
                              [*args, size, (page - 1) * size])
            return {'items': [json.loads(r[0]) for r in rows], 'page': page, 'pageSize': size, 'total': total}
