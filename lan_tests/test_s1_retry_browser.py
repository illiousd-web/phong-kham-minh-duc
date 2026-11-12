"""Run the actual api() implementation in the CI Chromium (including 109)."""
import os
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright


@pytest.mark.parametrize('method,body,failures,expected', [
    ('POST',{'idempotency_key':'gia-lap'},1,2),
    ('POST',{'idempotency_key':'gia-lap'},2,2),
    ('POST',{'request_key':'gia-lap'},1,1),
    ('POST',{},1,1),
    ('GET',{'idempotency_key':'gia-lap'},1,1)])
def test_only_idempotent_write_retries_once_after_retry_after(method,body,failures,expected):
    source = (Path(__file__).resolve().parents[1]/'app/static/app.js').read_text()
    function = source[source.index('async function api('):source.index('function field(')]
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH','/usr/bin/chromium'), args=['--no-sandbox','--disable-dev-shm-usage'])
        if os.getenv('MINHDUC_EXPECT_CHROMIUM_MAJOR'):
            assert browser.version.split('.')[0] == os.environ['MINHDUC_EXPECT_CHROMIUM_MAJOR']
        page = browser.new_page()
        page.evaluate('window.authHeader=()=>({});'+function)
        result = page.evaluate('''async ({method,body,failures})=>{
          let calls=[];window.fetch=async (url,options)=>{
            calls.push({body:options.body,at:performance.now()});
            return calls.length<=failures ? new Response(JSON.stringify({detail:'Đang sao lưu, thử lại sau 1 giây'}),{status:503,headers:{'Retry-After':'1'}})
              :new Response(JSON.stringify({ok:true}),{status:200});
          };
          let error=null;try{await api('/gia-lap',{method,body})}catch(e){error=e.message}
          return {calls,error};
        }''', {'method':method,'body':body,'failures':failures})
        assert len(result['calls']) == expected
        if expected == 2:
            assert result['calls'][1]['at']-result['calls'][0]['at'] >= 950
            assert result['calls'][1]['body'] == result['calls'][0]['body']
        assert bool(result['error']) == (failures >= expected)
        if result['error']:
            assert result['error'] == 'Đang sao lưu, thử lại sau 1 giây'
        browser.close()
