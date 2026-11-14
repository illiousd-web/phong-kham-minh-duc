"""Công cụ C5 phải nhận diện đăng nhập khi logout nằm trong menu đóng."""
import os
import pytest
from playwright.sync_api import sync_playwright, TimeoutError
from scripts.ui_wait import wait_for_login


@pytest.mark.parametrize('html,authenticated',[
    ('<button id="logout">Đăng xuất</button>',True),
    ('<details><summary class="account-trigger">Tài khoản</summary><button id="logout">Đăng xuất</button></details>',True),
    ('<button id="logout" hidden>Đăng xuất</button><div class="account-trigger" hidden>Tài khoản</div><form>Đăng nhập</form>',False),
])
def test_login_wait_old_new_and_anonymous(html,authenticated):
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH'),headless=True,args=['--no-sandbox'])
        try:
            page=browser.new_page();page.set_default_timeout(250);page.set_content(html)
            if authenticated:wait_for_login(page)
            else:
                with pytest.raises(TimeoutError):wait_for_login(page)
        finally:browser.close()


@pytest.mark.parametrize('script',['do_hieu_nang','ui_screenshots'])
def test_ui_tool_direct_file_entrypoint(script):
    import subprocess
    import sys
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    env=dict(os.environ,PYTHONPATH='')
    result=subprocess.run([sys.executable,str(root/'scripts'/f'{script}.py'),'--help'],cwd=root,env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert 'usage:' in result.stdout
