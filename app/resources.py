"""Validated resource limits; security and transaction guarantees are unchanged."""
from dataclasses import dataclass
from functools import wraps
import os
import inspect
import threading

MIB = 1024*1024


def integer(name, default, low, high):
    raw=os.getenv(name,str(default))
    if not raw.isdecimal():raise RuntimeError(f'{name} must be an integer')
    value=int(raw)
    if not low<=value<=high:raise RuntimeError(f'{name} must be between {low} and {high}')
    return value


@dataclass(frozen=True)
class Limits:
    workers:int
    pool_min:int
    pool_max:int
    threads:int
    concurrency:int
    export_slots:int
    export_bytes:int
    upload_bytes:int
    upload_total_bytes:int
    min_free_bytes:int
    backup_total_bytes:int


def read_limits():
    result=Limits(
        integer('CLINIC_WORKERS',1,1,2),integer('CLINIC_POOL_MIN',1,0,8),
        integer('CLINIC_POOL_MAX',4,1,8),integer('CLINIC_THREAD_LIMIT',8,4,32),
        integer('CLINIC_CONCURRENCY',48,8,80),integer('CLINIC_EXPORT_SLOTS',1,1,2),
        integer('CLINIC_EXPORT_MAX_MB',10,1,10)*MIB,
        integer('CLINIC_UPLOAD_MAX_MB',5,1,5)*MIB,
        integer('CLINIC_UPLOAD_TOTAL_MB',2048,16,16384)*MIB,
        integer('CLINIC_MIN_FREE_MB',10240,256,65536)*MIB,
        integer('CLINIC_BACKUP_TOTAL_MB',20480,256,131072)*MIB)
    if result.pool_min>result.pool_max:raise RuntimeError('CLINIC_POOL_MIN cannot exceed CLINIC_POOL_MAX')
    if result.pool_max>result.threads:raise RuntimeError('CLINIC_POOL_MAX cannot exceed CLINIC_THREAD_LIMIT')
    if result.workers*result.pool_max>12:raise RuntimeError('Total application DB connections cannot exceed 12 on the 8 GB profile')
    return result


LIMITS=read_limits()
_exports=threading.BoundedSemaphore(LIMITS.export_slots)


def export_slot(function):
    @wraps(function)
    def limited(*args,**kwargs):
        if not _exports.acquire(blocking=False):
            from fastapi import HTTPException
            raise HTTPException(503,'Đang xuất biểu mẫu khác, vui lòng thử lại sau',headers={'Retry-After':'2'})
        try:
            result=function(*args,**kwargs)
            if len(getattr(result,'body',b''))>LIMITS.export_bytes:
                from fastapi import HTTPException
                raise HTTPException(413,'Biểu mẫu vượt giới hạn dung lượng xuất; liên hệ quản trị, không cắt bỏ nội dung hồ sơ')
            return result
        finally:_exports.release()
    limited.__signature__=inspect.signature(function,eval_str=True)
    return limited
