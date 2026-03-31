from ros_mcp.imece.boundary_tools import _subscription_payload


def test_subscription_payload_compacts_messages_and_keeps_first_last():
    messages = [
        {"value": 1},
        {"value": 2},
        {"value": 3},
        {"value": 4},
    ]
    payload = _subscription_payload("/mavros/battery", messages)
    assert payload["collected_count"] == 4
    assert payload["first_msg"] == {"value": 1}
    assert payload["last_msg"] == {"value": 4}
    assert payload["messages"] == [{"value": 1}, {"value": 3}, {"value": 4}]


def test_subscription_payload_adds_pose_summary():
    messages = [
        {"pose": {"position": {"x": 0.0, "y": 0.0, "z": 0.2}}},
        {"pose": {"position": {"x": 1.0, "y": 1.0, "z": 1.0}}},
    ]
    payload = _subscription_payload("/mavros/local_position/pose", messages)
    assert payload["summary"]["first_position"] == {"x": 0.0, "y": 0.0, "z": 0.2}
    assert payload["summary"]["last_position"] == {"x": 1.0, "y": 1.0, "z": 1.0}
    assert payload["summary"]["x_span_m"] == 1.0
    assert payload["summary"]["y_span_m"] == 1.0
    assert payload["summary"]["min_z"] == 0.2
    assert payload["summary"]["max_z"] == 1.0
