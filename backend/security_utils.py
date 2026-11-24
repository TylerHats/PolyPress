import ipaddress
import os
import socket
import stat
import threading
import time
import urllib.parse
import zipfile
from collections import defaultdict, deque
from pathlib import PurePosixPath


def _check_ip_safety(
    ip_obj,
    allow_private: bool,
    allow_loopback: bool,
    loopback_hint: str = "",
) -> tuple[bool, str]:
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped is not None:
        ip_obj = ip_obj.ipv4_mapped

    if ip_obj.is_link_local:
        return False, f"Blocked link-local address: {ip_obj}"
    if ip_obj.is_multicast or ip_obj.is_unspecified or ip_obj.is_reserved:
        return False, f"Blocked reserved or multicast address: {ip_obj}"
    if ip_obj.is_loopback and not allow_loopback:
        hint = f" ({loopback_hint})" if loopback_hint else ""
        return False, f"Blocked loopback address: {ip_obj}{hint}"
    if ip_obj.is_private and not allow_private:
        return False, f"Blocked private network address: {ip_obj} (set POLYPRESS_ALLOW_PRIVATE_WEBHOOKS=true to allow private LAN URLs)"
    return True, ""


def _resolve_host_ips(hostname: str) -> list:
    clean_host = hostname.split("%", 1)[0].strip("[]")
    try:
        return [ipaddress.ip_address(clean_host)]
    except ValueError:
        pass

    infos = socket.getaddrinfo(clean_host, None, type=socket.SOCK_STREAM)
    ips = []
    for info in infos:
        sockaddr = info[4]
        if sockaddr:
            addr = sockaddr[0].split("%", 1)[0]
            ips.append(ipaddress.ip_address(addr))
    return ips


def is_safe_outbound_url(url: str, allow_private: bool = False) -> tuple[bool, str]:
    """
    Validate outbound HTTP(S) webhook/backup URLs against SSRF targets.
    Always blocks link-local (169.254.0.0/16), multicast, reserved, and unspecified IPs.
    Blocks loopback and RFC1918 private IPs unless explicitly allowed.
    """
    if not url or not isinstance(url, str):
        return False, "URL is required"

    trimmed = url.strip()
    if any(ch.isspace() for ch in trimmed):
        return False, "URL contains whitespace"

    parsed = urllib.parse.urlparse(trimmed)
    if parsed.scheme.lower() not in ("http", "https"):
        return False, "Only http and https URLs are supported"

    hostname = parsed.hostname
    if not hostname:
        return False, "URL is missing a valid hostname"

    env_allow_private = os.getenv("POLYPRESS_ALLOW_PRIVATE_WEBHOOKS", "").lower() == "true"
    effective_allow_private = allow_private or env_allow_private

    try:
        ips = _resolve_host_ips(hostname)
    except Exception:
        return False, f"Could not resolve hostname: {hostname}"

    if not ips:
        return False, f"Could not resolve hostname: {hostname}"

    for ip_obj in ips:
        ok, reason = _check_ip_safety(
            ip_obj,
            allow_private=effective_allow_private,
            allow_loopback=effective_allow_private,
            loopback_hint="set POLYPRESS_ALLOW_PRIVATE_WEBHOOKS=true to allow private LAN/loopback URLs",
        )
        if not ok:
            return False, reason

    return True, ""


def is_safe_mail_host(host: str) -> tuple[bool, str]:
    """
    Validate SMTP/IMAP hostnames against metadata/loopback SSRF while permitting
    standard private/LAN mail relays.
    """
    if not host or not isinstance(host, str):
        return False, "Mail server host is required"

    cleaned = host.strip()
    if not cleaned or any(ch.isspace() or ord(ch) < 32 for ch in cleaned):
        return False, "Invalid mail server hostname"
    if cleaned.startswith("-"):
        return False, "Invalid mail server hostname"

    allow_local = os.getenv("POLYPRESS_ALLOW_LOCAL_MAIL", "").lower() == "true"

    try:
        ips = _resolve_host_ips(cleaned)
    except Exception:
        return False, f"Could not resolve mail host: {cleaned}"

    if not ips:
        return False, f"Could not resolve mail host: {cleaned}"

    for ip_obj in ips:
        ok, reason = _check_ip_safety(
            ip_obj,
            allow_private=True,
            allow_loopback=allow_local,
            loopback_hint="set POLYPRESS_ALLOW_LOCAL_MAIL=true to allow local mail relays",
        )
        if not ok:
            return False, reason

    return True, ""


def is_path_within(child_path: str, parent_dir: str) -> bool:
    """Safely verify that child_path resolves inside parent_dir."""
    try:
        real_parent = os.path.realpath(parent_dir)
        real_child = os.path.realpath(child_path)
        return os.path.commonpath([real_child, real_parent]) == real_parent
    except Exception:
        return False


def safe_extract_zip(
    zip_path: str,
    dest_dir: str,
    max_files: int = 500,
    max_total_bytes: int = 2 * 1024 * 1024 * 1024,
) -> None:
    """
    Safely extract a ZIP archive into dest_dir, preventing Zip Slip path traversal,
    symlink extraction, and decompression zip-bombs.
    """
    real_dest = os.path.realpath(dest_dir)
    os.makedirs(real_dest, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zipf:
        infos = zipf.infolist()
        if len(infos) > max_files:
            raise ValueError(f"Archive contains too many entries ({len(infos)} > {max_files})")

        total_bytes = 0
        for info in infos:
            raw_name = info.filename
            if not raw_name:
                continue

            # Reject symlinks
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError(f"Symlink entries are not allowed in backup archive: {raw_name}")

            # Normalize separators and reject absolute paths, drive letters, or parent traversal
            normalized = raw_name.replace("\\", "/")
            if normalized.startswith("/") or (len(normalized) >= 2 and normalized[1] == ":"):
                raise ValueError(f"Absolute path entry is not allowed in backup archive: {raw_name}")

            parts = PurePosixPath(normalized).parts
            if any(part in ("..", "") and idx > 0 for idx, part in enumerate(parts)) or ".." in parts:
                raise ValueError(f"Path traversal entry is not allowed in backup archive: {raw_name}")

            target_path = os.path.realpath(os.path.join(real_dest, *parts))
            if not is_path_within(target_path, real_dest):
                raise ValueError(f"Archive entry escapes destination directory: {raw_name}")

            if info.is_dir():
                os.makedirs(target_path, exist_ok=True)
                continue

            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with zipf.open(info, "r") as src, open(target_path, "wb") as dst:
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > max_total_bytes:
                        raise ValueError("Backup archive exceeds maximum uncompressed size limit")
                    dst.write(chunk)


class SlidingWindowRateLimiter:
    """Thread-safe in-memory sliding window rate limiter."""

    def __init__(self):
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._last_prune = 0.0

    def check_and_record(self, key: str, max_requests: int, window_seconds: int) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            q = self._events[key]
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= max_requests:
                return False
            q.append(now)

            if now - self._last_prune > 300:
                self._last_prune = now
                stale_keys = [k for k, dq in self._events.items() if not dq]
                for k in stale_keys:
                    del self._events[k]

            return True


login_rate_limiter = SlidingWindowRateLimiter()
totp_rate_limiter = SlidingWindowRateLimiter()
password_reset_rate_limiter = SlidingWindowRateLimiter()
embed_rate_limiter = SlidingWindowRateLimiter()

_totp_step_lock = threading.Lock()
_last_totp_steps: dict[int, int] = {}


def check_and_record_totp_step(user_id: int, time_step: int) -> bool:
    """Prevent TOTP replay attacks by rejecting already-consumed or older time steps."""
    with _totp_step_lock:
        last_step = _last_totp_steps.get(user_id)
        if last_step is not None and time_step <= last_step:
            return False
        _last_totp_steps[user_id] = time_step
        return True

