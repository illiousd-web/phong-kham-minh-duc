"""Bounded-memory storage accounting. Never deletes patient data or audit rows."""
from pathlib import Path
import os
import shutil
from .resources import LIMITS


class StorageLimitError(RuntimeError):
    pass


def tree_bytes(path):
    path=Path(path)
    if not path.exists():return 0
    if path.is_symlink():raise StorageLimitError('Không chấp nhận thư mục dữ liệu là symlink')
    total=0
    with os.scandir(path) as entries:
        for entry in entries:
            if entry.is_symlink():raise StorageLimitError('Thư mục dữ liệu chứa symlink')
            if entry.is_dir(follow_symlinks=False):total+=tree_bytes(entry.path)
            elif entry.is_file(follow_symlinks=False):total+=entry.stat(follow_symlinks=False).st_size
    return total


def free_bytes(path):
    path=Path(path).resolve()
    while not path.exists():path=path.parent
    return shutil.disk_usage(path).free


def require_space(path, additional=0):
    if free_bytes(path)<LIMITS.min_free_bytes+additional:
        raise StorageLimitError('Ổ đĩa thiếu chỗ dự phòng. Dừng ghi mới, kiểm tra dung lượng và sao lưu; không xóa hồ sơ hoặc WAL.')


def check_upload(path,size):
    require_space(path,size*2)
    if tree_bytes(path)+size>LIMITS.upload_total_bytes:
        raise StorageLimitError('Kho tệp đạt giới hạn dung lượng. Liên hệ quản trị, không tự xóa dữ liệu bệnh nhân.')
