"""Manifest dùng dấu / trên mọi hệ điều hành; vẫn bắt tệp thừa hoặc sai hash."""
import json
from pathlib import PureWindowsPath

import pytest
from scripts import backup_lan


@pytest.mark.parametrize('windows_tree',[False,True])
@pytest.mark.parametrize('damage',['none','checksum','extra'])
def test_lan_backup_nested_paths_are_portable_and_hashes_stay_required(tmp_path,windows_tree,damage):
    source=tmp_path/'source';source.mkdir()
    (source/'attachments'/'nested').mkdir(parents=True)
    (source/'database.dump').write_bytes(b'Du lieu PostgreSQL gia lap')
    attachment=source/'attachments'/'nested'/'kết quả.pdf'
    attachment.write_bytes(b'Tep dinh kem gia lap')
    files={name:backup_lan.checksum(source/name) for name in
           ('database.dump','attachments/nested/kết quả.pdf')}
    (source/'manifest.json').write_text(json.dumps({'format':1,'files':files}),encoding='utf-8')
    if damage=='checksum':attachment.write_bytes(b'Tep da bi doi')
    if damage=='extra':(source/'attachments'/'ngoai-danh-sach.txt').write_bytes(b'Tep thua')
    key=tmp_path/'backup.key';key.write_bytes(b'x'*32)
    archive=tmp_path/'synthetic.mdbackup'
    backup_lan.encrypt_archive([(source/'database.dump','database.dump'),
        (source/'attachments','attachments'),(source/'manifest.json','manifest.json')],archive,key.read_bytes())
    destination=tmp_path/'verified';destination.mkdir()

    class WindowsFile:
        def __init__(self,path):self.path=path
        def is_file(self):return self.path.is_file()
        def relative_to(self,root):return PureWindowsPath(self.path.relative_to(destination))

    class WindowsTree:
        # Tái hiện relative_to trả đường dẫn có dấu \ trên cả máy Linux CI.
        # TAR, AES-GCM, giải nén và kiểm hash vẫn dùng tệp thật.
        def __fspath__(self):return str(destination)
        def __truediv__(self,name):return destination/name
        def rglob(self,pattern):return (WindowsFile(p) for p in destination.rglob(pattern))

    target=WindowsTree() if windows_tree else destination
    if damage!='none':
        with pytest.raises(ValueError,match='checksum mismatch' if damage=='checksum' else 'manifest mismatch'):
            backup_lan.unpack_verified(archive,key,target)
    else:
        verified=backup_lan.unpack_verified(archive,key,target)
        assert verified['files']==files
        assert (destination/'attachments'/'nested'/'kết quả.pdf').read_bytes()==attachment.read_bytes()
