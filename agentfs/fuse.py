#!/usr/bin/env python3
"""AgentFS FUSE Implementation for Linux."""

import os
import sys
import errno
import hashlib
import json
import time
from pathlib import Path
from fuse import FUSE, Operations, LoggingMixIn
from collections import OrderedDict


class AgentFS(LoggingMixIn, Operations):
    """AgentFS - A FUSE-based overlay filesystem for AI agents."""

    def __init__(self, repo_path):
        """Initialize AgentFS with repository path."""
        self.repo_path = Path(repo_path)
        self.base_path = self.repo_path / "base"
        self.agents_dir = self.repo_path / "agents"
        self.work_path = self.repo_path / "work"
        
        self.agents = self._load_agents()
        
        self._ensure_directories()
        
        self._agent_id = os.environ.get('AGENT_ID', 'default')
        
        self.file_contents = {}
        
        self.conflicts = []

    def _ensure_directories(self):
        """Create required directory structure."""
        for path in [self.base_path, self.agents_dir, self.work_path]:
            path.mkdir(parents=True, exist_ok=True)
        
        for agent_name in self.agents:
            agent_path = self.agents_dir / agent_name
            agent_path.mkdir(parents=True, exist_ok=True)

    def _load_agents(self):
        """Load agents from agents.json."""
        agents_file = self.repo_path / "agents.json"
        if agents_file.exists():
            with open(agents_file, 'r') as f:
                data = json.load(f)
                return data.get('agents', [])
        return []

    def _save_agents(self):
        """Save agents to agents.json."""
        agents_file = self.repo_path / "agents.json"
        with open(agents_file, 'w') as f:
            json.dump({'agents': self.agents}, f, indent=2)

    def _get_agent_path(self, agent_name, path):
        """Get the path for an agent's diff layer."""
        return self.agents_dir / agent_name / path.lstrip('/')

    def _get_resolved_path(self, path):
        """Resolve a path to the topmost layer that contains it."""
        path = '/' + path.lstrip('/')
        
        for agent_name in reversed(self.agents):
            agent_path = self._get_agent_path(agent_name, path)
            if agent_path.exists():
                return agent_path, agent_name
        
        base_path = self.base_path / path.lstrip('/')
        if base_path.exists():
            return base_path, 'base'
        
        return None, None

    def _compute_hash(self, path):
        """Compute SHA256 hash of a file."""
        if not path or not path.exists():
            return None
        try:
            with open(path, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except (IOError, OSError):
            return None

    def _check_conflict(self, path, new_content=None):
        """Check if writing to path would cause a conflict."""
        resolved_path, _ = self._get_resolved_path(path)
        current_hash = self._compute_hash(resolved_path)
        
        path_key = path.lstrip('/')
        if path_key in self.file_contents:
            stored_hash = self.file_contents[path_key].get('hash')
            if stored_hash and current_hash and stored_hash != current_hash:
                return True
        
        return False

    def _record_conflict(self, path, agent):
        """Record a conflict."""
        self.conflicts.append({
            'path': path,
            'agent': agent,
            'timestamp': time.time()
        })

    def _get_all_entries(self, path):
        """Get all entries in a directory across all layers."""
        entries = OrderedDict()
        
        for agent_name in reversed(self.agents):
            agent_path = self._get_agent_path(agent_name, path)
            if agent_path.exists() and agent_path.is_dir():
                try:
                    for entry in os.listdir(agent_path):
                        entries[entry] = True
                except OSError:
                    pass
        
        base_path = self.base_path / path.lstrip('/')
        if base_path.exists() and base_path.is_dir():
            try:
                for entry in os.listdir(base_path):
                    entries[entry] = True
            except OSError:
                pass
        
        return list(entries.keys())

    def _get_size(self, path):
        """Get file size from resolved path."""
        resolved_path, _ = self._get_resolved_path(path)
        if resolved_path and resolved_path.exists():
            return resolved_path.stat().st_size
        return 0

    def _get_stat(self, path):
        """Get stat info from resolved path."""
        resolved_path, _ = self._get_resolved_path(path)
        if resolved_path and resolved_path.exists():
            return resolved_path.stat()
        return None

    def getattr(self, path, fh=None):
        """Get file attributes."""
        path = '/' + path.lstrip('/')
        
        stat = self._get_stat(path)
        if stat is None:
            raise FileNotFoundError(errno.ENOENT, path)
        
        return {
            'st_atime': stat.st_atime,
            'st_ctime': stat.st_ctime,
            'st_gid': stat.st_gid,
            'st_mode': stat.st_mode,
            'st_mtime': stat.st_mtime,
            'st_nlink': stat.st_nlink,
            'st_size': stat.st_size,
            'st_uid': stat.st_uid,
        }

    def readlink(self, path):
        """Read symlink."""
        path = '/' + path.lstrip('/')
        resolved_path, _ = self._get_resolved_path(path)
        if resolved_path and resolved_path.is_symlink():
            return os.readlink(resolved_path)
        raise ValueError("Not a symlink")

    def readdir(self, path, fh):
        """List directory contents."""
        path = '/' + path.lstrip('/')
        entries = self._get_all_entries(path)
        for entry in entries:
            yield entry

    def lookup(self, path, fh=None):
        """Look up a file by name."""
        path = '/' + path.lstrip('/')
        resolved_path, _ = self._get_resolved_path(path)
        if resolved_path is None:
            raise FileNotFoundError(errno.ENOENT, path)
        return {'st_ino': 1, 'st_mode': 33188, 'st_nlink': 1}

    def open(self, path, flags):
        """Open a file."""
        path = '/' + path.lstrip('/')
        self._last_opened_path = path
        return 0

    def read(self, path, size, offset, fh):
        """Read from file."""
        path = '/' + path.lstrip('/')
        resolved_path, agent = self._get_resolved_path(path)
        
        if resolved_path is None or not resolved_path.exists():
            raise FileNotFoundError(errno.ENOENT, path)
        
        with open(resolved_path, 'rb') as f:
            f.seek(offset)
            data = f.read(size)
            return data

    def write(self, path, data, offset, fh):
        """Write to file with conflict detection."""
        path = '/' + path.lstrip('/')
        
        if self._check_conflict(path):
            self._record_conflict(path, self._agent_id)
            raise IOError(errno.EBUSY, "Conflict detected")
        
        agent_path = self._get_agent_path(self._agent_id, path)
        agent_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(agent_path, 'r+b') as f:
                f.seek(offset)
                f.write(data)
        except FileNotFoundError:
            with open(agent_path, 'wb') as f:
                f.write(data)
        
        path_key = path.lstrip('/')
        self.file_contents[path_key] = {
            'hash': self._compute_hash(agent_path),
            'agent': self._agent_id
        }
        
        return len(data)

    def create(self, path, mode, fh=None):
        """Create a new file in agent's diff layer."""
        path = '/' + path.lstrip('/')
        
        agent_path = self._get_agent_path(self._agent_id, path)
        agent_path.parent.mkdir(parents=True, exist_ok=True)
        
        agent_path.touch(mode=mode)
        
        path_key = path.lstrip('/')
        self.file_contents[path_key] = {
            'hash': None,
            'agent': self._agent_id
        }
        
        return 0

    def unlink(self, path):
        """Delete a file from agent's diff layer."""
        path = '/' + path.lstrip('/')
        
        resolved_path, _ = self._get_resolved_path(path)
        if resolved_path is None:
            raise FileNotFoundError(errno.ENOENT, path)
        
        agent_path = self._get_agent_path(self._agent_id, path)
        if agent_path.exists():
            agent_path.unlink()
        elif resolved_path == agent_path:
            resolved_path.unlink()
        
        path_key = path.lstrip('/')
        if path_key in self.file_contents:
            del self.file_contents[path_key]

    def rename(self, old, new):
        """Rename a file with conflict checking."""
        old = '/' + old.lstrip('/')
        new = '/' + new.lstrip('/')
        
        if self._check_conflict(old):
            self._record_conflict(old, self._agent_id)
            raise IOError(errno.EBUSY, "Conflict detected")
        
        old_agent_path = self._get_agent_path(self._agent_id, old)
        new_agent_path = self._get_agent_path(self._agent_id, new)
        
        old_resolved, _ = self._get_resolved_path(old)
        if old_resolved and old_resolved != old_agent_path:
            raise IOError(errno.EXDEV, "Cannot rename files outside agent layer")
        
        if old_agent_path.exists():
            old_agent_path.rename(new_agent_path)
            
            old_key = old.lstrip('/')
            new_key = new.lstrip('/')
            if old_key in self.file_contents:
                self.file_contents[new_key] = self.file_contents[old_key]
                del self.file_contents[old_key]

    def flush(self, path, fh):
        """Flush file changes."""
        return 0

    def release(self, path, fh):
        """Release file handle."""
        return 0

    def statfs(self, path):
        """Get filesystem statistics."""
        stat = os.statvfs(self.repo_path)
        return {
            'f_bsize': stat.f_bsize,
            'f_blocks': stat.f_blocks,
            'f_bfree': stat.f_bfree,
            'f_bavail': stat.f_bavail,
            'f_files': stat.f_files,
            'f_ffree': stat.f_ffree,
            'f_namemax': stat.f_namemax,
        }


def mount(repo_path, mount_path, foreground=False, debug=False):
    """Mount the AgentFS filesystem."""
    fs = AgentFS(repo_path)
    FUSE(
        fs,
        mount_path,
        foreground=foreground,
        debug=debug,
        nothreads=True
    )


def unmount(mount_path):
    """Unmount the AgentFS filesystem."""
    import subprocess
    subprocess.run(['fusermount', '-u', mount_path], check=True)


def init_repo(repo_path):
    """Initialize a new AgentFS repository."""
    repo = Path(repo_path)
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "base").mkdir(exist_ok=True)
    (repo / "agents").mkdir(exist_ok=True)
    (repo / "work").mkdir(exist_ok=True)
    (repo / "agents.json").write_text(json.dumps({'agents': []}, indent=2))
    print(f"Initialized AgentFS repository at {repo_path}")


def add_agent(repo_path, agent_name):
    """Add a new agent to the repository."""
    repo = Path(repo_path)
    agents_file = repo / "agents.json"
    
    with open(agents_file, 'r') as f:
        data = json.load(f)
    
    if agent_name in data['agents']:
        print(f"Agent '{agent_name}' already exists")
        return
    
    data['agents'].append(agent_name)
    
    with open(agents_file, 'w') as f:
        json.dump(data, f, indent=2)
    
    agent_dir = repo / "agents" / agent_name
    agent_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Added agent '{agent_name}'")


def get_status(repo_path):
    """Get repository status."""
    repo = Path(repo_path)
    agents_file = repo / "agents.json"
    
    print(f"Repository: {repo_path}")
    
    if agents_file.exists():
        with open(agents_file, 'r') as f:
            data = json.load(f)
        print(f"Agents: {', '.join(data.get('agents', []))}")
    
    base_size = sum(f.stat().st_size for f in (repo / "base").rglob('*') if f.is_file()) if (repo / "base").exists() else 0
    print(f"Base layer size: {base_size} bytes")


def get_conflicts(repo_path):
    """Get conflicts from the repository."""
    repo = Path(repo_path)
    conflicts_file = repo / "conflicts.json"
    
    if conflicts_file.exists():
        with open(conflicts_file, 'r') as f:
            conflicts = json.load(f)
        print("Conflicts:")
        for c in conflicts:
            print(f"  - {c['path']} (agent: {c['agent']})")
    else:
        print("No conflicts")


def generate_direnv(repo_path, agent_name=None):
    """Generate direnv configuration."""
    repo = Path(repo_path)
    
    if agent_name is None:
        agents_file = repo / "agents.json"
        if agents_file.exists():
            with open(agents_file, 'r') as f:
                data = json.load(f)
                if data.get('agents'):
                    agent_name = data['agents'][0]
    
    work_dir = repo / "work"
    
    print("Generated .envrc content:")
    print(f"export AGENTFS_WORKDIR={work_dir}")
    if agent_name:
        print(f"export AGENT_ID={agent_name}")
