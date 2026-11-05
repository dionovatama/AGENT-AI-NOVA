from __future__ import annotations
import argparse, asyncio, getpass, json, os, subprocess, uuid
from .config import config_path

def write_config(server_url: str, agent_id: str, token: str):
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"server_url":server_url.rstrip("/"),"agent_id":str(uuid.UUID(agent_id)),
                                "token":token,"heartbeat_interval_seconds":30}, indent=2), encoding="utf-8")
    if os.name == "nt":
        subprocess.run(["icacls",str(path),"/inheritance:r","/grant:r","*S-1-5-18:F","*S-1-5-32-544:F"],
                       check=True, capture_output=True)
    else:
        path.chmod(0o600)
    print(f"Configuration saved: {path}")

def main():
    p=argparse.ArgumentParser(prog="nova-agent")
    sub=p.add_subparsers(dest="command",required=True)
    init=sub.add_parser("init"); init.add_argument("--server-url",required=True); init.add_argument("--agent-id",required=True); init.add_argument("--token", help="Avoid this option in production; prompted securely when omitted.")
    sub.add_parser("run")
    for cmd in ("install-service","uninstall-service","start","stop","status"): sub.add_parser(cmd)
    a=p.parse_args()
    if a.command=="init":
        token = a.token or getpass.getpass("Agent token (input hidden): ")
        if len(token)<32: p.error("token must be at least 32 characters")
        write_config(a.server_url,a.agent_id,token); return
    if a.command=="run":
        from .client import AgentClient
        from .config import AgentConfig
        from .logging_setup import setup_logging
        setup_logging(); asyncio.run(AgentClient(AgentConfig.load()).run()); return
    if os.name!="nt": p.error("Windows service commands are only supported on Windows")
    if a.command == "status":
        result = subprocess.run(["sc.exe", "query", "NOVARemoteAgent"], text=True, capture_output=True)
        print(result.stdout or result.stderr)
        raise SystemExit(result.returncode)
    import win32serviceutil
    from .windows_service import NovaAgentService
    actions={"install-service":"install","uninstall-service":"remove","start":"start","stop":"stop"}
    win32serviceutil.HandleCommandLine(NovaAgentService, argv=["nova-agent",actions[a.command]])

if __name__=="__main__": main()
