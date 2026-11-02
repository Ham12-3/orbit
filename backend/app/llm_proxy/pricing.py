"""List prices per million tokens, from platform.claude.com/docs/en/about-claude/pricing
(checked 2026-11-02). The keys double as the allow-list of models bots may use.
"""

from dataclasses import dataclass
from decimal import Decimal

MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Rates:
    input: Decimal
    cache_write_5m: Decimal
    cache_write_1h: Decimal
    cache_read: Decimal
    output: Decimal


@dataclass(frozen=True)
class ModelPricing:
    base: Rates
    # Haiku 5.5 charges every token type more once the prompt passes a threshold.
    long_prompt: Rates | None = None
    long_prompt_threshold: int | None = None


def _rates(input_: str, write_5m: str, write_1h: str, read: str, output: str) -> Rates:
    return Rates(*(Decimal(v) for v in (input_, write_5m, write_1h, read, output)))


PRICING: dict[str, ModelPricing] = {
    "claude-opus-5-5": ModelPricing(_rates("4", "5", "8", "0.20", "20")),
    "claude-sonnet-5-5": ModelPricing(_rates("2", "2.50", "4", "0.10", "10")),
    "claude-haiku-5-5": ModelPricing(
        base=_rates("0.10", "0.125", "0.20", "0.01", "0.50"),
        long_prompt=_rates("0.50", "0.625", "1", "0.05", "2.50"),
        long_prompt_threshold=100_000,
    ),
}

SUPPORTED_MODELS = frozenset(PRICING)


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0

    @property
    def cache_write_tokens(self) -> int:
        return self.cache_write_5m_tokens + self.cache_write_1h_tokens

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    @property
    def budget_tokens(self) -> int:
        """Tokens that count against a bot's daily budget. Cache reads are excluded: they
        are the re-read conversation prefix (cheap, and huge in agent loops)."""
        return self.input_tokens + self.cache_write_tokens + self.output_tokens


def cost_usd(model: str, usage: Usage) -> Decimal:
    pricing = PRICING[model]
    rates = pricing.base
    if (
        pricing.long_prompt is not None
        and pricing.long_prompt_threshold is not None
        and usage.prompt_tokens > pricing.long_prompt_threshold
    ):
        rates = pricing.long_prompt
    total = (
        usage.input_tokens * rates.input
        + usage.cache_write_5m_tokens * rates.cache_write_5m
        + usage.cache_write_1h_tokens * rates.cache_write_1h
        + usage.cache_read_tokens * rates.cache_read
        + usage.output_tokens * rates.output
    )
    return (total / MILLION).quantize(Decimal("0.000001"))
