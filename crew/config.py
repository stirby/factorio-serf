"""crew.toml loading. Everything model/backend-related lives here so a demo is a config change."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MODEL = "claude-sonnet-5-5"


@dataclass
class AgentConfig:
    name: str
    backend: str = "claude-code"  # "claude-code" (Claude Code login / subscription) or "api" (ANTHROPIC_API_KEY)
    model: str = DEFAULT_MODEL
    effort: str | None = None  # low | medium | high
    role: str = "worker"  # worker | foreman
    focus: str = ""  # domain: production | resources | infrastructure | free text
    personality: str = ""
    color: list[float] | None = None
    max_turns_per_hour: int = 120
    max_autonomous_turns: int = 40  # consecutive self-continued turns before it must check in


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    rcon_port: int = 27015
    rcon_password: str = ""


@dataclass
class CrewConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    agents: list[AgentConfig] = field(default_factory=list)
    spawn_near: str | None = None  # player name to spawn next to, if online
    starter_kit: bool = True
    state_dir: Path = Path("~/.local/state/claude-crew").expanduser()
    source: Path | None = None  # crew.toml this came from (watched for live changes)
    advisor: AgentConfig | None = None  # characterless senior engineer the crew can consult
    advisor_for: str = "all"  # "all" or "foreman"
    foreman: AgentConfig | None = None  # characterless lead every worker can ask without waiting
    flags: dict = field(default_factory=dict)  # [experiment] toggles for A/B runs

    def flag(self, name: str, default: bool = True) -> bool:
        return bool(self.flags.get(name, default))

    def foreman_name(self) -> str | None:
        if self.foreman:
            return self.foreman.name
        return next((a.name for a in self.agents if a.role == "foreman"), None)


def _password(raw: dict, base: Path) -> str:
    if raw.get("rcon_password"):
        return raw["rcon_password"]
    if os.environ.get("FACTORIO_RCON_PASSWORD"):
        return os.environ["FACTORIO_RCON_PASSWORD"]
    if raw.get("rcon_password_file"):
        p = Path(raw["rcon_password_file"]).expanduser()
        return (p if p.is_absolute() else base / p).read_text().strip()
    return ""


def load(path: str | Path | None, overrides: dict | None = None) -> CrewConfig:
    overrides = overrides or {}
    raw: dict = {}
    base = Path.cwd()
    if path:
        p = Path(path).expanduser()
        raw = tomllib.loads(p.read_text())
        base = p.parent
    srv = raw.get("server", {})
    server = ServerConfig(
        host=srv.get("host", "127.0.0.1"),
        rcon_port=int(srv.get("rcon_port", 27015)),
        rcon_password=_password(srv, base),
    )
    if overrides.get("server"):
        host, _, port = overrides["server"].partition(":")
        server.host = host or server.host
        if port:
            server.rcon_port = int(port)
    if overrides.get("password"):
        server.rcon_password = overrides["password"]

    defaults = raw.get("defaults", {})
    if overrides.get("model"):
        defaults["model"] = overrides["model"]
    if overrides.get("backend"):
        defaults["backend"] = overrides["backend"]
    agents = []
    entries = raw.get("agent") or raw.get("agents") or []
    n = int(overrides.get("count") or 0)
    if n and len(entries) < n:
        entries = entries + [{"name": f"claude-{i + 1}"} for i in range(len(entries), n)]
    if not entries:
        entries = [{"name": "claude-1"}]
    if n:
        entries = entries[:n]
    for e in entries:
        merged = {**defaults, **e}
        if overrides.get("model"):  # CLI flag wins over per-agent config
            merged["model"] = overrides["model"]
        known = AgentConfig.__dataclass_fields__.keys()
        agents.append(AgentConfig(**{k: v for k, v in merged.items() if k in known}))

    cfg = CrewConfig(server=server, agents=agents,
                     spawn_near=raw.get("spawn_near"), starter_kit=raw.get("starter_kit", True))
    cfg.source = Path(path).expanduser().resolve() if path else None
    cfg.flags = dict(raw.get("experiment", {}))
    adv = raw.get("advisor")
    if adv and adv.get("enabled", True):
        known = AgentConfig.__dataclass_fields__.keys()
        merged = {"name": "architect", "model": "claude-opus-5-5", "effort": "high",
                  "backend": defaults.get("backend", "claude-code"), **adv}
        cfg.advisor = AgentConfig(**{k: v for k, v in merged.items() if k in known})
        cfg.advisor_for = adv.get("for", "all")
    fm = raw.get("foreman")
    if fm and fm.get("enabled", True):
        known = AgentConfig.__dataclass_fields__.keys()
        merged = {"name": "foreman", "model": defaults.get("model", "claude-opus-5-5"), "effort": "medium",
                  "backend": defaults.get("backend", "claude-code"), "max_turns_per_hour": 60, **fm}
        cfg.foreman = AgentConfig(**{k: v for k, v in merged.items() if k in known})
        for a in cfg.agents:  # the characters all work; the lead is the characterless foreman
            if a.role == "foreman":
                a.role = "worker"
    if raw.get("state_dir"):
        cfg.state_dir = Path(raw["state_dir"]).expanduser()
    return cfg
