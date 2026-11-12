"""Immutable text-result revisions with optimistic API concurrency."""
import json
from fastapi import Depends, HTTPException


def latest_version(c, oid):
    return c.execute('SELECT COALESCE(MAX(version),0) FROM order_result_versions WHERE order_id=?',(oid,)).fetchone()[0]


def save_version(c, order, data, u, stamp):
    version=latest_version(c,order['id'])
    if data.version!=version:raise HTTPException(409,'Kết quả đã được người khác sửa; tải lại phiên bản mới trước khi gửi')
    c.execute('''INSERT INTO order_result_versions(order_id,version,result_text,created_by,created_at)
      VALUES(?,?,?,?,?)''',(order['id'],version+1,data.result_text,u['id'],stamp))
    return version+1


def approve_version(c, order, u, stamp):
    current=c.execute('SELECT * FROM order_result_versions WHERE order_id=? ORDER BY version DESC LIMIT 1',(order['id'],)).fetchone()
    if not current:raise HTTPException(409,'Kết quả chưa có phiên bản; cần tải lại và gửi kết quả')
    if current['result_text']!=order['result_text']:raise HTTPException(409,'Nội dung không khớp phiên bản chờ duyệt')
    snapshot={'order_id':order['id'],'version':current['version'],'result_text':current['result_text'],
              'created_by':current['created_by'],'created_at':current['created_at'],'approved_by':u['id'],'approved_at':stamp}
    c.execute('UPDATE order_result_versions SET approved_by=?,approved_at=?,snapshot=? WHERE id=?',
              (u['id'],stamp,json.dumps(snapshot,ensure_ascii=False),current['id']))


def has_approved_result(c, order):
    return order['status']=='approved' or bool(order['approved_at']) or bool(c.execute("SELECT 1 FROM lab_reports WHERE order_id=? AND status='approved'",(order['id'],)).fetchone()) or bool(c.execute('SELECT 1 FROM order_result_versions WHERE order_id=? AND snapshot IS NOT NULL',(order['id'],)).fetchone())


def install_result_history(app,db,principal,require,audit,visit_access):
    @app.get('/api/orders/{oid}/result/versions')
    def history(oid:int,u=Depends(principal)):
        require(u,'technician','doctor')
        with db('access') as c:
            order=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
            if not order:raise HTTPException(404,'Không có chỉ định')
            if 'technician' not in u['roles']:visit_access(c,u,order['visit_id'],clinical=True)
            condition='' if 'technician' in u['roles'] else ' AND snapshot IS NOT NULL'
            rows=[dict(r) for r in c.execute('SELECT * FROM order_result_versions WHERE order_id=?'+condition+' ORDER BY version',(oid,))]
            audit(c,u,'result_versions_viewed','order',oid)
            return {'items':rows}
