"""Tests for Research models."""

import pytest

from agentbenchplatform.models.research import Learning, ResearchConfig, SearchResult


class TestResearchConfig:
    def test_create(self):
        rc = ResearchConfig(query="auth patterns", breadth=4, depth=3)
        assert rc.query == "auth patterns"

    def test_empty_query_raises(self):
        with pytest.raises(ValueError, match="query cannot be empty"):
            ResearchConfig(query="")

    def test_invalid_breadth(self):
        with pytest.raises(ValueError, match="breadth must be >= 1"):
            ResearchConfig(query="test", breadth=0)

    def test_invalid_depth(self):
        with pytest.raises(ValueError, match="depth must be >= 1"):
            ResearchConfig(query="test", depth=0)


class TestLearning:
    def test_create(self):
        lr = Learning(content="JWT tokens are stateless", source_url="https://example.com")
        assert lr.content == "JWT tokens are stateless"

    def test_empty_content_raises(self):
        with pytest.raises(ValueError, match="content cannot be empty"):
            Learning(content="")

    def test_invalid_confidence(self):
        with pytest.raises(ValueError, match="Confidence must be"):
            Learning(content="test", confidence=1.5)


class TestSearchResult:
    def test_create(self):
        sr = SearchResult(title="Test", url="https://example.com", content="body")
        assert sr.title == "Test"
