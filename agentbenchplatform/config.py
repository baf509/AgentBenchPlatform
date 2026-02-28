"""Configuration loading: TOML file + environment variable overlay."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


DEFAULT_CONFIG_DIR = Path.home() / ".config" / "agentbenchplatform"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.toml"


def _default_socket_path() -> str:
    """Return default socket path using XDG_RUNTIME_DIR or /tmp fallback."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return str(Path(runtime) / "agentbenchplatform.sock")
    return f"/tmp/agentbenchplatform-{os.getuid()}.sock"


def _default_pid_path() -> str:
    """Return default PID file path."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return str(Path(runtime) / "agentbenchplatform.pid")
    return f"/tmp/agentbenchplatform-{os.getuid()}.pid"


DEFAULT_CONFIG_TOML = """\
[general]
workspace_root = "~/agentbench-workspaces"
default_agent = "claude_code"

[mongodb]
uri = "mongodb://localhost:27017/?directConnection=true&replicaSet=rs0"
database = "agentbenchplatform"

[providers.anthropic]
api_key_env = "ANTHROPIC_API_KEY"
default_model = "claude-sonnet-4-20250514"

[providers.openrouter]
api_key_env = "OPENROUTER_API_KEY"
default_model = "anthropic/claude-sonnet-4"

[providers.llamacpp]
base_url = "http://localhost:8080"
opencode_model = "llamacpp/step3p5_flash_Q4_K_S-00001-of-00012.gguf"

[embeddings]
provider = "voyage-4-nano"
base_url = "http://localhost:8001"
dimensions = 1024

[coordinator]
provider = "anthropic"
model = "claude-sonnet-4-20250514"

[research]
default_provider = "anthropic"
default_search = "brave"
default_breadth = 4
default_depth = 3

[search.brave]
api_key_env = "BRAVE_SEARCH_API_KEY"

[signal]
enabled = false
account = ""
http_url = "http://127.0.0.1:8080"
auto_start = true
dm_policy = "allowlist"
allowed_senders = []
whisper_url = "http://localhost:8082"

[tmux]
enabled = true
session_prefix = "ab"

[server]
# socket_path and pid_file default to XDG_RUNTIME_DIR or /tmp
"""


@dataclass
class MongoConfig:
    uri: str = "mongodb://localhost:27017/?directConnection=true&replicaSet=rs0"
    database: str = "agentbenchplatform"


@dataclass
class ProviderConfig:
    api_key_env: str = ""
    api_key: str = ""
    default_model: str = ""
    base_url: str = ""
    opencode_model: str = ""


@dataclass
class EmbeddingsConfig:
    provider: str = "voyage-4-nano"
    base_url: str = "http://localhost:8001"
    dimensions: int = 1024


@dataclass
class CoordinatorConfig:
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    provider_order: list[str] = field(default_factory=list)
    patrol_enabled: bool = False
    patrol_interval: int = 300
    patrol_autonomy: str = "observe"  # observe, nudge, full
    patrol_notify_phone: str = ""
    auto_respond_prompts: bool = True
    watchdog_check_interval: int = 30
    watchdog_stall_threshold: int = 600
    watchdog_idle_interval: int = 120
    max_conversation_exchanges: int = 20
    max_tool_rounds: int = 10
    notification_cooldown: int = 300


@dataclass
class ResearchDefaults:
    default_provider: str = "anthropic"
    default_search: str = "brave"
    default_breadth: int = 4
    default_depth: int = 3


@dataclass
class SignalConfig:
    enabled: bool = False
    account: str = ""
    http_url: str = "http://127.0.0.1:8080"
    auto_start: bool = True
    dm_policy: str = "allowlist"
    allowed_senders: list[str] = field(default_factory=list)
    whisper_url: str = "http://localhost:8081"


@dataclass
class TmuxConfig:
    enabled: bool = True
    session_prefix: str = "ab"


@dataclass
class ServerConfig:
    socket_path: str = ""
    pid_file: str = ""

    @property
    def resolved_socket_path(self) -> str:
        return self.socket_path or _default_socket_path()

    @property
    def resolved_pid_file(self) -> str:
        return self.pid_file or _default_pid_path()


@dataclass
class AppConfig:
    workspace_root: str = "~/agentbench-workspaces"
    default_agent: str = "claude_code"
    mongodb: MongoConfig = field(default_factory=MongoConfig)
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    embeddings: EmbeddingsConfig = field(default_factory=EmbeddingsConfig)
    coordinator: CoordinatorConfig = field(default_factory=CoordinatorConfig)
    research: ResearchDefaults = field(default_factory=ResearchDefaults)
    search: dict[str, ProviderConfig] = field(default_factory=dict)
    signal: SignalConfig = field(default_factory=SignalConfig)
    tmux: TmuxConfig = field(default_factory=TmuxConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    config_path: Path = DEFAULT_CONFIG_PATH

    @property
    def resolved_workspace_root(self) -> Path:
        return Path(self.workspace_root).expanduser()


def _env_overlay(config: AppConfig) -> None:
    """Override config values with environment variables where applicable."""
    # MongoDB
    if uri := os.environ.get("MONGODB_URI"):
        config.mongodb.uri = uri
    if db := os.environ.get("AGENTBENCH_DB"):
        config.mongodb.database = db

    # Resolve API keys from env vars
    for name, prov in config.providers.items():
        if prov.api_key_env:
            prov.api_key = os.environ.get(prov.api_key_env, "")

    for name, search in config.search.items():
        if search.api_key_env:
            search.api_key = os.environ.get(search.api_key_env, "")


def _parse_provider(data: dict) -> ProviderConfig:
    return ProviderConfig(
        api_key_env=data.get("api_key_env", ""),
        default_model=data.get("default_model", ""),
        base_url=data.get("base_url", ""),
        opencode_model=data.get("opencode_model", ""),
    )


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load configuration from TOML file with env var overlay."""
    path = config_path or DEFAULT_CONFIG_PATH

    if path.exists():
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    else:
        raw = tomllib.loads(DEFAULT_CONFIG_TOML)

    general = raw.get("general", {})
    mongo_raw = raw.get("mongodb", {})
    providers_raw = raw.get("providers", {})
    embeddings_raw = raw.get("embeddings", {})
    coordinator_raw = raw.get("coordinator", {})
    research_raw = raw.get("research", {})
    search_raw = raw.get("search", {})
    signal_raw = raw.get("signal", {})
    tmux_raw = raw.get("tmux", {})
    server_raw = raw.get("server", {})

    config = AppConfig(
        workspace_root=general.get("workspace_root", "~/agentbench-workspaces"),
        default_agent=general.get("default_agent", "claude_code"),
        mongodb=MongoConfig(
            uri=mongo_raw.get("uri", "mongodb://localhost:27017/?directConnection=true&replicaSet=rs0"),
            database=mongo_raw.get("database", "agentbenchplatform"),
        ),
        providers={name: _parse_provider(data) for name, data in providers_raw.items()},
        embeddings=EmbeddingsConfig(
            provider=embeddings_raw.get("provider", "voyage-4-nano"),
            base_url=embeddings_raw.get("base_url", "http://localhost:8001"),
            dimensions=embeddings_raw.get("dimensions", 1024),
        ),
        coordinator=CoordinatorConfig(
            provider=coordinator_raw.get("provider", "anthropic"),
            model=coordinator_raw.get("model", "claude-sonnet-4-20250514"),
            patrol_enabled=coordinator_raw.get("patrol_enabled", False),
            patrol_interval=coordinator_raw.get("patrol_interval", 300),
            patrol_autonomy=coordinator_raw.get("patrol_autonomy", "observe"),
            patrol_notify_phone=coordinator_raw.get("patrol_notify_phone", ""),
            auto_respond_prompts=coordinator_raw.get("auto_respond_prompts", True),
            watchdog_check_interval=coordinator_raw.get("watchdog_check_interval", 30),
            watchdog_stall_threshold=coordinator_raw.get("watchdog_stall_threshold", 600),
            watchdog_idle_interval=coordinator_raw.get("watchdog_idle_interval", 120),
            max_conversation_exchanges=coordinator_raw.get("max_conversation_exchanges", 20),
            max_tool_rounds=coordinator_raw.get("max_tool_rounds", 10),
            notification_cooldown=coordinator_raw.get("notification_cooldown", 300),
        ),
        research=ResearchDefaults(
            default_provider=research_raw.get("default_provider", "anthropic"),
            default_search=research_raw.get("default_search", "brave"),
            default_breadth=research_raw.get("default_breadth", 4),
            default_depth=research_raw.get("default_depth", 3),
        ),
        search={name: _parse_provider(data) for name, data in search_raw.items()},
        signal=SignalConfig(
            enabled=signal_raw.get("enabled", False),
            account=signal_raw.get("account", ""),
            http_url=signal_raw.get("http_url", "http://127.0.0.1:8080"),
            auto_start=signal_raw.get("auto_start", True),
            dm_policy=signal_raw.get("dm_policy", "allowlist"),
            allowed_senders=signal_raw.get("allowed_senders", []),
            whisper_url=signal_raw.get("whisper_url", "http://localhost:8081"),
        ),
        tmux=TmuxConfig(
            enabled=tmux_raw.get("enabled", True),
            session_prefix=tmux_raw.get("session_prefix", "ab"),
        ),
        server=ServerConfig(
            socket_path=server_raw.get("socket_path", ""),
            pid_file=server_raw.get("pid_file", ""),
        ),
        config_path=path,
    )

    _env_overlay(config)
    return config


def init_config(config_path: Path | None = None) -> Path:
    """Create default config file."""
    path = config_path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TOML)
    return path
