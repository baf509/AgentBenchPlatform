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


async def merge_branch(workspace_path: str, branch_name: str) -> str:
    """Merge a branch into the current branch at workspace_path.

    Runs ``git merge <branch_name> --no-edit``.  On conflict the merge is
    automatically aborted so the workspace stays clean.  Returns the merge
    output on success or an error description on failure.
    """
    proc = await asyncio.create_subprocess_exec(
        "git", "merge", branch_name, "--no-edit",
        cwd=workspace_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        # Auto-abort to leave workspace clean
        abort = await asyncio.create_subprocess_exec(
            "git", "merge", "--abort",
            cwd=workspace_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await abort.communicate()
        error_msg = stderr.decode(errors="replace").strip()
        logger.warning("git merge %s failed in %s: %s", branch_name, workspace_path, error_msg)
        raise RuntimeError(f"Merge failed (auto-aborted): {error_msg}")

    result = stdout.decode(errors="replace").strip()
    logger.info("Merged branch %s into %s", branch_name, workspace_path)
    return result


async def get_branch_changed_files(worktree_path: str) -> list[str]:
    """Get list of files changed in the current branch vs its merge base with HEAD."""
    # Find the merge base
    proc = await asyncio.create_subprocess_exec(
        "git", "diff", "--name-only", "HEAD",
        cwd=worktree_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    files = [f for f in stdout.decode(errors="replace").strip().splitlines() if f]
    return files


async def get_head_sha(path: str) -> str:
    """Get the HEAD commit SHA."""
    proc = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "HEAD",
        cwd=path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    sha = stdout.decode().strip()
    if proc.returncode != 0 or not sha:
        raise RuntimeError("Could not get HEAD SHA")
    return sha


async def revert_merge(workspace_path: str, merge_sha: str) -> str:
    """Revert a merge commit. Returns the revert commit SHA."""
    proc = await asyncio.create_subprocess_exec(
        "git", "revert", "--no-edit", "-m", "1", merge_sha,
        cwd=workspace_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode(errors="replace").strip()
        raise RuntimeError(f"git revert failed: {error_msg}")

    revert_sha = await get_head_sha(workspace_path)
    logger.info("Reverted merge %s -> %s in %s", merge_sha, revert_sha, workspace_path)
    return revert_sha


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
