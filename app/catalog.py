"""Maintain service/medicine catalogs without editing historical charges."""
from fastapi import Depends
from pydantic import BaseModel, Field
from typing import Literal

class ServiceInput(BaseModel):
    name: str = Field(min_length=2,max_length=180)
    price: int = Field(ge=0,le=2_000_000_000)
    category: Literal['consultation','lab','ultrasound','xray','ecg'] = 'consultation'

class MedicineInput(BaseModel):
    name: str = Field(min_length=2,max_length=180)
    base_unit: str = Field(min_length=1,max_length=40)


def install_catalog(app, db, principal, require, audit):
    @app.get('/api/catalog')
    def catalog(u=Depends(principal)):
        require(u,'admin','manager','pharmacy')
        with db() as c:
            return {'services':[dict(x) for x in c.execute('''SELECT sc.*,COALESCE(cat.category,'consultation') AS category
                       FROM service_catalog sc LEFT JOIN service_categories cat ON cat.service_id=sc.id ORDER BY sc.id''')],
                    'medicines':[dict(x) for x in c.execute('SELECT * FROM medicines ORDER BY id')]}

    @app.post('/api/catalog/services',status_code=201)
    def service(data:ServiceInput,u=Depends(principal)):
        require(u,'admin','manager')
        with db(True) as c:
            c.execute('INSERT INTO service_catalog(name,price) VALUES(?,?)',(data.name,data.price))
            uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute('INSERT INTO service_categories(service_id,category) VALUES(?,?)',(uid,data.category))
            audit(c,u,'service_created','service',uid)
        return {'id':uid}

    @app.post('/api/catalog/medicines',status_code=201)
    def medicine(data:MedicineInput,u=Depends(principal)):
        require(u,'admin','manager','pharmacy')
        with db(True) as c:
            c.execute('INSERT INTO medicines(name,base_unit) VALUES(?,?)',(data.name,data.base_unit))
            uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            audit(c,u,'medicine_created','medicine',uid)
        return {'id':uid}
