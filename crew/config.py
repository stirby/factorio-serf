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
    fast: bool = False  # fast mode: Opus only, premium price (extra usage credits on a subscription)
    focus: str = ""  # domain: production | resources | infrastructure | free text
    personality: str = ""
    color: list[float] | None = None
    max_turns_per_hour: int = 120
    max_autonomous_turns: int = 40  # consecutive self-continued turns before it must check in
    base_url: str | None = None  # backend "openai": any OpenAI-compatible endpoint (e.g. the Vercel AI Gateway)
    api_key_env: str | None = None  # env var holding its key (default: AI_GATEWAY_API_KEY for the gateway, else OPENAI_API_KEY)
    owner: str | None = None  # the player it works for (set by /serf add); default: the config's spawn_near


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    rcon_port: int = 27015
    rcon_password: str = ""
    transport: str = "rcon"  # "rcon" (server operator) or "udp" (a player's own app: Factorio's --enable-lua-udp)
    udp_port: int = 27200
    client: str = "rcon"  # this orchestrator's name to the mod over RCON (two `crew up` on one server need two)


@dataclass
class CrewConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    agents: list[AgentConfig] = field(default_factory=list)
    spawn_near: str | None = None  # player name to spawn next to, if online
    starter_kit: bool = True
    state_dir: Path = field(default_factory=lambda: _home("~/.local/state", "factorio-serf"))
    source: Path | None = None  # crew.toml this came from (watched for live changes)
    foreman: AgentConfig | None = None  # characterless lead every worker can ask without waiting
    usd_per_hour: float | None = None  # [budget] usd_per_hour: hard cap on spend over the last hour (all models)
    kind: str = "serf"  # [identity] kind: what an agent is called (the user's pick: short to type in chat)
    title: str | None = None  # [identity] title: the in-game panel's caption (default "serf · with otterplex")
    defaults: dict = field(default_factory=dict)  # [defaults]: template for agents that arrive by /serf add
    join: bool = False  # agents come only from /serf add (the player's app); none spawn at start
    host_serfs: bool = False  # take /serf add from players without their own app (they run on this login)

    @property
    def owner(self) -> str | None:
        return self.spawn_near

    def panel_title(self) -> str:
        if self.title:
            return self.title
        if len(self.agents) == 1:
            name = self.agents[0].name
            head = name if name == self.kind else f"{name} · {self.kind}"
            return head + (f" · with {self.owner}" if self.owner else "")
        return f"{self.kind}s".capitalize()

    def agent_for(self, name: str, owner: str | None) -> AgentConfig:
        """Config for an agent that arrived by /serf add: [defaults] plus its name and owner."""
        known = AgentConfig.__dataclass_fields__.keys()
        return AgentConfig(**{k: v for k, v in {**self.defaults, "name": name, "owner": owner}.items() if k in known})

    def foreman_name(self) -> str | None:
        return self.foreman.name if self.foreman else None


def _password(raw: dict, base: Path) -> str:
    if raw.get("rcon_password"):
        return raw["rcon_password"]
    if os.environ.get("FACTORIO_RCON_PASSWORD"):
        return os.environ["FACTORIO_RCON_PASSWORD"]
    if raw.get("rcon_password_file"):
        p = Path(raw["rcon_password_file"]).expanduser()
        return (p if p.is_absolute() else base / p).read_text().strip()
    return ""


def _home(base: str, name: str) -> Path:
    """~/<base>/factorio-serf, or the folder from before the rename (claude-crew) if only that one exists."""
    new, old = Path(base, name).expanduser(), Path(base, "claude-crew").expanduser()
    return old if old.exists() and not new.exists() else new


CONFIG_DIR = _home("~/.config", "factorio-serf")
ENV_FILE = CONFIG_DIR / "env"


def load_env_file(path: Path = ENV_FILE) -> None:
    """Provider keys live in a private KEY=VALUE file, not in crew.toml. Existing env vars win."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().removeprefix("export ").strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if k:
            os.environ.setdefault(k, v)


def load(path: str | Path | None, overrides: dict | None = None) -> CrewConfig:
    overrides = overrides or {}
    load_env_file()
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
        transport=srv.get("transport", "rcon"),
        udp_port=int(srv.get("udp_port", 27200)),
        client=srv.get("client", "rcon"),
    )
    if overrides.get("udp"):
        server.transport = "udp"
        if overrides["udp"] is not True:
            server.udp_port = int(overrides["udp"])
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
    join = bool(overrides.get("join") or raw.get("join"))
    if not entries and not join:
        entries = [{"name": "serf"}]
    if n:
        entries = entries[:n]
    for e in entries:
        merged = {**defaults, **e}
        if overrides.get("model"):  # CLI flag wins over per-agent config
            merged["model"] = overrides["model"]
        known = AgentConfig.__dataclass_fields__.keys()
        agents.append(AgentConfig(**{k: v for k, v in merged.items() if k in known}))

    # These are top-level keys, but written after [server] they land inside it (TOML), so accept both.
    srv = raw.get("server", {})

    def top(key, default=None):
        return raw.get(key, srv.get(key, default))
    cfg = CrewConfig(server=server, agents=agents,
                     spawn_near=top("spawn_near"), starter_kit=top("starter_kit", True))
    cfg.source = Path(path).expanduser().resolve() if path else None
    cfg.defaults, cfg.join = defaults, join
    cfg.host_serfs = bool(top("host_serfs", False))
    ident = raw.get("identity", {})
    cfg.kind = ident.get("kind", cfg.kind)
    cfg.title = ident.get("title")
    if raw.get("budget", {}).get("usd_per_hour"):
        cfg.usd_per_hour = float(raw["budget"]["usd_per_hour"])
    fm = raw.get("foreman")
    if fm and fm.get("enabled", True):
        known = AgentConfig.__dataclass_fields__.keys()
        merged = {"name": "foreman", "model": defaults.get("model", "claude-opus-5-5"), "effort": "medium",
                  "backend": defaults.get("backend", "claude-code"), "max_turns_per_hour": 60, **fm}
        cfg.foreman = AgentConfig(**{k: v for k, v in merged.items() if k in known})
    if top("state_dir"):
        cfg.state_dir = Path(top("state_dir")).expanduser()
    return cfg
