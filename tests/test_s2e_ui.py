"""Static wiring for the S2e-2 management reports screen."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

STATIC = Path(__file__).resolve().parents[1] / 'app' / 'static'


def test_index_loads_report_script_after_m5():
    index = (STATIC / 'index.html').read_text(encoding='utf-8')
    assert re.search(
        r'<script src="/assets/m5\.js" defer></script>\s*'
        r'<script src="/assets/s2e\.js" defer></script>',
        index,
    )


def test_report_screen_registered_for_manager_and_admin():
    script = (STATIC / 's2e.js').read_text(encoding='utf-8')
    assert "SCREENS['s2e-reports']=()=>S2E.screen();" in script
    for role in ('manager', 'admin'):
        assert f"menus.{role}.push(['s2e-reports','Báo cáo quản lý']);" in script


def test_report_script_uses_escaped_templates_instead_of_direct_html_assignment():
    script = (STATIC / 's2e.js').read_text(encoding='utf-8')
    assert not re.search(r'\bonclick\s*=|\binnerHTML\s*(?:\+?=)', script, re.IGNORECASE)
    for value in ('data.warning', 'data.note', 'error.message'):
        assert 'esc(' + value + ')' in script
    assert "esc(value===null?'—':format==='money'?money(value):format==='date'?showDay(value):value)" in script


def test_report_script_is_served():
    response = TestClient(app).get('/assets/s2e.js')
    assert response.status_code == 200
    assert "SCREENS['s2e-reports']" in response.text


def test_report_display_limits_and_revenue_labels():
    script = (STATIC / 's2e.js').read_text(encoding='utf-8')
    assert re.search(r'rowLimit:\s*500\b', script)
    assert 'rows.slice(0,this.rowLimit)' in script
    assert 'totals.known_due' in script
    assert 'Đã thu thuần (sau hoàn tiền)' in script
