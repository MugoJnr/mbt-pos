"""Apply app_updates RLS via Supabase SQL Editor (Playwright)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "_qa_shop_update_fix"
OUT.mkdir(parents=True, exist_ok=True)

SQL = """
drop policy if exists app_updates_read on public.app_updates;
create policy app_updates_read on public.app_updates
 for select using (is_active = true);
""".strip()

DASHBOARD_URL = "https://supabase.com/dashboard/project/uynfglgttkaibyeglsrt/sql/new"
CHROME_USER_DATA = Path.home() / "AppData/Local/Google/Chrome/User Data"


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        import subprocess

        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright", "-q"])
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium", "-q"])
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    log: dict = {"steps": [], "success": False}
    shot_before = OUT / "01_sql_editor_loaded.png"
    shot_after = OUT / "02_sql_success.png"

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        page.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(4000)
        page.screenshot(path=str(shot_before), full_page=True)
        log["steps"].append({"step": "navigate", "url": page.url})

        if "sign-in" in page.url or "login" in page.url:
            log["error"] = "Not logged into Supabase dashboard"
            (OUT / "validation_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
            page.close()
            return 2

        # Monaco SQL editor
        editor = page.locator(".monaco-editor textarea").first
        try:
            editor.wait_for(state="visible", timeout=30_000)
        except PWTimeout:
            # fallback: click editor surface
            page.locator(".monaco-editor").first.click(timeout=10_000)
            editor = page.locator(".monaco-editor textarea").first
            editor.wait_for(state="attached", timeout=10_000)

        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        page.keyboard.type(SQL, delay=5)
        log["steps"].append({"step": "paste_sql"})

        run_btn = page.get_by_role("button", name="Run", exact=False)
        if run_btn.count() == 0:
            run_btn = page.locator("button:has-text('Run')")
        run_btn.first.click(timeout=15_000)
        log["steps"].append({"step": "click_run"})
        page.wait_for_timeout(5000)

        body = page.inner_text("body").lower()
        success_markers = ("success", "completed", "no rows returned", "policy")
        error_markers = ("error", "failed", "permission denied")
        has_success = any(m in body for m in success_markers)
        has_error = any(m in body for m in error_markers)
        log["result_text_snippet"] = body[:800]
        log["success"] = has_success and not has_error

        page.screenshot(path=str(shot_after), full_page=True)
        page.close()

    (OUT / "validation_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(json.dumps({"success": log["success"], "screenshots": [str(shot_before), str(shot_after)]}))
    return 0 if log["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
