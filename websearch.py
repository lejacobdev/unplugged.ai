"""Optional web access for the chat models. OFF by default: when the user switches it on, search queries and page requests
leave this Mac (to DuckDuckGo and to the pages the model reads). Pages on this machine or the local network are refused."""
import html
import ipaddress
import re
import socket
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _public(newurl)   # a public page must not bounce us to this Mac or the local network
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirect)


def _fetch(url, data=None, limit=600_000, timeout=15):
    req = urllib.request.Request(url, data, {"User-Agent": UA, "Accept-Language": "en"})
    with _opener.open(req, timeout=timeout) as r:
        ctype = r.headers.get("Content-Type", "")
        return r.read(limit).decode(r.headers.get_content_charset() or "utf-8", "replace"), ctype


def search(query, n=6):
    body, _ = _fetch("https://html.duckduckgo.com/html/", urllib.parse.urlencode({"q": query[:300]}).encode())
    clean = lambda t: html.unescape(re.sub(r"<[^>]+>", "", t or "")).strip()
    links = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', body, re.S)
    snips = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', body, re.S)
    out = []
    for i, (href, title) in enumerate(links[:n]):
        href = html.unescape(href)
        if "uddg=" in href:
            href = urllib.parse.unquote(href.split("uddg=", 1)[1].split("&", 1)[0])
        if href.startswith("//"):
            href = "https:" + href
        out.append({"title": clean(title), "url": href, "snippet": clean(snips[i]) if i < len(snips) else ""})
    return out


def _public(url):
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("only http and https pages can be opened")
    for info in socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80)):
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("pages on this Mac or the local network are not allowed")


def page_text(url, max_chars=6000):
    _public(url)
    body, ctype = _fetch(url)
    if "html" not in ctype and "text" not in ctype:
        raise ValueError(f"not a text page ({ctype or 'unknown type'})")
    body = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav)[^>]*>.*?</\1>", " ", body)
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", body)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", body))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return (html.unescape(title.group(1)).strip() + "\n\n" if title else "") + text[:max_chars]
