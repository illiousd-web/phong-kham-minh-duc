"""Admin-managed clinic identity and private signatures, stored in database backups."""
import hashlib
import json
import warnings
from io import BytesIO

from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

MAX_SIGNATURE_BYTES = 300 * 1024
PROFILE_FIELDS = ('name', 'governing_body', 'address', 'phone', 'email')


class ClinicProfileInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(default='', max_length=250)
    governing_body: str = Field(default='', max_length=250)
    address: str = Field(default='', max_length=500)
    phone: str = Field(default='', max_length=100)
    email: str = Field(default='', max_length=250)


def read_profile(c):
    return dict(c.execute('SELECT name,governing_body,address,phone,email FROM clinic_profile WHERE id=1').fetchone())


def signature_type(payload):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(payload)) as image:
                if image.format not in ('PNG', 'JPEG') or image.width * image.height > 4_000_000:
                    raise ValueError
                media_type = Image.MIME[image.format]
                image.verify()
            with Image.open(BytesIO(payload)) as image:
                image.load()
        return media_type
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(422, 'Chỉ nhận ảnh PNG/JPG hợp lệ, tối đa 4 triệu điểm ảnh') from None


def install_clinic_profile(app, db, principal, require, audit, now):
    @app.get('/api/clinic-profile')
    def get_profile(u=Depends(principal)):
        require(u, 'admin')
        with db() as c:
            return read_profile(c)

    @app.put('/api/clinic-profile')
    def put_profile(data: ClinicProfileInput, u=Depends(principal)):
        require(u, 'admin')
        values = data.model_dump()
        with db(True) as c:
            before = read_profile(c)
            if before != values:
                c.execute('UPDATE clinic_profile SET name=?,governing_body=?,address=?,phone=?,email=? WHERE id=1',
                          tuple(values[key] for key in PROFILE_FIELDS))
                audit(c, u, 'clinic_profile_changed', 'clinic_profile', 1,
                      json.dumps({'old': before, 'new': values}, ensure_ascii=False), details_limit=20000)
        return values

    @app.put('/api/users/{user_id}/signature')
    def put_signature(user_id: int, file: UploadFile = File(...), u=Depends(principal)):
        require(u, 'admin')
        payload = file.file.read(MAX_SIGNATURE_BYTES + 1)
        if len(payload) > MAX_SIGNATURE_BYTES:
            raise HTTPException(413, 'Ảnh chữ ký không được vượt quá 300 KB')
        media_type = signature_type(payload)
        uploaded_at = now()
        with db(True) as c:
            if not c.execute('SELECT 1 FROM users WHERE id=?', (user_id,)).fetchone():
                raise HTTPException(404, 'Không có tài khoản')
            prior = c.execute('SELECT image FROM user_signatures WHERE user_id=?', (user_id,)).fetchone()
            c.execute('''INSERT INTO user_signatures(user_id,image,media_type,uploaded_at,uploaded_by) VALUES(?,?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET image=excluded.image,media_type=excluded.media_type,
                uploaded_at=excluded.uploaded_at,uploaded_by=excluded.uploaded_by''',
                      (user_id, payload, media_type, uploaded_at, u['id']))
            audit(c, u, 'user_signature_changed', 'user', user_id, json.dumps({
                'old_sha256': hashlib.sha256(bytes(prior['image'])).hexdigest() if prior else None,
                'new_sha256': hashlib.sha256(payload).hexdigest(), 'media_type': media_type, 'bytes': len(payload)}))
        return {'user_id': user_id, 'uploaded_at': uploaded_at, 'uploaded_by': u['id']}

    @app.get('/api/users/{user_id}/signature')
    def get_signature(user_id: int, u=Depends(principal)):
        if u['id'] != user_id and 'admin' not in u['roles']:
            raise HTTPException(403, 'Chỉ chính chủ tài khoản và quản trị được xem chữ ký')
        with db() as c:
            signature = c.execute('SELECT image,media_type FROM user_signatures WHERE user_id=?', (user_id,)).fetchone()
            if not signature:
                raise HTTPException(404, 'Chưa có ảnh chữ ký')
            return Response(bytes(signature['image']), media_type=signature['media_type'], headers={
                'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                'Content-Disposition': 'inline; filename="chu-ky"'})
