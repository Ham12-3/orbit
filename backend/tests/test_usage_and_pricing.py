from decimal import Decimal

from app.llm_proxy.pricing import Usage, cost_usd
from app.llm_proxy.usage import SseUsageTracker, usage_from_message


def test_tracker_reads_usage_across_arbitrary_chunk_boundaries() -> None:
    body = (
        b'data: {"type":"message_start","message":{"usage":{"input_tokens":5,'
        b'"cache_read_input_tokens":20,"output_tokens":1}}}\r\n\r\n'
        b'data: {"type":"message_delta","usage":{"output_tokens":9}}\n\n'
        b"data: not json\n\n"
    )
    tracker = SseUsageTracker()
    for i in range(0, len(body), 3):
        tracker.feed(body[i : i + 3])

    assert tracker.usage == Usage(input_tokens=5, output_tokens=9, cache_read_tokens=20)


def test_cache_writes_without_a_ttl_breakdown_count_as_five_minute_writes() -> None:
    usage = usage_from_message({"usage": {"input_tokens": 1, "cache_creation_input_tokens": 50}})
    assert usage.cache_write_5m_tokens == 50
    assert usage.cache_write_1h_tokens == 0


def test_opus_cost() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000, cache_write_1h_tokens=1_000_000)
    assert cost_usd("claude-opus-5-5", usage) == Decimal("32")  # 4 + 20 + 8


def test_haiku_long_prompts_use_the_higher_tier() -> None:
    short = Usage(input_tokens=100_000, output_tokens=1_000)
    long = Usage(input_tokens=60_000, cache_read_tokens=40_001, output_tokens=1_000)

    assert cost_usd("claude-haiku-5-5", short) == Decimal("0.010500")  # 0.10*0.1 + 0.50*0.001
    # Over 100K (cache reads count toward the threshold): every rate is 5x.
    assert cost_usd("claude-haiku-5-5", long) == Decimal("0.034500")


def test_budget_tokens_exclude_cache_reads() -> None:
    usage = Usage(input_tokens=1, output_tokens=2, cache_read_tokens=1000, cache_write_5m_tokens=3)
    assert usage.budget_tokens == 6
