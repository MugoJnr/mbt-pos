"""A dead printer fails the print job and does not invent another sale."""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _Sink:
    def __init__(self, fail=False):
        self.fail = fail
        self.writes = 0
        self.started = threading.Event()
        self.release = threading.Event()

    def write(self, data):
        self.started.set()
        self.release.wait(2)
        if self.fail:
            raise OSError("paper out")
        self.writes += 1

    def flush(self):
        return None


class PrintQueueTests(unittest.TestCase):
    def test_missing_printer_fails_the_job(self):
        from printing.printer_engine import PrintQueue
        queue = PrintQueue(lambda: None, retry_waits=(0, 0))
        queue.start()
        try:
            queue.enqueue(b"receipt", label="RCP-1", job_id="RCP-1")
            job = self._wait(queue, "RCP-1", "failed")
            self.assertEqual(job["status"], "failed")
            self.assertIn("unavailable", job["error"].lower())
            self.assertGreaterEqual(job["attempts"], 1)
        finally:
            queue.stop()

    def test_duplicate_while_printing_does_not_write_twice(self):
        from printing.printer_engine import PrintQueue
        sink = _Sink()
        queue = PrintQueue(lambda: sink, retry_waits=(0,))
        queue.start()
        try:
            queue.enqueue(b"one", label="RCP-2", job_id="RCP-2")
            self.assertTrue(sink.started.wait(2))
            again = queue.enqueue(b"one", label="RCP-2", job_id="RCP-2")
            self.assertIn(again["status"], ("queued", "printing"))
            sink.release.set()
            job = self._wait(queue, "RCP-2", "printed")
            self.assertEqual(job["status"], "printed")
            self.assertEqual(sink.writes, 1)
        finally:
            sink.release.set()
            queue.stop()

    def test_reprint_after_failure_is_a_new_attempt(self):
        from printing.printer_engine import PrintQueue
        sink = _Sink(fail=True)
        holder = {"sink": sink}

        def getter():
            return holder["sink"]

        queue = PrintQueue(getter, retry_waits=(0,))
        queue.start()
        try:
            queue.enqueue(b"pay", label="PAY-1", job_id="PAY-1")
            self.assertTrue(sink.started.wait(2))
            sink.release.set()
            failed = self._wait(queue, "PAY-1", "failed")
            self.assertEqual(failed["status"], "failed")
            nxt = _Sink()
            holder["sink"] = nxt
            queue.enqueue(b"pay", label="PAY-1", job_id="PAY-1", reprint=True)
            self.assertTrue(nxt.started.wait(2))
            nxt.release.set()
            printed = self._wait(queue, "PAY-1", "printed")
            self.assertEqual(printed["status"], "printed")
            self.assertEqual(nxt.writes, 1)
        finally:
            sink.release.set()
            queue.stop()

    def _wait(self, queue, job_id, status):
        deadline = time.time() + 3
        job = None
        while time.time() < deadline:
            job = queue.job(job_id)
            if job and job["status"] == status:
                return job
            time.sleep(0.01)
        self.fail(f"{job_id} stayed {None if job is None else job['status']}")


if __name__ == "__main__":
    unittest.main()
