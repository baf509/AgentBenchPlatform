"""Research service: recursive depth-first research loop."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from agentbenchplatform.config import AppConfig
from agentbenchplatform.infra.db.sessions import SessionRepo
from agentbenchplatform.infra.db.usage import UsageRepo
from agentbenchplatform.infra.providers.registry import get_provider_with_fallback
from agentbenchplatform.infra.search.brave import BraveSearchProvider
from agentbenchplatform.models.memory import MemoryScope
from agentbenchplatform.models.provider import LLMConfig, LLMMessage
from agentbenchplatform.models.research import Learning, ResearchConfig, ResearchReport
from agentbenchplatform.models.session import (
    ResearchProgress,
    Session,
    SessionKind,
    SessionLifecycle,
)
from agentbenchplatform.models.usage import UsageEvent
from agentbenchplatform.services.memory_service import MemoryService

logger = logging.getLogger(__name__)


class ResearchService:
    """Recursive deep research agent.

    Pattern from dzhng/deep-research:
    1. LLM generates N sub-queries (breadth)
    2. Each sub-query -> web search
    3. LLM extracts atomic learnings from results
    4. If depth > 0, recurse with refined queries
    5. Final synthesis into report
    """

    def __init__(
        self,
        session_repo: SessionRepo,
        memory_service: MemoryService,
        config: AppConfig,
        usage_repo: UsageRepo | None = None,
    ) -> None:
        self._session_repo = session_repo
        self._memory_service = memory_service
        self._config = config
        self._usage_repo = usage_repo
        self._active_tasks: dict[str, asyncio.Task] = {}

    async def start_research(
        self,
        task_id: str,
        research_config: ResearchConfig,
    ) -> Session:
        """Start a research session and run research as an async task."""
        # Create session
        session = Session(
            task_id=task_id,
            kind=SessionKind.RESEARCH_AGENT,
            lifecycle=SessionLifecycle.RUNNING,
            display_name=f"research-{research_config.query[:30]}",
            research_progress=ResearchProgress(
                max_depth=research_config.depth,
            ),
        )
        session = await self._session_repo.insert(session)

        # Run research in background, store ref to prevent GC
        task = asyncio.create_task(self._run_research(session.id, task_id, research_config))
        self._active_tasks[session.id] = task
        task.add_done_callback(lambda _t: self._active_tasks.pop(session.id, None))

        return session

    async def wait_for_research(self, session_id: str) -> None:
        """Wait for a running research task to complete."""
        task = self._active_tasks.get(session_id)
        if task:
            await task

    async def _run_research(
        self,
        session_id: str,
        task_id: str,
        research_config: ResearchConfig,
    ) -> None:
        """Execute the full research loop."""
        try:
            logger.info(
                "Starting research for session %s, query: %s", session_id, research_config.query
            )
            provider = get_provider_with_fallback(self._config, research_config.provider)
            search_provider = self._get_search_provider(research_config.search_provider)
            logger.info("Providers initialized for session %s", session_id)

            all_learnings: list[Learning] = []
            queries_completed = 0

            async def _research_recursive(
                query: str, depth: int, breadth: int, context_learnings: list[Learning]
            ) -> list[Learning]:
                nonlocal queries_completed

                if depth <= 0:
                    return context_learnings

                # Generate sub-queries
                logger.debug("Generating %d sub-queries for: %s", breadth, query)
                sub_queries = await self._generate_sub_queries(
                    provider, query, breadth, context_learnings, research_config.model,
                    session_id=session_id,
                )
                logger.debug("Generated %d sub-queries", len(sub_queries))

                new_learnings = list(context_learnings)

                for sub_query in sub_queries:
                    # Search
                    logger.debug("Searching for: %s", sub_query)
                    results = await search_provider.search(sub_query, max_results=5)
                    logger.debug("Search returned %d results", len(results))
                    queries_completed += 1

                    # Extract learnings
                    extracted = await self._extract_learnings(
                        provider, sub_query, results, depth, research_config.model,
                        session_id=session_id,
                    )
                    new_learnings.extend(extracted)
                    all_learnings.extend(extracted)

                    # Update progress
                    await self._session_repo.update_research_progress(
                        session_id,
                        ResearchProgress(
                            current_depth=research_config.depth - depth + 1,
                            max_depth=research_config.depth,
                            queries_completed=queries_completed,
                            queries_total=queries_completed + breadth * (depth - 1),
                            learnings_count=len(all_learnings),
                        ).to_doc(),
                    )

                # Recurse with reduced breadth and depth
                if depth > 1:
                    follow_ups = await self._generate_follow_up_queries(
                        provider,
                        query,
                        new_learnings,
                        max(1, breadth // 2),
                        research_config.model,
                        session_id=session_id,
                    )
                    for fq in follow_ups:
                        new_learnings = await _research_recursive(
                            fq, depth - 1, max(1, breadth // 2), new_learnings
                        )

                return new_learnings

            # Run recursive research
            final_learnings = await _research_recursive(
                research_config.query,
                research_config.depth,
                research_config.breadth,
                [],
            )

            # Store learnings as task memories
            for i, learning in enumerate(final_learnings):
                await self._memory_service.store(
                    key=f"research-learning-{i}",
                    content=learning.content,
                    scope=MemoryScope.TASK,
                    task_id=task_id,
                    metadata={
                        "source_url": learning.source_url,
                        "confidence": learning.confidence,
                        "depth_found": learning.depth_found,
                        "research_query": research_config.query,
                    },
                )

            # Generate final report
            report = await self._synthesize_report(
                provider, research_config.query, final_learnings, research_config.model,
                session_id=session_id,
            )

            # Store report as memory
            await self._memory_service.store(
                key="research-report",
                content=report.report_text,
                scope=MemoryScope.TASK,
                task_id=task_id,
                metadata={"research_query": research_config.query},
            )

            await self._session_repo.update_lifecycle(session_id, SessionLifecycle.COMPLETED)
            logger.info(
                "Research completed: %d learnings, session %s",
                len(final_learnings),
                session_id,
            )

        except Exception:
            logger.exception("Research failed for session %s", session_id)
            await self._session_repo.update_lifecycle(session_id, SessionLifecycle.FAILED)

    async def _log_usage(self, response, model: str, session_id: str = "") -> None:
        """Log token usage from an LLM response."""
        if not self._usage_repo:
            return
        try:
            await self._usage_repo.insert(UsageEvent(
                source="research",
                model=response.model or model,
                input_tokens=response.usage.get("input_tokens", 0),
                output_tokens=response.usage.get("output_tokens", 0),
                session_id=session_id,
                timestamp=datetime.now(timezone.utc),
            ))
        except Exception:
            logger.debug("Failed to log research usage", exc_info=True)

    def _get_search_provider(self, provider_name: str):
        """Get a search provider instance."""
        if provider_name == "brave":
            brave_config = self._config.search.get("brave")
            api_key = brave_config.api_key if brave_config else ""
            return BraveSearchProvider(api_key=api_key)
        raise ValueError(f"Unknown search provider: {provider_name}")

    async def _generate_sub_queries(
        self,
        provider,
        query: str,
        breadth: int,
        learnings: list[Learning],
        model: str,
        session_id: str = "",
    ) -> list[str]:
        """Use LLM to generate sub-queries for research."""
        learnings_text = "\n".join(f"- {l.content}" for l in learnings[-20:])
        prompt = f"""Given the research query: "{query}"

And these existing learnings:
{learnings_text or "(none yet)"}

Generate exactly {breadth} specific, diverse sub-queries that would help research this topic thoroughly. Each sub-query should explore a different aspect.

Return as a JSON array of strings. Example: ["sub-query 1", "sub-query 2"]"""

        response = await provider.complete(
            messages=[LLMMessage(role="user", content=prompt)],
            config=LLMConfig(model=model, temperature=0.7, max_tokens=1024),
        )
        await self._log_usage(response, model, session_id)

        try:
            # Extract JSON array from response
            text = response.content.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            queries = json.loads(text)
            if isinstance(queries, list):
                return [str(q) for q in queries[:breadth]]
            else:
                logger.warning("Sub-queries response is not a list: %s", type(queries).__name__)
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse sub-queries JSON: %s. Response: %s", e, text[:200])
        except IndexError as e:
            logger.warning("Failed to extract sub-queries from response: %s", e)

        return [query]

    async def _extract_learnings(
        self,
        provider,
        query: str,
        results,
        depth: int,
        model: str,
        session_id: str = "",
    ) -> list[Learning]:
        """Extract atomic learnings from search results."""
        if not results:
            return []

        results_text = "\n\n".join(
            f"Source: {r.url}\nTitle: {r.title}\nContent: {r.content[:1000]}" for r in results
        )

        prompt = f"""Analyze these search results for the query: "{query}"

{results_text}

Extract key factual learnings as atomic statements. Each learning should be a single, specific fact or insight.

Return as a JSON array of objects with "content" and "source_url" fields.
Example: [{{"content": "fact here", "source_url": "https://..."}}]"""

        response = await provider.complete(
            messages=[LLMMessage(role="user", content=prompt)],
            config=LLMConfig(model=model, temperature=0.3, max_tokens=2048),
        )
        await self._log_usage(response, model, session_id)

        learnings = []
        try:
            text = response.content.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            parsed = json.loads(text)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and "content" in item:
                        learnings.append(
                            Learning(
                                content=item["content"],
                                source_url=item.get("source_url", ""),
                                depth_found=depth,
                            )
                        )
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse learnings JSON: %s. Response: %s", e, text[:200])
        except (IndexError, KeyError) as e:
            logger.warning("Failed to extract learnings from response: %s", e)

        return learnings

    async def _generate_follow_up_queries(
        self,
        provider,
        original_query: str,
        learnings: list[Learning],
        count: int,
        model: str,
        session_id: str = "",
    ) -> list[str]:
        """Generate follow-up queries based on learnings so far."""
        learnings_text = "\n".join(f"- {l.content}" for l in learnings[-20:])

        prompt = f"""Based on the original research query: "{original_query}"

And these learnings discovered so far:
{learnings_text}

Generate {count} follow-up queries that would deepen the research. Focus on gaps in knowledge or interesting threads to explore further.

Return as a JSON array of strings."""

        response = await provider.complete(
            messages=[LLMMessage(role="user", content=prompt)],
            config=LLMConfig(model=model, temperature=0.7, max_tokens=1024),
        )
        await self._log_usage(response, model, session_id)

        try:
            text = response.content.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            queries = json.loads(text)
            if isinstance(queries, list):
                return [str(q) for q in queries[:count]]
            else:
                logger.warning("Follow-up queries response is not a list: %s", type(queries).__name__)
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse follow-up queries JSON: %s. Response: %s", e, text[:200])
        except IndexError as e:
            logger.warning("Failed to extract follow-up queries from response: %s", e)

        return []

    async def _synthesize_report(
        self,
        provider,
        query: str,
        learnings: list[Learning],
        model: str,
        session_id: str = "",
    ) -> ResearchReport:
        """Compile all learnings into a final report."""
        learnings_text = "\n".join(f"- {l.content} (source: {l.source_url})" for l in learnings)
        sources = list({l.source_url for l in learnings if l.source_url})

        prompt = f"""Write a comprehensive research report on: "{query}"

Based on these research findings:
{learnings_text}

Write a well-structured report with sections, covering all key findings. Include source references where relevant. Be thorough but concise."""

        response = await provider.complete(
            messages=[LLMMessage(role="user", content=prompt)],
            config=LLMConfig(model=model, temperature=0.5, max_tokens=4096),
        )
        await self._log_usage(response, model, session_id)

        return ResearchReport(
            query=query,
            report_text=response.content,
            learnings=tuple(learnings),
            sources=tuple(sources),
        )

    async def get_research_status(self, session_id: str) -> Session | None:
        """Get current research progress."""
        return await self._session_repo.find_by_id(session_id)

    async def get_research_results(self, task_id: str) -> list:
        """Get research learnings stored as task memories."""
        memories = await self._memory_service.get_task_memories(task_id)
        return [m for m in memories if m.key.startswith("research-")]
