from forven.agents import runner


def test_tool_call_chain_starts_with_requested_agent_model(monkeypatch):
    monkeypatch.setattr(runner, "normalize_provider_and_model", lambda provider, model: (provider, model))
    monkeypatch.setattr(
        runner,
        "get_fallback_chain",
        lambda provider: [("minimax", "MiniMax-M2.5"), ("openai", "gpt-5.2")],
    )

    assert runner._resolve_tool_call_chain("minimax", "MiniMax-M2.7") == [
        ("minimax", "MiniMax-M2.7"),
        ("minimax", "MiniMax-M2.5"),
        ("openai", "gpt-5.2"),
    ]


def test_tool_call_chain_dedupes_configured_primary(monkeypatch):
    monkeypatch.setattr(runner, "normalize_provider_and_model", lambda provider, model: (provider, model))
    monkeypatch.setattr(
        runner,
        "get_fallback_chain",
        lambda provider: [("minimax", "MiniMax-M2.5"), ("openai", "gpt-5.2")],
    )

    assert runner._resolve_tool_call_chain("minimax", "MiniMax-M2.5") == [
        ("minimax", "MiniMax-M2.5"),
        ("openai", "gpt-5.2"),
    ]
