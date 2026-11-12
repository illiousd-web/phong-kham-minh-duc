"""TT18 public-source matching; uncertain strengths never bypass the lock gate."""
import difflib
import json
import re
from decimal import Decimal, localcontext
from .m6 import fold, components

LABEL = 'thuốc dạng phối hợp có chứa chất kiểm soát'


def key(value):
    return re.sub(r'[^a-z0-9]', '', fold(value))


def aliases(name):
    values = {name.strip()}
    upper = name.strip().upper()
    if upper.endswith('E'): values.add(name.strip()[:-1])
    if upper.endswith('INE'): values.add(name.strip()[:-3]+'IN')
    return values


def matches(c, text):
    return [dict(r) for r in c.execute('''SELECT s.* FROM controlled_substances s JOIN controlled_substance_aliases a ON a.substance_key=s.source_key
        WHERE a.alias_key=? AND s.active=1''',(key(text),))]


def assess(c, line):
    actives = components(line.get('ingredient',''))
    found = [(i, matches(c, name)) for i,name in enumerate(actives)]
    exact = [(i,row) for i,rows in found for row in rows]
    types = {row['controlled_type'] for _,row in exact}
    result = {'types':sorted(types),'label':'','errors':[],'warnings':[]}
    for i,name in enumerate(actives):
        if found[i][1]: continue
        token = key(name)
        candidates = [r['alias'] for r in c.execute('SELECT alias,alias_key FROM controlled_substance_aliases')
                      if len(token)>=5 and difflib.SequenceMatcher(None,token,r['alias_key']).ratio()>=0.85]
        if candidates:
            result['warnings'].append('Tên hoạt chất gần chất kiểm soát: '+name)
    if result['warnings'] and not (line.get('controlled_acknowledged') is True and len(line.get('controlled_reason','').strip())>=8):
        result['errors'].append('Tên gần chất kiểm soát; bác sĩ xác nhận đã rà soát và nhập lý do ít nhất 8 ký tự')
    if not exact: return result
    if len(actives)==1:
        result['errors'].append('Đơn thuốc N/H chưa hỗ trợ')
        return result
    # Explicit strengths must correspond to ingredient order, separated by +.
    strengths = components(line.get('strength',''))
    for index, substance in exact:
        limits = json.loads(substance['limits_json'])
        part = strengths[index] if len(strengths)==len(actives) else ''
        dose = re.fullmatch(r'\s*(\d+(?:[.,]\d+)?)\s*(mg|g|mcg|µg)\s*',part,re.I)
        maximums = [Decimal(r['ham_luong_toi_da_mg_moi_don_vi_chia_lieu'].replace(',','.')) for r in limits if r['ham_luong_toi_da_mg_moi_don_vi_chia_lieu']]
        if not dose or not maximums:
            result['errors'].append('Đơn thuốc N/H chưa hỗ trợ: không xác định được hàm lượng mỗi đơn vị chia liều hoặc ngưỡng phối hợp')
            continue
        with localcontext() as context:
            context.prec = 600
            amount = Decimal(dose[1].replace(',','.')) * {'mg':Decimal(1),'g':Decimal(1000),'mcg':Decimal('0.001'),'µg':Decimal('0.001')}[dose[2].lower()]
        if amount > min(maximums): result['errors'].append('Đơn thuốc N/H chưa hỗ trợ: vượt ngưỡng phối hợp')
    if not result['errors']: result['label']=LABEL
    return result


def flag_drug(c, did, ingredient, u, audit):
    types = {r['controlled_type'] for name in components(ingredient) for r in matches(c,name)}
    if not types:return
    value = next(t for t in ('N','H','precursor') if t in types)
    old = c.execute('SELECT controlled_type FROM drugs WHERE id=?',(did,)).fetchone()
    if old['controlled_type']!=value:
        c.execute('UPDATE drugs SET controlled_type=? WHERE id=?',(value,did))
        audit(c,u,'drug_controlled_auto_flagged','drug',did,json.dumps({'old':old['controlled_type'],'new':value},ensure_ascii=False))


from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field


class AliasInput(BaseModel):
    substance_key: str = Field(min_length=1,max_length=100)
    alias: str = Field(min_length=2,max_length=180)


def install_controlled(app, db, principal, require, audit):
    @app.get('/api/controlled-substances')
    def catalog(u=Depends(principal)):
        require(u,'admin')
        with db() as c:
            items=[dict(r) for r in c.execute('SELECT source_key,name,controlled_type,limits_json FROM controlled_substances ORDER BY source_key')]
            for item in items:item['aliases']=[r['alias'] for r in c.execute('SELECT alias FROM controlled_substance_aliases WHERE substance_key=? ORDER BY alias',(item['source_key'],))]
            return {'items':items}

    @app.post('/api/controlled-substances/aliases',status_code=201)
    def add_alias(data:AliasInput,u=Depends(principal)):
        require(u,'admin')
        alias=data.alias.strip()
        if not key(alias):raise HTTPException(422,'Tên gọi khác không hợp lệ')
        with db(True) as c:
            if not c.execute('SELECT 1 FROM controlled_substances WHERE source_key=?',(data.substance_key,)).fetchone():raise HTTPException(404,'Không có dược chất')
            if c.execute('SELECT 1 FROM controlled_substance_aliases WHERE alias_key=? AND substance_key=?',(key(alias),data.substance_key)).fetchone():raise HTTPException(409,'Tên gọi khác đã có')
            c.execute('INSERT INTO controlled_substance_aliases VALUES(?,?,?,?)',(key(alias),data.substance_key,alias,'admin'))
            audit(c,u,'controlled_alias_added','controlled_substance',None,json.dumps({'substance_key':data.substance_key,'alias':re.sub(r'\d{6,}','[đã che chuỗi số]',alias)},ensure_ascii=False))
            for row in c.execute('SELECT id,ingredient FROM drugs').fetchall():flag_drug(c,row['id'],row['ingredient'],u,audit)
        return {'ok':True}
