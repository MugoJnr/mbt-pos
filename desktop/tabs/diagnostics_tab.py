"""MBT POS - Diagnostics | MugoByte Technologies (Lovable layout)"""
import sys, os
from datetime import datetime
from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *
from desktop.utils.theme   import C, RADIUS
from desktop.utils.widgets import (Card, H2, Caption, PrimaryBtn, SecondaryBtn,
                                    GhostBtn, page_layout, lovable_tab_qss, Badge)


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
        lay, _ = page_layout(self, margins=(24,24,24,24), spacing=16)
        hdr=QHBoxLayout(); hdr.setSpacing(8)
        title=QLabel('System Diagnostics')
        title.setStyleSheet(
            f"color:{C['text']}; font-size:20px; font-weight:700; "
            f"background:transparent; border:none;")
        hdr.addWidget(title); hdr.addStretch()
        run=PrimaryBtn('▶  Run Check', 40); run.clicked.connect(self.run_check)
        exp=SecondaryBtn('⬇  Export', 40); exp.clicked.connect(self._export)
        rot=GhostBtn('↺  Rotate Logs', 40); rot.clicked.connect(self._rotate)
        hdr.addWidget(run); hdr.addWidget(exp); hdr.addWidget(rot)
        lay.addLayout(hdr)

        cr=QHBoxLayout(); cr.setSpacing(12); self._cards={}
        for name, label in [
            ('database','Database'), ('disk_space','Disk Space'),
            ('log_files','Log Files'), ('backend_process','Backend Process')
        ]:
            card=Card(); cl=card.layout_v((16,14,16,14),6)
            tl=QLabel(label.upper())
            tl.setStyleSheet(
                f"color:{C['text2']}; font-size:10px; font-weight:700; "
                f"letter-spacing:1.5px; background:transparent; border:none;")
            st=QLabel('—'); st.setStyleSheet(
                f"color:{C['text2']}; font-size:14px; font-weight:700; background:transparent;")
            ms=QLabel(''); ms.setStyleSheet(
                f"color:{C['muted']}; font-size:12px; background:transparent;")
            ms.setWordWrap(True)
            cl.addWidget(tl); cl.addWidget(st); cl.addWidget(ms)
            self._cards[name]=(card,st,ms); cr.addWidget(card)
        lay.addLayout(cr)

        self._overall=QLabel('Not checked yet')
        self._overall.setStyleSheet(
            f"color:{C['text2']}; font-size:14px; font-weight:700; "
            f"background:transparent; padding:2px 0;")
        lay.addWidget(self._overall)

        log_card = Card()
        lcl = log_card.layout_v(margins=(0,0,0,0), spacing=0)
        tabs=QTabWidget(); tabs.setStyleSheet(lovable_tab_qss())
        self._dlog=self._lv(); tabs.addTab(self._dlog,'Diagnostic Log')
        self._blog=self._lv(); tabs.addTab(self._blog,'App Log')
        self._slog=self._lv(); tabs.addTab(self._slog,'Sync Queue')
        lcl.addWidget(tabs)
        lay.addWidget(log_card, 1)

        import platform
        self._si=Caption(
            f"Platform: {platform.system()} {platform.release()}  ·  "
            f"Python: {sys.version.split()[0]}  ·  PID: {os.getpid()}")
        self._si.setAlignment(Qt.AlignCenter); lay.addWidget(self._si)

    def _lv(self):
        te=QTextEdit(); te.setReadOnly(True); te.setFont(QFont('Consolas',11))
        te.setStyleSheet(
            f"background:{C['app']}; color:{C['text2']}; border:none; "
            f"border-radius:0; padding:14px; font-size:12.5px;")
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
        r = RADIUS['lg']
        for name,(card,st,ms) in self._cards.items():
            chk=report.get('checks',{}).get(name,{}); s=chk.get('status','unknown'); col=colors.get(s,C['text2'])
            card.setStyleSheet(
                f"QFrame {{ background:{C['card']}; border:1px solid {C['border']}; "
                f"border-top:3px solid {col}; border-radius:{r}px; }}")
            st.setText(f"{icons.get(s,'?')}  {s.upper()}")
            st.setStyleSheet(f"color:{col}; font-size:14px; font-weight:700; background:transparent;")
            ms.setText(chk.get('message','')[:80])
        ov=report.get('overall','?'); oc=colors.get(ov,C['text2'])
        self._overall.setText(f"Overall: {ov.upper()}")
        self._overall.setStyleSheet(f"color:{oc}; font-size:14px; font-weight:700; background:transparent;")

    def _basic(self):
        import sqlite3, shutil
        checks={'database':('healthy','OK'),'disk_space':('healthy','OK'),
                'log_files':('healthy','OK'),'backend_process':('healthy','OK')}
        try:
            db=sqlite3.connect(self.db_path,timeout=3); db.execute("PRAGMA integrity_check"); db.close()
        except Exception as e: checks['database']=('error',str(e)[:50])
        try:
            _,_,free=shutil.disk_usage(os.path.dirname(self.db_path) or '.'); fg=free/(1024**3)
            checks['disk_space']=('healthy' if fg>1 else 'warning',f'{fg:.1f}GB free')
        except: pass
        colors={'healthy':C['ok'],'warning':C['warn'],'error':C['err']}
        icons={'healthy':'✓','warning':'⚠','error':'✗'}
        r = RADIUS['lg']
        for name,(card,st,ms) in self._cards.items():
            s,m=checks.get(name,('unknown','—')); col=colors.get(s,C['text2'])
            card.setStyleSheet(
                f"QFrame {{ background:{C['card']}; border:1px solid {C['border']}; "
                f"border-top:3px solid {col}; border-radius:{r}px; }}")
            st.setText(f"{icons.get(s,'?')}  {s.upper()}")
            st.setStyleSheet(f"color:{col}; font-size:14px; font-weight:700; background:transparent;")
            ms.setText(m)
        self._overall.setText('Overall: CHECKED')
        self._overall.setStyleSheet(f"color:{C['text2']}; font-size:14px; font-weight:700; background:transparent;")

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
                p=(r['payload'] or '')[:40]+('...' if len(r['payload'] or '')>40 else '')
                lines.append(f"{r['id']:<5} {r['status']:<12} {r.get('type','') or r.get('entity_type',''):<12} "
                             f"{(r['created_at'] or '')[:19]:<21} {p}")
            self._slog.setPlainText('\n'.join(lines) if len(lines)>2 else 'Queue empty.')
        except Exception as e:
            self._slog.setPlainText(f'No sync queue / {e}')

    def _export(self):
        path,_=QFileDialog.getSaveFileName(self,'Export Diagnostics','mbt_diagnostics.txt','Text (*.txt)')
        if not path: return
        try:
            with open(path,'w',encoding='utf-8') as f:
                f.write(self._dlog.toPlainText()+'\n\n'+self._blog.toPlainText())
            QMessageBox.information(self,'Exported',f'Saved to {path}')
        except Exception as e: QMessageBox.warning(self,'Error',str(e))

    def _rotate(self):
        pr=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        lp=os.path.join(pr,'logs','app.log')
        try:
            if os.path.exists(lp):
                bak=lp+'.'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.bak'
                os.rename(lp, bak); open(lp,'w').close()
                self._log(f'Rotated log → {bak}')
                QMessageBox.information(self,'Rotated',f'Log archived to:\n{bak}')
        except Exception as e: QMessageBox.warning(self,'Error',str(e))
