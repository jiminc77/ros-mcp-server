import unittest

from drone_perception.state_machine import build_status_payload, initial_idle_payload


class StateMachineContractTests(unittest.TestCase):
    def test_initial_idle_payload_contract(self):
        payload = initial_idle_payload(source="gemini_grounding")
        self.assertEqual(payload["status"], "idle")
        self.assertEqual(payload["status_code"], "IDLE")
        self.assertEqual(payload["status_message"], "No active query")
        self.assertEqual(payload["status_detail"], "IDLE: No active query")
        self.assertEqual(payload["source"], "gemini_grounding")

    def test_build_status_payload_contract(self):
        payload = build_status_payload(
            query="white cup",
            generation=7,
            status="running",
            status_code="RUNNING",
            status_message="Vision grounding in progress",
            source="gemini_grounding",
            extra={"depth_m": 1.2},
        )
        self.assertEqual(payload["query"], "white cup")
        self.assertEqual(payload["generation"], 7)
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["status_detail"], "RUNNING: Vision grounding in progress")
        self.assertEqual(payload["depth_m"], 1.2)


if __name__ == "__main__":
    unittest.main()
