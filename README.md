# StackedDiffFS

**A horizontal, merge-safe filesystem for AI agents**

StackedDiffFS (StackedFS) solves a common problem when using multiple AI agents with your codebase: how can multiple agents work on the same files without stepping on each other's changes? Instead of requiring agents to coordinate or merge changes manually, StackedDiffFS provides each agent with their own view of your files while keeping the original intact.

## Rationale

When multiple AI agents modify the same files:
- **Merge conflicts** become frequent and tedious
- **Loss of context** occurs when changes overwrite each other
- **Reproducibility** is hard to maintain across agent runs

StackedFS uses an overlay filesystem approach where:
- The **base layer** contains your original files (read-only)
- Each **agent layer** stores modifications specific to that agent
- The **working layer** shows the merged view with agent changes taking precedence
- **Conflict detection** alerts you when modifications diverge from the base

### Example Scenario

Imagine two AI agents working on the same project:

1. **Agent Claude** wants to refactor `utils.py`
2. **Agent Cline** wants to add features to `utils.py`

Without StackedFS:
- Both agents start with the same version
- Claude refactors and saves
- Siri adds features and saves
- One set of changes is lost or they conflict

With StackedFS:
- Claude's changes go to `agents/claude/utils.py`
- Siri's changes go to `agents/siri/utils.py`
- Both can work independently
- Conflicts are detected when both modify the same file

## Features

- **Overlay Filesystem**: View your filesystem with agent-specific modifications layered on top
- **Agent Isolation**: Each agent sees their own modified files while preserving the base layer
- **Conflict Detection**: Automatic detection when modified files differ from the base layer
- **CLI Interface**: Simple commands to manage repositories and agents
- **direnv Integration**: Automatic environment setup for agent workspaces
- **FUSE-based**: Works with any tool that reads files through the mounted filesystem

## Quick Start

### 1. Initialize a Repository

Create a new StackedFS repository:

```bash
stackedfs init ~/my-agent-repo
```

This creates the directory structure:
```
my-agent-repo/
├── base/              # Original files (read-only)
├── agents/            # Agent-specific overlays
├── work/              # Current working directory
└── agents.json        # Agent configuration
```

### 2. Add an Agent

Add an agent to the repository:

```bash
stackedfs agent add claude --repo ~/my-agent-repo
```

### 3. Mount the Filesystem

Mount the StackedFS filesystem:

```bash
# Set the active agent
export AGENT_ID=claude

# Mount the filesystem
stackedfs mount ~/my-agent-repo ~/mount-point
```

### 4. Working with Files

When you write to the mounted filesystem, files go to your agent's overlay:

```bash
# Create a new file (goes to claude's overlay)
echo "new content" > ~/mount-point/newfile.txt

# Modify an existing file (goes to claude's overlay)
echo "modified" > ~/mount-point/basefile.txt
```

### 5. View Status

Check repository status and conflicts:

```bash
stackedfs status ~/my-agent-repo
```

## Installation

### Prerequisites

- Python 3.8+
- FUSE (Linux) or macFUSE (macOS)
- `pyfuse3` package (requires FUSE development libraries)

#### Recommended: Use conda-forge

The easiest way to install is using conda-forge, which provides prebuilt FUSE libraries:

```bash
# Create a new conda environment
conda create -n stackedfs python=3.10
conda activate stackedfs

# Install FUSE dependencies from conda-forge
conda install -c conda-forge fuse3 pyfuse3

# Install StackedFS
pip install -e .
```

#### Manual Installation

If you don't use conda, you'll need to install FUSE development libraries manually:

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get install libfuse3-dev python3-dev
pip install pyfuse3
```

**macOS:**
```bash
brew install macfuse
pip install pyfuse3
```

**Note:** On some systems, you may need to set `PKG_CONFIG_PATH` to help pyfuse3 find fuse3:
```bash
export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:$PKG_CONFIG_PATH"
```

For macOS, install macFUSE:
```bash
brew install macfuse
```

### Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/stackedfs.git
cd stackedfs

# Install dependencies (check/install required FUSE libraries)
./scripts/check-deps.sh    # Check if dependencies are satisfied
# OR
./scripts/install-deps.sh  # Install missing dependencies

# Install stackedfs
pip install -e .

# Verify installation
stackedfs --help
```

## CLI Commands

```bash
# Initialize a repository
stackedfs init <path>                # Create new stackedfs repository

# Mount/unmount filesystem
stackedfs mount <repo> <mount_point> # Mount filesystem at mount point
stackedfs unmount <mount_point>      # Unmount filesystem

# Agent management
stackedfs agent add <name>           # Add a new agent
stackedfs agent list                 # List all agents
stackedfs agent remove <name>        # Remove an agent

# Configuration
stackedfs status <repo>              # Show repository status
stackedfs conflicts <repo>           # Show conflicts
stackedfs direnv <repo>              # Generate direnv configuration
```

For help with any command:
```bash
stackedfs <command> --help
```

## Environment Variables

StackedFS uses the following environment variables:

- `AGENT_ID` - Active agent identifier (must be set before mounting)
- `STACKEDFS_WORKDIR` - Directory containing working files (set by direnv)
- `STACKEDFS_BASE` - Path to base layer (set by direnv)

## Directory Structure

```
 Repository Root
├── base/              # Original files (shared, read-only)
│   ├── file1.txt
│   └── subdir/
│       └── file2.txt
├── agents/            # Agent-specific overlays
│   ├── agent1/        # Agent 1's modifications
│   │   ├── file1.txt  # Modified version
│   │   └── new.txt    # New file
│   └── agent2/        # Agent 2's modifications
│       └── ...
├── work/              # Current working layer
│   └── (symlinks to base or agent files)
└── agents.json        # Agent configuration
```

## Conflict Detection

StackedFS automatically detects when files differ from the base:

```json
{
  "conflicts": [
    {
      "path": "/modified_file.txt",
      "agent": "agent1",
      "timestamp": "2024-01-01T12:00:00Z"
    }
  ]
}
```

## direnv Integration

To automatically set up your environment when entering a repository:

```bash
# Generate direnv configuration
stackedfs direnv ~/my-agent-repo > ~/my-agent-repo/.envrc

# direnv will automatically use this when you cd into the directory
```

Note: The `direnv` command outputs the configuration content to stdout. You need to redirect it to `.envrc` in your repository.

## Testing

StackedFS uses pytest for its test suite. The tests cover repository management, path resolution, file operations, and conflict detection.

### Prerequisites

Before running tests, ensure dependencies are installed:

```bash
# Check dependencies
./scripts/check-deps.sh

# Or install missing dependencies
./scripts/install-deps.sh
```

### Running Tests

```bash
# Install dependencies first
pip install -e . pytest pytest-cov pyfuse3

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=stackedfs --cov-report=html
```

**Note:** Tests require pyfuse3 for FUSE operations. The test suite verifies agent management, conflict detection, and path resolution logic.

### Test Structure

- `tests/conftest.py` - Shared fixtures (e.g., `temp_repo`)
- `tests/test_stackedfs.py` - Unit and integration tests organized by functionality

### Writing Tests

When writing tests for StackedFS:
1. Use the `temp_repo` fixture to get a temporary repository structure
2. Test agent isolation by creating files in different agent layers
3. Verify conflict detection by checking hash comparisons
4. Test FUSE operations through the `StackedFS` class directly

## License

MIT License

## Contributing

We welcome contributions! Here's how to get started:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests: `pytest`
5. Ensure all tests pass
6. Submit a pull request

### Development Setup

For development, you'll need:
- Python 3.8+
- pytest for testing
- pyfuse3 for FUSE operations (requires FUSE development libraries)
- pytest-asyncio for async test support

Install in development mode:
```bash
pip install -e . pytest pytest-cov pytest-asyncio
```

Use the provided scripts to manage dependencies:
```bash
./scripts/check-deps.sh     # Verify dependencies
./scripts/install-deps.sh   # Install missing dependencies
```
