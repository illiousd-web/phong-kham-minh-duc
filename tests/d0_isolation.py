"""Independent synthetic rows for D0 scenarios; never pick shared queue entries."""
import secrets

def service(db):
    suffix=secrets.token_hex(6)
    with db(True) as c:
        c.execute('INSERT INTO service_catalog(name,price,code) VALUES(?,?,?)',('Dịch vụ D0 giả lập '+suffix,12345,'FAKE-D0-'+suffix))
        return c.execute('SELECT last_insert_rowid()').fetchone()[0]

def lab(admin):
    suffix=secrets.token_hex(6)
    response=admin.post('/api/lab/catalog',json={'code':'FAKE-D0-'+suffix,'name':'Chỉ số D0 giả lập '+suffix,'abbreviation':'FAKE','group_name':'other','result_type':'number','unit':'đv giả lập'})
    assert response.status_code==201,response.text
    return response.json()['id']
