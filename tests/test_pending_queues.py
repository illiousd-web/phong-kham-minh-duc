"""Việc cũ không mất khi có hơn 100 hồ sơ đã xong mới hơn (SQLite)."""
from tests.test_workflows import client,token
from tests.pending_queue_cases import pending_data,assert_pending_queues,assert_more_than_100_pending_approvals
from app import main
from app.ui_settings import read_settings,settings_path
from app.main import FILES


def test_pending_queues_sqlite_keep_old_work_counts_and_permissions():
    names={'doctor':'bs_noi','doctor2':'bs_san','reception':'letan','nurse':'dieuduong','pharmacy':'duoc','technician':'kythuat','manager':'quanly','cashier':'thungan'}
    headers={role:token(user) for role,user in names.items()}
    def get(role,path):return client.get(path,headers=headers.get(role,{}))
    with main.db() as c:
        ids={role:c.execute('SELECT id FROM users WHERE username=?',(user,)).fetchone()[0] for role,user in names.items()}
    before={role:get(role,'/api/queue-counts').json() for role in ('technician','reception','doctor','nurse','manager')}
    with pending_data(main.db,ids) as data:
        assert_pending_queues(get,data,before,read_settings(settings_path(FILES))['addendum'])
        assert_more_than_100_pending_approvals(main.db,get,data,before,read_settings(settings_path(FILES))['addendum'])
