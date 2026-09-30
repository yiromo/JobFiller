from urllib.parse import urlparse

SITE = "linkedin"
NAME = "LinkedIn"
LOGIN_URL = "https://www.linkedin.com/login"
SESSION_COOKIE = "li_at"


def handles(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def is_logged_in(page) -> bool:
    cookies = page.context.cookies("https://www.linkedin.com")
    return any(cookie["name"] == SESSION_COOKIE and cookie["value"] for cookie in cookies)
