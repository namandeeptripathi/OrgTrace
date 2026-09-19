"""Stage 11: Production Configuration & Secret Management.

Provides structured, validated, environment-aware configuration:
- Application configuration (environment, debug flags)
- Provider credentials & endpoints (Brave Search, BRREG)
- Network safety policies (timeouts, retry counts, URL length limits)
- Logging configuration (level, structured JSON, redaction)
- Evaluation & batch limits (envelope size, request budget, cost budget)
- Automatic secret redaction for logs, reports, and error messages
- Strict validation preventing invalid or dangerous settings
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any


VALID_ENVIRONMENTS = frozenset({"production", "staging", "development", "test"})
VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class ConfigValidationError(ValueError):
    """Raised when configuration contains invalid or contradictory settings."""
    pass


class MissingCredentialError(RuntimeError):
    """Raised when an operation requires an API key or credential that is not configured."""
    pass


@dataclass
class NetworkSafetyConfig:
    """Network request timeouts, retry policies, and URL length constraints."""
    connect_timeout: float = 10.0
    read_timeout: float = 20.0
    max_retries: int = 3
    retry_backoff: float = 0.4
    max_url_length: int = 4096
    enforce_dns_check: bool = False

    def validate(self) -> None:
        if self.connect_timeout <= 0:
            raise ConfigValidationError(f"connect_timeout must be > 0, got {self.connect_timeout}")
        if self.read_timeout <= 0:
            raise ConfigValidationError(f"read_timeout must be > 0, got {self.read_timeout}")
        if self.max_retries < 0:
            raise ConfigValidationError(f"max_retries cannot be negative, got {self.max_retries}")
        if self.retry_backoff < 0:
            raise ConfigValidationError(f"retry_backoff cannot be negative, got {self.retry_backoff}")
        if self.max_url_length < 100:
            raise ConfigValidationError(f"max_url_length too small, got {self.max_url_length}")


@dataclass
class ProviderConfig:
    """External provider API keys, base URLs, and access settings."""
    brave_search_api_key: str | None = None
    brave_search_api_url: str = "https://api.search.brave.com/res/v1/web/search"
    brreg_api_base_url: str = "https://data.brreg.no/enhetsregisteret/api"
    brreg_accounts_base_url: str = "https://data.brreg.no/regnskapsregisteret/regnskap"

    def require_brave_api_key(self) -> str:
        """Return the Brave Search API key or raise a clear, actionable error."""
        if not self.brave_search_api_key or not self.brave_search_api_key.strip():
            raise MissingCredentialError(
                "Brave Search API key is required for external search discovery, "
                "but BRAVE_SEARCH_API_KEY is not set or empty. "
                "Set BRAVE_SEARCH_API_KEY in your environment or .env file."
            )
        return self.brave_search_api_key.strip()

    def validate(self) -> None:
        if not self.brreg_api_base_url.startswith("https://"):
            raise ConfigValidationError("brreg_api_base_url must use HTTPS")
        if not self.brreg_accounts_base_url.startswith("https://"):
            raise ConfigValidationError("brreg_accounts_base_url must use HTTPS")


@dataclass
class LoggingConfig:
    """Logging verbosity, formatting, and secret redaction controls."""
    log_level: str = "INFO"
    structured_json: bool = False
    redact_secrets: bool = True

    def validate(self) -> None:
        if self.log_level.upper() not in VALID_LOG_LEVELS:
            raise ConfigValidationError(
                f"Invalid log_level '{self.log_level}'. Must be one of: {sorted(VALID_LOG_LEVELS)}"
            )


@dataclass
class EvaluationConfig:
    """Default envelopes and resource budgets for batch evaluations."""
    default_envelope_count: int = 100
    default_request_budget: int = 500
    default_runtime_budget_seconds: float = 300.0
    default_cost_budget: float = 10.0

    def validate(self) -> None:
        if self.default_envelope_count <= 0:
            raise ConfigValidationError("default_envelope_count must be positive")
        if self.default_request_budget <= 0:
            raise ConfigValidationError("default_request_budget must be positive")
        if self.default_runtime_budget_seconds <= 0:
            raise ConfigValidationError("default_runtime_budget_seconds must be positive")
        if self.default_cost_budget <= 0:
            raise ConfigValidationError("default_cost_budget must be positive")


@dataclass
class AppConfig:
    """Unified application configuration."""
    environment: str = "production"
    network: NetworkSafetyConfig = field(default_factory=NetworkSafetyConfig)
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)

    def validate(self) -> None:
        if self.environment.lower() not in VALID_ENVIRONMENTS:
            raise ConfigValidationError(
                f"Invalid environment '{self.environment}'. Must be one of: {sorted(VALID_ENVIRONMENTS)}"
            )
        self.network.validate()
        self.provider.validate()
        self.logging.validate()
        self.evaluation.validate()

    def get_known_secrets(self) -> list[str]:
        """Return a list of configured sensitive values for automatic redaction."""
        secrets: list[str] = []
        if self.provider.brave_search_api_key:
            k = self.provider.brave_search_api_key.strip()
            if len(k) >= 4:
                secrets.append(k)
        return secrets

    def to_dict(self, redact: bool = True) -> dict[str, Any]:
        """Convert configuration to a safe dictionary."""
        key = self.provider.brave_search_api_key
        if key and redact:
            key = redact_secret_value(key)

        return {
            "environment": self.environment,
            "network": {
                "connect_timeout": self.network.connect_timeout,
                "read_timeout": self.network.read_timeout,
                "max_retries": self.network.max_retries,
                "retry_backoff": self.network.retry_backoff,
                "max_url_length": self.network.max_url_length,
                "enforce_dns_check": self.network.enforce_dns_check,
            },
            "provider": {
                "brave_search_api_key": key,
                "brave_search_api_url": self.provider.brave_search_api_url,
                "brreg_api_base_url": self.provider.brreg_api_base_url,
                "brreg_accounts_base_url": self.provider.brreg_accounts_base_url,
            },
            "logging": {
                "log_level": self.logging.log_level,
                "structured_json": self.logging.structured_json,
                "redact_secrets": self.logging.redact_secrets,
            },
            "evaluation": {
                "default_envelope_count": self.evaluation.default_envelope_count,
                "default_request_budget": self.evaluation.default_request_budget,
                "default_runtime_budget_seconds": self.evaluation.default_runtime_budget_seconds,
                "default_cost_budget": self.evaluation.default_cost_budget,
            },
        }


def redact_secret_value(value: str | None, visible_chars: int = 4) -> str:
    """Mask a secret value, keeping at most visible_chars at prefix and suffix."""
    if not value:
        return ""
    val = str(value).strip()
    if len(val) <= visible_chars:
        return "[REDACTED]"
    if len(val) <= 8:
        return val[:2] + "****"
    return val[:visible_chars] + "****" + val[-visible_chars:]


def redact_secrets_from_text(text: str, known_secrets: list[str] | None = None) -> str:
    """Redact known secret values and common API key patterns from text."""
    if not text:
        return ""
    redacted = text

    # Redact known secrets
    for secret in (known_secrets or []):
        if secret and len(secret) >= 4:
            redacted = redacted.replace(secret, redact_secret_value(secret))

    # Redact common Authorization / Token header patterns
    redacted = re.sub(
        r'(?i)(x-subscription-token|authorization|bearer|api[_-]?key|token)["\':\s=]+([a-zA-Z0-9_\-\.]{8,})',
        r'\1: [REDACTED]',
        redacted,
    )

    return redacted


def load_config_from_env(env: dict[str, str] | None = None) -> AppConfig:
    """Load and validate application configuration from environment variables."""
    source = os.environ if env is None else env

    def _str(key: str, default: str) -> str:
        return source.get(key, default).strip()

    def _float(key: str, default: float) -> float:
        val = source.get(key)
        if val is None or not val.strip():
            return default
        try:
            return float(val.strip())
        except ValueError:
            raise ConfigValidationError(f"Environment variable '{key}' must be a float, got '{val}'")

    def _int(key: str, default: int) -> int:
        val = source.get(key)
        if val is None or not val.strip():
            return default
        try:
            return int(val.strip())
        except ValueError:
            raise ConfigValidationError(f"Environment variable '{key}' must be an integer, got '{val}'")

    def _bool(key: str, default: bool) -> bool:
        val = source.get(key)
        if val is None or not val.strip():
            return default
        return val.strip().lower() in ("1", "true", "yes", "on")

    config = AppConfig(
        environment=_str("ORGTRACE_ENV", "production").lower(),
        network=NetworkSafetyConfig(
            connect_timeout=_float("ORGTRACE_CONNECT_TIMEOUT", 10.0),
            read_timeout=_float("ORGTRACE_READ_TIMEOUT", 20.0),
            max_retries=_int("ORGTRACE_MAX_RETRIES", 3),
            retry_backoff=_float("ORGTRACE_RETRY_BACKOFF", 0.4),
            max_url_length=_int("ORGTRACE_MAX_URL_LENGTH", 4096),
            enforce_dns_check=_bool("ORGTRACE_ENFORCE_DNS_CHECK", False),
        ),
        provider=ProviderConfig(
            brave_search_api_key=source.get("BRAVE_SEARCH_API_KEY", "").strip() or None,
            brave_search_api_url=_str("BRAVE_SEARCH_API_URL", "https://api.search.brave.com/res/v1/web/search"),
            brreg_api_base_url=_str("BRREG_API_BASE_URL", "https://data.brreg.no/enhetsregisteret/api"),
            brreg_accounts_base_url=_str("BRREG_ACCOUNTS_BASE_URL", "https://data.brreg.no/regnskapsregisteret/regnskap"),
        ),
        logging=LoggingConfig(
            log_level=_str("ORGTRACE_LOG_LEVEL", "INFO").upper(),
            structured_json=_bool("ORGTRACE_LOG_JSON", False),
            redact_secrets=_bool("ORGTRACE_REDACT_SECRETS", True),
        ),
        evaluation=EvaluationConfig(
            default_envelope_count=_int("ORGTRACE_DEFAULT_ENVELOPE_COUNT", 100),
            default_request_budget=_int("ORGTRACE_DEFAULT_REQUEST_BUDGET", 500),
            default_runtime_budget_seconds=_float("ORGTRACE_DEFAULT_RUNTIME_BUDGET", 300.0),
            default_cost_budget=_float("ORGTRACE_DEFAULT_COST_BUDGET", 10.0),
        ),
    )

    config.validate()
    return config
