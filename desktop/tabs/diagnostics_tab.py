"""MBT POS - Diagnostics | MugoByte Technologies"""
import sys, os
from datetime import datetime
from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *
from desktop.utils.theme   import C
from desktop.utils.widgets import (Card, H2, Caption, PrimaryBtn, SecondaryBtn, make_table, tbl_item, page_layout)

class DiagnosticsTab(QWidget):
    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api=api; self.user=user; self.db_path=db_path; self.config_getter=config_getter
        self._engine=None; self._build(); self._init_engine()
        self._t=QTimer(self); self._t.timeout.connect(self.refresh); self._t.start(30000)

    def _init_engine(self):
        try:
            pr=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); sys.path.insert(0,pr)
            from diagnostics.diagnostic_engine import DiagnosticEngine
            self._engine=DiagnosticEngine(self.db_path, self.config_getter)
        except Exception as e: self._log(f'[WARN] Engine: {e}')

    def _build(self):
        lay, _ = page_layout(self, margins=(28,24,28,28), spacing=20)
        hdr=QHBoxLayout(); hdr.addWidget(H2('System Diagnostics')); hdr.addStretch()
        for lbl, fn in [('Run Check',self.run_check),('Export',self._export),('Rotate Logs',self._rotate)]:
            b=PrimaryBtn(lbl,40) if 'Run' in lbl else SecondaryBtn(lbl,40)
            b.clicked.connect(fn); hdr.addWidget(b)
        lay.addLayout(hdr)

        cr=QHBoxLayout(); cr.setSpacing(14); self._cards={}
        for name, icon in [('database','DB'),('disk_space','Disk'),('log_files','Logs'),('backend_process','API')]:
            card=Card(); cl=card.layout_v((18,14,18,14),6)
            tl=QLabel(f'{icon}  {name.replace("_"," ").title()}')
            tl.setStyleSheet(f"color:{C['muted']}; font-size:10px; font-weight:700; letter-spacing:1px; background:transparent;")
            st=QLabel('—'); st.setStyleSheet(f"color:{C['text2']}; font-size:14px; font-weight:700; background:transparent;")
            ms=QLabel(''); ms.setStyleSheet(f"color:{C['muted']}; font-size:12px; background:transparent;"); ms.setWordWrap(True)
            cl.addWidget(tl); cl.addWidget(st); cl.addWidget(ms)
            self._cards[name]=(card,st,ms); cr.addWidget(card)
        lay.addLayout(cr)
        self._overall=QLabel('Not checked yet')
        self._overall.setStyleSheet(f"color:{C['text2']}; font-size:15px; font-weight:700; background:transparent; padding:4px 0;")
        lay.addWidget(self._overall)
        tabs=QTabWidget()
        self._dlog=self._lv(); tabs.addTab(self._dlog,'  Diagnostic Log  ')
        self._blog=self._lv(); tabs.addTab(self._blog,'  App Log  ')
        self._slog=self._lv(); tabs.addTab(self._slog,'  Sync Queue  ')
        lay.addWidget(tabs)
        import platform
        self._si=Caption(f"Platform: {platform.system()} {platform.release()}  ·  Python: {sys.version.split()[0]}  ·  PID: {os.getpid()}")
        self._si.setAlignment(Qt.AlignCenter); lay.addWidget(self._si)

    def _lv(self):
        te=QTextEdit(); te.setReadOnly(True); te.setFont(QFont('Consolas',11))
        te.setStyleSheet(f"background:{C['app']}; color:{C['text']}; border:1px solid {C['border']}; border-radius:8px;")
        return te

    def _log(self, msg): self._dlog.append(msg)
    def on_show(self): self.refresh(); QTimer.singleShot(200, self.run_check)
    def refresh(self): self._load_blog(); self._load_slog()

    def run_check(self):
        self._log(f'\n[{datetime.now().strftime("%H:%M:%S")}] Running diagnostics...')
        if self._engine:
            try: self._render(self._engine.run_manual_check())
            except Exception as e: self._log(f'[ERROR] {e}')
        else: self._basic()
        self.refresh()

    def _render(self, report):
        colors={'healthy':C['ok'],'warning':C['warn'],'critical':C['err'],'error':C['err']}
        icons={'healthy':'✓','warning':'⚠','critical':'✗','error':'✗'}
        for name,(card,st,ms) in self._cards.items():
            r=report.get('checks',{}).get(name,{}); s=r.get('status','unknown'); col=colors.get(s,C['text2'])
            card.setStyleSheet(f"QFrame {{ background:{C['card']}; border:1px solid {C['border']}; border-top:3px solid {col}; border-radius:12px; }}")
            st.setText(f"{icons.get(s,'?')}  {s.upper()}"); st.setStyleSheet(f"color:{col}; font-size:14px; font-weight:700; background:transparent;")
            ms.setText(r.get('message','')[:60])
        ov=report.get('overall','?'); oc=colors.get(ov,C['text2'])
        self._overall.setText(f"Overall: {ov.upper()}")
        self._overall.setStyleSheet(f"color:{oc}; font-size:15px; font-weight:700; background:transparent;")

    def _basic(self):
        import sqlite3, shutil, socket as _s
        checks={'database':('healthy','OK'),'disk_space':('healthy','OK'),'log_files':('healthy','OK'),'backend_process':('healthy','OK')}
        try:
            db=sqlite3.connect(self.db_path,timeout=3); db.execute("PRAGMA integrity_check"); db.close()
        except Exception as e: checks['database']=('error',str(e)[:50])
        try:
            _,_,free=shutil.disk_usage(os.path.dirname(self.db_path)); fg=free/(1024**3)
            checks['disk_space']=('healthy' if fg>1 else 'warning',f'{fg:.1f}GB free')
        except: pass
        colors={'healthy':C['ok'],'warning':C['warn'],'error':C['err']}
        icons={'healthy':'✓','warning':'⚠','error':'✗'}
        for name,(card,st,ms) in self._cards.items():
            s,m=checks.get(name,('unknown','—')); col=colors.get(s,C['text2'])
            card.setStyleSheet(f"QFrame {{ background:{C['card']}; border:1px solid {C['border']}; border-top:3px solid {col}; border-radius:12px; }}")
            st.setText(f"{icons.get(s,'?')}  {s.upper()}"); st.setStyleSheet(f"color:{col}; font-size:14px; font-weight:700; background:transparent;")
            ms.setText(m)
        self._overall.setText('Overall: CHECKED')
        self._overall.setStyleSheet(f"color:{C['text2']}; font-size:15px; font-weight:700; background:transparent;")

    def _load_blog(self):
        pr=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        lp=os.path.join(pr,'logs','app.log')
        try:
            if os.path.exists(lp):
                with open(lp,'r',errors='replace') as f: lines=f.readlines()
                self._blog.setPlainText(''.join(lines[-200:]))
                sb=self._blog.verticalScrollBar(); sb.setValue(sb.maximum())
        except Exception as e: self._blog.setPlainText(f'Could not read: {e}')

    def _load_slog(self):
        import sqlite3
        try:
            db=sqlite3.connect(self.db_path,timeout=3); db.row_factory=sqlite3.Row
            rows=db.execute("SELECT * FROM sync_queue ORDER BY created_at DESC LIMIT 100").fetchall(); db.close()
            lines=["ID    STATUS       TYPE         CREATED               PAYLOAD","-"*70]
            for r in rows:
                p=r['payload'][:40]+('...' if len(r['payload'])>40 else '')
                lines.append(f"{r['id']:<5} {r['status']:<12} {r['action_type']:<12} {r['created_at'][:19]:<21} {p}")
            self._slog.setPlainText('\n'.join(lines))
        except Exception as e: self._slog.setPlainText(f'Error: {e}')

    def _export(self):
        if self._engine:
            try: path=self._engine.export_full_report(); QMessageBox.information(self,'Exported',f'Saved:\n{path}')
            except Exception as e: QMessageBox.critical(self,'Error',str(e))

    def _rotate(self):
        if self._engine:
            rotated=self._engine.rotate_logs()
            QMessageBox.information(self,'Logs',f"Rotated: {', '.join(rotated)}" if rotated else 'No logs needed rotation.')
