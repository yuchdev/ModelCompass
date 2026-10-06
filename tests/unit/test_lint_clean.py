"""Repository-wide lint gate via flakeforge."""

from __future__ import annotations

import pytest
from flakeforge.testing import assert_lint_clean


@pytest.mark.unit
def test_repository_is_lint_clean():
    """[Unit] lint gate: verifies src/ and tests/ carry no flakeforge X-series violations.

    Scenario: Invokes flakeforge's assert_lint_clean over the src and tests trees.
    Boundaries: Runs the real flakeforge checker against the real repository files.
    On failure, first check: the flakeforge violation report for the offending file and rule code.
    """
    assert_lint_clean("src", "tests")
