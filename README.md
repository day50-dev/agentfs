# AgentFS

AgentFS is a FUSE-based filesystem that provides a unified view of your filesystem with agent-specific overlays. It allows multiple AI agents to work with modified copies of your files without affecting the original, while maintaining visibility into what each agent has changed.

## Features

- **Overlay Filesystem**: View your filesystem with agent-specific modifications layered on top
- **Agent Isolation**: Each agent sees their own modified files while preserving the base layer
- **Conflict Detection**: Automatic detection when modified files differ from the base layer
- **CLI Interface**: Simple commands to manage repositories and agents
- **direnv Integration**: Automatic environment setup for agent workspaces

## Installation

### Requirements

- Python 3.8+
- FUSE (Linux) or macFUSE (macOS)
- `pyfuse3` package

### Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/agentfs.git
cd agentfs

# Install dependencies
pip install -e .
```

## Usage

### Initialize a Repository

Create a new agentfs repository:

```bash
agentfs init ~/my-agent-repo
```

This creates the directory structure:
```
my-agent-repo/
├── base/              # Original files (read-only)
├── agents/            # Agent-specific overlays
├── work/              # Current working directory
└── agents.json        # Agent configuration
```

### Add an Agent

Add an agent to the repository:

```bash
agentfs agent add claude --repo ~/my-agent-repo
```

### Mount the Filesystem

Mount the agentfs filesystem:

```bash
# Start with FUSE
agentfs mount ~/my-agent-repo ~/mount-point

# Or use direnv for automatic setup
agentfs direnv ~/my-agent-repo
```

### Working with Files

When working in the mounted filesystem:

1. **Read operations**: Get the topmost version (agent overlay > base)
2. **Write operations**: Files are written to your active agent's overlay
3. **Conflict detection**: AgentFS tracks which files differ from the base

### View Status

Check repository status and conflicts:

```bash
agentfs status ~/my-agent-repo
```

## CLI Commands

```bash
# Initialize a repository
agentfs init <path>                # Create new agentfs repository

# Mount/unmount filesystem
agentfs mount <repo> <mount点>      # Mount filesystem at mount point
agentfs unmount <mount点>          # Unmount filesystem

# Agent management
agentfs agent add <name>           # Add a new agent
agentfs agent list                 # List all agents
agentfs agent remove <name>        # Remove an agent

# Configuration
agentfs status <repo>              # Show repository status
agentfs direnv <repo>              # Generate direnv configuration
```

## Environment Variables

When mounted, AgentFS sets:

- `AGENTFS_WORKDIR` - Directory containing working files
- `AGENT_ID` - Active agent identifier
- `AGENTFS_BASE` - Path to base layer

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

AgentFS automatically detects when files differ from the base:

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
agentfs direnv ~/my-agent-repo > ~/my-agent-repo/.envrc

# direnv will automatically use this when you cd into the directory
```

## Testing

Run the test suite:

```bash
pytest tests/
```

## License

MIT License

## Contributing

1. Fork the repository
2. Create a feature branch
3. Run tests: `pytest tests/`
4. Submit a pull request
