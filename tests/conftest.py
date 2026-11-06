"""Opt-in validated model transport; no real providers in worker tests."""

from collections.abc import Iterator
from unittest.mock import patch

import httpx
import pytest

from digest.llm.client import Client
from digest.llm.router import Router
from tests.fixtures.llm import fake_response


@pytest.fixture
def valid_llm(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DIGEST_FIXTURE_UNUSED_KEY", "synthetic-key")
    client = Client(transport=httpx.MockTransport(fake_response))
    original = Router.__init__

    def setup(self, *args, **kwargs):
        original(self, *args, **kwargs, client=client)

    with patch.object(Router, "__init__", setup):
        yield
