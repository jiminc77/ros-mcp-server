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
    assert "Never end with `DONE.`" in prompt


def test_t1_prompt_includes_takeoff_verification_protocol():
    prompt = build_episode_prompt("C2", "T1", 1, "127.0.0.1", 9090, selected_helpers=["setpoint_relay"])
    assert "C2 takeoff verification refinement:" in prompt
    assert "Treat the takeoff hold as reached only when altitude is at least `0.8 m`" in prompt
    assert "Do not land or emit `DONE` before the altitude criterion is satisfied" in prompt


def test_t4_prompt_includes_staged_followup_protocol():
    prompt = build_episode_prompt("C2", "T4", 1, "127.0.0.1", 9090, selected_helpers=["setpoint_relay"])
    assert "Read the current local pose exactly once before the first motion target" in prompt
    assert "Use exactly two motion targets in the first turn" in prompt
    assert "Keep all T4 motion targets start-relative" in prompt
    assert "Do not retarget for the halfway-forward motion until the current pose is near the takeoff hold" in prompt
    assert "do not send a new origin-based target" in prompt
    assert "CLARIFY: awaiting correction" in prompt
    assert "Come back." not in prompt


def test_t2_prompt_includes_two_stage_motion_protocol():
    prompt = build_episode_prompt("C2", "T2", 1, "127.0.0.1", 9090, selected_helpers=["setpoint_relay"])
    assert "Use exactly two motion targets" in prompt
    assert "Do not retarget for the forward motion until the current pose is near the takeoff hold" in prompt


def test_t3_prompt_includes_square_pattern_protocol():
    prompt = build_episode_prompt("C2", "T3", 1, "127.0.0.1", 9090, selected_helpers=["setpoint_relay"])
    assert "task_name: `Square Pattern Flight`" in prompt
    assert "fly a square with one-meter sides" in prompt
    assert "Read the current local pose exactly once" in prompt
    assert "Use exactly five `setpoint_relay` motion targets" in prompt
    assert "Keep the square axis-aligned in local ENU" in prompt
    assert "subscribe_for_duration" in prompt
    assert "`3.0` seconds per check" in prompt
    assert "at most two checks for the same target" in prompt
    assert "Read the verification result from `last_msg.pose.position`" in prompt
    assert "DONE: square complete" in prompt


def test_r2_prompt_reuses_translation_protocol():
    prompt = build_episode_prompt("C2", "R2", 1, "127.0.0.1", 9090, selected_helpers=["setpoint_relay"])
    assert "task_name: `Real Short Translation`" in prompt
    assert "Take off, move one meter forward, hover, and land." in prompt
    assert "Translation execution protocol:" in prompt
    assert "Use exactly two motion targets" in prompt


def test_educational_prompt_profile_replaces_task_prompt():
    prompt = build_episode_prompt(
        "C2",
        "T3",
        1,
        "127.0.0.1",
        9090,
        selected_helpers=["setpoint_relay"],
        prompt_level="elementary",
        prompt_variant="c",
    )
    assert "prompt_level: `elementary`" in prompt
    assert "prompt_variant: `c`" in prompt
    assert (
        "Go up to about one meter. Fly a one-meter square. Come back near the start. Come down and land."
        in prompt
    )
    assert "Take off, fly a square with one-meter sides, return near the start, and land." not in prompt


def test_prompt_profile_requires_level_and_variant_together():
    try:
        build_episode_prompt("C2", "T1", 1, "127.0.0.1", 9090, prompt_level="elementary")
    except ValueError as exc:
        assert "prompt_level and prompt_variant must be provided together" in str(exc)
    else:
        raise AssertionError("expected prompt profile validation error")


def test_t4_educational_prompt_profile_is_not_supported():
    try:
        build_episode_prompt(
            "C2",
            "T4",
            1,
            "127.0.0.1",
            9090,
            prompt_level="elementary",
            prompt_variant="a",
        )
    except ValueError as exc:
        assert "defined only for T1, T2, T3" in str(exc)
    else:
        raise AssertionError("expected unsupported-task validation error")


def test_educational_prompt_profiles_show_level_and_variant_contrast():
    elementary_prompt = build_episode_prompt(
        "C2",
        "T1",
        1,
        "127.0.0.1",
        9090,
        selected_helpers=["setpoint_relay"],
        prompt_level="elementary",
        prompt_variant="a",
    )
    college_prompt = build_episode_prompt(
        "C2",
        "T1",
        1,
        "127.0.0.1",
        9090,
        selected_helpers=["setpoint_relay"],
        prompt_level="college",
        prompt_variant="c",
    )

    elementary_task_prompt = elementary_prompt.split("Task prompt:\n", 1)[1]
    college_task_prompt = college_prompt.split("Task prompt:\n", 1)[1]

    assert "Make the drone go up. Stop when it is about one meter high. Wait there for five seconds. Then bring it down and land." in elementary_task_prompt
    assert "Perform takeoff to approximately one meter, maintain a five-second hover, and execute landing." in college_task_prompt
    assert elementary_task_prompt.count(".") >= 4
    assert college_task_prompt.count(".") <= 1
