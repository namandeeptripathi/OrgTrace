"""Stage 11: Production URL Safety & SSRF Protection.

Provides centralized, robust URL validation and SSRF defenses:
- Rejects dangerous schemes (file://, javascript:, data:, etc.)
- Rejects embedded credentials (http://user:pass@host)
- Rejects localhost, loopback, link-local, multicast, and private IP ranges
- Enforces maximum URL length limits against buffer/memory abuse
- Validates hostnames, ports, and optional DNS-level global IP checks
- Sanitizes URLs for safe logging by redacting credentials and sensitive query params
"""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
from dataclasses import dataclass, field


ALLOWED_SCHEMES = frozenset({"http", "https"})
DANGEROUS_SCHEMES = frozenset({
    "file", "javascript", "data", "vbscript", "ftp", "ftps",
    "ldap", "ldaps", "gopher", "dict", "tftp", "telnet",
})
BLOCKED_HOSTNAMES = frozenset({
    "localhost", "127.0.0.1", "0.0.0.0", "::1", "::",
})
BLOCKED_SUFFIXES = (
    ".localhost", ".local", ".internal", ".corp", ".lan", ".home.arpa",
)
MAX_URL_LENGTH = 4096
SENSITIVE_PARAM_NAMES = frozenset({
    "api_key", "apikey", "key", "token", "access_token", "secret",
    "client_secret", "password", "passwd", "auth", "credential",
})


class UrlSafetyError(ValueError):
    """Base exception for URL safety and validation violations."""
    pass


class DangerousSchemeError(UrlSafetyError):
    """Raised when an unsupported or dangerous scheme is supplied."""
    pass


class EmbeddedCredentialsError(UrlSafetyError):
    """Raised when a URL contains embedded userinfo (username or password)."""
    pass


class PrivateNetworkAccessError(UrlSafetyError):
    """Raised when a URL attempts to access private, loopback, or reserved network addresses."""
    pass


class UrlLengthExceededError(UrlSafetyError):
    """Raised when a URL exceeds the maximum allowed length."""
    pass


class InvalidHostError(UrlSafetyError):
    """Raised when a URL has an invalid, empty, or unresolvable hostname."""
    pass


@dataclass(frozen=True)
class UrlValidationResult:
    """Detailed verdict of a URL safety validation check."""
    url: str
    is_safe: bool
    normalized_url: str | None = None
    scheme: str | None = None
    host: str | None = None
    port: int | None = None
    error: str | None = None
    ip_addresses: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "is_safe": self.is_safe,
            "normalized_url": self.normalized_url,
            "scheme": self.scheme,
            "host": self.host,
            "port": self.port,
            "error": self.error,
            "ip_addresses": list(self.ip_addresses),
        }


def validate_public_url(
    url: str | None,
    *,
    check_dns: bool = False,
    max_length: int = MAX_URL_LENGTH,
) -> UrlValidationResult:
    """Validate that a URL is a safe, public HTTP(S) URL.

    Checks:
    1. Not empty or whitespace-only
    2. Length <= max_length
    3. Scheme is strictly 'http' or 'https' (rejects dangerous schemes)
    4. No embedded credentials (username/password)
    5. Valid hostname (not localhost or internal suffix)
    6. If literal IP: must be public/global (not private, loopback, link-local)
    7. If check_dns is True: resolves DNS and verifies all IPs are global
    """
    raw = str(url or "").strip()
    if not raw:
        return UrlValidationResult(url="", is_safe=False, error="URL is empty or whitespace-only")

    if len(raw) > max_length:
        return UrlValidationResult(
            url=raw[:100] + "...[truncated]",
            is_safe=False,
            error=f"URL length {len(raw)} exceeds maximum allowed limit of {max_length} characters",
        )

    try:
        parsed = urllib.parse.urlsplit(raw)
    except Exception as exc:
        return UrlValidationResult(url=raw, is_safe=False, error=f"Malformed URL: {exc}")

    scheme = (parsed.scheme or "").lower()
    if not scheme or scheme not in ALLOWED_SCHEMES:
        if scheme in DANGEROUS_SCHEMES:
            err = f"Dangerous URL scheme '{scheme}' is strictly blocked"
        else:
            err = f"Unsupported scheme '{scheme}'; only public HTTP(S) URLs are allowed"
        return UrlValidationResult(url=raw, is_safe=False, scheme=scheme, error=err)

    # Check for embedded credentials (e.g. http://admin:pass@host)
    if parsed.username or parsed.password:
        return UrlValidationResult(
            url=raw,
            is_safe=False,
            scheme=scheme,
            error="URLs with embedded credentials (username/password) are blocked",
        )

    # Check for invalid characters in netloc
    if any(c in parsed.netloc for c in ("\r", "\n", "\t", " ")):
        return UrlValidationResult(url=raw, is_safe=False, scheme=scheme, error="URL contains illegal whitespace characters")

    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return UrlValidationResult(url=raw, is_safe=False, scheme=scheme, error="URL hostname is missing or invalid")

    # Validate port
    port = parsed.port
    if port is not None and not (1 <= port <= 65535):
        return UrlValidationResult(url=raw, is_safe=False, scheme=scheme, host=host, error=f"Port {port} out of range (1-65535)")

    # Check blocked hostnames and suffixes
    if host in BLOCKED_HOSTNAMES or any(host.endswith(sfx) for sfx in BLOCKED_SUFFIXES):
        return UrlValidationResult(
            url=raw,
            is_safe=False,
            scheme=scheme,
            host=host,
            port=port,
            error=f"Host '{host}' is an internal, local, or reserved hostname",
        )

    # Check if host is an IP literal
    resolved_ips: list[str] = []
    try:
        ip_obj = ipaddress.ip_address(host)
        resolved_ips.append(str(ip_obj))
        if not ip_obj.is_global:
            return UrlValidationResult(
                url=raw,
                is_safe=False,
                scheme=scheme,
                host=host,
                port=port,
                error=f"IP address '{host}' is not global (private, loopback, or reserved)",
                ip_addresses=resolved_ips,
            )
    except ValueError:
        # Not a raw IP literal; host is a domain name
        pass

    # Optional DNS-level resolution check
    if check_dns and not resolved_ips:
        try:
            target_port = port or (443 if scheme == "https" else 80)
            addr_info = socket.getaddrinfo(host, target_port, type=socket.SOCK_STREAM)
            resolved_ips = list({item[4][0] for item in addr_info})
            for addr in resolved_ips:
                ip = ipaddress.ip_address(addr)
                if not ip.is_global:
                    return UrlValidationResult(
                        url=raw,
                        is_safe=False,
                        scheme=scheme,
                        host=host,
                        port=port,
                        error=f"Hostname '{host}' resolved to non-global IP '{addr}'",
                        ip_addresses=resolved_ips,
                    )
        except socket.gaierror as exc:
            return UrlValidationResult(
                url=raw,
                is_safe=False,
                scheme=scheme,
                host=host,
                port=port,
                error=f"Hostname '{host}' did not resolve: {exc}",
            )

    normalized = urllib.parse.urlunsplit((
        scheme,
        parsed.netloc.lower(),
        parsed.path or "/",
        parsed.query,
        "",  # Strip fragment for safe HTTP requests
    ))

    return UrlValidationResult(
        url=raw,
        is_safe=True,
        normalized_url=normalized,
        scheme=scheme,
        host=host,
        port=port,
        ip_addresses=resolved_ips,
    )


def assert_public_url(url: str, check_dns: bool = False) -> None:
    """Enforce that a URL is a safe public URL.

    Raises UrlSafetyError (which inherits from ValueError) if the URL is unsafe.
    Preserves exact backward compatibility with existing Stage 0–10 tests.
    """
    result = validate_public_url(url, check_dns=check_dns)
    if not result.is_safe:
        err = result.error or "Invalid URL"
        if "Dangerous URL scheme" in err:
            raise DangerousSchemeError(err)
        if "embedded credentials" in err:
            raise EmbeddedCredentialsError(err)
        if "length" in err and "exceeds" in err:
            raise UrlLengthExceededError(err)
        if "internal, local" in err or "non-global" in err or "not global" in err:
            raise PrivateNetworkAccessError(err)
        if "hostname is missing" in err or "did not resolve" in err:
            raise InvalidHostError(err)
        raise UrlSafetyError(err)


def sanitize_url_for_logging(url: str) -> str:
    """Sanitize a URL for logging by redacting credentials and sensitive query parameters."""
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlsplit(url)
        # Redact credentials in netloc
        netloc = parsed.netloc
        if parsed.username or parsed.password:
            host_part = parsed.hostname or ""
            if parsed.port:
                host_part = f"{host_part}:{parsed.port}"
            netloc = f"[REDACTED]:[REDACTED]@{host_part}"

        # Redact sensitive query parameters
        query = parsed.query
        if query:
            params = urllib.parse.parse_qsl(query, keep_blank_values=True)
            sanitized_params = []
            for k, v in params:
                if k.lower() in SENSITIVE_PARAM_NAMES:
                    sanitized_params.append((k, "[REDACTED]"))
                else:
                    sanitized_params.append((k, v))
            query = urllib.parse.urlencode(sanitized_params)

        return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, query, parsed.fragment))
    except Exception:
        # If parsing fails, mask the entire string except scheme
        return re.sub(r"://.*", "://[MALFORMED_URL_REDACTED]", url)
