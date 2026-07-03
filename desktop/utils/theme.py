"""
MBT POS - Premium Enterprise Theme v4
MugoByte Technologies | mugobyte.com
"""

C = {
    'app':      '#070C14',
    'surface':  '#0A1220',
    'panel':    '#0D1828',
    'card':     '#111F33',
    'card2':    '#162540',
    'sidebar':  '#080E1C',
    'input':    '#0F1C30',
    'hover':    '#192D48',
    'selected': '#1B3560',
    'gold':     '#F0A500',
    'gold_lt':  '#FFBE3A',
    'gold_dk':  '#C07800',
    'gold_dim': '#F0A50018',
    'text':     '#F0F4FC',
    'text2':    '#6E8FA8',
    'muted':    '#374F66',
    'disabled': '#222E3C',
    'ok':       '#00D68F',
    'ok_dim':   '#00D68F18',
    'warn':     '#FFAA00',
    'warn_dim': '#FFAA0018',
    'err':      '#FF4757',
    'err_dim':  '#FF475718',
    'info':     '#4E90FF',
    'info_dim': '#4E90FF18',
    'border':   '#141E2E',
    'border2':  '#1A2D44',
    'sep':      '#0D1620',
}

COLORS = {
    'accent': C['gold'], 'success': C['ok'], 'danger': C['err'],
    'warning': C['warn'], 'info': C['info'],
    'text_primary': C['text'], 'text_secondary': C['text2'],
    'text_muted': C['muted'], 'bg_card': C['card'],
    'bg_sidebar': C['sidebar'], 'border': C['border'],
    'border_strong': C['border2'],
}

def _ss():
    return f"""
* {{
    font-family: 'Segoe UI', 'Inter', 'Ubuntu', Arial, sans-serif;
    font-size: 14px;
    color: {C['text']};
    outline: none;
}}
QMainWindow, QWidget, QDialog {{ background: {C['surface']}; border: none; }}
QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QFrame {{ border: none; }}

#sidebar {{ background: {C['sidebar']}; border-right: 1px solid {C['border']}; min-width:220px; max-width:220px; }}
#sidebarLogo {{ background: {C['app']}; min-height:78px; max-height:78px; border-bottom:1px solid {C['border']}; }}
#sidebarLogoText {{ color:{C['gold']}; font-size:24px; font-weight:900; letter-spacing:10px; background:transparent; }}
#sidebarLogoSub  {{ color:{C['muted']}; font-size:9px; letter-spacing:4px; font-weight:600; background:transparent; }}

#navBtn {{
    background: transparent; color: {C['text2']}; border: none;
    padding: 12px 14px 12px 16px; text-align: left;
    font-size: 14px; font-weight: 600; border-radius: 8px;
    margin: 2px 8px; min-height: 46px;
}}
#navBtn:hover {{ background:{C['hover']}; color:{C['text']}; }}
#navBtn:checked {{ background:{C['selected']}; color:{C['gold']}; font-weight:700; }}

#sidebarUser {{ background:{C['app']}; border-top:1px solid {C['border']}; min-height:72px; }}
#sidebarUserName {{ color:{C['text']}; font-size:14px; font-weight:700; background:transparent; }}
#sidebarUserRole {{ color:{C['gold']}; font-size:10px; letter-spacing:2.5px; font-weight:600; background:transparent; }}
#logoutBtn {{
    background:transparent; color:{C['muted']}; border:1px solid {C['border2']};
    border-radius:6px; padding:4px 12px; font-size:11px; margin-top:4px; min-height:0;
}}
#logoutBtn:hover {{ color:{C['err']}; border-color:{C['err']}; background:{C['err_dim']}; }}

#topbar {{ background:{C['panel']}; border-bottom:1px solid {C['border']}; min-height:56px; max-height:56px; }}
#pageTitle {{ color:{C['text']}; font-size:18px; font-weight:700; background:transparent; }}
#connBadge {{ font-size:12px; font-weight:600; padding:3px 10px; border-radius:20px; background:transparent; }}
#syncLbl   {{ color:{C['text2']}; font-size:12px; background:transparent; }}
#clockLbl  {{ color:{C['text2']}; font-size:12px; font-family:'Consolas','Courier New',monospace; background:transparent; padding:0 4px; }}
#refreshBtn {{ background:transparent; color:{C['text2']}; border:1px solid {C['border2']}; border-radius:7px; padding:5px 14px; font-size:12px; min-height:0; }}
#refreshBtn:hover {{ color:{C['text']}; background:{C['hover']}; }}

#statusBar {{ background:{C['app']}; border-top:1px solid {C['border']}; min-height:24px; max-height:24px; }}
#statusLeft  {{ color:{C['muted']}; font-size:11px; background:transparent; }}
#statusRight {{ color:{C['muted']}; font-size:11px; background:transparent; }}
#pageStack {{ background:{C['surface']}; }}
#content  {{ background:{C['surface']}; }}

QPushButton {{
    background:{C['card2']}; color:{C['text']};
    border:1px solid {C['border2']}; border-radius:8px;
    padding:10px 18px; font-size:14px; font-weight:600; min-height:40px;
}}
QPushButton:hover {{ background:{C['hover']}; color:{C['text']}; }}
QPushButton:pressed {{ background:{C['app']}; color:{C['text']}; }}
QPushButton:disabled {{ background:{C['panel']}; color:{C['text2']}; border-color:{C['border2']}; }}

QPushButton[objectName="primaryBtn"] {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {C['gold_lt']}, stop:1 {C['gold']});
    color:{C['app']}; border:none; font-weight:800; font-size:14.5px; border-radius:8px;
}}
QPushButton[objectName="primaryBtn"]:hover {{ background:{C['gold_lt']}; }}
QPushButton[objectName="primaryBtn"]:pressed {{ background:{C['gold_dk']}; }}
QPushButton[objectName="successBtn"] {{ background:{C['ok']}; color:#000; border:none; font-weight:700; border-radius:8px; }}
QPushButton[objectName="successBtn"]:hover {{ background:#1DFAA0; }}
QPushButton[objectName="dangerBtn"]  {{ background:{C['err']}; color:#fff; border:none; font-weight:700; border-radius:8px; }}
QPushButton[objectName="dangerBtn"]:hover {{ background:#FF6B78; }}

QLineEdit, QTextEdit, QPlainTextEdit {{
    background:{C['input']}; color:{C['text']};
    border:1px solid {C['border2']}; border-radius:8px;
    padding:9px 14px; font-size:14px;
    selection-background-color:{C['gold']}; selection-color:{C['app']};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border-color:{C['gold']}; background:{C['hover']}; }}
QLineEdit[readOnly="true"] {{ color:{C['text2']}; border-color:{C['border2']}; background:{C['panel']}; }}

QSpinBox, QDoubleSpinBox {{
    background:{C['input']}; color:{C['text']};
    border:1px solid {C['border2']}; border-radius:8px; padding:8px 10px; font-size:14px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color:{C['gold']}; }}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background:{C['border2']}; border:none; width:22px; border-radius:3px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{ background:{C['gold']}; }}

QComboBox {{
    background:{C['input']}; color:{C['text']};
    border:1px solid {C['border2']}; border-radius:8px; padding:8px 14px; font-size:14px;
}}
QComboBox:focus {{ border-color:{C['gold']}; }}
QComboBox::drop-down {{ border:none; width:30px; }}
QComboBox QAbstractItemView {{
    background:{C['card2']}; color:{C['text']};
    border:1px solid {C['border2']}; border-radius:8px;
    selection-background-color:{C['selected']}; selection-color:{C['gold']}; padding:4px;
}}
QComboBox QAbstractItemView::item {{ padding:8px 12px; min-height:32px; }}

QTableWidget, QTableView {{
    background:{C['card']}; color:{C['text']};
    gridline-color:transparent; border:none; border-radius:10px;
    font-size:14.5px; alternate-background-color:{C['card2']};
    selection-background-color:{C['selected']}; selection-color:{C['gold']};
    show-decoration-selected:1;
}}
QTableWidget::item, QTableView::item {{ padding:11px 14px; border:none; }}
QTableWidget::item:selected, QTableView::item:selected {{ color:{C['gold']}; }}
QHeaderView::section {{
    background:{C['panel']}; color:{C['text2']};
    font-size:11.5px; font-weight:800; letter-spacing:0.8px;
    padding:12px 14px; border:none; border-bottom:1px solid {C['border2']};
    text-transform:uppercase;
}}
QHeaderView {{ border:none; background:transparent; }}
QTableCornerButton::section {{ background:{C['panel']}; border:none; }}

QTabWidget::pane {{ background:{C['card']}; border:1px solid {C['border']}; border-radius:10px; border-top-left-radius:0; }}
QTabBar {{ background:transparent; }}
QTabBar::tab {{
    background:transparent; color:{C['text2']}; border:none;
    border-bottom:2px solid transparent; padding:10px 24px;
    margin-right:2px; font-size:13px; font-weight:500;
}}
QTabBar::tab:selected {{ color:{C['gold']}; border-bottom:2px solid {C['gold']}; font-weight:700; }}
QTabBar::tab:hover:!selected {{ color:{C['text']}; background:{C['hover']}20; }}

QScrollBar:vertical {{ background:transparent; width:5px; border-radius:3px; margin:0; }}
QScrollBar::handle:vertical {{ background:{C['border2']}; border-radius:3px; min-height:30px; }}
QScrollBar::handle:vertical:hover {{ background:{C['gold']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
QScrollBar:horizontal {{ background:transparent; height:5px; border-radius:3px; }}
QScrollBar::handle:horizontal {{ background:{C['border2']}; border-radius:3px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width:0; }}

QGroupBox {{
    border:1px solid {C['border2']}; border-radius:12px;
    margin-top:20px; padding:20px 18px 16px 18px;
    background:{C['card']};
}}
QGroupBox::title {{
    subcontrol-origin:margin; left:18px; padding:0 8px;
    color:{C['gold']}; font-size:10px; font-weight:700; letter-spacing:1.5px;
}}

QCheckBox, QRadioButton {{ color:{C['text']}; font-size:14px; spacing:10px; background:transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width:17px; height:17px;
    border:2px solid {C['border2']}; border-radius:4px; background:{C['input']};
}}
QCheckBox::indicator:checked {{ background:{C['gold']}; border-color:{C['gold']}; }}
QRadioButton::indicator {{ border-radius:9px; }}
QRadioButton::indicator:checked {{ background:{C['gold']}; border-color:{C['gold']}; }}

QProgressBar {{ background:{C['border2']}; border:none; border-radius:4px; height:5px; text-align:center; color:transparent; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {C['gold']}, stop:1 {C['gold_lt']}); border-radius:4px; }}

QMessageBox {{ background:{C['card2']}; border:1px solid {C['border2']}; border-radius:12px; }}
QMessageBox QLabel {{ color:{C['text']}; font-size:14px; background:transparent; }}
QMessageBox QPushButton {{ min-width:90px; color:{C['text']}; }}

QDialogButtonBox QPushButton {{
    background:{C['card2']}; color:{C['text']};
    border:1px solid {C['border2']}; border-radius:8px;
    padding:8px 22px; font-size:13px; font-weight:500; min-height:34px; min-width:80px;
}}
QDialogButtonBox QPushButton:hover {{ background:{C['hover']}; color:{C['text']}; }}
QDialogButtonBox QPushButton:pressed {{ background:{C['app']}; }}
QDialogButtonBox QPushButton[text="OK"], QDialogButtonBox QPushButton[text="Save"] {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {C['gold_lt']}, stop:1 {C['gold']});
    color:{C['app']}; border:none; font-weight:800;
}}

QSplitter::handle {{ background:{C['border']}; width:1px; height:1px; }}

QListWidget {{
    background:{C['card']}; color:{C['text']};
    border:none; border-radius:10px; outline:none;
}}
QListWidget::item {{
    padding:10px 14px; border:none; border-radius:6px; margin:1px 4px;
}}
QListWidget::item:selected {{ background:{C['selected']}; color:{C['gold']}; }}
QListWidget::item:hover:!selected {{ background:{C['hover']}; }}

QDateEdit {{
    background:{C['input']}; color:{C['text']};
    border:1px solid {C['border2']}; border-radius:8px; padding:8px 12px; font-size:13px;
}}
QDateEdit:focus {{ border-color:{C['gold']}; }}
QDateEdit::drop-down {{ border:none; width:26px; }}
QCalendarWidget {{ background:{C['card2']}; color:{C['text']}; }}

#loginBrand {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 {C['app']}, stop:0.5 {C['sidebar']}, stop:1 {C['card']});
    border-bottom:1px solid {C['border2']};
}}
#logoText {{
    color:{C['gold']}; font-size:46px; font-weight:900;
    letter-spacing:12px; background:transparent;
}}
#loginTitle    {{ color:{C['text']};  font-size:11px; font-weight:700; letter-spacing:5px; background:transparent; }}
#loginSubtitle {{ color:{C['muted']}; font-size:11px; letter-spacing:1px; background:transparent; }}
#loginForm     {{ background:{C['surface']}; }}
#loginStatus   {{ font-size:13px; color:{C['text2']}; min-height:28px; background:transparent; }}
#loginInput    {{ font-size:15px; padding:13px 16px; border-radius:9px; }}
#loginBtn {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {C['gold_lt']}, stop:1 {C['gold']});
    color:{C['app']}; font-size:14px; font-weight:900; letter-spacing:2px;
    padding:14px; border:none; border-radius:9px; min-height:46px;
}}
#loginBtn:hover  {{ background:{C['gold_lt']}; }}
#loginBtn:pressed {{ background:{C['gold_dk']}; }}
#loginFooter {{ font-size:11px; color:{C['muted']}; background:transparent; }}

#kpiLabel {{ color:{C['muted']}; font-size:10px; font-weight:700; letter-spacing:1px; background:transparent; }}
#kpiSub   {{ color:{C['text2']}; font-size:12px; background:transparent; }}
#sectionEyebrow {{ color:{C['muted']}; font-size:10px; font-weight:700; letter-spacing:2px; background:transparent; }}
#sectionTitle   {{ color:{C['text']}; font-size:18px; font-weight:700; background:transparent; }}
"""

MBT_STYLESHEET = _ss()
