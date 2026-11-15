"""S2b real HTTPS UI: 390px tables, resize persistence, documents and role privacy."""
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from .browser_helpers import settle, no_horizontal_scroll
from .conftest import PASSWORDS
from tests.s2b_cases import med, owner_sessions, receive


def check_stock_390px_sticky_resize_cost_privacy_and_forms(https_server, clients):
    factory = owner_sessions(clients)
    owner = factory()
    mid = med(clients)
    for i in range(18):
        receive(owner, mid, qty=1000000, cost=1900000000, lot=f'S2B-390-{mid}-{i}')
    origin, _ = https_server
    evidence = Path('test_evidence/s2b')
    evidence.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH', '/usr/bin/chromium'), headless=True,
                                    args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = browser.new_context(ignore_https_errors=True, accept_downloads=True, viewport={'width': 390, 'height': 844})
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(origin)
        page.locator('[name=username]').fill(factory.username)
        page.locator('[name=password]').fill(factory.password)
        page.locator('[data-form=login] button').click()
        page.locator('.account-trigger').wait_for()
        settle(page)
        page.locator('[data-r5-jump=r5-stock]').click()
        table = page.locator('[data-stock-table="lots-true"]')
        wrapper = table.locator('..')
        expect(table.locator('thead')).to_be_visible()
        assert table.evaluate("e=>getComputedStyle(e).tableLayout") == 'fixed'
        assert table.locator('col').count() == table.locator('th').count() == 8
        assert wrapper.evaluate('e=>e.scrollWidth>e.clientWidth&&e.scrollHeight>e.clientHeight')
        before = table.locator('tbody td').first.bounding_box()
        wrapper.evaluate('e=>{e.scrollLeft=500;e.scrollTop=160}')
        page.wait_for_timeout(80)
        after = table.locator('tbody tr').nth(5).locator('td').first.bounding_box()
        assert abs(after['x'] - before['x']) <= 1
        head = table.locator('th').first.bounding_box()
        frame = wrapper.bounding_box()
        assert abs(head['y'] - frame['y']) <= 2
        assert table.locator('th').first.evaluate("e=>getComputedStyle(e).position") == 'sticky'
        assert table.locator('tbody td').first.evaluate("e=>getComputedStyle(e).position") == 'sticky'
        for cell in table.locator('tbody td.r').all():
            assert cell.get_attribute('title') == cell.inner_text()
            assert cell.evaluate('e=>e.scrollWidth<=e.clientWidth+1'), str(cell.evaluate("""e=>({text:e.innerText,scroll:e.scrollWidth,width:e.clientWidth,font:getComputedStyle(e).font,table:e.closest('table').getBoundingClientRect().width,cols:[...e.closest('table').querySelectorAll('col')].map(c=>({inline:c.style.width,computed:getComputedStyle(c).width})),cells:[...e.parentElement.cells].map(c=>({text:c.innerText,width:c.clientWidth}))})"""))
            assert cell.evaluate("e=>getComputedStyle(e).fontVariantNumeric") == 'tabular-nums'
        wrapper.evaluate('e=>{e.scrollLeft=0;e.scrollTop=0}')
        width = table.locator('col').first.evaluate('e=>parseFloat(e.style.width)')
        grip = table.locator('.s2b-grip').first
        wrapper.scroll_into_view_if_needed()
        table.evaluate('e=>window.scrollBy(0,e.getBoundingClientRect().top-140)')
        grip.scroll_into_view_if_needed()
        box = grip.bounding_box()
        assert grip.evaluate('e=>{const b=e.getBoundingClientRect();return document.elementFromPoint(b.x+b.width/2,b.y+b.height/2)===e}')
        page.mouse.move(box['x'] + box['width']/2, box['y'] + box['height']/2)
        page.mouse.down()
        page.mouse.move(box['x'] + box['width']/2 + 70, box['y'] + box['height']/2, steps=5)
        page.mouse.up()
        assert table.locator('col').first.evaluate('e=>parseFloat(e.style.width)') >= width + 60
        stored = page.evaluate("JSON.parse(localStorage.getItem('minhduc.stock.columns.v1.lots-true'))")
        assert stored[0] >= width + 60
        page.reload()
        settle(page)
        page.locator('[data-r5-jump=r5-stock]').click()
        table = page.locator('[data-stock-table="lots-true"]')
        assert table.locator('col').first.evaluate('e=>parseFloat(e.style.width)') == stored[0]
        # Keyboard shrink is clamped to full numeric content width.
        numeric = table.locator('th.r .s2b-grip').last
        numeric.focus()
        for _ in range(12):
            numeric.press('ArrowLeft')
        assert all(cell.evaluate('e=>e.scrollWidth<=e.clientWidth+1') for cell in table.locator('tbody td.r').all())
        no_horizontal_scroll(page)
        wrapper.scroll_into_view_if_needed()
        table.evaluate('e=>window.scrollBy(0,e.getBoundingClientRect().top-100)')
        page.screenshot(path=str(evidence/'kho-390.png'))
        page.set_viewport_size({'width': 1366, 'height': 900})
        page.locator('[data-r5-jump=r5-receipt]').click()
        receipt = page.locator('[data-form=stock-receipt]')
        receipt.locator('[name=medicine_id]').select_option(str(mid))
        receipt.locator('[name=supplier]').fill('Nhà cung cấp giả lập qua giao diện')
        receipt.locator('[name=invoice_no]').fill('HĐ-UI-GIẢ-LẬP')
        receipt.locator('[name=invoice_date]').fill('15/11/2026')
        receipt.locator('[name=lot_number]').fill(f'S2B-UI-{mid}')
        receipt.locator('[name=expiry_date]').fill('01/01/2029')
        receipt.locator('[name=quantity]').fill('5')
        receipt.locator('[name=unit_cost]').fill('1200')
        receipt.locator('[name=vat_rate]').fill('5')
        expect(receipt.locator('[data-s2b-total]')).to_have_text('6.300 đ')
        receipt.locator('button').click()
        expect(page.locator('#toast')).to_contain_text('Đã lưu phiếu nhập PN-')
        with page.expect_download() as download:
            page.locator('[data-action=s2b-print-document][data-kind=receipts]').click()
        download.value.save_as(str(evidence/'phieu-nhap-01VT.pdf'))
        page.locator('[data-r5-jump=r5-report]').click()
        period = page.locator('[data-form=s2b-period]')
        period.locator('[name=period]').select_option('quarter')
        period.locator('[name=quarter]').select_option('4')
        period.locator('[name=year]').fill('2026')
        period.locator('button').click()
        settle(page)
        expect(page.locator('#r5-report h2')).to_contain_text('01/10/2026–31/12/2026')
        with page.expect_download() as download:
            page.locator('[data-action=s2b-report-export][data-format=xlsx]').click()
        download.value.save_as(str(evidence/'xuat-nhap-ton.xlsx'))
        # Storage denied must still render and resize.
        page.evaluate("()=>{Storage.prototype.setItem=function(){throw new Error('Bộ nhớ bị khóa')};Storage.prototype.getItem=function(){throw new Error('Bộ nhớ bị khóa')};}")
        page.locator('[data-action=s2b-filter][data-value=expiring]').click()
        settle(page)
        expect(page.locator('[data-stock-table]')).to_have_count(2)
        page.locator('[data-stock-table]').first.locator('.s2b-grip').first.focus()
        page.locator('[data-stock-table]').first.locator('.s2b-grip').first.press('ArrowRight')
        page.screenshot(path=str(evidence/'kho-1366.png'), full_page=True)
        context.close()
        # A pharmacy account without the auxiliary role receives no finance columns/forms.
        context = browser.new_context(ignore_https_errors=True, viewport={'width': 390, 'height': 844})
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(origin)
        page.locator('[name=username]').fill('test_pharmacy')
        page.locator('[name=password]').fill(PASSWORDS['pharmacy'])
        page.locator('[data-form=login] button').click()
        settle(page)
        page.locator('[data-r5-jump=r5-stock]').click()
        expect(page.locator('[data-stock-table="lots-false"] th')).to_have_count(6)
        expect(page.locator('[data-form=stock-receipt] [name=unit_cost]')).to_have_count(0)
        assert 'Giá trị tồn kho' not in page.locator('.s2b-stats').inner_text()
        assert 'Lãi gộp' not in page.locator('.s2b-stats').inner_text()
        no_horizontal_scroll(page)
        context.close()
        # Admin assigns the auxiliary role through the existing account editor.
        context = browser.new_context(ignore_https_errors=True, viewport={'width': 1366, 'height': 900})
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(origin)
        page.locator('[name=username]').fill('test_admin')
        page.locator('[name=password]').fill(PASSWORDS['admin'])
        page.locator('[data-form=login] button').click()
        settle(page)
        account = next(row for row in clients['admin'].get('/api/accounts').json() if row['username'] == factory.username)
        page.locator('#account_choose').select_option(str(account['id']))
        settle(page)
        editor = page.locator('[data-form=account-edit]')
        expect(editor.locator('[name=roles][value=stock_owner]')).to_be_checked()
        expect(editor).to_contain_text('Quyền phụ kho thuốc')
        editor.locator('[name=roles][value=stock_owner]').uncheck()
        editor.locator('button').first.click()
        settle(page)
        changed = next(row for row in clients['admin'].get('/api/accounts').json() if row['id'] == account['id'])
        assert changed['roles'] == ['pharmacy']
        editor = page.locator('[data-form=account-edit]')
        editor.locator('[name=roles][value=stock_owner]').check()
        editor.locator('button').first.click()
        settle(page)
        changed = next(row for row in clients['admin'].get('/api/accounts').json() if row['id'] == account['id'])
        assert set(changed['roles']) == {'pharmacy', 'stock_owner'}
        context.close()
        browser.close()
    owner.close()
    assert errors == []
