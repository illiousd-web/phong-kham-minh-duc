"""Read models and strictly guarded M0 mutations. Existing billing stays untouched."""
import json
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from .domain import ensure_open, invoice, revision
from .labels import VN_TZ, parse_day
from .manager_visits import fold_name, _utc_start


class AllergiesInput(BaseModel):
    allergies: str | None = Field(default=None, max_length=2000)

    @field_validator('allergies')
    @classmethod
    def clean(cls, value):
        return (value or '').strip() or None


class CloseInput(BaseModel):
    reason: Literal['Người bệnh bỏ về', 'Tạo nhầm', 'Khác']
    note: str = Field(default='', max_length=1000)

    @field_validator('note')
    @classmethod
    def clean(cls, value):
        return value.strip()


def doctor_queue(c, uid, day='', q=''):
    try:
        day = parse_day(day) or datetime.now(VN_TZ).date().isoformat()
        end = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
    except ValueError:
        raise HTTPException(422, 'Ngày phải có thật, dạng dd/mm/yyyy')
    # Number BEFORE filtering doctor/name/status, so the daily reception order is stable.
    rows = c.execute('''WITH daily AS (
        SELECT v.*,ROW_NUMBER() OVER (ORDER BY v.created_at,v.id) AS daily_number
        FROM visits v WHERE v.created_at>=? AND v.created_at<?)
        SELECT v.id,v.patient_id,v.status,v.created_at,v.daily_number,
        p.full_name AS patient_name,p.date_of_birth,p.sex,
        CASE WHEN v.status IN ('completed','cancelled') THEN v.status
          WHEN EXISTS(SELECT 1 FROM orders o WHERE o.visit_id=v.id AND o.status='pending_review') THEN 'results_ready'
          WHEN EXISTS(SELECT 1 FROM orders o WHERE o.visit_id=v.id AND o.status IN ('requested','ordered')) THEN 'waiting_results'
          WHEN EXISTS(SELECT 1 FROM orders o WHERE o.visit_id=v.id AND o.status='approved') THEN 'results_ready'
          ELSE v.status END AS queue_status
        FROM daily v JOIN patients p ON p.id=v.patient_id
        WHERE v.doctor_id=? AND v.status<>'cancelled' ORDER BY v.daily_number''',
        (_utc_start(day), _utc_start(end), uid)).fetchall()
    needle = fold_name(q[:100])
    return {'day': day, 'visits': [dict(r) for r in rows if needle in fold_name(r['patient_name'])]}


def install_doctor_workspace(app, db, principal, require, audit, visit_access, now):
    @app.put('/api/patients/{pid}/allergies')
    def update_allergies(pid: int, data: AllergiesInput, u=Depends(principal)):
        require(u, 'reception', 'doctor')
        with db(True) as c:
            if 'reception' not in u['roles'] and not c.execute(
                'SELECT 1 FROM visits WHERE patient_id=? AND doctor_id=?', (pid, u['id'])).fetchone():
                raise HTTPException(403, 'Không được sửa hồ sơ này')
            p = c.execute('SELECT allergies FROM patients WHERE id=?', (pid,)).fetchone()
            if not p:
                raise HTTPException(404, 'Không có bệnh nhân')
            if p['allergies'] != data.allergies:
                c.execute('UPDATE patients SET allergies=? WHERE id=?', (data.allergies, pid))
                # Full old/new values, never audit()'s 500-character truncation.
                c.execute('INSERT INTO audit_log(user_id,event,object_type,object_id,details,created_at) VALUES(?,?,?,?,?,?)',
                          (u['id'], 'patient_allergies_updated', 'patient', pid,
                           json.dumps({'old': p['allergies'], 'new': data.allergies}, ensure_ascii=False), now()))
            return {'allergies': data.allergies}

    @app.get('/api/doctor/queue')
    def queue(day: str = '', q: str = '', u=Depends(principal)):
        require(u, 'doctor')
        with db() as c:
            return doctor_queue(c, u['id'], day, q)

    @app.get('/api/visits/{vid}/patient-history')
    def patient_history(vid: int, u=Depends(principal)):
        require(u, 'doctor')
        with db(True) as c:
            v = visit_access(c, u, vid, clinical=True)
            rows = c.execute('''SELECT id,created_at,diagnosis FROM visits
                WHERE patient_id=? AND doctor_id=? AND (created_at<? OR (created_at=? AND id<?))
                ORDER BY created_at DESC,id DESC''', (v['patient_id'], u['id'], v['created_at'], v['created_at'], vid)).fetchall()
            result = []
            for r in rows:
                item = dict(r)
                item['prescriptions'] = [dict(x) for x in c.execute(
                    'SELECT drug_lines,instructions,status FROM prescriptions WHERE visit_id=?', (r['id'],))]
                item['results'] = [dict(x) for x in c.execute(
                    "SELECT name,result_text,status FROM orders WHERE visit_id=? AND result_text IS NOT NULL AND result_text<>''", (r['id'],))]
                result.append(item)
            audit(c, u, 'patient_history_viewed', 'visit', vid)
            return result

    @app.get('/api/visits/{vid}/payment-status')
    def payment_status(vid: int, u=Depends(principal)):
        require(u, 'doctor')
        with db() as c:
            visit_access(c, u, vid, clinical=True)
            state = invoice(c, vid)
            provisional = c.execute("SELECT 1 FROM payments WHERE visit_id=? AND kind='provisional'", (vid,)).fetchone()
            return {'status': 'Thu tạm' if state['unpriced_count'] or provisional else 'Còn nợ' if state['due'] else 'Đã thu'}

    @app.post('/api/visits/{vid}/close-abandoned')
    def close_abandoned(vid: int, data: CloseInput, u=Depends(principal)):
        require(u, 'reception', 'doctor')
        if data.reason == 'Khác' and not data.note:
            raise HTTPException(422, 'Lý do khác phải có ghi chú')
        with db(True) as c:
            v = visit_access(c, u, vid, clinical='reception' not in u['roles'])
            ensure_open(v)
            if any(c.execute('SELECT 1 FROM ' + table + ' WHERE visit_id=? LIMIT 1', (vid,)).fetchone()
                   for table in ('payments', 'charges', 'dispensations')):
                raise HTTPException(409, 'Lượt đã có tiền thu, khoản phí hoặc thuốc đã cấp; phải qua quy trình hủy/hoàn hiện có')
            if c.execute("SELECT 1 FROM orders WHERE visit_id=? AND status<>'cancelled'", (vid,)).fetchone():
                raise HTTPException(409, 'Phải xử lý/hủy chỉ định qua quy trình hiện có trước')
            if c.execute("SELECT 1 FROM nursing_tasks WHERE visit_id=? AND status='pending'", (vid,)).fetchone():
                raise HTTPException(409, 'Còn y lệnh chưa xử lý; phải qua quy trình hiện có')
            if c.execute("SELECT 1 FROM prescriptions WHERE visit_id=? AND status<>'cancelled'", (vid,)).fetchone():
                raise HTTPException(409, 'Phải hủy/đối soát đơn thuốc qua quy trình hiện có trước')
            reason = data.reason + (': ' + data.note if data.note else '')
            c.execute("UPDATE visits SET status='cancelled',version=version+1 WHERE id=?", (vid,))
            c.execute('INSERT INTO visit_cancellations(visit_id,actor_id,reason,created_at) VALUES(?,?,?,?)', (vid, u['id'], reason, now()))
            revision(c, vid, u, now, 'cancel', reason)
            audit(c, u, 'visit_cancelled', 'visit', vid, reason)
            return {'status': 'cancelled'}
