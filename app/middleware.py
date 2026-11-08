"""Bound request bodies before multipart files or JSON can exhaust server disk."""
from starlette.responses import JSONResponse


class BodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    def __init__(self, app, max_bytes=6*1024*1024):
        self.app=app
        self.max_bytes=max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope,receive,send)
        headers=dict(scope.get('headers',[]))
        length=headers.get(b'content-length',b'0')
        try:
            too_large=int(length)>self.max_bytes
        except ValueError:
            too_large=True
        if too_large:
            return await JSONResponse({'detail':'Yêu cầu vượt giới hạn 6 MB'},status_code=413)(scope,receive,send)
        total=0
        async def limited_receive():
            nonlocal total
            message=await receive()
            total+=len(message.get('body',b''))
            if total>self.max_bytes:
                raise BodyTooLarge()
            return message
        try:
            await self.app(scope,limited_receive,send)
        except BodyTooLarge:
            await JSONResponse({'detail':'Yêu cầu vượt giới hạn 6 MB'},status_code=413)(scope,receive,send)
