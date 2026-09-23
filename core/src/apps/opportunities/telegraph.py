import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

TELEGRAPH_HOSTS = {"graph.org", "telegra.ph"}
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


@dataclass(frozen=True)
class TelegraphPage:
    title: str
    text: str
    links: list[tuple[str, str]]


class _ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.title_depth = 0
        self.title_parts = []
        self.text_parts = []
        self.links = []
        self.current_link = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "article" and not self.depth:
            self.depth = 1
        elif self.depth and tag not in VOID_TAGS:
            self.depth += 1
        else:
            return
        if tag == "h1" and not self.title_parts:
            self.title_depth = self.depth
        if tag == "a":
            self.current_link = (attrs.get("href", ""), [])
        if tag in {"p", "h1", "h2", "h3", "h4", "li", "blockquote", "br"}:
            self.text_parts.append("\n")

    def handle_data(self, data):
        if not self.depth:
            return
        self.text_parts.append(data)
        if self.title_depth:
            self.title_parts.append(data)
        if self.current_link:
            self.current_link[1].append(data)

    def handle_endtag(self, tag):
        if not self.depth:
            return
        if tag == "a" and self.current_link:
            href, parts = self.current_link
            self.links.append((href, " ".join("".join(parts).split())))
            self.current_link = None
        if tag == "h1" and self.title_depth == self.depth:
            self.title_depth = 0
        self.depth -= 1


def is_telegraph(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in TELEGRAPH_HOSTS


def fetch_page(url: str) -> TelegraphPage:
    if not is_telegraph(url):
        raise ValueError("Only Telegraph pages can be fetched")
    request = Request(url, headers={"User-Agent": "job-filler/0.1"})
    with urlopen(request, timeout=15) as response:
        if not is_telegraph(response.geturl()):
            raise ValueError("Telegraph page redirected to another host")
        html = response.read(1_000_001)
    if len(html) > 1_000_000:
        raise ValueError("Telegraph page is too large")
    parser = _ArticleParser()
    parser.feed(html.decode("utf-8", errors="replace"))
    links = [(urljoin(url, href), label) for href, label in parser.links if href]
    text = "\n".join(" ".join(line.split()) for line in "".join(parser.text_parts).splitlines())
    return TelegraphPage(" ".join("".join(parser.title_parts).split()), text[:12000], links)


def category_jobs(category_urls: list[str]) -> list[tuple[str, str]]:
    """Return distinct Telegraph job pages and their link titles from category pages."""
    found = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch_page, url): url for url in category_urls[:60]}
        for future in as_completed(futures):
            try:
                page = future.result()
            except (OSError, ValueError):
                continue
            for url, title in page.links:
                if is_telegraph(url) and title:
                    found.setdefault(url, title)
    return list(found.items())


def application_link(page: TelegraphPage) -> str:
    def is_external(url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
            return False
        if host in TELEGRAPH_HOSTS | {"t.me", "telegram.me", "localhost"} or host.endswith(
            ".local"
        ):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True

    external = [(url, label) for url, label in page.links if is_external(url)]
    preferred = [
        url
        for url, label in external
        if any(word in label.lower() for word in ("apply", "отклик", "заявк", "respond"))
    ]
    if len(preferred) == 1:
        return preferred[0]
    if len(external) == 1:
        return external[0][0]
    return ""
