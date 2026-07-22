"""
Back-compat shim — AccountingTab is now FinanceTab.

Canonical implementation: desktop.tabs.finance_tab
"""
from desktop.tabs.finance_tab import FinanceTab, FinanceTab as AccountingTab

__all__ = ['AccountingTab', 'FinanceTab']
