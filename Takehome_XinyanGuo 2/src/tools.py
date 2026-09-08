"""Tools the agent can call.

Contract: every tool returns a JSON-serialisable dict and NEVER raises.
A failure comes back as {"ok": false, "error": "..."} so the model can see
what went wrong and choose to retry, reformulate, or move on. A tool that
raises would end the run; a tool that reports is something the agent can
recover from, which is the behaviour the exercise asks for.
"""
import re
import time
import html as htmllib

import requests

from . import config


HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; forecast-agent/0.1)"}


# --------------------------------------------------------------------------
# web_search
# --------------------------------------------------------------------------
def web_search(query: str, max_results: int = 5) -> dict:
    provider = config.SEARCH_PROVIDER
    try:
        if provider == "brave":
            if not config.BRAVE_API_KEY:
                return {"ok": False, "error": "SEARCH_PROVIDER=brave but BRAVE_API_KEY is unset"}
            return _brave(query, max_results)
        if provider == "tavily":
            if not config.TAVILY_API_KEY:
                return {"ok": False, "error": "SEARCH_PROVIDER=tavily but TAVILY_API_KEY is unset"}
            return _tavily(query, max_results)
        return _duckduckgo(query, max_results)
    except requests.Timeout:
        return {"ok": False, "error": f"search timed out after {config.REQUEST_TIMEOUT}s"}
    except Exception as e:  # deliberately broad: tools report, they do not raise
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _brave(query: str, max_results: int) -> dict:
    """Brave Search API. Free tier: 1 query/second, 2000/month - the rate limit
    is why a 429 here is retried rather than treated as a hard failure."""
    r = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": max(1, min(int(max_results), 20))},
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": config.BRAVE_API_KEY,
        },
        timeout=config.REQUEST_TIMEOUT,
    )
    if r.status_code == 429:
        time.sleep(1.2)  # free tier is 1 query/second
        return {"ok": False, "error": "brave rate limit (429); waited 1s, safe to retry with a different query"}
    if r.status_code != 200:
        return {"ok": False, "error": f"brave HTTP {r.status_code}: {r.text[:200]}"}
    results = [
        {
            "title": it.get("title", ""),
            "url": it.get("url", ""),
            "snippet": _strip_tags(it.get("description", ""))[:500],
            "age": it.get("age", ""),
        }
        for it in (r.json().get("web", {}) or {}).get("results", [])
    ]
    if not results:
        return {"ok": False, "error": "brave returned no results"}
    return {"ok": True, "provider": "brave", "query": query, "results": results}


def _tavily(query: str, max_results: int) -> dict:
    r = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": config.TAVILY_API_KEY,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
        },
        timeout=config.REQUEST_TIMEOUT,
    )
    if r.status_code != 200:
        return {"ok": False, "error": f"tavily HTTP {r.status_code}: {r.text[:200]}"}
    data = r.json()
    results = [
        {"title": it.get("title", ""), "url": it.get("url", ""), "snippet": it.get("content", "")[:500]}
        for it in data.get("results", [])
    ]
    return {"ok": True, "provider": "tavily", "query": query, "results": results}


def _duckduckgo(query: str, max_results: int) -> dict:
    """No-key fallback. Scrapes the DuckDuckGo HTML endpoint.

    Declared in the README as the no-signup option. It is brittle by nature -
    if the markup changes this returns ok=false rather than silently nothing.
    """
    r = requests.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        headers=HEADERS,
        timeout=config.REQUEST_TIMEOUT,
    )
    if r.status_code != 200:
        return {"ok": False, "error": f"duckduckgo HTTP {r.status_code}"}
    results = []
    for m in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S
    ):
        url, title = m.group(1), _strip_tags(m.group(2))
        results.append({"title": title, "url": html_unescape(url), "snippet": ""})
        if len(results) >= max_results:
            break
    if not results:
        return {"ok": False, "error": "duckduckgo returned no parseable results (markup may have changed)"}
    return {"ok": True, "provider": "duckduckgo", "query": query, "results": results}


# --------------------------------------------------------------------------
# fetch_page
# --------------------------------------------------------------------------
def fetch_page(url: str) -> dict:
    try:
        r = requests.get(url, headers=HEADERS, timeout=config.REQUEST_TIMEOUT)
        if r.status_code != 200:
            return {"ok": False, "error": f"HTTP {r.status_code} for {url}"}
        ctype = r.headers.get("content-type", "")
        if "html" not in ctype and "text" not in ctype and "json" not in ctype:
            return {"ok": False, "error": f"unsupported content-type {ctype!r} for {url}"}
        text = _strip_tags(r.text)
        truncated = len(text) > config.MAX_FETCH_CHARS
        return {
            "ok": True,
            "url": url,
            "chars": len(text),
            "truncated": truncated,
            "text": text[: config.MAX_FETCH_CHARS],
        }
    except requests.Timeout:
        return {"ok": False, "error": f"fetch timed out after {config.REQUEST_TIMEOUT}s: {url}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def html_unescape(s: str) -> str:
    return htmllib.unescape(s)


def _strip_tags(s: str) -> str:
    s = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = htmllib.unescape(s)
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n\n", s)).strip()
