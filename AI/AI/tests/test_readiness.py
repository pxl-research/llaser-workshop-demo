import sys
import unittest
from pathlib import Path


PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from AI.API.readiness import ComponentState, ReadinessTracker


class ReadinessTrackerTestCase(unittest.TestCase):
    def test_reset_tracks_expected_components(self):
        tracker = ReadinessTracker()
        tracker.reset()

        payload = tracker.to_dict()

        self.assertEqual(payload["status"], ComponentState.LOADING.value)
        self.assertEqual(
            set(payload["components"].keys()),
            {"embedding", "reranker", "vector_store", "llm"},
        )
        self.assertEqual(payload["components"]["embedding"]["state"], ComponentState.PENDING.value)

    def test_component_progression_marks_system_ready(self):
        tracker = ReadinessTracker()
        tracker.reset()
        tracker.set_component_loading("embedding", model="baai/bge-m3")
        tracker.set_component_ready("embedding", model="baai/bge-m3")
        tracker.mark_ready()

        payload = tracker.to_dict()

        self.assertEqual(payload["status"], ComponentState.READY.value)
        self.assertEqual(payload["components"]["embedding"], {"state": "ready", "model": "baai/bge-m3"})

    def test_mark_error_marks_system_failed(self):
        tracker = ReadinessTracker()
        tracker.reset()
        tracker.mark_error("download failed")

        payload = tracker.to_dict()

        self.assertTrue(tracker.is_error())
        self.assertEqual(payload["status"], ComponentState.ERROR.value)
        self.assertEqual(payload["message"], "download failed")


if __name__ == "__main__":
    unittest.main()
