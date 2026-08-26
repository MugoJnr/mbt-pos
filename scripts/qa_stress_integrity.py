#!/usr/bin/env python3
"""Isolated SQLite stress, concurrency, integrity, backup, and restore gate."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import statistics
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _timed_ms(callable_) -> float:
    started = time.perf_counter()
    callable_()
    return (time.perf_counter() - started) * 1000.0


def run(data_root: Path, products: int, output: Path, reset: bool) -> dict:
    resolved = data_root.resolve()
    if "MBT_Release_Cert" not in str(resolved):
        raise RuntimeError("data root must be inside MBT_Release_Cert")
    if reset and resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)
    os.environ["MBT_DATA_ROOT"] = str(resolved)

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from desktop.utils.api_client import _db
    from mbt_paths import get_db_path

    db = _db()
    db_path = Path(get_db_path())
    result: dict = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "data_root": str(resolved),
        "db_path": str(db_path),
        "products_requested": products,
        "errors": [],
    }
    try:
        db.execute("DELETE FROM products WHERE sku LIKE 'STRESS-%'")
        rows = [
            (
                f"Stress Product {index:06d}",
                f"STRESS-{index:06d}",
                "Stress",
                100.0 + (index % 100),
                60.0 + (index % 50),
                float(index % 500),
                5.0,
                "pcs",
            )
            for index in range(products)
        ]
        started = time.perf_counter()
        db.executemany(
            "INSERT INTO products "
            "(name,sku,category,price,cost_price,stock,min_stock,unit) "
            "VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        db.commit()
        result["insert_seconds"] = time.perf_counter() - started
        result["product_count"] = db.execute(
            "SELECT COUNT(*) FROM products WHERE sku LIKE 'STRESS-%'"
        ).fetchone()[0]

        sku_latencies = []
        search_latencies = []
        for index in range(30):
            sku = f"STRESS-{(index * 3571) % products:06d}"
            sku_latencies.append(_timed_ms(
                lambda sku=sku: db.execute(
                    "SELECT id,name,stock FROM products WHERE sku=?",
                    (sku,),
                ).fetchone()
            ))
            term = f"%{(index * 97) % products:04d}%"
            search_latencies.append(_timed_ms(
                lambda term=term: db.execute(
                    "SELECT id,name,sku FROM products "
                    "WHERE name LIKE ? OR sku LIKE ? ORDER BY name LIMIT 100",
                    (term, term),
                ).fetchall()
            ))
        result["sku_lookup_ms"] = {
            "median": statistics.median(sku_latencies),
            "p95": _percentile(sku_latencies, 0.95),
            "max": max(sku_latencies),
        }
        result["search_ms"] = {
            "median": statistics.median(search_latencies),
            "p95": _percentile(search_latencies, 0.95),
            "max": max(search_latencies),
        }

        thread_errors: list[str] = []

        def reader(worker: int) -> None:
            try:
                conn = sqlite3.connect(str(db_path), timeout=10)
                for step in range(100):
                    conn.execute(
                        "SELECT stock FROM products WHERE sku=?",
                        (f"STRESS-{(worker * 1009 + step) % products:06d}",),
                    ).fetchone()
                conn.close()
            except Exception as exc:
                thread_errors.append(f"{type(exc).__name__}: {exc}")

        threads = [
            threading.Thread(target=reader, args=(worker,), daemon=True)
            for worker in range(8)
        ]
        concurrent_started = time.perf_counter()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        result["concurrent_read_seconds"] = time.perf_counter() - concurrent_started
        result["concurrent_thread_errors"] = thread_errors
        result["concurrent_threads_alive"] = sum(t.is_alive() for t in threads)

        result["integrity_check"] = [
            row[0] for row in db.execute("PRAGMA integrity_check").fetchall()]
        result["foreign_key_errors"] = [
            list(row) for row in db.execute("PRAGMA foreign_key_check").fetchall()]

        backup_path = resolved / "backups" / "stress_cert.db"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup = sqlite3.connect(str(backup_path))
        db.backup(backup)
        backup.close()
        restored_path = resolved / "restore" / "stress_cert_restored.db"
        restored_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_path, restored_path)
        restored = sqlite3.connect(str(restored_path))
        result["restored_integrity_check"] = [
            row[0] for row in restored.execute("PRAGMA integrity_check").fetchall()]
        result["restored_product_count"] = restored.execute(
            "SELECT COUNT(*) FROM products WHERE sku LIKE 'STRESS-%'"
        ).fetchone()[0]
        restored.close()
        result["backup_bytes"] = backup_path.stat().st_size
    finally:
        db.close()

    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    if result.get("product_count") != products:
        result["errors"].append("insert count mismatch")
    if result.get("integrity_check") != ["ok"]:
        result["errors"].append("source integrity check failed")
    if result.get("foreign_key_errors"):
        result["errors"].append("foreign key check failed")
    if result.get("restored_integrity_check") != ["ok"]:
        result["errors"].append("restored integrity check failed")
    if result.get("restored_product_count") != products:
        result["errors"].append("restore count mismatch")
    if result.get("concurrent_thread_errors") or result.get("concurrent_threads_alive"):
        result["errors"].append("concurrent readers failed")
    if result.get("sku_lookup_ms", {}).get("p95", 999999) > 100:
        result["errors"].append("SKU lookup p95 exceeded 100 ms")
    if result.get("search_ms", {}).get("p95", 999999) > 1500:
        result["errors"].append("search p95 exceeded 1500 ms")
    result["ok"] = not result["errors"]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--products", type=int, default=100_000)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    result = run(args.data_root, max(1, args.products), args.output, args.reset)
    print(json.dumps({
        "ok": result["ok"],
        "products": result.get("product_count"),
        "insert_seconds": result.get("insert_seconds"),
        "sku_p95_ms": result.get("sku_lookup_ms", {}).get("p95"),
        "search_p95_ms": result.get("search_ms", {}).get("p95"),
        "backup_bytes": result.get("backup_bytes"),
        "errors": result["errors"],
    }, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
