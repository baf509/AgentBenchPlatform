"""Git worktree operations for session isolation."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def is_git_repo(path: str) -> bool:
    """Check if a path is inside a git work tree."""
    proc = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "--is-inside-work-tree",
        cwd=path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode == 0 and stdout.strip() == b"true"


async def create_worktree(
    workspace_path: str, session_short_id: str, branch_name: str
) -> str:
    """Create a git worktree for a session.

    Places worktrees in a sibling directory: ``<repo>-worktrees/<session_short_id>/``.
    Returns the absolute path of the new worktree.
    """
    repo = Path(workspace_path).resolve()
    worktree_dir = repo.parent / f"{repo.name}-worktrees" / session_short_id
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        "git", "worktree", "add", "-b", branch_name, str(worktree_dir),
        cwd=str(repo),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(
            f"git worktree add failed (rc={proc.returncode}): {stderr.decode().strip()}"
        )

    logger.info("Created worktree %s on branch %s", worktree_dir, branch_name)
    return str(worktree_dir)


async def get_diff(worktree_path: str) -> str:
    """Get git diff (staged + unstaged) in a worktree."""
    proc = await asyncio.create_subprocess_exec(
        "git", "diff", "HEAD",
        cwd=worktree_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    text = stdout.decode(errors="replace")
    return text[:10_000]


async def get_log(worktree_path: str, max_commits: int = 10) -> str:
    """Get recent git log from a worktree."""
    proc = await asyncio.create_subprocess_exec(
        "git", "log", "--oneline", f"-{max_commits}",
        cwd=worktree_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode(errors="replace").strip()


async def remove_worktree(workspace_path: str, worktree_path: str) -> bool:
    """Remove a git worktree. Returns True on success."""
    if not worktree_path:
        return False

    proc = await asyncio.create_subprocess_exec(
        "git", "worktree", "remove", "--force", worktree_path,
        cwd=workspace_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.warning(
            "git worktree remove failed (rc=%d): %s",
            proc.returncode, stderr.decode().strip(),
        )
        return False

    logger.info("Removed worktree %s", worktree_path)
    return True
