# UI Walkthrough — MBT POS 3.0.75

**Verdict:** PASS  
**Fails:** 0 · **Partials:** 0

| Area | Status | Note |
|------|--------|------|
| auth | PASS | v=3.0.75 role=superadmin |
| ui.login | PASS | dialog rendered |
| ui.main_window | PASS | title='MBT POS - MugoByte Technologies' |
| tab.dashboard | PASS | btns=16 fields=0 checks=0 empty_label=0 |
| tab.sales | PASS | btns=26 fields=4 checks=0 empty_label=0 |
| tab.inventory | PASS | btns=7 fields=1 checks=0 empty_label=0 |
| tab.consumption | PASS | btns=4 fields=5 checks=0 empty_label=0 |
| tab.debt | PASS | btns=3 fields=0 checks=0 empty_label=0 |
| tab.accounting | PASS | btns=11 fields=0 checks=0 empty_label=0 |
| tab.reports | PASS | btns=8 fields=2 checks=2 empty_label=0 |
| tab.notes | PASS | btns=6 fields=2 checks=0 empty_label=0 |
| tab.ai_ops | PASS | btns=2 fields=0 checks=0 empty_label=0 |
| tab.admin | PASS | btns=19 fields=1 checks=14 empty_label=0 |
| tab.settings | PASS | btns=114 fields=30 checks=73 empty_label=0 |
| tab.security | PASS | btns=1 fields=3 checks=0 empty_label=0 |
| tab.license | PASS | btns=5 fields=1 checks=0 empty_label=0 |
| tab.diagnostics | PASS | btns=6 fields=0 checks=0 empty_label=0 |
| finance.shell | PASS | label='Finance' nav='  Finance' pages=['overview', 'money', 'expenses', 'credit', 'reports', 'coa', 'ledger', 'journals', 'trial', 'balance' |
| finance.page.overview | PASS | refreshed ok (_OverviewPage) |
| finance.page.money | PASS | refreshed ok (_MoneyPage) |
| finance.page.expenses | PASS | refreshed ok (_ExpensesPage) |
| finance.page.credit | PASS | refreshed ok (_CreditPage) |
| finance.page.reports | PASS | refreshed ok (_ReportsPage) |
| finance.adv.coa | PASS | _AccountsPage |
| finance.adv.ledger | PASS | _LedgerPage |
| finance.adv.journals | PASS | _JournalsPage |
| finance.adv.trial | PASS | _StatementPage |
| finance.adv.balance | PASS | _StatementPage |
| finance.adv.cashflow | PASS | _CashFlowPage |
| finance.adv.periods | PASS | _PeriodsPage |
| finance.adv.fin_settings | PASS | _FinanceSettingsPage |
| finance.settings_persist | PASS | ok=True method='accrual' note='QA finance note' cash='1000' |
| ui.theme_toggle | PASS | dark+light grabs |
| settings.persist | PASS | saved=True probe='My Shop ·CERT' cfg_keys=['shop_email', 'theme', 'printer_name', 'accounting_fx_enabled', 'accounting_multi_branch', 'auto_ |
| settings.checkbox_toggle | PASS | 'Auto-print receipt after each sale' flipped True->False |
| dialog.return_sale | PASS | opened=True |
| dialog.void_sale | PASS | opened=True |
| dialog.receive_stock | PASS | opened=True |
| dialog.suppliers | PASS | opened=True |
| dialog.add_product | PASS | opened=True |
| dialog.global_search | PASS | opened=True |
| ui.sales_focus | PASS | focus+restore |
| error.invalid_product | PASS | {'error': 'Product name is required.'} |
| error.empty_sale | PASS | {'error': 'Cart is empty — add at least one product before charging.'} |
| settings.no_telegram_ui | PASS | leaked=[] |
| ui.sidebar_nav | PASS | items=14 |
