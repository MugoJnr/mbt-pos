import os
import sys

os.environ['MBT_DATA_ROOT'] = r'C:\MBT_Build\qa-isolated-consumption'
os.environ['PROGRAMDATA'] = r'C:\MBT_Build\qa-isolated-consumption\programdata'
os.environ['QT_QPA_PLATFORM'] = 'windows'
sys.path.insert(0, r'C:\MBT_Build\mbt-pos-port')

from PyQt5.QtWidgets import QApplication
from desktop.tabs.consumption_tab import ConsumptionTab
from desktop.utils.api_client import APIClient
import desktop.utils.api_client as ac

ac._SCHEMA_READY = False
api = APIClient()
api._role = 'superadmin'
api._user_id = 1
api._username = 'admin'
app = QApplication.instance() or QApplication([])
tab = ConsumptionTab(api, {'user': {'id': 1, 'username': 'admin', 'role': 'superadmin', 'full_name': 'Shop Owner'}}, api.db_path if hasattr(api, 'db_path') else '', lambda: {})
tab.resize(1280, 860)
tab.show()
tab._tabs.setCurrentIndex(1)
tab._history.refresh()
app.processEvents()
out = r'C:\MBT_Build\mbt-pos-port\artifacts\internal_consumption_audit\desktop\history-today-filter.png'
tab.grab().save(out)
print(tab._history._s.date().toString('yyyy-MM-dd'), tab._history._e.date().toString('yyyy-MM-dd'), os.path.getsize(out))
