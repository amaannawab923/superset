"""Settings — env-driven config (A1/A3 feature gate, LLM, DB, control plane)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Feature gate (A3): when false, copilot routes return 404.
    copilot_ws_enabled: bool = True

    # LLM
    anthropic_api_key: str = ""
    # Optional Anthropic-compatible endpoint (e.g. a z.ai/GLM base URL). Empty =
    # api.anthropic.com. When set, use a matching model + key.
    copilot_anthropic_base_url: str = ""
    copilot_model: str = "claude-opus-5"
    copilot_max_tokens: int = 16000
    copilot_thinking: bool = False
    copilot_fake_llm: bool = False
    # Local-testing only: run inference through the Claude Agent SDK, which uses
    # the machine's logged-in `claude` CLI (subscription auth). Needs the CLI
    # logged in (`claude setup-token`). Pair with COPILOT_MCP_ENABLED=false.
    copilot_use_claude_sdk: bool = False
    # The long-lived subscription token from `claude setup-token` (sk-ant-oat01-…).
    # Put it in .env (gitignored). Exported to the Agent SDK subprocess at startup.
    claude_code_oauth_token: str = ""

    # Tools — the LangGraph tools_node (A6). When enabled, tools are discovered
    # from the local Superset MCP server (`superset mcp run`, streamable-http).
    # Falls back to the local stub tool if the server is unreachable.
    copilot_mcp_enabled: bool = True
    copilot_mcp_url: str = "http://localhost:5008/mcp/"

    # Persistence (A4)
    copilot_database_url: str = "sqlite+aiosqlite:///./copilot.db"

    # Control plane (Redis optional; in-memory fallback)
    copilot_redis_url: str = ""
    copilot_max_concurrent_per_user: int = 2

    # CORS — origins allowed to call the copilot (the Superset frontend + the
    # extension dev server). Comma-separated.
    copilot_cors_origins: str = (
        "http://localhost:9000,http://localhost:9001,http://localhost:8088,"
        "http://localhost:3000"
    )

    # Dev auth shim — a real deployment resolves these from a verified JWT.
    copilot_dev_user_id: int = 1
    copilot_dev_workspace_id: str = "default"

    # Migration Buddy: which Superset database connection a migrated
    # workbook's extract is loaded into (via create_dataset_from_data).
    # A real deployment would resolve this per-workspace; dev defaults to
    # the "BI Spike" connection already used by this environment.
    copilot_migration_database_id: int = 2

    # Migration Buddy — free-form mode (app/agent/migration/freeform.py): a
    # Claude Agent SDK session with real Bash/Read/Write, hitting Superset's
    # REST API directly with these credentials rather than going through
    # the MCP layer. Dev defaults match this environment's local instance;
    # a real deployment should set these to a scoped service account, not
    # an admin login.
    copilot_migration_superset_base_url: str = "http://localhost:8088"
    copilot_migration_superset_admin_user: str = "admin"
    copilot_migration_superset_admin_password: str = "admin"


@lru_cache
def get_settings() -> Settings:
    return Settings()
