import re

from reddit.subreddit_scraper import FakeReddit, FakeComment
from utils import settings
from utils.ai_methods import sort_by_similarity
from utils.console import print_step, print_substep
from utils.posttextparser import posttextparser
from utils.subreddit import _contains_blocked_words, get_subreddit_undone
from utils.videos import check_done
from utils.voice import sanitize_text


def get_subreddit_threads(POST_ID: str):
    """
    Returns a list of threads from the AskReddit subreddit.
    """

    print_substep("Initializing Reddit scraper (no API key needed).")

    content = {}
    reddit = FakeReddit()

    # Ask user for subreddit input
    print_step("Getting subreddit threads...")
    similarity_score = 0

    search_query = settings.config["reddit"]["thread"].get("search_query", "")
    if search_query:
        print_substep(f"Searching Reddit for: \"{search_query}\"")
        search_sort = settings.config["reddit"]["thread"].get("search_sort", "hot")
        search_time = settings.config["reddit"]["thread"].get("search_time", "all")
        search_limit = int(settings.config["reddit"]["thread"].get("search_limit", 25))
        threads = list(reddit.search(search_query, sort=search_sort, time_filter=search_time, limit=search_limit))
        if not threads:
            # Fallback: try with just the first word of the query
            first_word = search_query.split()[0] if search_query.split() else ""
            if first_word and first_word != search_query:
                print_substep(f"No results for full query. Trying fallback: '{first_word}'")
                threads = list(reddit.search(first_word, sort=search_sort, time_filter=search_time, limit=search_limit))
            if not threads:
                raise RuntimeError(f"No results found for search query '{search_query}'. Try a broader term or change the time filter.")
        # For search mode we bypass the subreddit object and pick directly
        subreddit = None
        if settings.config["ai"]["ai_similarity_enabled"]:
            keywords = settings.config["ai"]["ai_similarity_keywords"].split(",")
            keywords = [keyword.strip() for keyword in keywords]
            keywords_print = ", ".join(keywords)
            print(f"Sorting threads by similarity to the given keywords: {keywords_print}")
            threads, similarity_scores = sort_by_similarity(threads, keywords)
            submission, similarity_score = get_subreddit_undone(threads, subreddit, similarity_scores=similarity_scores)
        else:
            submission = get_subreddit_undone(threads, subreddit)
        if submission is None:
            raise RuntimeError("All found threads were already used or filtered out. Try a different search or clear the done-videos list.")
    else:
        # If a specific post_id is configured, use it directly (bypass subreddit selection)
        if settings.config["reddit"]["thread"]["post_id"]:
            post_ids = str(settings.config["reddit"]["thread"]["post_id"]).split("+")
            if len(post_ids) == 1:
                submission = reddit.submission(id=post_ids[0])
            else:
                # Multiple post IDs — handled by main.py loop, here we just take the first
                submission = reddit.submission(id=post_ids[0])
        elif not settings.config["reddit"]["thread"][
            "subreddit"
        ]:
            try:
                subreddit = reddit.subreddit(
                    re.sub(r"r\/", "", input("What subreddit would you like to pull from? "))
                    # removes the r/ from the input
                )
            except ValueError:
                subreddit = reddit.subreddit("askreddit")
                print_substep("Subreddit not defined. Using AskReddit.")
        else:
            sub = settings.config["reddit"]["thread"]["subreddit"]
            print_substep(f"Using subreddit: r/{sub} from TOML config")
            subreddit_choice = sub
            if str(subreddit_choice).casefold().startswith("r/"):
                subreddit_choice = subreddit_choice[2:]
            subreddit = reddit.subreddit(subreddit_choice)

        if POST_ID:
            submission = reddit.submission(id=POST_ID)
        elif settings.config["ai"]["ai_similarity_enabled"]:
            threads = list(subreddit.hot(limit=50))
            keywords = settings.config["ai"]["ai_similarity_keywords"].split(",")
            keywords = [keyword.strip() for keyword in keywords]
            keywords_print = ", ".join(keywords)
            print(f"Sorting threads by similarity to the given keywords: {keywords_print}")
            threads, similarity_scores = sort_by_similarity(threads, keywords)
            submission, similarity_score = get_subreddit_undone(
                threads, subreddit, similarity_scores=similarity_scores
            )
        elif not settings.config["reddit"]["thread"]["post_id"]:
            threads = list(subreddit.hot(limit=25))
            submission = get_subreddit_undone(threads, subreddit)

    if submission is None:
        raise RuntimeError(
            "All found threads were already used or filtered out. "
            "Try a different search query, change the time filter, or click '🗑 Clear done list' to reuse previous threads."
        )

    elif not submission.num_comments and settings.config["settings"]["storymode"] == "false":
        raise RuntimeError("No comments found on this post. Try a different thread or enable story mode.")

    submission = check_done(submission)  # double-checking

    # Re-fetch the full post with comments since hot/top listings don't include them
    submission = reddit.submission(id=submission.id)

    # Double-check after re-fetch — Reddit may mark it as removed even if PullPush had the old title
    if "removed by moderator" in (submission.title or "").lower():
        print_substep("Post was removed by moderator (detected after re-fetch). Skipping...")
        return get_subreddit_threads(POST_ID)

    upvotes = submission.score
    ratio = submission.upvote_ratio * 100
    num_comments = submission.num_comments
    threadurl = f"https://www.reddit.com/{submission.permalink}"

    print_substep(f"Video will be: {submission.title} :thumbsup:", style="bold green")
    print_substep(f"Thread url is: {threadurl} :thumbsup:", style="bold green")
    print_substep(f"Thread has {upvotes} upvotes", style="bold blue")
    print_substep(f"Thread has a upvote ratio of {ratio}%", style="bold blue")
    print_substep(f"Thread has {num_comments} comments", style="bold blue")
    if similarity_score:
        print_substep(
            f"Thread has a similarity score up to {round(similarity_score * 100)}%",
            style="bold blue",
        )

    content["thread_url"] = threadurl
    content["thread_title"] = submission.title
    content["thread_id"] = submission.id
    content["is_nsfw"] = submission.over_18
    content["comments"] = []
    if settings.config["settings"]["storymode"]:
        if settings.config["settings"]["storymodemethod"] == 1:
            content["thread_post"] = posttextparser(submission.selftext)
        else:
            content["thread_post"] = submission.selftext
    else:
        for top_level_comment in submission.comments:
            if isinstance(top_level_comment, FakeComment):
                # our scraper already skips MoreComments, so no need for that check
                pass

            if top_level_comment.body in ["[removed]", "[deleted]"]:
                continue  # # see https://github.com/JasonLovesDoggo/RedditVideoMakerBot/issues/78
            if _contains_blocked_words(top_level_comment.body):
                continue
            if not top_level_comment.stickied:
                sanitised = sanitize_text(top_level_comment.body)
                if not sanitised or sanitised == " ":
                    continue
                if len(top_level_comment.body) <= int(
                    settings.config["reddit"]["thread"]["max_comment_length"]
                ):
                    if len(top_level_comment.body) >= int(
                        settings.config["reddit"]["thread"]["min_comment_length"]
                    ):
                        if (
                            top_level_comment.author is not None
                            and sanitize_text(top_level_comment.body) is not None
                        ):  # if errors occur with this change to if not.
                            content["comments"].append(
                                {
                                    "comment_body": top_level_comment.body,
                                    "comment_url": top_level_comment.permalink,
                                    "comment_id": top_level_comment.id,
                                }
                            )

    print_substep("Received subreddit threads Successfully.", style="bold green")
    return content
