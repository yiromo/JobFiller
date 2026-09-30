from urllib.parse import urlparse

SITE = "indeed"
NAME = "Indeed"
LOGIN_URL = "https://secure.indeed.com/auth"
SESSION_COOKIES = {"SOCK", "SHOE"}


def handles(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "indeed.com" or host.endswith(".indeed.com")


def is_logged_in(page) -> bool:
    cookies = page.context.cookies("https://secure.indeed.com")
    return any(cookie["name"] in SESSION_COOKIES and cookie["value"] for cookie in cookies)
