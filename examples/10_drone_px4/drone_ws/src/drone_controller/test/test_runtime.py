import asyncio
import json
import unittest

from drone_controller.runtime import CancelToken, StatusEnvelope, status_detail


class RuntimeContractTests(unittest.TestCase):
    def test_status_detail_format(self):
        self.assertEqual(status_detail("E_TEST", "failure"), "E_TEST: failure")

    def test_status_envelope_contract(self):
        raw = StatusEnvelope(
            status="error",
            status_code="E_TIMEOUT",
            status_message="timeout",
            source="drone_controller",
            generation=3,
            goal_id="abc123",
        ).to_json()
        data = json.loads(raw)
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["status_code"], "E_TIMEOUT")
        self.assertEqual(data["status_message"], "timeout")
        self.assertEqual(data["status_detail"], "E_TIMEOUT: timeout")
        self.assertEqual(data["source"], "drone_controller")
        self.assertEqual(data["generation"], 3)
        self.assertEqual(data["goal_id"], "abc123")

    def test_cancel_token_cancelled_sleep(self):
        async def _run():
            token = CancelToken()
            token.cancel()
            ok = await token.sleep(0.01)
            self.assertFalse(ok)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
