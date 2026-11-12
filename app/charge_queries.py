"""Chỉ tối ưu cách đọc giá; view v4 vẫn quyết định mọi khoản đã thay đổi.

Không có dòng trong bốn bảng của view => giá hiệu lực chính là snapshot
charges.amount, kể cả NULL. Khoản có bất kỳ dấu vết thay đổi nào luôn đọc
effective_charges: không sao chép thứ tự ưu tiên giá, hoàn thuốc hoặc hủy phí.
"""
PRICE_INPUTS=('charge_voids','charge_pricing','manual_charge_prices','charge_credits')


def priced_ctes(scope='',materialized='MATERIALIZED '):
    # scope chỉ là đoạn SQL cố định ở các call site; giá trị vẫn bind parameter.
    selected=' AND '+scope if scope else ''
    changed=' UNION '.join('SELECT charge_id FROM '+table for table in PRICE_INPUTS)
    return f'''charge_changes AS {materialized}({changed}),
priced AS {materialized}(
 SELECT ch.id,ch.visit_id,ch.amount FROM charges ch
 WHERE NOT EXISTS(SELECT 1 FROM charge_changes x WHERE x.charge_id=ch.id){selected}
 UNION ALL
 SELECT e.id,e.visit_id,e.amount FROM effective_charges e
 JOIN charge_changes x ON x.charge_id=e.id WHERE 1=1{selected})'''


DUES_SQL='WITH '+priced_ctes()+''',
     ch AS (SELECT visit_id,COALESCE(SUM(amount),0) AS total,
          SUM(CASE WHEN amount IS NULL THEN 1 ELSE 0 END) AS unpriced FROM priced GROUP BY visit_id),
     adj AS (SELECT visit_id,SUM(CASE WHEN kind='discount' THEN amount ELSE 0 END) AS discount,
          SUM(CASE WHEN kind='refund' THEN amount ELSE 0 END) AS refund
          FROM effective_adjustments WHERE status='approved' GROUP BY visit_id),
     pay AS (SELECT visit_id,SUM(amount) AS total FROM payments GROUP BY visit_id),
     t AS (SELECT v.id,v.patient_id,v.created_at,COALESCE(ch.total,0)-COALESCE(adj.discount,0) AS charged,
          COALESCE(pay.total,0)-COALESCE(adj.refund,0) AS paid,COALESCE(ch.unpriced,0) AS unpriced_count
          FROM visits v LEFT JOIN ch ON ch.visit_id=v.id LEFT JOIN adj ON adj.visit_id=v.id LEFT JOIN pay ON pay.visit_id=v.id)
SELECT t.id AS visit_id,p.code AS patient_code,p.full_name AS patient_name,t.charged,t.paid,t.unpriced_count
FROM t JOIN patients p ON p.id=t.patient_id
WHERE t.charged<>t.paid OR t.unpriced_count>0 OR t.created_at>=?
ORDER BY t.id DESC'''


def orders_sql(where='',hide_results=False,limit=100):
    results='NULL AS result_text,NULL AS file_name' if hide_results else 'o.result_text,o.file_name'
    predicate=' WHERE '+where if where else ''
    cap=' LIMIT '+str(int(limit)) if limit is not None else ''
    return f'''WITH candidates AS MATERIALIZED (
 SELECT o.id,o.visit_id,o.category,o.name,o.status,o.service_id,o.proposed_price,{results},o.created_at,
 (SELECT COALESCE(MAX(rv.version),0) FROM order_result_versions rv WHERE rv.order_id=o.id) AS result_version,
 p.code AS patient_code,p.full_name AS patient_name
 FROM orders o JOIN visits v ON v.id=o.visit_id JOIN patients p ON p.id=v.patient_id
 {predicate} ORDER BY o.id DESC{cap}),
 {priced_ctes('visit_id IN (SELECT visit_id FROM candidates)')},
 unpriced_orders AS MATERIALIZED (SELECT cs.source_id FROM priced ch
 JOIN charge_sources cs ON cs.charge_id=ch.id WHERE cs.source_type='order' AND ch.amount IS NULL)
 SELECT id,visit_id,category,name,status,service_id,proposed_price,result_text,file_name,created_at,result_version,
 CASE WHEN status='requested' AND proposed_price IS NULL THEN 1
 WHEN id IN (SELECT source_id FROM unpriced_orders) THEN 1 ELSE 0 END AS unpriced
 ,patient_code,patient_name
 FROM candidates ORDER BY id DESC'''


# Cùng t và điều kiện nợ với /dues; không tải tên hoặc danh sách về Python.
DUES_COUNT_SQL=DUES_SQL[:DUES_SQL.index('SELECT t.id AS visit_id')]+"SELECT COUNT(*) FROM t WHERE t.charged>t.paid OR t.unpriced_count>0"
