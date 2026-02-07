"""AppContext: wires DB, config, and services together."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentbenchplatform.config import AppConfig, load_config
from agentbenchplatform.infra.db.client import MongoClient

if TYPE_CHECKING:
    from pathlib import Path

    from agentbenchplatform.infra.db.coordinator_history import CoordinatorHistoryRepo
    from agentbenchplatform.infra.db.memory import MemoryRepo
    from agentbenchplatform.infra.db.sessions import SessionRepo
    from agentbenchplatform.infra.db.tasks import TaskRepo
    from agentbenchplatform.infra.db.usage import UsageRepo
    from agentbenchplatform.infra.db.workspaces import WorkspaceRepo
    from agentbenchplatform.services.coordinator_service import CoordinatorService
    from agentbenchplatform.services.dashboard_service import DashboardService
    from agentbenchplatform.services.embedding_service import EmbeddingService
    from agentbenchplatform.services.memory_service import MemoryService
    from agentbenchplatform.services.research_service import ResearchService
    from agentbenchplatform.services.session_service import SessionService
    from agentbenchplatform.services.signal_service import SignalService
    from agentbenchplatform.services.task_service import TaskService

logger = logging.getLogger(__name__)


class AppContext:
    """Central wiring for all application dependencies.

    Lazily initializes services on first access. Call `initialize()` to
    set up the database connection and run migrations.
    """

    def __init__(self, config: AppConfig | None = None, config_path: Path | None = None) -> None:
        self.config = config or load_config(config_path)
        self._mongo: MongoClient | None = None
        self._task_repo: TaskRepo | None = None
        self._session_repo: SessionRepo | None = None
        self._memory_repo: MemoryRepo | None = None
        self._usage_repo: UsageRepo | None = None
        self._workspace_repo: WorkspaceRepo | None = None
        self._coordinator_history_repo: CoordinatorHistoryRepo | None = None
        self._task_service: TaskService | None = None
        self._session_service: SessionService | None = None
        self._memory_service: MemoryService | None = None
        self._embedding_service: EmbeddingService | None = None
        self._research_service: ResearchService | None = None
        self._coordinator_service: CoordinatorService | None = None
        self._dashboard_service: DashboardService | None = None
        self._signal_service: SignalService | None = None

    async def initialize(self) -> None:
        """Initialize the database connection and run migrations."""
        from agentbenchplatform.infra.db.migrations import create_vector_search_index, run_migrations

        self._mongo = MongoClient(
            uri=self.config.mongodb.uri,
            database=self.config.mongodb.database,
        )
        await run_migrations(self._mongo.db)
        await create_vector_search_index(self._mongo.db, self.config.embeddings.dimensions)
        logger.info("AppContext initialized")

    async def close(self) -> None:
        """Close all connections."""
        if self._mongo:
            self._mongo.close()
        logger.info("AppContext closed")

    @property
    def mongo(self) -> MongoClient:
        if self._mongo is None:
            raise RuntimeError("AppContext not initialized. Call initialize() first.")
        return self._mongo

    @property
    def task_repo(self) -> TaskRepo:
        if self._task_repo is None:
            from agentbenchplatform.infra.db.tasks import TaskRepo

            self._task_repo = TaskRepo(self.mongo.db)
        return self._task_repo

    @property
    def session_repo(self) -> SessionRepo:
        if self._session_repo is None:
            from agentbenchplatform.infra.db.sessions import SessionRepo

            self._session_repo = SessionRepo(self.mongo.db)
        return self._session_repo

    @property
    def memory_repo(self) -> MemoryRepo:
        if self._memory_repo is None:
            from agentbenchplatform.infra.db.memory import MemoryRepo

            self._memory_repo = MemoryRepo(self.mongo.db)
        return self._memory_repo

    @property
    def usage_repo(self) -> UsageRepo:
        if self._usage_repo is None:
            from agentbenchplatform.infra.db.usage import UsageRepo

            self._usage_repo = UsageRepo(self.mongo.db)
        return self._usage_repo

    @property
    def workspace_repo(self) -> WorkspaceRepo:
        if self._workspace_repo is None:
            from agentbenchplatform.infra.db.workspaces import WorkspaceRepo

            self._workspace_repo = WorkspaceRepo(self.mongo.db)
        return self._workspace_repo

    @property
    def coordinator_history_repo(self) -> CoordinatorHistoryRepo:
        if self._coordinator_history_repo is None:
            from agentbenchplatform.infra.db.coordinator_history import CoordinatorHistoryRepo

            self._coordinator_history_repo = CoordinatorHistoryRepo(self.mongo.db)
        return self._coordinator_history_repo

    @property
    def task_service(self) -> TaskService:
        if self._task_service is None:
            from agentbenchplatform.services.task_service import TaskService

            self._task_service = TaskService(self.task_repo)
        return self._task_service

    @property
    def session_service(self) -> SessionService:
        if self._session_service is None:
            from agentbenchplatform.services.session_service import SessionService

            self._session_service = SessionService(
                session_repo=self.session_repo,
                config=self.config,
                task_repo=self.task_repo,
            )
        return self._session_service

    @property
    def embedding_service(self) -> EmbeddingService:
        if self._embedding_service is None:
            from agentbenchplatform.services.embedding_service import EmbeddingService

            self._embedding_service = EmbeddingService(config=self.config.embeddings)
        return self._embedding_service

    @property
    def memory_service(self) -> MemoryService:
        if self._memory_service is None:
            from agentbenchplatform.services.memory_service import MemoryService

            self._memory_service = MemoryService(
                memory_repo=self.memory_repo,
                embedding_service=self.embedding_service,
            )
        return self._memory_service

    @property
    def dashboard_service(self) -> DashboardService:
        if self._dashboard_service is None:
            from agentbenchplatform.services.dashboard_service import DashboardService

            self._dashboard_service = DashboardService(
                task_repo=self.task_repo,
                session_repo=self.session_repo,
                workspace_repo=self.workspace_repo,
            )
        return self._dashboard_service

    @property
    def research_service(self) -> ResearchService:
        if self._research_service is None:
            from agentbenchplatform.services.research_service import ResearchService

            self._research_service = ResearchService(
                session_repo=self.session_repo,
                memory_service=self.memory_service,
                config=self.config,
                usage_repo=self.usage_repo,
            )
        return self._research_service

    @property
    def coordinator_service(self) -> CoordinatorService:
        if self._coordinator_service is None:
            from agentbenchplatform.services.coordinator_service import CoordinatorService

            self._coordinator_service = CoordinatorService(
                dashboard_service=self.dashboard_service,
                session_service=self.session_service,
                memory_service=self.memory_service,
                task_service=self.task_service,
                config=self.config,
                research_service=self.research_service,
                usage_repo=self.usage_repo,
                history_repo=self.coordinator_history_repo,
            )
        return self._coordinator_service

    @property
    def signal_service(self) -> SignalService:
        if self._signal_service is None:
            from agentbenchplatform.services.signal_service import SignalService

            self._signal_service = SignalService(
                coordinator=self.coordinator_service,
                config=self.config.signal,
            )
        return self._signal_service
