"""Cách chờ ổn định cho kiểm thử trình duyệt.

Nguyên nhân lỗi chập chờn cũ (run 42586944493): kiểm thử coi tiêu đề trang
hoặc thông báo nổi là dấu hiệu "đã xong", trong khi app.js đặt tiêu đề trước
khi tải dữ liệu và hiện thông báo trước khi vẽ lại màn hình. Thao tác tiếp
theo rơi vào phần tử cũ sắp bị thay (ví dụ gõ huyết áp vào ô cũ rồi chờ cảnh
báo "Huyết áp cao" ở ô mới → hết 30 giây). Ngoài ra bộ hẹn giờ của thông báo
trước có thể ẩn thông báo sau.

Cách chờ ở đây chỉ dựa vào tín hiệu chắc chắn:
- #workspace[aria-busy] được đặt "true" đồng bộ ngay trong trình xử lý sự kiện
  và chỉ về "false" khi màn hình đã vẽ xong;
- #workspace[data-page] cho biết màn hình nào đang hiện;
- phản hồi HTTP của chính thao tác (expect_response), không đoán theo chữ.
"""
from playwright.sync_api import expect


def settle(page):
    expect(page.locator('#workspace')).to_have_attribute('aria-busy', 'false')


def go(page, where):
    """Bấm menu và chờ đúng màn hình đó vẽ xong."""
    page.locator(f'#navigation [data-action="navigate"][data-page="{where}"]').click()
    expect(page.locator('#workspace')).to_have_attribute('data-page', where)
    settle(page)
    text = page.locator('#workspace').inner_text()
    assert 'Không thể tải trang:' not in text, text
    return page


def pick(page, kind, ident):
    """Chọn một dòng trong hàng chờ; chờ màn hình vẽ lại với dòng đó được chọn."""
    page.locator(f'[data-action="pick"][data-kind="{kind}"][data-id="{ident}"]').first.click()
    settle(page)
    if kind not in ('patient', 'dispense'):
        expect(page.locator(f'[data-action="pick"][data-kind="{kind}"][data-id="{ident}"]').first).to_have_attribute('aria-pressed', 'true')


def send(page, trigger, toast=None):
    """Bấm nút gửi, kiểm mã phản hồi của chính yêu cầu đó, rồi chờ màn hình vẽ lại."""
    with page.expect_response(lambda r: '/api/' in r.url and r.request.method in ('POST', 'PUT')) as sent:
        trigger.click()
    response = sent.value
    assert response.status in (200, 201), (response.url, response.status, response.text())
    settle(page)
    if toast:
        expect(page.locator('#toast')).to_contain_text(toast)
    return response


def submit(page, form, toast=None):
    return send(page, page.locator(f'[data-form="{form}"] button.btn').first, toast)


def no_horizontal_scroll(page):
    width = page.evaluate('document.documentElement.scrollWidth')
    view = page.viewport_size['width']
    assert width <= view, f'tràn ngang: {width}px > {view}px'


def small_targets(page):
    """Các nút đang hiện phải cao ít nhất 40px trên điện thoại."""
    sizes = page.locator('#workspace button:visible, #navigation button:visible').evaluate_all('els=>els.map(e=>[e.textContent.trim(),e.getBoundingClientRect().height])')
    return [s for s in sizes if s[1] < 40]
