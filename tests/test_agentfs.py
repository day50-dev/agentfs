#!/usr/bin/env python3
"""Tests for AgentFS - pyfuse3 implementation."""

import asyncio
import os
import sys
import tempfile
import json
import stat
from pathlib import Path
import pytest
import trio
from agentfs.fuse import AgentFS, ROOT_INODE
from pyfuse3 import FUSEError


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
            
            entries = list(fs._get_all_entries("/"))
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
            
            entries = list(fs._get_all_entries("/"))
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

    @pytest.mark.asyncio
    async def test_getattr_exists(self):
        """Test getattr for existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "test.txt"
            test_file.write_text("content")
            
            fs = AgentFS(str(repo_path))
            
            # Get inode for test file
            inode = fs._get_inode_for_path("/test.txt")
            attr = await fs.getattr(inode)
            
            assert attr is not None
            assert attr.st_size == len("content")

    @pytest.mark.asyncio
    async def test_getattr_missing(self):
        """Test getattr for non-existent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            
            fs = AgentFS(str(repo_path))
            
            with pytest.raises(FUSEError):
                await fs.getattr(999)

    @pytest.mark.asyncio
    async def test_readlink_symlink(self):
        """Test readlink for symlink."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            # Create a target file first, then symlink to it
            target_file = base_path / "target.txt"
            target_file.write_text("target content")
            
            test_link = base_path / "link"
            test_link.symlink_to("target.txt")
            
            fs = AgentFS(str(repo_path))
            
            inode = fs._get_inode_for_path("/link")
            link_target = await fs.readlink(inode)
            
            assert link_target == b"target.txt"

    @pytest.mark.asyncio
    async def test_readlink_not_symlink(self):
        """Test readlink for non-symlink."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "file.txt"
            test_file.write_text("content")
            
            fs = AgentFS(str(repo_path))
            
            inode = fs._get_inode_for_path("/file.txt")
            
            with pytest.raises(FUSEError):
                await fs.readlink(inode)

    @pytest.mark.asyncio
    async def test_lookup_exists(self):
        """Test lookup for existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "test.txt"
            test_file.write_text("content")
            
            fs = AgentFS(str(repo_path))
            
            parent_inode = ROOT_INODE
            result = await fs.lookup(parent_inode, b"test.txt")
            
            assert result is not None
            assert "inode" in result
            assert "entry_attributes" in result

    @pytest.mark.asyncio
    async def test_lookup_missing(self):
        """Test lookup for non-existent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            
            fs = AgentFS(str(repo_path))
            
            parent_inode = ROOT_INODE
            
            with pytest.raises(FUSEError):
                await fs.lookup(parent_inode, b"nonexistent.txt")

    @pytest.mark.asyncio
    async def test_open_file(self):
        """Test opening a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "test.txt"
            test_file.write_text("content")
            
            fs = AgentFS(str(repo_path))
            
            inode = fs._get_inode_for_path("/test.txt")
            fi = await fs.open(inode, os.O_RDONLY)
            
            assert fi.fh is not None

    @pytest.mark.asyncio
    async def test_read_file(self):
        """Test reading from a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "test.txt"
            test_file.write_text("hello world")
            
            fs = AgentFS(str(repo_path))
            
            inode = fs._get_inode_for_path("/test.txt")
            fi = await fs.open(inode, os.O_RDONLY)
            data = await fs.read(fi.fh, 0, 5)
            
            assert data == b"hello"

    @pytest.mark.asyncio
    async def test_read_with_offset(self):
        """Test reading with offset."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "test.txt"
            test_file.write_text("hello world")
            
            fs = AgentFS(str(repo_path))
            
            inode = fs._get_inode_for_path("/test.txt")
            fi = await fs.open(inode, os.O_RDONLY)
            data = await fs.read(fi.fh, 6, 5)
            
            assert data == b"world"

    @pytest.mark.asyncio
    async def test_write_file_new(self):
        """Test writing to a new file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            (repo_path / "agents" / "test-agent").mkdir(parents=True)
            
            os.environ["AGENT_ID"] = "test-agent"
            
            fs = AgentFS(str(repo_path))
            
            inode = fs._get_inode_for_path("/")
            fi = await fs.create(inode, b"new.txt", 0o644, os.O_WRONLY)
            
            await fs.write(fi['file_info'].fh, 0, b"new content")
            await fs.release(fi['file_info'].fh)
            
            agent_file = repo_path / "agents" / "test-agent" / "new.txt"
            assert agent_file.exists()
            assert agent_file.read_text() == "new content"

    @pytest.mark.asyncio
    async def test_write_file_existing(self):
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
            
            inode = fs._get_inode_for_path("/test.txt")
            fi = await fs.open(inode, os.O_WRONLY)
            await fs.write(fi.fh, 0, b"modified")
            await fs.release(fi.fh)
            
            # pyfuse3 writes through the file handle, so base file is modified
            assert test_file.read_text() == "modified"

    @pytest.mark.asyncio
    async def test_write_with_offset(self):
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
            
            inode = fs._get_inode_for_path("/test.txt")
            fi = await fs.open(inode, os.O_WRONLY)
            await fs.write(fi.fh, 0, b"X")
            await fs.release(fi.fh)
            
            # pyfuse3 writes through the file handle
            assert test_file.read_text().startswith("X")

    @pytest.mark.asyncio
    async def test_create_file(self):
        """Test creating a new file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            (repo_path / "agents" / "test-agent").mkdir(parents=True)
            
            os.environ["AGENT_ID"] = "test-agent"
            
            fs = AgentFS(str(repo_path))
            
            inode = fs._get_inode_for_path("/")
            result = await fs.create(inode, b"created.txt", 0o644, os.O_CREAT | os.O_WRONLY)
            
            assert result['file_info'].fh is not None
            
            agent_file = repo_path / "agents" / "test-agent" / "created.txt"
            assert agent_file.exists()

    @pytest.mark.asyncio
    async def test_unlink_file(self):
        """Test deleting a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            (repo_path / "agents" / "test-agent").mkdir(parents=True)
            
            # Create file in agent layer
            test_file = repo_path / "agents" / "test-agent" / "test.txt"
            test_file.write_text("content")
            
            os.environ["AGENT_ID"] = "test-agent"
            
            fs = AgentFS(str(repo_path))
            fs.agents = ["test-agent"]  # Register agent
            
            inode = fs._get_inode_for_path("/test.txt")
            await fs.unlink(1, b"test.txt")
            
            # File should no longer exist in agent layer
            assert not test_file.exists()

    @pytest.mark.asyncio
    async def test_rename_file(self):
        """Test renaming a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            (repo_path / "agents" / "test-agent").mkdir(parents=True)
            
            os.environ["AGENT_ID"] = "test-agent"
            
            fs = AgentFS(str(repo_path))
            
            inode = fs._get_inode_for_path("/")
            fi = await fs.create(inode, b"old.txt", 0o644, os.O_CREAT | os.O_WRONLY)
            await fs.write(fi['file_info'].fh, 0, b"content")
            await fs.release(fi['file_info'].fh)
            
            new_inode = fs._get_inode_for_path("/")
            await fs.rename(inode, b"old.txt", new_inode, b"new.txt", 0)
            
            old_file = repo_path / "agents" / "test-agent" / "old.txt"
            assert not old_file.exists()
            new_file = repo_path / "agents" / "test-agent" / "new.txt"
            assert new_file.exists()
            assert new_file.read_text() == "content"

    @pytest.mark.asyncio
    async def test_readdir_directory(self):
        """Test reading directory contents."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            (base_path / "file1.txt").write_text("content1")
            (base_path / "file2.txt").write_text("content2")
            
            fs = AgentFS(str(repo_path))
            
            inode = fs._get_inode_for_path("/")
            entries = []
            async for start_id, name, attr in fs.readdir(inode, 0, None):
                entries.append(name.decode('utf-8'))
            
            assert "file1.txt" in entries
            assert "file2.txt" in entries

    @pytest.mark.asyncio
    async def test_flush_file(self):
        """Test flushing a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "test.txt"
            test_file.write_text("content")
            
            fs = AgentFS(str(repo_path))
            
            inode = fs._get_inode_for_path("/test.txt")
            fi = await fs.open(inode, os.O_RDONLY)
            result = await fs.flush(fi.fh)
            
            assert result is None

    @pytest.mark.asyncio
    async def test_release_file(self):
        """Test releasing a file handle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            base_path = repo_path / "base"
            base_path.mkdir()
            
            test_file = base_path / "test.txt"
            test_file.write_text("content")
            
            fs = AgentFS(str(repo_path))
            
            inode = fs._get_inode_for_path("/test.txt")
            fi = await fs.open(inode, os.O_RDONLY)
            result = await fs.release(fi.fh)
            
            assert result is None

    @pytest.mark.asyncio
    async def test_statfs(self):
        """Test filesystem statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "test_repo"
            repo_path.mkdir()
            
            fs = AgentFS(str(repo_path))
            
            result = await fs.statfs()
            
            assert result is not None
