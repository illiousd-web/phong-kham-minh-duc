"""Dấu hiệu đăng nhập cho công cụ UI, tương thích cả bản trước và sau U1-R1."""


def wait_for_login(page):
    # Bản cũ hiện nút logout; bản mới đặt nút đó trong menu tài khoản đóng.
    # Cả hai dấu hiệu đều bị ẩn trên màn đăng nhập; không đổi timeout của bộ gọi.
    page.locator('#logout:visible, .account-trigger:visible').first.wait_for()
