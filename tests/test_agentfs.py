#!/usr/bin/env python3
"""Tests for AgentFS - Linux implementation."""

import os
import sys
import tempfile
import shutil
import json
import subprocess
import time
from pathlib import Path
from threading import Thread
import pytest

sys.path.insert(0, str(Path(__file__).parent))

from agentfs.fuse import AgentFS


class TestAgentFSRepository:
    """Tests for repository initialization and management."""

    def test_init_creates_structure(self):
        """Test that init creates the required directory structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            base_path = repo_path / "base"
            agents_path = repo_path / "agents"
            work_path = repo_path / "work"
            
            base_path.mkdir(parents=True)
            agents_path.mkdir()
            work_path.mkdir()
            
            assert repo_path.exists()
            assert base_path.exists()
            assert agents_path.exists()
            assert work_path.exists()

    def test_load_agents_empty(self):
        """Test loading agents from empty repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            
            fs = AgentFS(str(repo_path))
            agents = fs.agents
            assert agents == []

    def test_save_agents(self):
        """Test saving agents to agents.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            
            fs = AgentFS(str(repo_path))
            fs.agents = ["agent1", "agent2"]
            fs._save_agents()
            
            agents_file = repo_path / "agents.json"
            assert agents_file.exists()
            
            with open(agents_file) as f:
                data = json.load(f)
            
            assert data["agents"] == ["agent1", "agent2"]

    def test_add_agent(self):
        """Test adding an agent to the repository."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            
            fs = AgentFS(str(repo_path))
            fs.agents = ["claude"]
            fs._save_agents()
            
            agent_dir = repo_path / "agents" / "claude"
            agent_dir.mkdir(parents=True)
            
            assert agent_dir.exists()

    def test_add_duplicate_agent(self):
        """Test that adding a duplicate agent is handled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            
            agents_file = repo_path / "agents.json"
            with open(agents_file, 'w') as f:
                json.dump({"agents": ["claude"]}, f)
            
            fs = AgentFS(str(repo_path))
            agents = fs.agents
            assert agents == ["claude"]


class TestAgentFSResolving:
    """Tests for path resolution in overlay filesystem."""

    def test_resolve_empty(self):
        """Test resolving path in empty filesystem."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            fs = AgentFS(str(repo_path))
            
            path, agent = fs._get_resolved_path("/nonexistent")
            assert path is None
            assert agent is None

    def test_resolve_from_base(self):
        """Test resolving path from base layer."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "test.txt"
            test_file.write_text("base content")
            
            fs = AgentFS(str(repo_path))
            
            path, agent = fs._get_resolved_path("/test.txt")
            assert path == test_file
            assert agent == "base"

    def test_resolve_from_agent(self):
        """Test resolving path from agent layer."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            (repo_path / "agents").mkdir()
            
            test_file = base_path / "test.txt"
            test_file.write_text("base content")
            
            agent_path = repo_path / "agents" / "claude"
            agent_path.mkdir()
            agent_file = agent_path / "test.txt"
            agent_file.write_text("agent content")
            
            fs = AgentFS(str(repo_path))
            fs.agents = ["claude"]
            
            path, agent = fs._get_resolved_path("/test.txt")
            assert path == agent_file
            assert agent == "claude"

    def test_resolve_topmost_wins(self):
        """Test that topmost agent layer wins resolution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            
            base_path = repo_path / "base"
            base_path.mkdir()
            (repo_path / "agents").mkdir()
            
            (repo_path / "agents" / "agent1").mkdir(parents=True)
            (repo_path / "agents" / "agent2").mkdir(parents=True)
            
            base_file = base_path / "test.txt"
            base_file.write_text("base")
            
            agent1_file = repo_path / "agents" / "agent1" / "test.txt"
            agent1_file.write_text("agent1")
            
            agent2_file = repo_path / "agents" / "agent2" / "test.txt"
            agent2_file.write_text("agent2")
            
            fs = AgentFS(str(repo_path))
            fs.agents = ["agent1", "agent2"]
            
            path, agent = fs._get_resolved_path("/test.txt")
            assert path == agent2_file
            assert agent == "agent2"

    def test_readdir_base_only(self):
        """Test readdir with only base layer."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            (base_path / "file1.txt").write_text("content1")
            (base_path / "file2.txt").write_text("content2")
            
            fs = AgentFS(str(repo_path))
            
            entries = list(fs.readdir("/", 0))
            assert "file1.txt" in entries
            assert "file2.txt" in entries

    def test_readdir_merged(self):
        """Test readdir with merged layers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            (repo_path / "agents").mkdir()
            
            (base_path / "base_file.txt").write_text("base")
            
            agent_path = repo_path / "agents" / "claude"
            agent_path.mkdir()
            (agent_path / "agent_file.txt").write_text("agent")
            
            fs = AgentFS(str(repo_path))
            fs.agents = ["claude"]
            
            entries = list(fs.readdir("/", 0))
            assert "base_file.txt" in entries
            assert "agent_file.txt" in entries


class TestAgentFSHashing:
    """Tests for file hashing and conflict detection."""

    def test_compute_hash_file(self):
        """Test computing hash of a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("test content")
            
            fs = AgentFS(str(Path(tmpdir).parent))
            hash1 = fs._compute_hash(test_file)
            hash2 = fs._compute_hash(test_file)
            
            assert hash1 is not None
            assert hash1 == hash2

    def test_compute_hash_missing(self):
        """Test computing hash of non-existent file."""
        fs = AgentFS(str(Path(tempfile.mkdtemp())))
        hash_val = fs._compute_hash(Path("/nonexistent"))
        assert hash_val is None

    def test_check_conflict_no_conflict(self):
        """Test conflict check when no conflict exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "test.txt"
            test_file.write_text("original")
            
            fs = AgentFS(str(repo_path))
            
            conflict = fs._check_conflict("/test.txt")
            assert conflict is False

    def test_check_conflict_with_change(self):
        """Test conflict check when file changed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "test.txt"
            test_file.write_text("original")
            
            fs = AgentFS(str(repo_path))
            fs.file_contents = {
                "test.txt": {"hash": "different_hash"}
            }
            
            conflict = fs._check_conflict("/test.txt")
            assert conflict is True


class TestAgentFSOperations:
    """Tests for FUSE operations."""

    def test_getattr_exists(self):
        """Test getattr for existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "test.txt"
            test_file.write_text("content")
            
            fs = AgentFS(str(repo_path))
            attr = fs.getattr("/test.txt")
            
            assert attr is not None
            assert "st_size" in attr
            assert attr["st_size"] == len("content")

    def test_getattr_missing(self):
        """Test getattr for non-existent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            
            fs = AgentFS(str(repo_path))
            
            with pytest.raises(FileNotFoundError):
                fs.getattr("/nonexistent")

    def test_readlink_symlink(self):
        """Test readlink for symlink."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_link = base_path / "link"
            test_link.symlink_to("target")
            
            fs = AgentFS(str(repo_path))
            
            try:
                link_target = fs.readlink("/link")
                assert link_target == "target"
            except ValueError:
                pytest.skip("readlink not implemented for symlinks")

    def test_readlink_not_symlink(self):
        """Test readlink for non-symlink."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "file.txt"
            test_file.write_text("content")
            
            fs = AgentFS(str(repo_path))
            
            with pytest.raises(ValueError):
                fs.readlink("/file.txt")

    def test_lookup_exists(self):
        """Test lookup for existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "test.txt"
            test_file.write_text("content")
            
            fs = AgentFS(str(repo_path))
            result = fs.lookup("/test.txt")
            
            assert result is not None
            assert "st_ino" in result

    def test_lookup_missing(self):
        """Test lookup for non-existent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            
            fs = AgentFS(str(repo_path))
            
            with pytest.raises(FileNotFoundError):
                fs.lookup("/nonexistent")

    def test_open_file(self):
        """Test opening a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "test.txt"
            test_file.write_text("content")
            
            fs = AgentFS(str(repo_path))
            result = fs.open("/test.txt", os.O_RDONLY)
            
            assert result == 0

    def test_read_file(self):
        """Test reading from a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "test.txt"
            test_file.write_text("hello world")
            
            fs = AgentFS(str(repo_path))
            fs.open("/test.txt", os.O_RDONLY)
            data = fs.read("/test.txt", 5, 0, 0)
            
            assert data == b"hello"

    def test_read_with_offset(self):
        """Test reading with offset."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "test.txt"
            test_file.write_text("hello world")
            
            fs = AgentFS(str(repo_path))
            data = fs.read("/test.txt", 5, 6, 0)
            
            assert data == b"world"

    def test_write_file_new(self):
        """Test writing to a new file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            (repo_path / "agents" / "test-agent").mkdir(parents=True)
            
            os.environ["AGENT_ID"] = "test-agent"
            
            fs = AgentFS(str(repo_path))
            
            data = fs.write("/new.txt", b"new content", 0, 0)
            
            assert data == len("new content")
            
            agent_file = repo_path / "agents" / "test-agent" / "new.txt"
            assert agent_file.exists()
            assert agent_file.read_text() == "new content"

    def test_write_file_existing(self):
        """Test writing to existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            (repo_path / "agents" / "test-agent").mkdir(parents=True)
            
            test_file = base_path / "test.txt"
            test_file.write_text("original")
            
            os.environ["AGENT_ID"] = "test-agent"
            
            fs = AgentFS(str(repo_path))
            
            fs.write("/test.txt", b"modified", 0, 0)
            
            agent_file = repo_path / "agents" / "test-agent" / "test.txt"
            assert agent_file.read_text() == "modified"

    def test_write_with_offset(self):
        """Test writing with offset."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            (repo_path / "agents" / "test-agent").mkdir(parents=True)
            
            test_file = base_path / "test.txt"
            test_file.write_text("hello world")
            
            os.environ["AGENT_ID"] = "test-agent"
            
            fs = AgentFS(str(repo_path))
            
            fs.write("/test.txt", b"X", 0, 0)
            
            agent_file = repo_path / "agents" / "test-agent" / "test.txt"
            content = agent_file.read_text()
            assert content.startswith("X")

    def test_create_file(self):
        """Test creating a new file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            (repo_path / "agents" / "test-agent").mkdir(parents=True)
            
            os.environ["AGENT_ID"] = "test-agent"
            
            fs = AgentFS(str(repo_path))
            
            result = fs.create("/created.txt", 0o644)
            
            assert result == 0
            
            agent_file = repo_path / "agents" / "test-agent" / "created.txt"
            assert agent_file.exists()

    def test_unlink_file(self):
        """Test deleting a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            (repo_path / "agents" / "test-agent").mkdir(parents=True)
            
            test_file = base_path / "test.txt"
            test_file.write_text("content")
            
            os.environ["AGENT_ID"] = "test-agent"
            
            fs = AgentFS(str(repo_path))
            
            fs.unlink("/test.txt")
            
            agent_file = repo_path / "agents" / "test-agent" / "test.txt"
            assert not agent_file.exists()

    def test_rename_file(self):
        """Test renaming a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            (repo_path / "agents" / "test-agent").mkdir(parents=True)
            
            os.environ["AGENT_ID"] = "test-agent"
            
            fs = AgentFS(str(repo_path))
            
            test_file = repo_path / "agents" / "test-agent" / "old.txt"
            test_file.write_text("content")
            
            fs.rename("/old.txt", "/new.txt")
            
            assert not test_file.exists()
            new_file = repo_path / "agents" / "test-agent" / "new.txt"
            assert new_file.exists()
            assert new_file.read_text() == "content"

    def test_readdir_directory(self):
        """Test reading directory contents."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            (base_path / "file1.txt").write_text("content1")
            (base_path / "file2.txt").write_text("content2")
            
            fs = AgentFS(str(repo_path))
            entries = list(fs.readdir("/", 0))
            
            assert "file1.txt" in entries
            assert "file2.txt" in entries

    def test_flush_file(self):
        """Test flushing a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "test.txt"
            test_file.write_text("content")
            
            fs = AgentFS(str(repo_path))
            result = fs.flush("/test.txt", 0)
            
            assert result == 0

    def test_release_file(self):
        """Test releasing a file handle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "test.txt"
            test_file.write_text("content")
            
            fs = AgentFS(str(repo_path))
            result = fs.release("/test.txt", 0)
            
            assert result == 0

    def test_statfs(self):
        """Test filesystem statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            
            fs = AgentFS(str(repo_path))
            stats = fs.statfs("/")
            
            assert stats is not None
            assert "f_bsize" in stats
            assert "f_blocks" in stats
            assert "f_bfree" in stats


class TestAgentFSConflictDetection:
    """Tests for conflict detection and resolution."""

    def test_detect_conflict_on_modify(self):
        """Test detecting conflict when file modified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "test.txt"
            test_file.write_text("original")
            
            fs = AgentFS(str(repo_path))
            fs.file_contents = {
                "test.txt": {"hash": "different_hash"}
            }
            
            conflict = fs._check_conflict("/test.txt")
            
            assert conflict is True

    def test_record_conflict(self):
        """Test recording a conflict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            
            fs = AgentFS(str(repo_path))
            
            fs._record_conflict("/test.txt", "test-agent")
            
            assert len(fs.conflicts) == 1
            assert fs.conflicts[0]["path"] == "/test.txt"
            assert fs.conflicts[0]["agent"] == "test-agent"
            assert "timestamp" in fs.conflicts[0]

    def test_conflict_on_rename(self):
        """Test conflict detection during rename."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            
            fs = AgentFS(str(repo_path))
            
            test_file = repo_path / "base" / "old.txt"
            test_file.write_text("content")
            
            fs.file_contents = {
                "old.txt": {"hash": "different_hash"}
            }
            
            try:
                fs.rename("/old.txt", "/new.txt")
            except IOError:
                pass


class TestAgentFSIntegration:
    """Integration tests for AgentFS."""

    def test_full_workflow(self):
        """Test full repository workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            
            from agentfs.fuse import init_repo, add_agent
            
            init_repo(str(repo_path))
            
            assert repo_path.exists()
            assert (repo_path / "base").exists()
            assert (repo_path / "agents").exists()
            assert (repo_path / "work").exists()
            
            add_agent(str(repo_path), "claude")
            
            agents_file = repo_path / "agents.json"
            with open(agents_file) as f:
                data = json.load(f)
            assert "claude" in data["agents"]

    def test_cli_commands(self):
        """Test CLI commands."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            mount_path = Path(tmpdir) / "mount"
            mount_path.mkdir()
            
            from agentfs.cli import main
            
            sys.argv = ["agentfs", "init", str(repo_path)]
            try:
                main()
            except SystemExit:
                pass
            
            assert repo_path.exists()
            
            sys.argv = ["agentfs", "agent", "add", "claude", "--repo", str(repo_path)]
            try:
                main()
            except SystemExit:
                pass


class TestAgentFSDirenv:
    """Tests for direnv integration."""

    def test_generate_direnv(self):
        """Test generating direnv configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            
            work_dir = repo_path / "work"
            work_dir.mkdir()
            
            agents_file = repo_path / "agents.json"
            with open(agents_file, 'w') as f:
                json.dump({"agents": ["claude"]}, f)
            
            from agentfs.fuse import generate_direnv
            import io
            from contextlib import redirect_stdout
            
            f = io.StringIO()
            with redirect_stdout(f):
                generate_direnv(str(repo_path))
            output = f.getvalue()
            
            assert "AGENTFS_WORKDIR" in output
            assert str(work_dir) in output
            assert "AGENT_ID" in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
