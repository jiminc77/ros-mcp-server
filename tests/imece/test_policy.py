from pathlib import Path


def test_policy_denies_all_then_allows_ros_mcp_imece_subset():
    policy = Path("config/imece/gemini-policy.toml").read_text(encoding="utf-8")
    assert 'toolName = "*"' in policy
    assert 'mcpName = "*"' in policy
    assert 'mcpName = "ros-mcp-imece"' in policy
    assert '"connect_to_robot"' in policy
    assert '"mode_guard"' in policy
