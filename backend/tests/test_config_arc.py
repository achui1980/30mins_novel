from app import config


def test_arc_defaults():
    assert config.ARC_BLOCKS_TARGET == 60
    assert config.MIN_ARC == 2
    assert config.MAX_ARC == 16
    assert config.ARC_ANCHOR_COUNT == 20
    assert config.GLOBAL_EXTRACT_CONCURRENCY == 20
    assert config.STRONG_MODEL_ID == ""
    assert config.STRONG_LLM_PROVIDER == config.LLM_PROVIDER


def test_strong_provider_inherits_llm_provider():
    assert config.STRONG_LLM_PROVIDER in {"bedrock", "openai_compatible"}
