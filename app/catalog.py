"""Versioned catalogue values never rewrite historical charge snapshots."""
from fastapi import Depends,HTTPException
from pydantic import BaseModel,Field,model_validator
from typing import Literal
import json

class ServiceInput(BaseModel):
    name:str=Field(min_length=2,max_length=180)
    price:int|None=Field(ge=0,le=2_000_000_000)
    price_at_collection:bool=False
    category:Literal['consultation','lab','ultrasound','xray','ecg','procedure']='consultation'
    code:str|None=Field(default=None,pattern=r'^[A-Za-z0-9_-]{2,40}$')
    active:bool=True

    @model_validator(mode='after')
    def require_fixed_price(self):
        if self.price is None and not self.price_at_collection:
            raise ValueError('Giá cố định cần số tiền; giá nhập khi thu phải bật cờ tương ứng')
        return self

class MedicineInput(BaseModel):
    name:str=Field(min_length=2,max_length=180)
    base_unit:str=Field(min_length=1,max_length=40)
    code:str|None=Field(default=None,pattern=r'^[A-Za-z0-9_-]{2,40}$')
    controlled:bool=False


def install_catalog(app,db,principal,require,audit):
    @app.get('/api/catalog')
    def catalog(u=Depends(principal)):
        require(u,'admin','manager','pharmacy')
        with db() as c:return {'services':[dict(x) for x in c.execute("SELECT sc.*,COALESCE(cat.category,'consultation') AS category FROM service_catalog sc LEFT JOIN service_categories cat ON cat.service_id=sc.id ORDER BY sc.id")],
          'medicines':[dict(x) for x in c.execute('SELECT m.*,p.unit_price FROM medicines m LEFT JOIN medicine_prices p ON p.medicine_id=m.id ORDER BY m.id')]}

    @app.post('/api/catalog/services',status_code=201)
    def service(data:ServiceInput,u=Depends(principal)):
        require(u,'admin','manager')
        with db(True) as c:
            if data.code and c.execute('SELECT 1 FROM service_catalog WHERE code=?',(data.code,)).fetchone():raise HTTPException(409,'Trùng mã dịch vụ')
            if c.execute('SELECT 1 FROM service_catalog WHERE name=?',(data.name,)).fetchone():raise HTTPException(409,'Trùng tên dịch vụ')
            c.execute('INSERT INTO service_catalog(name,price,code,active,price_at_collection) VALUES(?,?,?,?,?)',(data.name,0 if data.price_at_collection else data.price,data.code,int(data.active),int(data.price_at_collection)))
            uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            if not data.code:c.execute('UPDATE service_catalog SET code=? WHERE id=?',('DV'+str(uid),uid))
            c.execute('INSERT INTO service_categories(service_id,category) VALUES(?,?)',(uid,data.category))
            audit(c,u,'service_created','service',uid,json.dumps(data.model_dump(),ensure_ascii=False))
        return {'id':uid}

    @app.put('/api/catalog/services/{sid}')
    def update_service(sid:int,data:ServiceInput,u=Depends(principal)):
        require(u,'admin','manager')
        with db(True) as c:
            old=c.execute('SELECT * FROM service_catalog WHERE id=?',(sid,)).fetchone()
            if not old:raise HTTPException(404,'Không có dịch vụ')
            if data.code and c.execute('SELECT 1 FROM service_catalog WHERE code=? AND id<>?',(data.code,sid)).fetchone():raise HTTPException(409,'Trùng mã')
            if c.execute('SELECT 1 FROM service_catalog WHERE name=? AND id<>?',(data.name,sid)).fetchone():raise HTTPException(409,'Trùng tên')
            c.execute('UPDATE service_catalog SET name=?,price=?,code=?,active=?,price_at_collection=? WHERE id=?',(data.name,0 if data.price_at_collection else data.price,data.code or old['code'] or 'DV'+str(sid),int(data.active),int(data.price_at_collection),sid))
            c.execute('INSERT INTO service_categories(service_id,category) VALUES(?,?) ON CONFLICT(service_id) DO UPDATE SET category=excluded.category',(sid,data.category))
            audit(c,u,'service_updated','service',sid,f"Giá {old['price']} -> {data.price}; hiệu lực {data.active}")
        return {'id':sid}

    @app.post('/api/catalog/medicines',status_code=201)
    def medicine(data:MedicineInput,u=Depends(principal)):
        require(u,'admin','manager','pharmacy')
        if data.controlled and not {'manager','controlled_reviewer'}.issubset(u['roles']):raise HTTPException(403,'Danh mục kiểm soát cần quản lý có quyền kiểm soát đặc biệt')
        with db(True) as c:
            if data.code and c.execute('SELECT 1 FROM medicines WHERE code=?',(data.code,)).fetchone():raise HTTPException(409,'Trùng mã thuốc')
            c.execute('INSERT INTO medicines(name,base_unit,code,controlled) VALUES(?,?,?,?)',(data.name,data.base_unit,data.code,int(data.controlled)))
            uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            if not data.code:c.execute('UPDATE medicines SET code=? WHERE id=?',('TH'+str(uid),uid))
            audit(c,u,'medicine_created','medicine',uid)
        return {'id':uid}
