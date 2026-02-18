#!/usr/bin/env python3
"""StackedDiffFS (StackedFS) FUSE Implementation using pyfuse3."""

import os
import sys
import errno
import hashlib
import json
import time
import stat
from pathlib import Path
from collections import OrderedDict
from pyfuse3 import Operations, EntryAttributes, FileInfo, ROOT_INODE, FUSEError, StatvfsData
from pyfuse3 import init as pyfuse3_init, main as pyfuse3_main, close as pyfuse3_close
import trio


class StackedFS(Operations):
    """StackedDiffFS (StackedFS) - A FUSE-based overlay filesystem for AI agents using pyfuse3."""

    def __init__(self, repo_path):
        """Initialize StackedFS with repository path."""
        self.repo_path = Path(repo_path)
        self.base_path = self.repo_path / "base"
        self.agents_dir = self.repo_path / "agents"
        self.work_path = self.repo_path / "work"
        
        self.agents = self._load_agents()
        self._ensure_directories()
        
        self._agent_id = os.environ.get('AGENT_ID', 'default')
        
        # Inode management - start at ROOT_INODE (1) for '/'
        self._inode_counter = ROOT_INODE
        self._path_to_inode = {}
        self._inode_to_path = {}
        
        # File handle management - store (file_obj, path) tuples
        self._fh_counter = 0
        self._open_files = {}
        
        # File contents for conflict detection
        self.file_contents = {}
        
        # Conflicts list
        self.conflicts = []
        
        # Initialize root inode
        self._path_to_inode["/"] = ROOT_INODE
        self._inode_to_path[ROOT_INODE] = "/"

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

    def _add_path_to_inode_map(self, path, file_path):
        """Add a path-to-inode mapping."""
        if path not in self._path_to_inode:
            self._inode_counter += 1
            inode = self._inode_counter
            self._path_to_inode[path] = inode
            self._inode_to_path[inode] = path
            return inode
        return self._path_to_inode[path]

    def _get_inode_for_path(self, path):
        """Get inode for a path, creating mapping if needed."""
        path = path.rstrip('/') or '/'
        if path in self._path_to_inode:
            return self._path_to_inode[path]
        
        resolved_path, _ = self._get_resolved_path(path)
        if resolved_path and resolved_path.exists():
            return self._add_path_to_inode_map(path, resolved_path)
        
        # Check if file exists in agent layer (even if not resolved)
        agent_path = self.agents_dir / self._agent_id / path.lstrip('/')
        if agent_path.exists():
            return self._add_path_to_inode_map(path, agent_path)
        
        return None

    def _get_path_for_inode(self, inode):
        """Get path for an inode."""
        return self._inode_to_path.get(inode)

    def _get_resolved_path(self, path):
        """Resolve a path to the topmost layer that contains it."""
        path = '/' + path.lstrip('/')
        
        for agent_name in reversed(self.agents):
            agent_path = self.agents_dir / agent_name / path.lstrip('/')
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
            agent_path = self.agents_dir / agent_name / path.lstrip('/')
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

    def _get_file_stat(self, file_path):
        """Get stat info for a file path."""
        if not file_path or not file_path.exists():
            return None
        file_stat = file_path.stat()
        
        attr = EntryAttributes()
        attr.st_mode = file_stat.st_mode
        attr.st_nlink = file_stat.st_nlink
        attr.st_uid = file_stat.st_uid
        attr.st_gid = file_stat.st_gid
        attr.st_size = file_stat.st_size
        attr.st_atime_ns = int(file_stat.st_atime * 1e9)
        attr.st_mtime_ns = int(file_stat.st_mtime * 1e9)
        attr.st_ctime_ns = int(file_stat.st_ctime * 1e9)
        attr.st_blksize = 512
        attr.st_blocks = (file_stat.st_size + 511) // 512
        
        return attr

    async def init(self):
        """Initialize filesystem."""
        pass

    async def destroy(self):
        """Cleanup on filesystem destruction."""
        for fh, (file_obj, path) in self._open_files.items():
            try:
                file_obj.close()
            except:
                pass
        self._open_files.clear()

    async def getattr(self, inode, ctx=None):
        """Get file attributes."""
        path = self._get_path_for_inode(inode)
        if path is None:
            raise FUSEError(errno.ENOENT)
        
        resolved_path, _ = self._get_resolved_path(path)
        if resolved_path is None or not resolved_path.exists():
            raise FUSEError(errno.ENOENT)
        
        attr = self._get_file_stat(resolved_path)
        if attr is None:
            raise FUSEError(errno.ENOENT)
        
        return attr

    async def lookup(self, parent_inode, name, ctx=None):
        """Look up a file by name."""
        parent_path = self._get_path_for_inode(parent_inode)
        if parent_path is None:
            raise FUSEError(errno.ENOENT)
        
        child_name = name.decode('utf-8')
        if child_name == '.':
            inode = parent_inode
            child_path = parent_path
        elif child_name == '..':
            if parent_path == '/':
                inode = parent_inode
                child_path = parent_path
            else:
                parent_parts = parent_path.rstrip('/').split('/')
                if len(parent_parts) > 1:
                    child_path = '/'.join(parent_parts[:-1]) or '/'
                else:
                    child_path = '/'
                inode = self._get_inode_for_path(child_path)
                if inode is None:
                    inode = self._add_path_to_inode_map(child_path, self.base_path)
        else:
            child_path = (parent_path.rstrip('/') + '/' + child_name) if parent_path != '/' else '/' + child_name
            inode = self._get_inode_for_path(child_path)
            if inode is None:
                raise FUSEError(errno.ENOENT)
        
        attr = await self.getattr(inode, ctx)
        return {'entry_attributes': attr, 'inode': inode}

    async def opendir(self, inode, ctx=None):
        """Open a directory."""
        path = self._get_path_for_inode(inode)
        if path is None:
            raise FUSEError(errno.ENOENT)
        
        return inode

    async def readdir(self, fh, start_id, token):
        """Read directory entries."""
        path = self._get_path_for_inode(fh)
        if path is None:
            raise FUSEError(errno.ENOENT)
        
        entries = self._get_all_entries(path)
        
        for i, entry in enumerate(entries, start=1):
            if i < start_id:
                continue
            
            attr = EntryAttributes()
            entry_path = (path.rstrip('/') + '/' + entry) if path != '/' else '/' + entry
            resolved_path, _ = self._get_resolved_path(entry_path)
            
            if resolved_path and resolved_path.is_dir():
                attr.st_mode = stat.S_IFDIR | 0o755
                attr.st_nlink = 2
                attr.st_size = 4096
            else:
                attr.st_mode = stat.S_IFREG | 0o644
                attr.st_nlink = 1
                if resolved_path and resolved_path.exists():
                    attr.st_size = resolved_path.stat().st_size
                else:
                    attr.st_size = 0
            
            attr.st_ino = i
            attr.st_uid = os.getuid()
            attr.st_gid = os.getgid()
            attr.st_atime_ns = int(time.time() * 1e9)
            attr.st_mtime_ns = int(time.time() * 1e9)
            attr.st_ctime_ns = int(time.time() * 1e9)
            
            yield (i, entry.encode('utf-8'), attr)

    async def open(self, inode, flags, ctx=None):
        """Open a file."""
        path = self._get_path_for_inode(inode)
        if path is None:
            raise FUSEError(errno.ENOENT)
        
        resolved_path, _ = self._get_resolved_path(path)
        if resolved_path is None or not resolved_path.exists():
            raise FUSEError(errno.ENOENT)
        
        self._fh_counter += 1
        fh = self._fh_counter
        
        if flags & os.O_WRONLY or flags & os.O_RDWR:
            file_obj = open(resolved_path, 'r+b')
        else:
            file_obj = open(resolved_path, 'rb')
        
        self._open_files[fh] = (file_obj, path)
        
        fi = FileInfo()
        fi.fh = fh
        return fi

    async def read(self, fh, off, size):
        """Read from file."""
        if fh not in self._open_files:
            raise FUSEError(errno.EBADF)
        
        file_obj, path = self._open_files[fh]
        file_obj.seek(off)
        data = file_obj.read(size)
        return data

    async def write(self, fh, off, buf):
        """Write to file with conflict detection."""
        if fh not in self._open_files:
            raise FUSEError(errno.ENOENT)
        
        file_obj, path = self._open_files[fh]
        
        if self._check_conflict(path):
            self._record_conflict(path, self._agent_id)
            raise FUSEError(errno.EBUSY)
        
        agent_path = self.agents_dir / self._agent_id / path.lstrip('/')
        agent_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_obj.seek(off)
        file_obj.write(buf)
        
        path_key = path.lstrip('/')
        self.file_contents[path_key] = {
            'hash': self._compute_hash(agent_path),
            'agent': self._agent_id
        }
        
        return len(buf)

    async def release(self, fh):
        """Release file handle."""
        if fh in self._open_files:
            try:
                self._open_files[fh][0].close()
            except:
                pass
            del self._open_files[fh]
        return None

    async def releasedir(self, fh):
        """Release directory handle."""
        return None

    async def unlink(self, parent_inode, name, ctx=None):
        """Delete a file."""
        parent_path = self._get_path_for_inode(parent_inode)
        if parent_path is None:
            raise FUSEError(errno.ENOENT)
        
        file_name = name.decode('utf-8')
        file_path = (parent_path.rstrip('/') + '/' + file_name) if parent_path != '/' else '/' + file_name
        
        resolved_path, _ = self._get_resolved_path(file_path)
        if resolved_path is None:
            raise FUSEError(errno.ENOENT)
        
        agent_path = self.agents_dir / self._agent_id / file_path.lstrip('/')
        if agent_path.exists():
            agent_path.unlink()
        else:
            resolved_path.unlink()
        
        if file_path in self._path_to_inode:
            inode = self._path_to_inode[file_path]
            del self._path_to_inode[file_path]
            del self._inode_to_path[inode]
        
        path_key = file_path.lstrip('/')
        if path_key in self.file_contents:
            del self.file_contents[path_key]
        
        return None

    async def rename(self, parent_inode_old, name_old, parent_inode_new, name_new, flags, ctx=None):
        """Rename a file."""
        old_parent_path = self._get_path_for_inode(parent_inode_old)
        new_parent_path = self._get_path_for_inode(parent_inode_new)
        
        if old_parent_path is None or new_parent_path is None:
            raise FUSEError(errno.ENOENT)
        
        old_name = name_old.decode('utf-8')
        new_name = name_new.decode('utf-8')
        
        old_path = (old_parent_path.rstrip('/') + '/' + old_name) if old_parent_path != '/' else '/' + old_name
        new_path = (new_parent_path.rstrip('/') + '/' + new_name) if new_parent_path != '/' else '/' + new_name
        
        if self._check_conflict(old_path):
            self._record_conflict(old_path, self._agent_id)
            raise FUSEError(errno.EBUSY)
        
        old_agent_path = self.agents_dir / self._agent_id / old_path.lstrip('/')
        new_agent_path = self.agents_dir / self._agent_id / new_path.lstrip('/')
        
        old_resolved, _ = self._get_resolved_path(old_path)
        if old_resolved and old_resolved != old_agent_path:
            raise FUSEError(errno.EXDEV)
        
        if old_agent_path.exists():
            old_agent_path.rename(new_agent_path)
            
            if old_path in self._path_to_inode:
                inode = self._path_to_inode[old_path]
                del self._path_to_inode[old_path]
                self._inode_to_path[inode] = new_path
                self._path_to_inode[new_path] = inode
            
            old_key = old_path.lstrip('/')
            new_key = new_path.lstrip('/')
            if old_key in self.file_contents:
                self.file_contents[new_key] = self.file_contents[old_key]
                del self.file_contents[old_key]
        
        return None

    async def mkdir(self, parent_inode, name, mode, ctx=None):
        """Create a directory."""
        parent_path = self._get_path_for_inode(parent_inode)
        if parent_path is None:
            raise FUSEError(errno.ENOENT)
        
        dir_name = name.decode('utf-8')
        dir_path = (parent_path.rstrip('/') + '/' + dir_name) if parent_path != '/' else '/' + dir_name
        
        agent_dir = self.agents_dir / self._agent_id / dir_path.lstrip('/')
        agent_dir.mkdir(parents=True, exist_ok=True)
        
        inode = self._add_path_to_inode_map(dir_path, agent_dir)
        
        attr = EntryAttributes()
        attr.st_mode = mode | stat.S_IFDIR
        attr.st_nlink = 2
        attr.st_size = 4096
        
        return {'entry_attributes': attr, 'inode': inode}

    async def rmdir(self, parent_inode, name, ctx=None):
        """Remove a directory."""
        parent_path = self._get_path_for_inode(parent_inode)
        if parent_path is None:
            raise FUSEError(errno.ENOENT)
        
        dir_name = name.decode('utf-8')
        dir_path = (parent_path.rstrip('/') + '/' + dir_name) if parent_path != '/' else '/' + dir_name
        
        agent_dir = self.agents_dir / self._agent_id / dir_path.lstrip('/')
        if agent_dir.exists():
            agent_dir.rmdir()
        
        if dir_path in self._path_to_inode:
            inode = self._path_to_inode[dir_path]
            del self._path_to_inode[dir_path]
            del self._inode_to_path[inode]
        
        return None

    async def symlink(self, parent_inode, name, target, ctx=None):
        """Create a symbolic link."""
        parent_path = self._get_path_for_inode(parent_inode)
        if parent_path is None:
            raise FUSEError(errno.ENOENT)
        
        link_name = name.decode('utf-8')
        link_path = (parent_path.rstrip('/') + '/' + link_name) if parent_path != '/' else '/' + link_name
        
        agent_link = self.agents_dir / self._agent_id / link_path.lstrip('/')
        agent_link.symlink_to(target.decode('utf-8'))
        
        inode = self._add_path_to_inode_map(link_path, agent_link)
        
        attr = EntryAttributes()
        attr.st_mode = stat.S_IFLNK | 0o777
        attr.st_nlink = 1
        attr.st_size = len(target)
        
        return {'entry_attributes': attr, 'inode': inode}

    async def readlink(self, inode, ctx=None):
        """Read a symbolic link."""
        path = self._get_path_for_inode(inode)
        if path is None:
            raise FUSEError(errno.ENOENT)
        
        resolved_path, _ = self._get_resolved_path(path)
        if resolved_path is None or not resolved_path.is_symlink():
            raise FUSEError(errno.EINVAL)
        
        target = os.readlink(resolved_path)
        return target.encode('utf-8')

    async def statfs(self, ctx=None):
        """Get filesystem statistics."""
        stat = os.statvfs(self.repo_path)
        
        fs_stats = StatvfsData()
        fs_stats.f_bsize = stat.f_bsize
        fs_stats.f_frsize = stat.f_frsize
        fs_stats.f_blocks = stat.f_blocks
        fs_stats.f_bfree = stat.f_bfree
        fs_stats.f_bavail = stat.f_bavail
        fs_stats.f_files = stat.f_files
        fs_stats.f_ffree = stat.f_ffree
        fs_stats.f_namemax = stat.f_namemax
        
        return fs_stats

    async def flush(self, fh):
        """Flush file changes."""
        if fh in self._open_files:
            self._open_files[fh][0].flush()
        return None

    async def fsync(self, fh, datasync):
        """Synchronize file changes."""
        if fh in self._open_files:
            self._open_files[fh][0].sync()
        return None

    async def fsyncdir(self, fh, datasync):
        """Synchronize directory changes."""
        return None

    async def create(self, parent_inode, name, mode, flags, ctx=None):
        """Create a new file."""
        parent_path = self._get_path_for_inode(parent_inode)
        if parent_path is None:
            raise FUSEError(errno.ENOENT)
        
        file_name = name.decode('utf-8')
        file_path = (parent_path.rstrip('/') + '/' + file_name) if parent_path != '/' else '/' + file_name
        
        agent_file = self.agents_dir / self._agent_id / file_path.lstrip('/')
        agent_file.parent.mkdir(parents=True, exist_ok=True)
        
        file_obj = open(agent_file, 'w+b')
        
        self._fh_counter += 1
        fh = self._fh_counter
        self._open_files[fh] = (file_obj, file_path)
        
        inode = self._add_path_to_inode_map(file_path, agent_file)
        
        self.file_contents[file_path.lstrip('/')] = {
            'hash': None,
            'agent': self._agent_id
        }
        
        fi = FileInfo()
        fi.fh = fh
        fi.direct_io = True
        
        attr = EntryAttributes()
        attr.st_mode = mode
        attr.st_nlink = 1
        attr.st_size = 0
        
        return {'entry_attributes': attr, 'inode': inode, 'file_info': fi}

    async def setxattr(self, inode, name, value, ctx=None):
        """Set extended attribute."""
        raise FUSEError(errno.ENOTSUP)

    async def getxattr(self, inode, name, ctx=None):
        """Get extended attribute."""
        raise FUSEError(errno.ENOATTR)

    async def listxattr(self, inode, ctx=None):
        """List extended attributes."""
        return []

    async def removexattr(self, inode, name, ctx=None):
        """Remove extended attribute."""
        raise FUSEError(errno.ENOTSUP)


def mount(repo_path, mount_path, foreground=False, debug=False):
    """Mount the StackedFS filesystem."""
    fs = StackedFS(repo_path)
    pyfuse3_init(fs, mount_path, pyfuse3.default_options)
    try:
        if foreground:
            pyfuse3_main(max_tasks=1)
        else:
            pyfuse3_main(max_tasks=1)
    finally:
        pyfuse3_close(unmount=True)


def unmount(mount_path):
    """Unmount the StackedFS filesystem."""
    import subprocess
    subprocess.run(['fusermount', '-u', mount_path], check=True)


def init_repo(repo_path):
    """Initialize a new StackedFS repository."""
    repo = Path(repo_path)
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "base").mkdir(exist_ok=True)
    (repo / "agents").mkdir(exist_ok=True)
    (repo / "work").mkdir(exist_ok=True)
    (repo / "agents.json").write_text(json.dumps({'agents': []}, indent=2))
    print(f"Initialized StackedFS repository at {repo_path}")


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
    print(f"export STACKEDFS_WORKDIR={work_dir}")
    if agent_name:
        print(f"export AGENT_ID={agent_name}")
