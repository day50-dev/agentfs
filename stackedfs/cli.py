#!/usr/bin/env python3
"""StackedDiffFS (StackedFS) Command-Line Interface."""

import sys
import argparse
from pathlib import Path

from .fuse import (
    mount, unmount, init_repo, add_agent, get_status, get_conflicts, generate_direnv
)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog='stackedfs',
        description='StackedDiffFS (StackedFS) - A horizontal, merge-safe filesystem for AI agents'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # init command
    init_parser = subparsers.add_parser('init', help='Initialize a new StackedFS repository')
    init_parser.add_argument('path', help='Path to repository directory')
    
    # mount command
    mount_parser = subparsers.add_parser('mount', help='Mount the StackedFS filesystem')
    mount_parser.add_argument('repo', help='Path to repository')
    mount_parser.add_argument('mount_point', help='Mount point')
    mount_parser.add_argument('--foreground', '-f', action='store_true', help='Run in foreground')
    mount_parser.add_argument('--debug', '-d', action='store_true', help='Enable debug output')
    
    # unmount command
    unmount_parser = subparsers.add_parser('unmount', help='Unmount the StackedFS filesystem')
    unmount_parser.add_argument('mount_point', help='Mount point')
    
    # agent add command
    agent_parser = subparsers.add_parser('agent', help='Manage agents')
    agent_subparsers = agent_parser.add_subparsers(dest='agent_command')
    
    agent_add_parser = agent_subparsers.add_parser('add', help='Add a new agent')
    agent_add_parser.add_argument('name', help='Agent name')
    agent_add_parser.add_argument('--repo', '-r', default='.', help='Repository path')
    
    # status command
    status_parser = subparsers.add_parser('status', help='Show repository status')
    status_parser.add_argument('--repo', '-r', default='.', help='Repository path')
    
    # conflicts command
    conflicts_parser = subparsers.add_parser('conflicts', help='Show conflicts')
    conflicts_parser.add_argument('--repo', '-r', default='.', help='Repository path')
    
    # direnv command
    direnv_parser = subparsers.add_parser('direnv', help='Generate direnv configuration')
    direnv_parser.add_argument('--repo', '-r', default='.', help='Repository path')
    direnv_parser.add_argument('--agent', '-a', default=None, help='Agent name')
    
    args = parser.parse_args()
    
    if args.command == 'init':
        init_repo(args.path)
    
    elif args.command == 'mount':
        mount(args.repo, args.mount_point, foreground=args.foreground, debug=args.debug)
    
    elif args.command == 'unmount':
        unmount(args.mount_point)
    
    elif args.command == 'agent':
        if args.agent_command == 'add':
            add_agent(args.repo, args.name)
    
    elif args.command == 'status':
        get_status(args.repo)
    
    elif args.command == 'conflicts':
        get_conflicts(args.repo)
    
    elif args.command == 'direnv':
        generate_direnv(args.repo, args.agent)
    
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
