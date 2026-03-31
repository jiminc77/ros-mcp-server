from ros_mcp.imece.analysis import review_c2_freeze_batch
from ros_mcp.imece.helpers import ModeGuard, PoseRelay


class _FakeRequester:
    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = 9090
        self.calls = []

    def call_service(self, service: str, service_type: str, args: dict, timeout: float = 5.0) -> dict:
        self.calls.append((service, service_type, args, timeout))
        if service.endswith("set_mode"):
            return {"service": service, "values": {"mode_sent": True}}
        if service.endswith("arming"):
            return {"service": service, "values": {"success": True, "result": 0}}
        return {"service": service, "ok": True}


class _FakeRelay:
    def __init__(self) -> None:
        self.stop_called = False
        self.rate_hz = 20.0
        self.publish_count = 50

    def stop(self) -> None:
        self.stop_called = True


def test_pose_relay_accepts_json_string_subfields():
    relay = PoseRelay(_FakeRequester())
    normalized = relay._normalize_target(
        {
            "header": {"frame_id": "map"},
            "pose": {
                "position": '{"x": 4.54, "y": 0.089, "z": 2.0}',
                "orientation": '{"x": 0.0, "y": 0.0, "z": 0.0, "w": -1.0}',
            },
        }
    )

    assert normalized["pose"]["position"] == {"x": 4.54, "y": 0.089, "z": 2.0}
    assert normalized["pose"]["orientation"]["w"] == -1.0


def test_pose_relay_returns_soft_error_for_empty_target():
    relay = PoseRelay(_FakeRequester())

    result = relay.set_target({})

    assert result["active"] is False
    assert result["error"] == "target.pose.position.{x,y,z} must be present and numeric"


def test_pose_relay_accepts_quoted_mapping_keys():
    relay = PoseRelay(_FakeRequester())

    normalized = relay._normalize_target(
        {
            '"pose"': {
                '"position"': {'"x"': -0.04, '"y"': 0.03, '"z"': 1.0},
                '"orientation"': {'"x"': 0.0, '"y"': 0.0, '"z"': 0.0, '"w"': 1.0},
            }
        }
    )

    assert normalized["pose"]["position"] == {"x": -0.04, "y": 0.03, "z": 1.0}


def test_mode_guard_land_waits_for_safe_landing(monkeypatch):
    class FakeSubscriber:
        def __init__(self, host: str, port: int, timeout: float = 1.0) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout

        def subscribe(self, topic: str, msg_type: str, callback, **_: object) -> None:
            if topic == "/mavros/state":
                callback({"armed": False})
            elif topic == "/mavros/local_position/pose":
                callback({"pose": {"position": {"z": 0.0}}})

        def stop(self) -> None:
            return

    monkeypatch.setattr("ros_mcp.imece.helpers.RosbridgeSubscriber", FakeSubscriber)

    requester = _FakeRequester()
    relay = _FakeRelay()
    guard = ModeGuard(requester, relay)

    result = guard.land()

    assert relay.stop_called is True
    assert result["landing_complete"] is True
    assert result["latest_armed"] is False
    assert result["latest_z"] == 0.0


def test_mode_guard_engage_offboard_surfaces_arming_failure(monkeypatch):
    class FakeSubscriber:
        def __init__(self, host: str, port: int, timeout: float = 1.0) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout

        def subscribe(self, topic: str, msg_type: str, callback, **_: object) -> None:
            if topic == "/mavros/state":
                callback({"mode": "OFFBOARD"})

        def stop(self) -> None:
            return

    monkeypatch.setattr("ros_mcp.imece.helpers.RosbridgeSubscriber", FakeSubscriber)

    class ArmingFailureRequester(_FakeRequester):
        def __init__(self) -> None:
            super().__init__()
            self.arming_calls = 0

        def call_service(self, service: str, service_type: str, args: dict, timeout: float = 5.0) -> dict:
            if service.endswith("set_mode"):
                return {"service": service, "values": {"mode_sent": True}}
            if service.endswith("arming"):
                self.arming_calls += 1
                return {"service": service, "values": {"success": False, "result": 1}}
            return super().call_service(service, service_type, args, timeout)

    requester = ArmingFailureRequester()
    guard = ModeGuard(requester, _FakeRelay())
    result = guard.engage_offboard()

    assert result["error"] == "Vehicle did not arm after OFFBOARD engage"
    assert result["arming_attempts"] == 2
    assert requester.arming_calls == 2


def test_review_c2_freeze_batch_marks_remaining_issues():
    review = review_c2_freeze_batch(
        [
            {"condition": "C2", "task_id": "T1", "task_success": True, "failure_codes": []},
            {"condition": "C2", "task_id": "T2", "task_success": False, "failure_codes": ["F5"]},
            {"condition": "C2", "task_id": "T3", "task_success": False, "failure_codes": ["F2", "F4"]},
        ]
    )

    assert review["status"] == "issues_found"
    assert review["helper_change_request"] == []
    assert review["counts"]["F5"] == 1
    assert review["counts"]["F2"] == 1
    assert review["task_success"]["T2"] == {"success": 0, "total": 1}
