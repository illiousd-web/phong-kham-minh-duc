"""Mã phiếu kho còn sau tải lại, tách theo form và xóa sau khi lưu."""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


def test_stock_request_keys_survive_reload_and_clear_on_success():
    source = (Path(__file__).resolve().parents[1] / 'app/static/app.js').read_text()
    keyed = source[source.index('const actionKeys=new Map();'):source.index('// Mỗi thao tác trả về')]
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'),
                                    args=['--no-sandbox', '--disable-dev-shm-usage'])
        if os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR'):
            assert browser.version.split('.')[0] == os.environ['MINHDUC_EXPECT_CHROMIUM_MAJOR']
        page = browser.new_page()
        page.route('https://t4.example/', lambda route: route.fulfill(status=200, body='<html></html>'))
        page.goto('https://t4.example/')
        setup = "()=>{window.requestId=()=>crypto.randomUUID();window.api=async (path,opts)=>{window.sent=opts.body;throw Error('mất mạng')};" + keyed + ';window.keyed=keyed;}'
        page.evaluate(setup)
        for kind in ('stock-receipt', 'stock-issue'):
            page.evaluate("async kind=>{try{await keyed(kind,'/test',{quantity:1})}catch(e){}}", kind)
        saved = page.evaluate("Object.keys(sessionStorage).sort().map(k=>JSON.parse(sessionStorage[k]).key)")
        assert len(saved) == 2 and saved[0] != saved[1]
        page.reload()
        page.evaluate(setup)
        page.evaluate("async()=>{try{await keyed('stock-receipt','/test',{quantity:1})}catch(e){}}")
        assert page.evaluate('window.sent.request_key') == saved[1]
        page.evaluate("()=>{window.api=async (path,opts)=>{window.sent=opts.body;return {ok:true}}}")
        page.evaluate("async()=>await keyed('stock-receipt','/test',{quantity:1})")
        assert page.evaluate("sessionStorage.getItem('md_stock_key_stock-receipt')") is None
        assert page.evaluate("sessionStorage.getItem('md_stock_key_stock-issue')") is not None
        browser.close()
