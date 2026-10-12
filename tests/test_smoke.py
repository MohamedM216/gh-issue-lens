from gh_issue_lens import __version__
from gh_issue_lens.core import get_graphql_query


def test_version_exists():
    assert __version__
    assert isinstance(__version__, str)


def test_graphql_query_contains_expected_fields():
    query = get_graphql_query()

    assert "repository" in query
    assert "issues" in query
    assert "pageInfo" in query
    assert "hasNextPage" in query
    assert "endCursor" in query
