"""Command-line chat.

    python -m emporio                      # new chat
    python -m emporio --session maria      # continue (or create) the chat called 'maria'
    python -m emporio -v                   # also show which tools the agent used
    python -m emporio --now 2026-11-07T14:00   # freeze the clock (store closed on Saturday afternoon)
"""
import argparse
import os
import sys

from . import config
from .prompt import GREETING


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="emporio", description="Chat com o Tom, assistente do Empório da Música.")
    parser.add_argument("--session", help="nome da conversa (continua se já existir)")
    parser.add_argument("--now", help="data e hora fixas, ex.: 2026-11-07T14:00")
    parser.add_argument("-v", "--verbose", action="store_true", help="mostra as ferramentas usadas")
    args = parser.parse_args(argv)

    # Some Windows terminals cannot print accents or emoji. Never crash because of that.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.now:
        os.environ["EMPORIO_NOW"] = args.now  # config.now() reads it

    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        print("Falta a chave da API. Copie .env.example para .env e preencha GEMINI_API_KEY.\n"
              "Pegue uma chave grátis em https://aistudio.google.com/apikey", file=sys.stderr)
        return 1

    from .agent import Agent  # imported here so --help works without the SDK key

    agent = Agent(session_id=args.session)
    print(f"[conversa: {agent.session_id} | modelo: {agent.model} | /sair para encerrar]\n")
    resumed = len(agent.messages) // 2
    if resumed:
        print(f"[conversa retomada: {resumed} trocas de mensagens anteriores]\n")
    print(f"Tom: {GREETING}\n")

    while True:
        try:
            text = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            continue
        if text.lower() in ("/sair", "/exit", "/quit"):
            return 0

        reply = agent.send(text)
        if args.verbose:
            for call in reply.tool_calls:
                print(f"   [ferramenta] {call.name}({call.args})")
        print(f"\nTom: {reply.text}\n")
        if reply.error:
            print(f"   [erro técnico] {reply.error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
