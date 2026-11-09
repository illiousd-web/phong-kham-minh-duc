"""Số việc đang chờ của từng màn hình, để hiện trên menu và tự cập nhật.

- Chỉ trả về con số, không trả tên hay mã người bệnh.
- Chỉ trả số của các màn hình ứng với vai trò của người gọi.
- Đếm bằng chính các API danh sách mà màn hình đó dùng (cùng phạm vi phân quyền,
  cùng giới hạn 100 dòng), nên số trên menu khớp với hàng chờ hiển thị.
- Xác thực bằng principal.peek: KHÔNG gia hạn phiên. Hỏi định kỳ mỗi 60 giây
  không làm mất tự đăng xuất sau 20 phút không thao tác.
"""
from fastapi import Depends

OPEN = lambda v: v['status'] not in ('completed', 'cancelled')


def install_queue_counts(app, peek, load_ui):
    cache = {}

    def get(path, u):
        if path not in cache:
            cache[path] = next(r.endpoint for r in app.routes
                               if getattr(r, 'path', None) == path and 'GET' in getattr(r, 'methods', ()))
        return cache[path](u=u)

    @app.get('/api/queue-counts')
    def queue_counts(u=Depends(peek)):
        roles = set(u['roles'])
        ui = load_ui()
        out = {}
        if roles & {'reception', 'doctor', 'nurse'}:
            visits = get('/api/visits', u)
            if 'reception' in roles:
                out['reception'] = sum(v['status'] == 'waiting' for v in visits)
            if 'doctor' in roles:
                out['doctor'] = sum(map(OPEN, visits))
            if 'nurse' in roles:
                out['nurse'] = sum(map(OPEN, visits))
        if 'technician' in roles:
            out['lab'] = sum(o['status'] == 'ordered' for o in get('/api/orders', u))
        if 'pharmacy' in roles:
            out['pharmacy'] = sum(x['status'] == 'draft' for x in get('/api/prescriptions', u))
        if 'cashier' in roles:
            out['cashier'] = sum(d['charged'] - d['paid'] > 0 for d in get('/api/dues', u))
        if 'manager' in roles:
            total = sum(x['status'] == 'pending' for x in get('/api/adjustments', u))
            total += sum(x['status'] == 'pending' for x in get('/api/orders/cancellation-requests', u))
            total += sum(x['status'] == 'pending' for x in get('/api/medication-returns', u))
            if ui['addendum']:
                total += len(get('/api/visits/addenda/pending', u))
            if ui['controlled_drugs'] and 'controlled_reviewer' in roles:
                total += sum(x['status'] == 'pending' for x in get('/api/controlled-receipts', u))
            out['manager'] = total
        return out
