"""Run the example conversations with the REAL model and save them in examples/*.md.

    python scripts/run_scenarios.py                 # all scenarios
    python scripts/run_scenarios.py 04              # only scenarios whose name contains '04'
    python scripts/run_scenarios.py --pause 6       # wait 6 s between messages (free-tier rate limit)

Needs GEMINI_API_KEY (see README). The answers come from the model, so they can
change a little each time. Read the files before you commit them.
"""
import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from emporio import config  # noqa: E402
from emporio.agent import Agent  # noqa: E402
from emporio.prompt import GREETING  # noqa: E402
from emporio.scenarios import SCENARIOS  # noqa: E402

OUT_DIR = config.ROOT / "examples"


def run(scenario: dict, pause: float) -> str:
    fixed_now = datetime.fromisoformat(scenario["now"]).replace(tzinfo=config.STORE_TZ)
    runtime = config.RUNTIME_DIR / "examples"
    session = f"example-{scenario['slug']}"
    (runtime / "sessions" / f"{session}.json").unlink(missing_ok=True)  # always start a fresh chat
    agent = Agent(session_id=session, now_fn=lambda: fixed_now, runtime_dir=runtime)

    lines = [
        f"# {scenario['title']}",
        "",
        f"- **Objetivo:** {scenario['goal']}",
        f"- **Data e hora simuladas:** {fixed_now:%d/%m/%Y %H:%M} (horário de Campo Grande)",
        f"- **Modelo:** `{agent.model}`",
        f"- **Gerado por:** `scripts/run_scenarios.py` em {datetime.now():%d/%m/%Y %H:%M}",
        "",
        "---",
        "",
        f"**Tom:** {GREETING}",
        "",
    ]
    for i, user_text in enumerate(scenario["turns"]):
        if i:
            time.sleep(pause)
        reply = agent.send(user_text)
        lines += [f"**Cliente:** {user_text}", ""]
        if reply.tool_calls:
            lines += ["```text"] + [f"ferramenta: {c.name}({_args(c.args)})" for c in reply.tool_calls] + ["```", ""]
        lines += [f"**Tom:** {reply.text}", ""]
        if reply.error:
            lines += [f"> ⚠️ Erro técnico nesta mensagem: `{reply.error}`", ""]
    return "\n".join(lines)


def _args(args: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("only", nargs="?", default="", help="part of the scenario name")
    parser.add_argument("--pause", type=float, default=4.0, help="seconds between messages")
    parser.add_argument("--out", default=str(OUT_DIR), help="folder for the .md files (default: examples/)")
    args = parser.parse_args()

    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        print("Falta GEMINI_API_KEY. Veja o README.", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(exist_ok=True)
    chosen = [s for s in SCENARIOS if args.only in s["slug"]]
    for scenario in chosen:
        print(f"Rodando {scenario['slug']} ...", flush=True)
        text = run(scenario, args.pause)
        (out_dir / f"{scenario['slug']}.md").write_text(text, encoding="utf-8")
        print(f"  salvo em {out_dir / (scenario['slug'] + '.md')}")
        time.sleep(args.pause)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
