from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "yclid",
}
_TRACKING_PREFIXES = ("utm_",)


def _drop_tracking(query: str) -> str:
    if not query:
        return ""
    kept = [
        (k, v)
        for k, v in parse_qsl(query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
        and not any(k.lower().startswith(p) for p in _TRACKING_PREFIXES)
    ]
    kept.sort()
    return urlencode(kept, doseq=True)


def normalize_url(url: str) -> str:
    """Canonical form for dedup: lowercase host, no tracking params, no trailing slash, no fragment.

    Returns the input unchanged if it doesn't parse cleanly — callers can still use it as a
    last-resort key, but downstream comparisons may miss matches in that case.
    """
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    scheme = parts.scheme.lower() or "http"
    netloc = parts.netloc.lower()
    path = parts.path or ""
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    query = _drop_tracking(parts.query)
    return urlunsplit((scheme, netloc, path, query, ""))
