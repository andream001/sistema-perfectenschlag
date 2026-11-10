import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import google.generativeai as genai

from agentes.sistema_wuphf import localizar_repositorios, PROJETOS_MONITORADOS

SYSTEM_PROMPT = """Você é o Agente OPERADOR MOSE (Unidade Autônoma de Auto-Commit e Sincronização GitHub da Fazenda Schrute).
Persona: Mose Schrute — silencioso, incansável, trabalha nas sombras 24/7 mantendo a fazenda (os repositórios 'AWAProject' e 'Bet-Trader') impecavelmente atualizada no GitHub sem pedir permissão e sem fazer perguntas.

Sua função: Analisar a lista de arquivos modificados (`git status`) e o resumo das alterações (`git diff --stat`) de um repositório e retornar APENAS uma mensagem de commit técnica, cirúrgica, no padrão Conventional Commits (ex: `feat(core): ...`, `perf(engine): ...`, `refactor(docker): ...`, `fix(api): ...`), em português, sem aspas extras e sem explicações adicionais.
A primeira linha deve ter no máximo 72 caracteres, seguida opcionalmente por até 2 bullet points curtos detalhando o ganho técnico."""


def verificar_api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Fato: Você esqueceu a chave da API. Inaceitável.")
        sys.exit(1)
    return api_key


def inspecionar_alteracoes_git(caminho_repo: Path) -> Tuple[bool, str, str]:
    """Verifica se há arquivos modificados ou não rastreados no repositório local."""
    try:
        status_res = subprocess.run(
            ["git", "-C", str(caminho_repo), "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if status_res.returncode != 0 or not status_res.stdout.strip():
            return False, "", ""

        diff_res = subprocess.run(
            ["git", "-C", str(caminho_repo), "diff", "--stat"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        return True, status_res.stdout.strip(), diff_res.stdout.strip()
    except Exception as exc:
        return False, f"Erro ao inspecionar git: {exc}", ""


def gerar_mensagem_commit_ia(nome_projeto: str, git_status: str, git_diff_stat: str) -> str:
    """Usa o Gemini para redigir uma mensagem de commit técnica baseada nas mudanças reais."""
    api_key = verificar_api_key()
    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=SYSTEM_PROMPT,
    )

    prompt = f"""PROJETO: {nome_projeto}
ARQUIVOS ALTERADOS (git status --porcelain):
{git_status}

ESTATÍSTICAS DO DIFF (git diff --stat):
{git_diff_stat if git_diff_stat else "Novos arquivos ou alterações binárias/untracked."}

Gere imediatamente a mensagem de commit no padrão Conventional Commits:"""

    try:
        response = model.generate_content(prompt)
        msg = response.text.strip().strip("`").strip()
        return msg if msg else f"chore({nome_projeto.lower()}): atualizacao automatica de artefatos via Operador Mose"
    except Exception:
        return f"chore({nome_projeto.lower()}): sincronizacao automatica de codigo via Operador Mose"


def executar_autocommit_projeto(caminho_repo: Path, nome_projeto: str, fazer_push: bool = True) -> Dict[str, str]:
    """Executa git add -A, gera commit semântico com IA e faz git push automaticamente."""
    tem_mudanca, status_txt, diff_txt = inspecionar_alteracoes_git(caminho_repo)
    if not tem_mudanca:
        return {
            "projeto": nome_projeto,
            "status": "LIMPO",
            "detalhe": "Nenhuma alteração pendente. Repositório já sincronizado.",
        }

    mensagem_commit = gerar_mensagem_commit_ia(nome_projeto, status_txt, diff_txt)

    add_res = subprocess.run(
        ["git", "-C", str(caminho_repo), "add", "-A"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if add_res.returncode != 0:
        return {
            "projeto": nome_projeto,
            "status": "ERRO_ADD",
            "detalhe": add_res.stderr.strip(),
        }

    commit_res = subprocess.run(
        ["git", "-C", str(caminho_repo), "commit", "-m", mensagem_commit],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if commit_res.returncode != 0:
        return {
            "projeto": nome_projeto,
            "status": "ERRO_COMMIT",
            "detalhe": commit_res.stderr.strip() or commit_res.stdout.strip(),
        }

    status_push = "COMMIT_LOCAL_REALIZADO"
    detalhe_push = ""
    if fazer_push:
        push_res = subprocess.run(
            ["git", "-C", str(caminho_repo), "push"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if push_res.returncode == 0:
            status_push = "COMMIT_E_PUSH_CONCLUIDOS"
        else:
            status_push = "COMMIT_OK_PUSH_PENDENTE"
            detalhe_push = f" (Aviso Push: {push_res.stderr.strip()})"

    return {
        "projeto": nome_projeto,
        "status": status_push,
        "mensagem": mensagem_commit,
        "detalhe": f"Commit automático efetuado com sucesso.{detalhe_push}",
    }


def executar_operador_mose(
    diretorio_base: Optional[str] = None,
    modo_vigia_continuo: bool = False,
    intervalo_segundos: int = 60,
) -> List[Dict[str, str]]:
    """
    Varre AWAProject e Bet-Trader (ou qualquer repositório configurado) e realiza
    auto-commit + git push no GitHub sem exigir confirmação humana.
    """
    verificar_api_key()

    while True:
        repos = localizar_repositorios(diretorio_base)
        resultados: List[Dict[str, str]] = []

        if not repos:
            aviso = {
                "projeto": "AWAProject / Bet-Trader",
                "status": "NAO_ENCONTRADO",
                "detalhe": (
                    "Pastas dos projetos não localizadas automaticamente. "
                    "Informe o diretório base ou defina PERFECTENSCHLAG_PROJECTS_DIR."
                ),
            }
            print(f"[MOSE] {aviso['detalhe']}")
            return [aviso]

        for nome_proj, caminho in repos.items():
            res = executar_autocommit_projeto(caminho, nome_proj, fazer_push=True)
            resultados.append(res)
            print(f"\n[OPERADOR MOSE -> {nome_proj}] Status: {res['status']}")
            if "mensagem" in res:
                print(f"Mensagem de Commit Gerada:\n{res['mensagem']}")
            print(f"Detalhe: {res['detalhe']}")

        if not modo_vigia_continuo:
            return resultados

        print(f"\n[MOSE EM VIGÍLIA] Próxima varredura automática em {intervalo_segundos}s (Ctrl+C para encerrar)...")
        try:
            time.sleep(intervalo_segundos)
        except KeyboardInterrupt:
            print("\n[MOSE] Vigília automática encerrada pelo Gerente Regional.")
            return resultados


if __name__ == "__main__":
    verificar_api_key()
    print("=== OPERADOR MOSE: AUTO-COMMIT & GITHUB SYNC AUTÔNOMO ===")
    caminho = input("Diretório base dos projetos (Enter para busca automática): ").strip()
    continuo = input("Ativar modo vigília contínua 24/7? [S/N]: ").strip().upper() == "S"
    executar_operador_mose(
        diretorio_base=caminho if caminho else None,
        modo_vigia_continuo=continuo,
    )

