from ros_mcp.imece.config import build_episode_prompt


def test_c0_prompt_has_no_c1_operational_facts():
    prompt = build_episode_prompt("C0", "T1", 1, "127.0.0.1", 9090)
    assert "local position is `ENU`" not in prompt
    assert "OFFBOARD requires setpoint prestream" not in prompt


def test_c1_prompt_contains_operational_facts():
    prompt = build_episode_prompt("C1", "T1", 1, "127.0.0.1", 9090)
    assert "local position is `ENU`" in prompt
    assert "setpoint streaming must continue during flight" in prompt


def test_c2_prompt_only_mentions_selected_helpers():
    prompt = build_episode_prompt(
        "C2",
        "T1",
        1,
        "127.0.0.1",
        9090,
        selected_helpers=["setpoint_relay", "mode_guard"],
    )
    assert "Callable helper tools:" in prompt
    assert "`setpoint_relay`" in prompt
    assert "`mode_guard`" in prompt
    assert "`frame_guard`" not in prompt
    assert "`abort_watchdog`" not in prompt


def test_c2_prompt_separates_runtime_safeguards_from_callable_tools():
    prompt = build_episode_prompt(
        "C2",
        "T1",
        1,
        "127.0.0.1",
        9090,
        selected_helpers=["setpoint_relay", "abort_watchdog"],
    )
    assert "Callable helper tools:" in prompt
    assert "Active runtime safeguards:" in prompt
    assert "`setpoint_relay`" in prompt
    assert "`abort_watchdog`" in prompt
    assert "Prefer the frozen helper path for transport and safety mechanics" in prompt


def test_shared_terminal_contract_is_present():
    prompt = build_episode_prompt("C0", "T1", 1, "127.0.0.1", 9090)
    assert "CLARIFY:" in prompt
    assert "REFUSE:" in prompt
    assert "DONE:" in prompt
