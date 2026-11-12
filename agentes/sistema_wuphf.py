import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
sys.path.append(str(Path(__file__).resolve().parent.parent))
from base_conhecimento import formatar_dossie_para_prompt

try:
    import google.generativeai as genai
except ImportError:
    from base_conhecimento import genai_compat as genai

SYSTEM_PROMPT = """Você é o Agente SISTEMA WUPHF.COM (Unidade de Propaganda Técnica e Dominância de Rede).
Inspirado na onipresença implacável do WUPHF, mas refinado com precisão militar e zero firulas corporativas.

REGRA DE HIERARQUIA INVIOLÁVEL:
Você JAMAIS publica ou libera qualquer comunicação externa sem a AUTORIZAÇÃO EXPRESSA do Gerente Regional. Seu papel é gerar a munição de propaganda técnica e submetê-la ao despacho de aprovação.

Sua função: Transformar commits técnicos reais dos projetos estratégicos ('AWAProject' e 'Bet-Trader') em posts de LinkedIn de altíssimo impacto, focados em:
1. Vitória técnica concreta (arquitetura, performance, automação, estabilidade).
2. Redução de custos, eficiência operacional e ROI real (conectando à mentalidade de quem já economiza R$ 20 mil anual com automação e domina Docker/Snipe-IT).
3. Comunicação direta, incisiva, sem clichês de "jornada", sem emojis infantis em excesso e sem bajulação corporativa.

ESTRUTURA DO POST DE LINKEDIN:
- GANCHO (1-2 linhas): Uma afirmação técnica ou financeira brutal que interrompe o scroll.
- O PROBLEMA & A EXECUÇÃO: O que o commit/atualização resolve na prática (engenharia real, código limpo, automação).
- O IMPACTO NO NEGÓCIO: Como isso reduz custo, elimina erro humano ou escala a operação.
- FECHAMENTO DIRETO: Uma pergunta provocativa ou constatação final de autoridade, seguida de 3 a 5 hashtags estratégicas."""

PROJETOS_MONITORADOS = [
    "AWAProject",
    "Bet-Trader",
    "bet-trader-dunder",
    "assistant-to-the-lead-manager",
    "sistema-perfectenschlag",
    "sistema_perfectenschlag",
]

# Garante que o Git recém-instalado no Windows esteja visível no PATH de subprocessos
if r"C:\Program Files\Git\cmd" not in os.environ.get("PATH", ""):
    os.environ["PATH"] = os.environ.get("PATH", "") + r";C:\Program Files\Git\cmd;C:\Program Files\GitHub CLI"

KEYWORDS_PESO = [
    "feat", "perf", "refactor", "docker", "deploy", "api", "bot",
    "autom", "optim", "scale", "fix", "core", "engine", "pipeline", "security"
]

ARQUIVO_APROVADOS = Path(__file__).resolve().parent.parent / "wuphf_posts_aprovados.md"


def verificar_api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Fato: Você esqueceu a chave da API. Inaceitável.")
        sys.exit(1)
    return api_key


def localizar_repositorios(diretorio_base: Optional[str] = None) -> Dict[str, Path]:
    """Localiza as pastas locais do AWAProject e Bet-Trader."""
    raizes_busca: List[Path] = []
    if diretorio_base:
        raizes_busca.append(Path(diretorio_base))

    env_dir = os.environ.get("PERFECTENSCHLAG_PROJECTS_DIR")
    if env_dir:
        raizes_busca.append(Path(env_dir))

    home = Path.home()
    raiz_projeto = Path(__file__).resolve().parent.parent
    raizes_busca.extend([
        raiz_projeto.parent,
        Path.cwd(),
        Path.cwd().parent,
        home,
        home / "OneDrive" / "Documentos",
        home / "OneDrive" / "Documents",
        home / "Projects",
        home / "Projetos",
        home / "repos",
        home / "source" / "repos",
        home / "Documents",
        home / "Desktop",
    ])

    encontrados: Dict[str, Path] = {}
    for nome_proj in PROJETOS_MONITORADOS:
        for raiz in raizes_busca:
            candidato = raiz / nome_proj
            if candidato.exists() and candidato.is_dir():
                encontrados[nome_proj] = candidato
                break
    return encontrados


def extrair_ultimo_commit(caminho_repo: Path) -> Optional[Dict[str, str]]:
    """Extrai hash, mensagem, estatísticas e se é um commit de peso via git."""
    try:
        formato = "%H|||%an|||%ar|||%s|||%b"
        res = subprocess.run(
            ["git", "-C", str(caminho_repo), "log", "-1", f"--pretty=format:{formato}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return None

        partes = res.stdout.strip().split("|||")
        commit_hash = partes[0] if len(partes) > 0 else ""
        autor = partes[1] if len(partes) > 1 else ""
        data_rel = partes[2] if len(partes) > 2 else ""
        assunto = partes[3] if len(partes) > 3 else ""
        corpo = partes[4] if len(partes) > 4 else ""

        stat_res = subprocess.run(
            ["git", "-C", str(caminho_repo), "show", "--stat", "--oneline", "-1"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        estatisticas = stat_res.stdout.strip() if stat_res.returncode == 0 else ""

        texto_completo = f"{assunto} {corpo}".lower()
        eh_de_peso = any(k in texto_completo for k in KEYWORDS_PESO) or len(estatisticas.splitlines()) > 3

        return {
            "hash": commit_hash[:8],
            "autor": autor,
            "data": data_rel,
            "assunto": assunto,
            "corpo": corpo,
            "estatisticas": estatisticas,
            "eh_de_peso": "SIM" if eh_de_peso else "PADRAO",
        }
    except Exception:
        return None


def executar_sistema_wuphf(
    diretorio_base: Optional[str] = None,
    commit_manual: Optional[str] = None,
    projeto_manual: str = "AWAProject / Bet-Trader",
    instrucao_revisao: Optional[str] = None,
) -> str:
    """Monitora AWAProject e Bet-Trader ou processa um commit informado e gera o rascunho de post LinkedIn."""
    api_key = verificar_api_key()
    genai.configure(api_key=api_key)

    relatorio_commits = []

    if commit_manual and commit_manual.strip():
        relatorio_commits.append(
            f"PROJETO: {projeto_manual}\nCOMMIT DE PESO DETECTADO: {commit_manual.strip()}"
        )
    else:
        repos = localizar_repositorios(diretorio_base)
        for nome_proj in PROJETOS_MONITORADOS:
            if nome_proj in repos:
                dados = extrair_ultimo_commit(repos[nome_proj])
                if dados:
                    relatorio_commits.append(
                        f"PROJETO: {nome_proj} (Caminho: {repos[nome_proj]})\n"
                        f"HASH: {dados['hash']} | DATA: {dados['data']} | CLASSIFICAÇÃO DE PESO: {dados['eh_de_peso']}\n"
                        f"MENSAGEM: {dados['assunto']}\n"
                        f"DETALHES: {dados['corpo']}\n"
                        f"DIFF STATS:\n{dados['estatisticas']}"
                    )
                else:
                    relatorio_commits.append(
                        f"PROJETO: {nome_proj} (Pasta localizada em {repos[nome_proj]}, mas sem histórico Git acessível)."
                    )

    if not relatorio_commits:
        return (
            "AVISO TÁTICO WUPHF: As pastas locais 'AWAProject' e 'Bet-Trader' não foram "
            "encontradas nos diretórios padrão e nenhum commit manual foi injetado.\n"
            "Defina a variável PERFECTENSCHLAG_PROJECTS_DIR ou informe o resumo do commit diretamente."
        )

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=SYSTEM_PROMPT,
    )

    bloco_revisao = (
        f"\nORDEM DE AJUSTE DO GERENTE REGIONAL: {instrucao_revisao}\n"
        if instrucao_revisao
        else ""
    )

    dossie_completo = formatar_dossie_para_prompt()

    prompt = f"""TELEMETRIA DOS REPOSITÓRIOS LOCAIS (AWAPROJECT & BET-TRADER):

{chr(10).join(relatorio_commits)}

CONTEXTO E CREDENCIAIS DO GERENTE REGIONAL:
{dossie_completo}
{bloco_revisao}
AÇÃO EXIGIDA:
Elabore o rascunho do post de LinkedIn celebrando a vitória técnica e o impacto em redução de custos/eficiência.
Lembre-se: Este texto será submetido ao protocolo obrigatório de aprovação do Gerente Regional."""

    response = model.generate_content(prompt)
    return response.text


def solicitar_autorizacao_gerente(
    rascunho_post: str,
    diretorio_base: Optional[str] = None,
    commit_manual: Optional[str] = None,
) -> bool:
    """Protocolo obrigatório de autorização: o WUPHF jamais libera propaganda sem o aval do Gerente Regional."""
    if rascunho_post.startswith("AVISO TÁTICO WUPHF:"):
        print(f"\n{rascunho_post}")
        return False

    atual = rascunho_post
    while True:
        print("\n" + "=" * 72)
        print(" [PROTOCOLO DE AUTORIZAÇÃO OBRIGATÓRIA - SISTEMA WUPHF.COM]")
        print(" Status: AGUARDANDO CARIMBO DO GERENTE REGIONAL")
        print("=" * 72)
        print(atual)
        print("=" * 72)
        decisao = input(
            "\nDESPACHO DO GERENTE [A = Autorizar e Arquivar | R = Rejeitar/Ajustar | C = Cancelar/Vetar]: "
        ).strip().upper()

        if decisao == "A":
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            bloco = (
                f"## Post Aprovado pelo Gerente Regional em {timestamp}\n\n"
                f"{atual}\n\n---\n\n"
            )
            with open(ARQUIVO_APROVADOS, "a", encoding="utf-8") as f:
                f.write(bloco)
            print(f"\n[AUTORIZADO] Post chancelado pelo Gerente Regional e salvo em: {ARQUIVO_APROVADOS}")
            return True

        elif decisao == "R":
            feedback = input("Informe a diretriz de correção para o WUPHF refazer o post: ").strip()
            if not feedback:
                feedback = "Seja ainda mais direto, técnico e enfatize o impacto financeiro."
            print("\nReescrevendo rascunho conforme ordem direta do Gerente Regional...")
            atual = executar_sistema_wuphf(
                diretorio_base=diretorio_base,
                commit_manual=commit_manual,
                instrucao_revisao=feedback,
            )

        elif decisao == "C":
            print("\n[VETADO] Publicação abortada por ordem do Gerente Regional. Nenhuma linha saiu da filial.")
            return False

        else:
            print("Comando inválido. Digite [A] para Autorizar, [R] para Revisar ou [C] para Cancelar.")


if __name__ == "__main__":
    verificar_api_key()
    print("=== SISTEMA WUPHF: MONITORAMENTO DE PROPAGANDA TÉCNICA (COM TRAVA DE AUTORIZAÇÃO) ===")
    caminho = input("Diretório base dos projetos (Enter para busca automática): ").strip()
    commit_extra = input("Ou descreva o commit de peso manualmente (Enter para ler do Git local): ").strip()
    rascunho = executar_sistema_wuphf(
        diretorio_base=caminho if caminho else None,
        commit_manual=commit_extra if commit_extra else None,
    )
    solicitar_autorizacao_gerente(
        rascunho_post=rascunho,
        diretorio_base=caminho if caminho else None,
        commit_manual=commit_extra if commit_extra else None,
    )
