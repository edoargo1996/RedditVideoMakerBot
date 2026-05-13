"""
Reddit scraper that uses the public JSON endpoints (.json) instead of the OAuth API.
No API credentials needed.
"""
import time
from typing import List, Optional

import requests


REDDIT_BASE = "https://www.reddit.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

# Shared session primed with a homepage visit so Reddit sets cookies and allows JSON endpoints.
_SESSION: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        })
        # Prime cookies by visiting the homepage once
        _SESSION.get(REDDIT_BASE, timeout=30)
    return _SESSION


class FakeAuthor:
    """Minimal author stand-in."""

    def __init__(self, name: Optional[str]):
        self.name = name

    def __str__(self):
        return self.name or "[deleted]"


class FakeComment:
    """Minimal comment stand-in compatible with praw Comment."""

    def __init__(self, data: dict):
        self.body = data.get("body", "")
        self.id = data.get("id", "")
        self.permalink = data.get("permalink", "")
        self.stickied = data.get("stickied", False)
        author = data.get("author")
        self.author = FakeAuthor(author) if author else None


class FakeSubmission:
    """Minimal submission stand-in compatible with praw Submission."""

    def __init__(self, data: dict, comments: Optional[List[FakeComment]] = None):
        self.title = data.get("title", "")
        self.id = data.get("id", "")
        self.permalink = data.get("permalink", "")
        self.score = data.get("score", 0)
        self.upvote_ratio = data.get("upvote_ratio", 0.0)
        self.num_comments = data.get("num_comments", 0)
        self.over_18 = data.get("over_18", False)
        self.selftext = data.get("selftext", "")
        self.stickied = data.get("stickied", False)
        self.is_self = data.get("is_self", True)
        author = data.get("author")
        self.author = FakeAuthor(author) if author else None
        self.comments = comments or []

    def __str__(self):
        return self.id


class FakeSubreddit:
    """Minimal subreddit stand-in that yields submissions via .json endpoints."""

    def __init__(self, name: str):
        self.name = name
        self._last_call = 0.0

    def _rate_limit(self):
        # Reddit JSON endpoints are generous, but let's be polite.
        elapsed = time.time() - self._last_call
        if elapsed < 0.5:
            time.sleep(0.5 - elapsed)
        self._last_call = time.time()

    def _get(self, url: str, params: Optional[dict] = None) -> dict:
        self._rate_limit()
        session = _get_session()
        resp = session.get(url, params=params or {}, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def hot(self, limit: int = 25):
        url = f"{REDDIT_BASE}/r/{self.name}/hot.json"
        data = self._get(url, {"limit": limit})
        for child in data.get("data", {}).get("children", []):
            if child.get("kind") == "t3":
                yield FakeSubmission(child["data"])

    def top(self, time_filter: str = "all", limit: int = 50):
        url = f"{REDDIT_BASE}/r/{self.name}/top.json"
        data = self._get(url, {"t": time_filter, "limit": limit})
        for child in data.get("data", {}).get("children", []):
            if child.get("kind") == "t3":
                yield FakeSubmission(child["data"])

    def submission(self, id: str) -> FakeSubmission:
        """Fetch a single submission + top-level comments via the comments JSON endpoint."""
        url = f"{REDDIT_BASE}/comments/{id}.json"
        data = self._get(url, {"limit": 50, "depth": 1})
        # data is a list: [post_listing, comments_listing]
        if not isinstance(data, list) or len(data) < 2:
            raise ValueError(f"Unexpected response format for post {id}")

        post_data = data[0]["data"]["children"][0]["data"]
        comments = []
        for child in data[1].get("data", {}).get("children", []):
            kind = child.get("kind")
            if kind == "t1":
                comments.append(FakeComment(child["data"]))
            elif kind == "more":
                # skip MoreComments equivalent
                continue

        return FakeSubmission(post_data, comments=comments)


class FakeSearchResults:
    """Search results across all of Reddit via PullPush API (no auth needed)."""

    def __init__(self, query: str, sort: str = "hot", time_filter: str = "all", limit: int = 25):
        self.query = query
        self.sort = sort
        self.time_filter = time_filter
        self.limit = limit

    def _params(self) -> dict:
        # PullPush sorting: score, num_comments, created_utc
        if self.sort == "new":
            sort_type, sort_dir = "created_utc", "desc"
        elif self.sort == "top":
            sort_type, sort_dir = "score", "desc"
        elif self.sort == "comments":
            sort_type, sort_dir = "num_comments", "desc"
        else:
            # hot, relevance -> fallback to score desc
            sort_type, sort_dir = "score", "desc"

        params = {
            "q": self.query,
            "size": self.limit,
            "sort": sort_dir,
            "sort_type": sort_type,
        }

        now = int(time.time())
        if self.time_filter == "hour":
            params["after"] = now - 3600
        elif self.time_filter == "day":
            params["after"] = now - 86400
        elif self.time_filter == "week":
            params["after"] = now - 604800
        elif self.time_filter == "month":
            params["after"] = now - 2592000
        elif self.time_filter == "year":
            params["after"] = now - 31536000

        return params

    def __iter__(self):
        url = "https://api.pullpush.io/reddit/search/submission/"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }
        resp = requests.get(url, params=self._params(), headers=headers, timeout=30)
        try:
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            raise RuntimeError(f"PullPush search failed: {exc}") from exc

        for post in payload.get("data", []):
            # PullPush returns raw API fields; author is a string
            if isinstance(post.get("author"), str):
                post["author"] = post["author"]
            yield FakeSubmission(post)


class FakeReddit:
    """Minimal reddit client stand-in."""

    def subreddit(self, name: str) -> FakeSubreddit:
        return FakeSubreddit(name)

    def submission(self, id: str) -> FakeSubmission:
        # Directly fetch without going through subreddit object
        return FakeSubreddit("all").submission(id)

    def search(self, query: str, sort: str = "hot", time_filter: str = "all", limit: int = 25):
        return FakeSearchResults(query, sort, time_filter, limit)
