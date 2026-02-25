"""Session review, reporting, and event tool handlers."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from agentbenchplatform.models.agent_event import AgentEventType
from agentbenchplatform.models.provider import LLMConfig, LLMMessage
from agentbenchplatform.models.session_report import DiffStats, SessionReport, TestResults
from agentbenchplatform.models.task import TaskStatus
from agentbenchplatform.services.coordinator_tools.context import ToolContext

logger = logging.getLogger(__name__)

# Agent tier ordering for escalation
_AGENT_TIERS = {"opencode_local": 0, "opencode": 1, "claude_code": 2}
_TIER_ORDER = ["opencode_local", "opencode", "claude_code"]


async def handle_review_session(ctx: ToolContext, arguments: dict) -> Any:
    """Generate a comprehensive session review with diff, tests, and AI summary."""
    session_id = arguments["session_id"]
    session = await ctx.session.get_session(session_id)
    if not session:
        return {"error": "Session not found"}

    # 1. Get diff stats via git diff --numstat (reliable)
    diff_stats, files_changed = await _get_diff_stats(ctx, session_id)

    # 2. Get unified diff for AI summary context
    try:
        diff = await ctx.session.get_session_diff(session_id)
    except Exception:
        diff = ""

    # 3. Run tests if command provided
    test_results = None
    test_output = ""
    if test_cmd := arguments.get("test_command"):
        try:
            test_output = await ctx.session.run_in_worktree(session_id, test_cmd)
            test_results = parse_test_results(test_output)
        except Exception as e:
            test_output = str(e)
            test_results = TestResults(errors=1, output_snippet=test_output[:500])

    # 4. Run lint if command provided
    lint_output = ""
    if lint_cmd := arguments.get("lint_command"):
        try:
            lint_output = await ctx.session.run_in_worktree(session_id, lint_cmd)
        except Exception as e:
            lint_output = str(e)

    # 5. Generate AI summary
    summary = ""
    try:
        summary_input = f"Diff stats: {diff_stats.insertions}+ {diff_stats.deletions}- across {diff_stats.files} files"
        if test_results:
            summary_input += f"\nTests: {test_results.passed} passed, {test_results.failed} failed, {test_results.errors} errors"
        if lint_output:
            summary_input += f"\nLint output: {lint_output[:300]}"
        if diff:
            summary_input += f"\nDiff preview:\n{diff[:1000]}"

        summary_config = LLMConfig(
            model=ctx.llm_config.model,
            max_tokens=200,
            temperature=0.3,
        )
        resp = await ctx.provider.complete(
            [
                LLMMessage(role="system", content="Summarize this session's work in 2 sentences. Focus on what was changed and whether it looks correct."),
                LLMMessage(role="user", content=summary_input),
            ],
            summary_config,
        )
        summary = resp.content
    except Exception:
        summary = f"Changed {diff_stats.files} files ({diff_stats.insertions}+ {diff_stats.deletions}-)"

    # 6. Determine status
    if test_results and test_results.failed > 0:
        status = "failed"
    elif test_results and test_results.errors > 0:
        status = "failed"
    elif diff_stats.files == 0:
        status = "partial"
    else:
        status = "success"

    # 7. Store report
    report = SessionReport(
        session_id=session_id,
        task_id=session.task_id,
        agent=session.agent_backend,
        status=status,
        summary=summary,
        files_changed=files_changed,
        test_results=test_results,
        diff_stats=diff_stats,
        agent_notes=lint_output[:500] if lint_output else "",
    )
    if ctx.session_report_repo:
        try:
            report = await ctx.session_report_repo.insert(report)
        except Exception:
            logger.warning("Failed to store session report", exc_info=True)

    await _record_session_metric(ctx, session, status)

    result: dict[str, Any] = {
        "session_id": session_id,
        "status": status,
        "summary": summary,
        "files_changed": list(files_changed),
        "diff_stats": diff_stats.to_doc(),
    }
    if test_results:
        result["test_results"] = test_results.to_doc()

    # 8. Auto-escalation if failed and agent is junior/mid
    if status == "failed" and session.agent_backend in ("opencode_local", "opencode"):
        escalation = await _auto_escalate(ctx, session, summary)
        if escalation:
            result["escalation"] = escalation

    # 9. Auto-unblock: check if downstream tasks are now unblocked
    if status == "success":
        unblocked = await _check_auto_unblock(ctx, session.task_id)
        if unblocked:
            result["unblocked_tasks"] = unblocked

    return result


async def handle_get_session_report(ctx: ToolContext, arguments: dict) -> Any:
    if not ctx.session_report_repo:
        return {"error": "Session report repo not available"}
    report = await ctx.session_report_repo.find_by_session(arguments["session_id"])
    if not report:
        return {"error": "No report found for this session"}
    return {
        "session_id": report.session_id,
        "status": report.status,
        "summary": report.summary,
        "files_changed": list(report.files_changed),
        "test_results": report.test_results.to_doc() if report.test_results else None,
        "diff_stats": report.diff_stats.to_doc() if report.diff_stats else None,
        "agent_notes": report.agent_notes,
    }


async def handle_list_reports_by_task(ctx: ToolContext, arguments: dict) -> Any:
    if not ctx.session_report_repo:
        return {"error": "Session report repo not available"}
    task = await ctx.task.get_task(arguments["task_slug"])
    if not task:
        return {"error": f"Task not found: {arguments['task_slug']}"}
    reports = await ctx.session_report_repo.list_by_task(
        task_id=task.id,
        limit=arguments.get("limit", 10),
    )
    return [
        {
            "session_id": r.session_id,
            "agent": r.agent,
            "status": r.status,
            "summary": r.summary[:200],
            "files_changed": list(r.files_changed),
            "created_at": r.created_at.isoformat(),
        }
        for r in reports
    ]


async def handle_list_recent_reports(ctx: ToolContext, arguments: dict) -> Any:
    if not ctx.session_report_repo:
        return {"error": "Session report repo not available"}
    reports = await ctx.session_report_repo.list_recent(
        limit=arguments.get("limit", 10),
    )
    return [
        {
            "session_id": r.session_id,
            "task_id": r.task_id,
            "agent": r.agent,
            "status": r.status,
            "summary": r.summary[:200],
            "created_at": r.created_at.isoformat(),
        }
        for r in reports
    ]


async def handle_list_agent_events(ctx: ToolContext, arguments: dict) -> Any:
    if not ctx.agent_event_repo:
        return {"error": "Agent event repo not available"}
    events = await ctx.agent_event_repo.list_unacknowledged(
        event_types=arguments.get("event_types"),
        limit=arguments.get("limit", 20),
    )
    return [
        {
            "id": e.id,
            "session_id": e.session_id,
            "event_type": e.event_type.value,
            "detail": e.detail,
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    ]


async def handle_acknowledge_events(ctx: ToolContext, arguments: dict) -> Any:
    if not ctx.agent_event_repo:
        return {"error": "Agent event repo not available"}
    count = await ctx.agent_event_repo.acknowledge(arguments["event_ids"])
    return {"acknowledged": count}


async def handle_list_events_by_session(ctx: ToolContext, arguments: dict) -> Any:
    if not ctx.agent_event_repo:
        return {"error": "Agent event repo not available"}
    events = await ctx.agent_event_repo.list_by_session(
        session_id=arguments["session_id"],
        limit=arguments.get("limit", 20),
    )
    return [
        {
            "id": e.id,
            "session_id": e.session_id,
            "event_type": e.event_type.value,
            "detail": e.detail,
            "acknowledged": e.acknowledged,
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    ]


# --- Internal helpers ---


async def _get_diff_stats(ctx: ToolContext, session_id: str) -> tuple[DiffStats, tuple[str, ...]]:
    """Get diff stats using git diff --numstat for reliability."""
    try:
        numstat_output = await ctx.session.run_in_worktree(
            session_id, "git diff --numstat HEAD"
        )
        return _parse_numstat(numstat_output or "")
    except Exception:
        # Fallback to unified diff parsing
        try:
            diff = await ctx.session.get_session_diff(session_id)
            return _parse_diff_stats_unified(diff or ""), _parse_files_from_diff(diff or "")
        except Exception:
            return DiffStats(), ()


def _parse_numstat(output: str) -> tuple[DiffStats, tuple[str, ...]]:
    """Parse git diff --numstat output: insertions<tab>deletions<tab>path."""
    insertions = 0
    deletions = 0
    files: list[str] = []
    for line in output.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        ins, dels, path = parts
        # Binary files show '-' for insertions/deletions
        if ins != "-":
            insertions += int(ins)
        if dels != "-":
            deletions += int(dels)
        files.append(path)
    return DiffStats(insertions=insertions, deletions=deletions, files=len(files)), tuple(files)


def _parse_diff_stats_unified(diff: str) -> DiffStats:
    """Fallback: parse insertions/deletions/files from unified diff format."""
    insertions = 0
    deletions = 0
    files = set()
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            parts = line.split("\t", 1)
            if len(parts) > 1:
                files.add(parts[1])
            elif line.startswith("+++ b/") or line.startswith("--- a/"):
                fname = line[6:]
                if fname != "/dev/null":
                    files.add(fname)
        elif line.startswith("+") and not line.startswith("+++"):
            insertions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return DiffStats(insertions=insertions, deletions=deletions, files=len(files))


def _parse_files_from_diff(diff: str) -> tuple[str, ...]:
    """Extract changed file paths from a unified diff."""
    files = []
    for line in diff.splitlines():
        if line.startswith("diff --git"):
            parts = line.split(" b/", 1)
            if len(parts) > 1:
                files.append(parts[1])
    return tuple(files)


def parse_test_results(output: str) -> TestResults:
    """Parse test results from common test runner output."""
    passed = 0
    failed = 0
    errors = 0

    # pytest pattern
    pytest_match = re.search(r"(\d+)\s+passed", output)
    if pytest_match:
        passed = int(pytest_match.group(1))
    fail_match = re.search(r"(\d+)\s+failed", output)
    if fail_match:
        failed = int(fail_match.group(1))
    error_match = re.search(r"(\d+)\s+error", output)
    if error_match:
        errors = int(error_match.group(1))

    # npm test / jest pattern
    if not pytest_match:
        jest_pass = re.search(r"Tests:\s+(\d+)\s+passed", output)
        jest_fail = re.search(r"Tests:\s+(\d+)\s+failed", output)
        if jest_pass:
            passed = int(jest_pass.group(1))
        if jest_fail:
            failed = int(jest_fail.group(1))

    return TestResults(
        passed=passed,
        failed=failed,
        errors=errors,
        output_snippet=output[-500:] if len(output) > 500 else output,
    )


async def auto_report_on_stop(ctx: ToolContext, session) -> None:
    """Generate a basic report when a session is stopped (diff only, no LLM)."""
    if not ctx.session_report_repo:
        return
    try:
        existing = await ctx.session_report_repo.find_by_session(session.id)
        if existing:
            return

        diff_stats, files_changed = await _get_diff_stats(ctx, session.id)

        report = SessionReport(
            session_id=session.id,
            task_id=session.task_id,
            agent=session.agent_backend,
            status="partial" if diff_stats.files == 0 else "success",
            summary=f"Session stopped. {diff_stats.files} files changed ({diff_stats.insertions}+ {diff_stats.deletions}-).",
            files_changed=files_changed,
            diff_stats=diff_stats,
        )
        await ctx.session_report_repo.insert(report)
        await _record_session_metric(ctx, session)
    except Exception:
        logger.debug("Failed to auto-generate report on stop", exc_info=True)


async def _record_session_metric(ctx: ToolContext, session, status: str = "success") -> None:
    """Record a session duration metric for progress estimation."""
    if not ctx.session_metric_repo:
        return
    try:
        duration = (datetime.now(timezone.utc) - session.created_at).total_seconds()
        complexity = ""
        try:
            task = await ctx.task.get_task_by_id(session.task_id)
            if task:
                complexity = task.complexity
        except Exception:
            pass

        from agentbenchplatform.models.session_metric import SessionMetric
        await ctx.session_metric_repo.insert(SessionMetric(
            session_id=session.id,
            task_id=session.task_id,
            agent_backend=session.agent_backend,
            complexity=complexity,
            status=status,
            duration_seconds=int(duration),
        ))
    except Exception:
        logger.debug("Failed to record session metric", exc_info=True)


async def _auto_escalate(ctx: ToolContext, session, failure_summary: str) -> dict | None:
    """Auto-start a higher-tier session when a lower tier fails."""
    current_tier = _AGENT_TIERS.get(session.agent_backend, 0)
    if current_tier >= 2:
        return None

    next_agent = _TIER_ORDER[current_tier + 1]

    await ctx.emit_event(
        session.id, session.task_id,
        AgentEventType.NEEDS_HELP,
        f"Auto-escalating from {session.agent_backend} to {next_agent}: {failure_summary[:200]}",
    )

    try:
        task = await ctx.task.get_task_by_id(session.task_id)
        if not task:
            return None
        escalated = await ctx.session.start_coding_session(
            task_id=task.id,
            agent_type=next_agent,
            prompt=f"Previous {session.agent_backend} session failed. Issue: {failure_summary}\nPlease fix the problems and complete the task.",
            workspace_path=task.workspace_path,
            task_tags=task.tags,
            task_complexity=task.complexity,
        )
        await ctx.emit_event(
            escalated.id, task.id,
            AgentEventType.STARTED,
            f"Escalated from {session.agent_backend}: {next_agent} started",
        )
        return {
            "escalated_to": next_agent,
            "new_session_id": escalated.id,
            "reason": failure_summary[:200],
        }
    except Exception:
        logger.warning("Auto-escalation failed", exc_info=True)
        return None


async def _check_auto_unblock(ctx: ToolContext, task_id: str) -> list[str]:
    """Check if completing a task unblocks downstream tasks."""
    try:
        task = await ctx.task.get_task_by_id(task_id)
        if not task:
            return []
        downstream = await ctx.task.get_downstream_tasks(task.slug)
        unblocked: list[str] = []
        for dt in downstream:
            if dt.status != TaskStatus.ACTIVE:
                continue
            deps = await ctx.task.get_task_dependencies(dt.slug)
            if not deps["blocking"]:
                unblocked.append(dt.slug)
                await ctx.emit_event(
                    "", task_id,
                    AgentEventType.NEEDS_HELP,
                    f"Task '{dt.slug}' is now unblocked — all dependencies satisfied",
                )
        return unblocked
    except Exception:
        logger.debug("Auto-unblock check failed", exc_info=True)
        return []
