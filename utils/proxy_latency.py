"""Proxy latency measurement shared by the robot API and the scraper.

The robot API uses :func:`measure_proxy_latency` for the Proxies page
connection test; the scraper uses :func:`pick_proxies_for_banks` once at run
start to assign the lowest-latency proxy to each bank login URL when the
operator started it with the "Auto" proxy option.

Only the standard library is used, so the robot needs no extra dependency.
"""

import socket
import ssl
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# Bank login URLs used by the proxy connection test and the Auto selection
# (config key per bank).
BANK_LOGIN_URL_KEYS = (
    ("mybca", "myBCA", "mybca_login_url"),
    ("klikbca", "KlikBCA", "klikbca_login_url"),
    ("cimb", "CIMB", "cimb_login_url"),
    ("permata", "Permata", "permata_login_url"),
)

BANK_LOGIN_URL_KEY_BY_BANK = {
    bank: config_key for bank, _label, config_key in BANK_LOGIN_URL_KEYS
}

PROXY_TEST_TIMEOUT = 5.0
MAX_TEST_WORKERS = 40


def classify_proxy_error(exc):
    """Short label for a proxy/HTTP failure (timeout, tls, connection)."""
    text = str(exc).lower()
    if isinstance(exc, socket.timeout) or "timed out" in text:
        return "timeout"
    if isinstance(exc, ssl.SSLError) or "ssl" in text or "certificate" in text:
        return "tls"
    return "connection"


def measure_proxy_latency(url, ip, port, timeout=PROXY_TEST_TIMEOUT):
    """Round-trip latency (ms) from this machine to *url* through a proxy.

    Returns ``{"ok": True, "latency_ms": int}`` or
    ``{"ok": False, "error": "timeout"|"tls"|"connection"|"auth required"}``.
    An HTTP error status still counts as success: the proxy reached the site,
    which is what this measurement is about.
    """
    proxy_url = "http://{}:{}".format(ip, port)
    handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    opener = urllib.request.build_opener(handler)
    request = urllib.request.Request(
        url, method="GET", headers={"User-Agent": "Mozilla/5.0"}
    )
    started = time.perf_counter()
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        elapsed = int(round((time.perf_counter() - started) * 1000))
        if exc.code == 407:
            # The proxy itself refused: no credentials are supported.
            return {"ok": False, "error": "auth required"}
        return {"ok": True, "latency_ms": elapsed}
    except Exception as exc:  # noqa: BLE001 - classified into a short label
        return {"ok": False, "error": classify_proxy_error(exc)}
    try:
        response.close()
    except Exception:
        pass
    elapsed = int(round((time.perf_counter() - started) * 1000))
    return {"ok": True, "latency_ms": elapsed}


def bank_login_url(config, bank):
    """Configured login URL for *bank* ('' when unknown or not configured)."""
    config_key = BANK_LOGIN_URL_KEY_BY_BANK.get(str(bank or "").lower())
    if not config_key:
        return ""
    return str(config.get(config_key) or "").strip()


def slow_threshold_ms(config, default=1000):
    """``proxy_test_slow_ms`` as an int, falling back to *default*."""
    try:
        return int(config.get("proxy_test_slow_ms", default))
    except (TypeError, ValueError):
        return default


def pick_proxies_for_banks(config, proxies, threshold_ms=None, timeout=PROXY_TEST_TIMEOUT):
    """Best proxy for every configured bank login URL (one run-start probe).

    Returns ``{bank: (ip, port, latency_ms)}`` for banks that have at least one
    proxy answering within the threshold; banks without a qualifying proxy are
    absent from the result. Called once when a run starts in Auto mode, so the
    assignment stays fixed until the operator stops the scraper.
    """
    if not proxies:
        return {}
    threshold = slow_threshold_ms(config) if threshold_ms is None else int(threshold_ms)

    banks = []
    for bank, _label, _config_key in BANK_LOGIN_URL_KEYS:
        url = bank_login_url(config, bank)
        if url:
            banks.append((bank, url))
    if not banks:
        return {}

    jobs = [
        (bank, url, proxy) for bank, url in banks for proxy in proxies
    ]
    best = {}
    workers = max(1, min(MAX_TEST_WORKERS, len(jobs)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            (
                bank,
                proxy,
                pool.submit(
                    measure_proxy_latency, url, proxy["ip"], proxy["port"], timeout
                ),
            )
            for bank, url, proxy in jobs
        ]
        for bank, proxy, future in futures:
            cell = future.result()
            if not cell.get("ok"):
                continue
            latency = int(cell.get("latency_ms", 0))
            if latency > threshold:
                continue
            current = best.get(bank)
            if current is None or latency < current[2]:
                best[bank] = (proxy["ip"], proxy["port"], latency)
    return best
