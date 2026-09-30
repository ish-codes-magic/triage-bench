"""Assemble an agent triager from config: MCP session, skills, tracer.

Everything with a lifetime (the repo-intel subprocess, its log file, the trace exporter)
is registered on the caller's ExitStack, so a finished, failed or interrupted run
always shuts the server down and flushes its spans.
"""

from contextlib import ExitStack
from pathlib import Path

from triagelab.config import AgentConfig, Config
from triagelab.data.profile import RepoProfile
from triagelab.harness.agent import AgentTriager
from triagelab.harness.mcp_client import McpSession, repo_intel_command
from triagelab.harness.tracing import RunTracer
from triagelab.llm_client import LLMClient
from triagelab.skills.loader import SkillSet


def open_repo_intel(cfg: Config, agent: AgentConfig, stack: ExitStack, run_dir: Path) -> McpSession:
    mcp_cfg = agent.mcp
    profile_path, data_dir = cfg.dataset.profile.resolve(), cfg.dataset.data_dir.resolve()
    if mcp_cfg.transport == "in_process":
        from triagelab.mcp_server.app import load_intel
        from triagelab.mcp_server.server import build_server

        server = build_server(load_intel(profile_path, data_dir, dense=mcp_cfg.dense))
        return stack.enter_context(McpSession.in_process(server))
    # The server's stderr (index loading, warnings) goes to the run folder, not the console.
    errlog = stack.enter_context((run_dir / "mcp_server.log").open("w", encoding="utf-8"))
    command, args = repo_intel_command(profile_path, data_dir, dense=mcp_cfg.dense)
    return stack.enter_context(McpSession.stdio(command, args, cwd=Path.cwd(), errlog=errlog))


def build_agent(
    cfg: Config,
    agent_cfg: AgentConfig,
    profile: RepoProfile,
    family_labels: list[str],
    client: LLMClient,
    *,
    max_body_chars: int,
    run_id: str,
    run_dir: Path,
    stack: ExitStack,
) -> AgentTriager:
    tracer = RunTracer(
        run_id=run_id,
        jsonl_path=run_dir / "traces.jsonl",
        otlp_endpoint=cfg.tracing.otlp_endpoint,
        project=cfg.tracing.project,
    )
    stack.callback(tracer.close)
    wants_mcp = agent_cfg.tools is None or bool(agent_cfg.tools) or agent_cfg.stuff_similar_k > 0
    triager = AgentTriager(
        client=client,
        llm=cfg.llm,
        agent=agent_cfg,
        profile=profile,
        family_labels=family_labels,
        skills=SkillSet.from_dir(agent_cfg.skills_dir, agent_cfg.skills),
        mcp=open_repo_intel(cfg, agent_cfg, stack, run_dir) if wants_mcp else None,
        tracer=tracer,
        max_body_chars=max_body_chars,
    )
    triager.warm_up()
    return triager
