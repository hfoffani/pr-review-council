from __future__ import annotations

from prc.context import PullRequestContext
from prc.pr_platforms.base import PullRequestMetadata


def test_pull_request_context_includes_escaped_metadata_before_diff() -> None:
    ctx = PullRequestContext(
        diff="diff --git a/file.py b/file.py\n+change",
        metadata=PullRequestMetadata(
            title="Use <metadata>",
            description="Reviewer context & details",
            url="https://github.com/org/repo/pull/1?a=1&b=2",
        ),
    )

    assert ctx.render() == (
        "<pull_request>\n"
        "<title>Use &lt;metadata&gt;</title>\n"
        "<description>\n"
        "Reviewer context &amp; details\n"
        "</description>\n"
        "<url>https://github.com/org/repo/pull/1?a=1&amp;b=2</url>\n"
        "</pull_request>\n\n"
        "<diff>\n"
        "diff --git a/file.py b/file.py\n"
        "+change\n"
        "</diff>"
    )


def test_pull_request_context_handles_empty_and_none_metadata_fields() -> None:
    ctx = PullRequestContext(
        diff="diff body",
        metadata=PullRequestMetadata(title="", description=None, url=None),
    )

    assert ctx.render() == (
        "<pull_request>\n"
        "<title></title>\n"
        "<description>\n"
        "\n"
        "</description>\n"
        "<url></url>\n"
        "</pull_request>\n\n"
        "<diff>\n"
        "diff body\n"
        "</diff>"
    )
