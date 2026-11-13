# -*- coding: utf-8 -*-
"""One-shot: strip emoji/unicode prefixes from common buttons + attach painted icons."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATCHES = {
    'desktop/tabs/settings_tab.py': [
        ("PrimaryBtn('💾  Save Changes', 40)", "PrimaryBtn('Save Changes', 40)"),
    ],
    'desktop/tabs/inventory_tab.py': [
        ("SecondaryBtn('\\u2699  Adjust Stock', 40)", "SecondaryBtn('Adjust Stock', 40)"),
        ("GhostBtn('\\u21bb  Refresh', 40)", "GhostBtn('Refresh', 40)"),
    ],
    'desktop/tabs/finance_tab.py': [
        ("GhostBtn('↺ Refresh', 40)", "GhostBtn('Refresh', 40)"),
        ("GhostBtn('↺ Refresh', 36)", "GhostBtn('Refresh', 36)"),
    ],
    'desktop/tabs/admin_tab.py': [
        ("GhostBtn('↺ Refresh', 40)", "GhostBtn('Refresh', 40)"),
    ],
    'desktop/tabs/reports_tab.py': [
        ("PrimaryBtn('⬇  Export Excel', 40)", "PrimaryBtn('Export Excel', 40)"),
        ("SecondaryBtn('✉  Email Report', 40)", "SecondaryBtn('Email Report', 40)"),
        ("self._exp_btn.setText('⬇  Export Excel')", "self._exp_btn.setText('Export Excel')"),
        ("self._email_btn.setText('✉  Email Report')", "self._email_btn.setText('Email Report')"),
        ("QLabel('✦  AI Summary')", "QLabel('AI Summary')"),
    ],
    'desktop/tabs/license_tab.py': [
        ('GhostBtn("↺  Refresh", 36)', 'GhostBtn("Refresh", 36)'),
        ('SecondaryBtn("⟳  Sync Now", 36)', 'SecondaryBtn("Sync Now", 36)'),
    ],
    'desktop/tabs/ai_ops_tab.py': [
        ("PrimaryBtn('↻  Refresh Health', 40)", "PrimaryBtn('Refresh Health', 40)"),
        ("PrimaryBtn('✦  Analyze with AI', 40)", "PrimaryBtn('Analyze with AI', 40)"),
    ],
    'desktop/tabs/security_tab.py': [
        ("SecondaryBtn('↺  Load Products', 42)", "SecondaryBtn('Load Products', 42)"),
        ("SecondaryBtn('↺ Refresh', 38)", "SecondaryBtn('Refresh', 38)"),
    ],
    'desktop/tabs/diagnostics_tab.py': [
        ("GhostBtn('↺  Rotate Logs', 40)", "GhostBtn('Rotate Logs', 40)"),
    ],
    'desktop/pos/panel_factory.py': [
        ("IconBtn('↺', 40, 40)", "IconBtn('', 40, 40)"),
    ],
    'desktop/widgets/ai_assistant.py': [
        ("super().__init__('✦  Copilot', parent)", "super().__init__('Copilot', parent)"),
    ],
}

# Inject apply_button_icon after key constructions where safe
INJECT_AFTER = [
    # (file, needle, injection block — must appear once)
    (
        'desktop/tabs/settings_tab.py',
        "save_top = PrimaryBtn('Save Changes', 40)",
        "\n        try:\n            from desktop.utils.nav_icons import apply_button_icon\n"
        "            apply_button_icon(save_top, 'save', 16)\n        except Exception:\n            pass",
    ),
    (
        'desktop/tabs/inventory_tab.py',
        "adj = SecondaryBtn('Adjust Stock', 40)",
        "\n            try:\n                from desktop.utils.nav_icons import apply_button_icon\n"
        "                apply_button_icon(adj, 'gear', 15)\n            except Exception:\n                pass",
    ),
    (
        'desktop/tabs/inventory_tab.py',
        "ref = GhostBtn('Refresh', 40)",
        "\n        try:\n            from desktop.utils.nav_icons import apply_button_icon\n"
        "            apply_button_icon(ref, 'refresh', 15)\n        except Exception:\n            pass",
    ),
    (
        'desktop/tabs/reports_tab.py',
        "self._exp_btn = PrimaryBtn('Export Excel', 40)",
        "\n        try:\n            from desktop.utils.nav_icons import apply_button_icon\n"
        "            apply_button_icon(self._exp_btn, 'export', 15)\n"
        "            apply_button_icon(self._email_btn, 'email', 15) if False else None\n"
        "        except Exception:\n            pass",
    ),
    (
        'desktop/widgets/ai_assistant.py',
        "super().__init__('Copilot', parent)",
        "\n        try:\n            from desktop.utils.nav_icons import apply_button_icon\n"
        "            apply_button_icon(self, 'sparkle', 16)\n        except Exception:\n            pass",
    ),
]


def main():
    changed = 0
    for rel, pairs in PATCHES.items():
        path = ROOT / rel
        text = path.read_text(encoding='utf-8')
        orig = text
        for a, b in pairs:
            if a in text:
                text = text.replace(a, b)
            else:
                # try unicode-decoded form already in file
                pass
        if text != orig:
            path.write_text(text, encoding='utf-8')
            changed += 1
            print('patched', rel)
        else:
            print('no-text-change', rel)

    for rel, needle, inject in INJECT_AFTER:
        path = ROOT / rel
        text = path.read_text(encoding='utf-8')
        if needle not in text:
            print('inject-skip-missing', rel, needle[:40])
            continue
        if 'apply_button_icon' in text[text.find(needle):text.find(needle) + 200]:
            print('inject-already', rel)
            continue
        text = text.replace(needle, needle + inject, 1)
        # Fix awkward reports inject
        if rel.endswith('reports_tab.py'):
            text = text.replace(
                "apply_button_icon(self._email_btn, 'email', 15) if False else None\n",
                "",
            )
            # place email icon after email btn create
            mark = "self._email_btn = SecondaryBtn('Email Report', 40)"
            if mark in text and "apply_button_icon(self._email_btn" not in text:
                text = text.replace(
                    mark,
                    mark + "\n        try:\n            from desktop.utils.nav_icons import apply_button_icon\n"
                    "            apply_button_icon(self._email_btn, 'email', 15)\n"
                    "        except Exception:\n            pass",
                    1,
                )
        path.write_text(text, encoding='utf-8')
        print('injected', rel)
        changed += 1

    # Debt refresh button with broken '?'
    debt = ROOT / 'desktop/tabs/debt_tab.py'
    dt = debt.read_text(encoding='utf-8')
    if "SecondaryBtn('?  Refresh'" in dt:
        dt = dt.replace("SecondaryBtn('?  Refresh', 40)", "SecondaryBtn('Refresh', 40)")
        debt.write_text(dt, encoding='utf-8')
        print('debt refresh fixed')
        changed += 1

    # Reports KPI icons
    rep = ROOT / 'desktop/tabs/reports_tab.py'
    rt = rep.read_text(encoding='utf-8')
    reps = [
        ("KPICard('Transactions', '0',  '', C['gold'])",
         "KPICard('Transactions', '0',  '', C['gold'], icon='count')"),
        ("KPICard('Final Total',  '—',  '', C['ok'])",
         "KPICard('Final Total',  '—',  '', C['ok'], icon='revenue')"),
        ("KPICard('Avg Sale',     '—',  '', C['info'])",
         "KPICard('Avg Sale',     '—',  '', C['info'], icon='avg')"),
        ("KPICard('Discounts',    '—',  '', C['warn'])",
         "KPICard('Discounts',    '—',  '', C['warn'], icon='alert')"),
    ]
    n = 0
    for a, b in reps:
        if a in rt:
            rt = rt.replace(a, b)
            n += 1
    if n:
        rep.write_text(rt, encoding='utf-8')
        print('reports kpis', n)
        changed += 1

    print('DONE changed_filesish', changed)


if __name__ == '__main__':
    main()
