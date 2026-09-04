"""Release metadata must not rely on an impossible self-referential hash."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class ReleaseIntegrityTests(unittest.TestCase):
    def test_spec_generates_sanitized_runtime_manifest(self):
        source = (ROOT / "mbt_pos.spec").read_text(encoding="utf-8")
        self.assertIn("def _runtime_version_manifest", source)
        self.assertIn("payload['checksum_sha256'] = ''", source)
        self.assertNotIn("'deploy.local.json',", source)

    def test_installer_retires_unsafe_system_update_helper(self):
        installer = (ROOT / "installer.nsi").read_text(encoding="utf-8")
        updater = (ROOT / "backend" / "updater.py").read_text(
            encoding="utf-8")
        self.assertIn(
            'schtasks /Delete /TN "MBT_POS_UpdateHelper" /F',
            installer,
        )
        self.assertIn('RMDir /r "$INSTDIR\\deploy"', installer)
        self.assertIn(
            'use_helper = False',
            updater,
        )
        self.assertIn("return False, 'requires_uac'", updater)

    def test_repair_flag_runs_before_any_profile_directory_is_created(self):
        """Elevated repair must not seed shop folders in the admin profile."""
        launcher = (ROOT / "launcher.py").read_text(encoding="utf-8")
        repair_at = launcher.index("'--repair-license-store' in sys.argv")
        paths_at = launcher.index("from mbt_paths import")
        self.assertLess(repair_at, paths_at)

    def test_installer_repairs_machine_wide_license_before_first_launch(self):
        installer = (ROOT / "installer.nsi").read_text(encoding="utf-8")
        self.assertNotIn('MUI_FINISHPAGE_RUN "', installer)
        self.assertIn('SetShellVarContext all', installer)
        self.assertNotIn('$COMMONAPPDATA', installer)
        self.assertIn('ReadEnvStr $LicenseMachineDir "PROGRAMDATA"', installer)
        self.assertIn(
            'CreateDirectory "$LicenseMachineDir"',
            installer,
        )
        self.assertIn('*S-1-5-32-545:(OI)(CI)M', installer)
        self.assertIn(
            'nsExec::ExecToLog \'"$INSTDIR\\MBT_POS.exe" '
            '--repair-license-store\'',
            installer,
        )
        repair_at = installer.index('--repair-license-store')
        finish_at = installer.index('CreateShortcut  "$SMPROGRAMS', repair_at)
        self.assertLess(repair_at, finish_at)

    def test_upgrade_removes_old_runtime_and_offline_variant_marker(self):
        installer = (ROOT / 'installer.nsi').read_text(encoding='utf-8')
        cleanup = installer.index('Delete "$INSTDIR\\EDMUS_OFFLINE_BUILD.flag"')
        copy_runtime = installer.index('File /r "dist\\MBT_POS\\*.*"')
        self.assertIn('RMDir /r "$INSTDIR\\_internal"', installer)
        self.assertLess(cleanup, copy_runtime)

    def test_upgrade_backup_scans_all_windows_user_profiles(self):
        installer = (ROOT / 'installer.nsi').read_text(encoding='utf-8')
        backup = (
            ROOT / 'deploy' / 'Backup-MBTUserData.ps1'
        ).read_text(encoding='utf-8')
        self.assertIn('Backup-MBTUserData.ps1', installer)
        self.assertIn("Join-Path $env:SystemDrive 'Users'", backup)
        self.assertIn("Get-ChildItem -LiteralPath $profilesRoot", backup)
        self.assertIn("backups\\pre_upgrade\\$Version", backup)

    def test_cloud_restore_uses_sqlite_backup_not_live_file_replacement(self):
        restore = (
            ROOT / 'backend' / 'cloud_backup' / 'restore_manager.py'
        ).read_text(encoding='utf-8')
        self.assertIn('restore_src.backup(live_dest)', restore)
        self.assertIn("PRAGMA integrity_check", restore)
        self.assertNotIn('shutil.copy2(snap, live)', restore)
        self.assertNotIn("os.remove(side)", restore)

    def test_web_stock_adjust_matches_desktop_security_policy(self):
        routes = (ROOT / 'web' / 'web_routes.py').read_text(encoding='utf-8')
        local_api = (
            ROOT / 'desktop' / 'utils' / 'api_client.py'
        ).read_text(encoding='utf-8')
        dashboard = (
            ROOT / 'web' / 'templates' / 'dashboard.html'
        ).read_text(encoding='utf-8')
        self.assertIn("g.current_user.get('role') != 'superadmin'", routes)
        self.assertIn('from desktop.utils.api_client import APIClient', routes)
        self.assertIn("data.get('direction')", routes)
        self.assertIn("data.get('quantity')", routes)
        self.assertIn("pin=str(data.get('pin') or '')", routes)
        self.assertIn("key='superadmin_pin_hash'", local_api)
        self.assertIn('hmac.compare_digest', local_api)
        self.assertIn("'SUPERADMIN_ADJUST'", local_api)
        self.assertIn('post_stock_adjust_journal', local_api)
        self.assertIn('expected_stock', routes)
        self.assertIn('id="adj-direction"', dashboard)
        self.assertIn('id="adj-qty"', dashboard)
        self.assertIn('id="adj-reason-other"', dashboard)
        self.assertIn('id="adj-pin"', dashboard)
        self.assertIn('direction, quantity, reason, pin, expected_stock:current', dashboard)
        self.assertIn("USER?.role === 'superadmin'", dashboard)
        self.assertIn("res?.current_stock !== undefined", dashboard)
        self.assertIn('id="adj-current-stock"', dashboard)

    def test_installer_cert_treats_uac_cancellation_as_failure(self):
        cert = (
            ROOT / 'scripts' / 'qa_installer_cert.py'
        ).read_text(encoding='utf-8')
        self.assertIn("$ErrorActionPreference='Stop'", cert)
        self.assertIn('exit 1223', cert)
        self.assertIn('if code != 0:', cert)

    def test_stock_reentry_guards_cover_confirmation_and_empty_refresh(self):
        security = (
            ROOT / 'desktop' / 'tabs' / 'security_tab.py'
        ).read_text(encoding='utf-8')
        inventory = (
            ROOT / 'desktop' / 'tabs' / 'inventory_tab.py'
        ).read_text(encoding='utf-8')
        apply_section = security[
            security.index('    def _apply_adj(self):'):
            security.index('    # ── Stock Movement Log')
        ]
        self.assertLess(
            apply_section.index('self._adjustment_busy = True'),
            apply_section.index('QMessageBox.question'),
        )
        refresh_section = inventory[
            inventory.index('    def _adjust_stock_dialog(self):'):
            inventory.index('    def _add(self):')
        ]
        self.assertIn('self.products = fresh_products', refresh_section)
        self.assertNotIn('if fresh_products:', refresh_section)
        # Nested prompts must parent to the modal Adjust Stock dialog — parenting
        # to the Inventory tab leaves them behind it (Windows "Not Responding").
        self.assertIn("prompt_superadmin_pin(\n                        dlg,", refresh_section)
        self.assertIn("QMessageBox.warning(dlg,", refresh_section)
        self.assertLess(
            refresh_section.index('self._adjust_stock_active = True'),
            refresh_section.index('fresh_products = self.api.get_products()'),
        )

    def test_main_window_does_not_duplicate_service_tamper_alert(self):
        main = (ROOT / 'desktop' / 'main.py').read_text(encoding='utf-8')
        section = main[
            main.index('    def _on_license_state('):
            main.index('    def _on_update_available(')
        ]
        self.assertNotIn('send_tamper_alert', section)
        self.assertIn('_replay_deferred_license_alert', section)

    def test_stamp_updates_external_metadata_only(self):
        from scripts import publish_release_3 as publish

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            setup = root / "dist" / "MBT_POS_Setup.exe"
            sidecar = root / "dist" / "MBT_POS_Setup.exe.sha256"
            manifest = root / "version.json"
            internal = root / "dist" / "MBT_POS" / "_internal" / "version.json"
            setup.parent.mkdir(parents=True)
            internal.parent.mkdir(parents=True)
            setup.write_bytes(b"certified installer bytes")
            payload = {
                "version": "9.9.9",
                "checksum_sha256": "",
                "download_url": "https://example.invalid/setup.exe",
            }
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            internal.write_text(json.dumps(payload), encoding="utf-8")

            with patch.object(publish, "SETUP", setup), \
                 patch.object(publish, "SIDECAR", sidecar), \
                 patch.object(publish, "VERSION_JSON", manifest):
                stamped = publish.stamp_checksum()

            expected = hashlib.sha256(setup.read_bytes()).hexdigest()
            self.assertEqual(stamped["checksum_sha256"], expected)
            self.assertTrue(sidecar.read_text(encoding="utf-8").startswith(expected))
            embedded = json.loads(internal.read_text(encoding="utf-8"))
            self.assertEqual(embedded["checksum_sha256"], "")


if __name__ == "__main__":
    unittest.main()
