"""Pytest configuration for AgentFS tests."""

import pytest
import trio


@pytest.fixture
def temp_repo(tmp_path):
    """Create a temporary repository for testing."""
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()
    
    base_path = repo_path / "base"
    base_path.mkdir()
    
    agents_path = repo_path / "agents"
    agents_path.mkdir()
    
    work_path = repo_path / "work"
    work_path.mkdir()
    
    return repo_path


@pytest.fixture
def event_loop():
    """Create a trio event loop for async tests."""
    loop = trio.new_event_loop()
    yield loop
    loop.close()
