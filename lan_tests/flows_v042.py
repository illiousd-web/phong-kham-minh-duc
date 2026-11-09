"""Helpers for priced synthetic LAN workflows (no unbilled CLS escape hatch)."""
import secrets


def create_order(clients,visit,category='lab'):
    manager=clients['manager']
    r=manager.post('/api/catalog/services',json={'name':'Synthetic CLS '+category+' '+secrets.token_hex(6),
                       'price':33000,'category':category})
    assert r.status_code==201,r.text
    order=clients['doctor'].post('/api/orders',json={'visit_id':visit,'category':category,'service_id':r.json()['id'],'request_key':secrets.token_hex(12)})
    assert order.status_code==201,order.text
    return order.json()['id']


def create_rx(clients,visit,instructions=''):
    manager=clients['manager']
    r=manager.post('/api/catalog/medicines',json={'name':'Thuốc giả lập '+secrets.token_hex(5),'base_unit':'viên'})
    assert r.status_code==201,r.text
    rx=clients['doctor'].post('/api/prescriptions',json={'visit_id':visit,
             'items':[{'medicine_id':r.json()['id'],'quantity':2,'directions':'Không dùng điều trị'}],
             'instructions':instructions})
    assert rx.status_code==201,rx.text
    return rx.json()
