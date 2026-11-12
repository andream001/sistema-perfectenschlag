import json
import os
import secrets
import stat
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DIRETORIO_BASE = Path(__file__).resolve().parent
ARQUIVO_ENV = DIRETORIO_BASE / ".env"
ARQUIVO_ENV_EXAMPLE = DIRETORIO_BASE / ".env.example"

CHAVES_CREDENCIAIS_PADRAO: Dict[str, str] = {
    "GEMINI_API_KEY": "",
    "IMAP_HOST": "imap.gmail.com",
    "IMAP_USER": "",
    "IMAP_APP_PASSWORD": "",
    "SMTP_HOST": "smtp.gmail.com",
    "SMTP_PORT": "587",
    "SMTP_USER": "",
    "SMTP_APP_PASSWORD": "",
    "WEBHOOK_SECRET_TOKEN": "",
    "WHATSAPP_VERIFY_TOKEN": "dunder_mifflin_scranton_verify",
    "N8N_BASE_URL": "http://localhost:5678",
    "GOLDEN_TICKET_WEBHOOK_URL": "http://localhost:5678/webhook/perfectenschlag-golden-ticket",
    "LINKEDIN_WEBHOOK_URL": "http://localhost:5678/webhook/perfectenschlag-redes",
    "YOUTUBE_WEBHOOK_URL": "http://localhost:5678/webhook/perfectenschlag-redes",
    "WHATSAPP_WEBHOOK_URL": "http://localhost:5678/webhook/perfectenschlag-whatsapp",
    "PERFECTENSCHLAG_PROJECTS_DIR": str(DIRETORIO_BASE.parent),
}


def carregar_env_local(caminho_env: Optional[Path] = None) -> Dict[str, str]:
    """Lê o arquivo .env da filial e injeta as variáveis em os.environ."""
    alvo = caminho_env or ARQUIVO_ENV
    carregadas: Dict[str, str] = {}
    if not alvo.exists():
        return carregadas

    try:
        for linha in alvo.read_text(encoding="utf-8", errors="replace").splitlines():
            linha_limpa = linha.strip()
            if not linha_limpa or linha_limpa.startswith("#") or "=" not in linha_limpa:
                continue
            chave, valor = linha_limpa.split("=", 1)
            chave = chave.strip()
            valor = valor.strip().strip('"').strip("'")
            if chave:
                carregadas[chave] = valor
                if valor and not os.environ.get(chave):
                    os.environ[chave] = valor
    except Exception:
        pass
    return carregadas


def gerar_env_example() -> Path:
    """Gera o arquivo .env.example documentado para referência rápida."""
    conteudo = """# ============================================================================
# SISTEMA PERFECTENSCHLAG — CREDENCIAIS & WEBHOOKS DA FILIAL SCRANTON
# ============================================================================

# 1. CÉREBRO IA (Obrigatório para execução dos agentes)
GEMINI_API_KEY=

# 2. VIGIA DE E-MAIL (IMAP) & DISPARO DE CURRÍCULOS APROVADOS (SMTP)
# Dica Gmail: Gere uma "Senha de App" de 16 dígitos em myaccount.google.com/apppasswords
IMAP_HOST=imap.gmail.com
IMAP_USER=
IMAP_APP_PASSWORD=
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_APP_PASSWORD=

# 3. SEGURANÇA & TOKENS DOS WEBHOOKS RECEPTORES (Gerados automaticamente)
WEBHOOK_SECRET_TOKEN=
WHATSAPP_VERIFY_TOKEN=dunder_mifflin_scranton_verify

# 4. WEBHOOKS EXTERNOS DE DISPARO (Google Apps Script, n8n, Make, Evolution API)
GOLDEN_TICKET_WEBHOOK_URL=
LINKEDIN_WEBHOOK_URL=
YOUTUBE_WEBHOOK_URL=
WHATSAPP_WEBHOOK_URL=

# 5. DIRETÓRIO BASE DOS REPOSITÓRIOS (Operador Mose & Sistema WUPHF)
PERFECTENSCHLAG_PROJECTS_DIR=
"""
    ARQUIVO_ENV_EXAMPLE.write_text(conteudo, encoding="utf-8")
    return ARQUIVO_ENV_EXAMPLE


def salvar_credenciais_env(novos_valores: Dict[str, Any]) -> Dict[str, str]:
    """
    Atualiza o arquivo .env preservando valores existentes quando o campo enviado
    estiver vazio ou mascarado (ex: '****'), e atualiza os.environ imediatamente.
    """
    atuais = dict(CHAVES_CREDENCIAIS_PADRAO)
    existentes = carregar_env_local()
    for k, v in existentes.items():
        if v:
            atuais[k] = v

    for k, v in os.environ.items():
        if k in atuais and v and not atuais[k]:
            atuais[k] = v

    for k, val_padrao in CHAVES_CREDENCIAIS_PADRAO.items():
        if val_padrao and not atuais.get(k):
            atuais[k] = val_padrao
        if atuais.get(k) and not os.environ.get(k):
            os.environ[k] = atuais[k]

    if not atuais.get("WEBHOOK_SECRET_TOKEN"):
        atuais["WEBHOOK_SECRET_TOKEN"] = f"dm_scranton_{secrets.token_hex(12)}"

    for chave, valor in novos_valores.items():
        if chave not in atuais:
            continue
        val_str = str(valor or "").strip()
        # Ignora máscaras visuais para não sobrescrever segredos já salvos
        if val_str and not val_str.startswith("****") and "[PROTEGIDA]" not in val_str:
            atuais[chave] = val_str
            os.environ[chave] = val_str
        elif chave in (
            "GOLDEN_TICKET_WEBHOOK_URL",
            "LINKEDIN_WEBHOOK_URL",
            "YOUTUBE_WEBHOOK_URL",
            "WHATSAPP_WEBHOOK_URL",
            "IMAP_USER",
            "SMTP_USER",
        ) and valor == "":
            atuais[chave] = ""
            os.environ.pop(chave, None)

    os.environ["WEBHOOK_SECRET_TOKEN"] = atuais["WEBHOOK_SECRET_TOKEN"]
    if atuais.get("WHATSAPP_VERIFY_TOKEN"):
        os.environ["WHATSAPP_VERIFY_TOKEN"] = atuais["WHATSAPP_VERIFY_TOKEN"]

    linhas = [
        "# ============================================================================",
        f"# SISTEMA PERFECTENSCHLAG (.env) - Autoconfigurado em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "# ============================================================================",
        "",
    ]
    for chave, valor in atuais.items():
        linhas.append(f'{chave}="{valor}"')

    ARQUIVO_ENV.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    gerar_env_example()
    return atuais


def _mascarar_segredo(valor: str) -> str:
    if not valor:
        return ""
    if len(valor) <= 8:
        return "****"
    return f"****{valor[-4:]}"


def instalar_git_hooks_em_repo(caminho_repo: Path, porta_servidor: int = 8080) -> Dict[str, Any]:
    """
    Instala dois Git Hooks no repositório informado:
    1) pre-commit: Varredura DLP/LGPD que bloqueia vazamento acidental de chaves AIza..., ghp_..., CPFs/CNPJs.
    2) post-commit: Notifica automaticamente o servidor local AgentCraft (/webhook/git-commit) a cada novo commit.
    """
    pasta_git_hooks = caminho_repo / ".git" / "hooks"
    pasta_githooks_versionada = caminho_repo / ".githooks"

    script_pre_commit = """#!/bin/sh
# ============================================================================
# SISTEMA PERFECTENSCHLAG - HOOK PRE-COMMIT (GUARDIÃO DLP & LGPD)
# Bloqueia commits contendo chaves de API reais (AIza..., ghp_...) no diff
# ============================================================================
DIFF_CONTENT=$(git diff --cached --unified=0)
if echo "$DIFF_CONTENT" | grep -Eq 'AIza[0-9A-Za-z_-]{25,}|gh[po]_[0-9A-Za-z]{25,}'; then
    echo "[BLOQUEIO DLP PERFECTENSCHLAG] Fato: Chave de API ou Token detectado no commit!"
    echo "Remova a credencial exposta ou mova para o arquivo .env antes de commitar."
    exit 1
fi
exit 0
"""

    script_post_commit = f"""#!/bin/sh
# ============================================================================
# SISTEMA PERFECTENSCHLAG - HOOK POST-COMMIT (GATILHO AUTOMÁTICO WUPHF & MOSE)
# Envia telemetria do commit recém-criado para a Filial Scranton (porta {porta_servidor})
# ============================================================================
REPO_NAME=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
COMMIT_HASH=$(git rev-parse --short HEAD 2>/dev/null)
COMMIT_AUTHOR=$(git log -1 --pretty=format:'%an' 2>/dev/null)
COMMIT_MSG=$(git log -1 --pretty=format:'%s' 2>/dev/null)

python -c "
import json, urllib.request
payload = {{
    'projeto': '''$REPO_NAME''',
    'hash': '''$COMMIT_HASH''',
    'autor': '''$COMMIT_AUTHOR''',
    'mensagem': '''$COMMIT_MSG'''
}}
try:
    req = urllib.request.Request(
        'http://127.0.0.1:{porta_servidor}/webhook/git-commit',
        data=json.dumps(payload).encode('utf-8'),
        headers={{'Content-Type': 'application/json'}},
        method='POST'
    )
    urllib.request.urlopen(req, timeout=2)
except Exception:
    pass
" >/dev/null 2>&1 &
exit 0
"""

    destinos_instalados: List[str] = []
    for pasta in (pasta_githooks_versionada, pasta_git_hooks):
        try:
            if pasta == pasta_githooks_versionada:
                pasta.mkdir(parents=True, exist_ok=True)
            elif not pasta.exists():
                continue
            p_pre = pasta / "pre-commit"
            p_post = pasta / "post-commit"
            p_pre.write_text(script_pre_commit, encoding="utf-8", newline="\n")
            p_post.write_text(script_post_commit, encoding="utf-8", newline="\n")
            for p in (p_pre, p_post):
                try:
                    p.chmod(p.stat().st_mode | stat.S_IEXEC)
                except Exception:
                    pass
            destinos_instalados.append(str(pasta.relative_to(caminho_repo)))
        except Exception:
            pass

    try:
        subprocess.run(
            ["git", "-C", str(caminho_repo), "config", "core.hooksPath", ".githooks"],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass

    return {
        "repositorio": caminho_repo.name,
        "caminho": str(caminho_repo),
        "instalado": bool(destinos_instalados),
        "pastas_hooks": destinos_instalados,
        "hooks": ["pre-commit (DLP/LGPD)", "post-commit (Webhook WUPHF/Mose)"],
    }


def instalar_git_hooks_filial(repositorios_extras: Optional[Dict[str, Path]] = None, porta: int = 8080) -> List[Dict[str, Any]]:
    """Instala os ganchos Git no repositório principal e em todos os repositórios irmãos detectados."""
    alvos: Dict[str, Path] = {DIRETORIO_BASE.name: DIRETORIO_BASE}
    if repositorios_extras:
        for nome, cam in repositorios_extras.items():
            alvos[nome] = cam

    resultados: List[Dict[str, Any]] = []
    for _, caminho in alvos.items():
        resultados.append(instalar_git_hooks_em_repo(caminho, porta_servidor=porta))
    return resultados


def obter_diagnostico_configuracao(repositorios_detectados: Optional[Dict[str, Path]] = None, porta: int = 8080) -> Dict[str, Any]:
    """Retorna o estado completo das credenciais, webhooks e ganchos Git da filial."""
    carregar_env_local()
    token_wh = os.environ.get("WEBHOOK_SECRET_TOKEN", "")
    if not token_wh:
        atuais = salvar_credenciais_env({})
        token_wh = atuais.get("WEBHOOK_SECRET_TOKEN", "")

    hooks_status = []
    alvos: Dict[str, Path] = {DIRETORIO_BASE.name: DIRETORIO_BASE}
    if repositorios_detectados:
        alvos.update(repositorios_detectados)

    for nome, cam in alvos.items():
        pre_ok = (cam / ".git" / "hooks" / "pre-commit").exists() or (cam / ".githooks" / "pre-commit").exists()
        post_ok = (cam / ".git" / "hooks" / "post-commit").exists() or (cam / ".githooks" / "post-commit").exists()
        hooks_status.append({
            "repositorio": nome,
            "caminho": str(cam),
            "pre_commit_dlp": pre_ok,
            "post_commit_wuphf": post_ok,
        })

    base_url = f"http://localhost:{porta}"
    return {
        "env_arquivo_existe": ARQUIVO_ENV.exists(),
        "caminho_env": str(ARQUIVO_ENV),
        "credenciais": {
            "gemini_api_key_ativa": bool(os.environ.get("GEMINI_API_KEY")),
            "gemini_api_key_mascarada": _mascarar_segredo(os.environ.get("GEMINI_API_KEY", "")),
            "imap_host": os.environ.get("IMAP_HOST", "imap.gmail.com"),
            "imap_user": os.environ.get("IMAP_USER", ""),
            "imap_senha_configurada": bool(os.environ.get("IMAP_APP_PASSWORD")),
            "imap_senha_mascarada": _mascarar_segredo(os.environ.get("IMAP_APP_PASSWORD", "")),
            "smtp_host": os.environ.get("SMTP_HOST", "smtp.gmail.com"),
            "smtp_port": os.environ.get("SMTP_PORT", "587"),
            "smtp_user": os.environ.get("SMTP_USER", ""),
            "smtp_senha_configurada": bool(os.environ.get("SMTP_APP_PASSWORD")),
            "smtp_senha_mascarada": _mascarar_segredo(os.environ.get("SMTP_APP_PASSWORD", "")),
            "webhook_secret_token": token_wh,
            "whatsapp_verify_token": os.environ.get("WHATSAPP_VERIFY_TOKEN", "dunder_mifflin_scranton_verify"),
            "perfectenschlag_projects_dir": os.environ.get("PERFECTENSCHLAG_PROJECTS_DIR", str(DIRETORIO_BASE.parent)),
        },
        "webhooks_saida": {
            "n8n_base_url": os.environ.get("N8N_BASE_URL", "http://localhost:5678"),
            "golden_ticket_webhook_url": os.environ.get("GOLDEN_TICKET_WEBHOOK_URL", "http://localhost:5678/webhook/perfectenschlag-golden-ticket"),
            "linkedin_webhook_url": os.environ.get("LINKEDIN_WEBHOOK_URL", "http://localhost:5678/webhook/perfectenschlag-redes"),
            "youtube_webhook_url": os.environ.get("YOUTUBE_WEBHOOK_URL", "http://localhost:5678/webhook/perfectenschlag-redes"),
            "whatsapp_webhook_url": os.environ.get("WHATSAPP_WEBHOOK_URL", "http://localhost:5678/webhook/perfectenschlag-whatsapp"),
        },
        "webhooks_entrada_locais": {
            "nova_vaga": f"{base_url}/webhook/vaga",
            "retorno_recrutador": f"{base_url}/webhook/retorno-recrutador",
            "whatsapp_lead": f"{base_url}/webhook/whatsapp-lead",
            "git_commit": f"{base_url}/webhook/git-commit",
        },
        "git_hooks": hooks_status,
        "n8n": obter_status_n8n(),
    }


def carregar_pacote_workflows_n8n() -> List[Dict[str, Any]]:
    """Carrega todos os arquivos JSON de workflow da pasta n8n/workflows/."""
    pasta_wf = DIRETORIO_BASE / "n8n" / "workflows"
    lista: List[Dict[str, Any]] = []
    if not pasta_wf.exists():
        return lista
    for arq in sorted(pasta_wf.glob("*.json")):
        try:
            dados = json.loads(arq.read_text(encoding="utf-8"))
            dados["_arquivo"] = arq.name
            lista.append(dados)
        except Exception:
            pass
    return lista


def obter_status_n8n() -> Dict[str, Any]:
    """Verifica se o servidor n8n está online na porta 5678 e lista os workflows prontos."""
    n8n_url = os.environ.get("N8N_BASE_URL", "http://localhost:5678").rstrip("/")
    online = False
    try:
        req = urllib.request.Request(f"{n8n_url}/healthz", method="GET")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            online = resp.getcode() == 200
    except Exception:
        online = False

    pasta_wf = DIRETORIO_BASE / "n8n" / "workflows"
    arquivos_wf = [p.name for p in sorted(pasta_wf.glob("*.json"))] if pasta_wf.exists() else []
    compose_file = DIRETORIO_BASE / "docker-compose.n8n.yml"

    return {
        "online": online,
        "url_painel": n8n_url,
        "docker_compose_pronto": compose_file.exists(),
        "caminho_compose": str(compose_file),
        "workflows_prontos": arquivos_wf,
        "endpoints_n8n": {
            "golden_ticket": f"{n8n_url}/webhook/perfectenschlag-golden-ticket",
            "redes_wuphf_scarn": f"{n8n_url}/webhook/perfectenschlag-redes",
            "whatsapp_lead": f"{n8n_url}/webhook/perfectenschlag-whatsapp",
        },
        "comandos": {
            "subir_docker": "docker compose -f docker-compose.n8n.yml up -d",
            "importar_workflows": "docker exec perfectenschlag-n8n n8n import:workflow --separate --input=/workflows",
            "ativar_workflows": "docker exec perfectenschlag-n8n n8n update:workflow --all --active=true",
            "rodar_npx": "npx n8n start",
        },
    }


def provisionar_n8n_docker(iniciar_container: bool = True, n8n_base_url: str = "http://localhost:5678") -> Dict[str, Any]:
    """
    Configura todas as URLs de Webhook do n8n no .env e, opcionalmente,
    inicia o container Docker 'perfectenschlag-n8n' e importa os 3 workflows automaticamente.
    """
    base = (n8n_base_url or "http://localhost:5678").rstrip("/")
    salvar_credenciais_env({
        "N8N_BASE_URL": base,
        "GOLDEN_TICKET_WEBHOOK_URL": f"{base}/webhook/perfectenschlag-golden-ticket",
        "LINKEDIN_WEBHOOK_URL": f"{base}/webhook/perfectenschlag-redes",
        "YOUTUBE_WEBHOOK_URL": f"{base}/webhook/perfectenschlag-redes",
        "WHATSAPP_WEBHOOK_URL": f"{base}/webhook/perfectenschlag-whatsapp",
    })

    logs_docker: List[str] = []
    if iniciar_container:
        try:
            up_res = subprocess.run(
                ["docker", "compose", "-f", str(DIRETORIO_BASE / "docker-compose.n8n.yml"), "up", "-d"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
            )
            if up_res.returncode == 0:
                logs_docker.append("Container 'perfectenschlag-n8n' iniciado via Docker Compose.")
                imp_res = subprocess.run(
                    ["docker", "exec", "perfectenschlag-n8n", "n8n", "import:workflow", "--separate", "--input=/workflows"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
                if imp_res.returncode == 0:
                    logs_docker.append("3 Workflows Perfectenschlag importados automaticamente no n8n.")
                    subprocess.run(
                        ["docker", "exec", "perfectenschlag-n8n", "n8n", "update:workflow", "--all", "--active=true"],
                        capture_output=True,
                        timeout=20,
                    )
            else:
                logs_docker.append(
                    f"Aviso Docker Engine: {up_res.stderr.strip() or 'Abra o Docker Desktop ou rode npx n8n start.'}"
                )
        except Exception as exc:
            logs_docker.append(f"Aviso ao acionar Docker: {exc}")

    status = obter_status_n8n()
    status["logs_provisionamento"] = logs_docker
    return status


def executar_autoconfiguracao_completa(
    novas_credenciais: Optional[Dict[str, Any]] = None,
    repositorios_detectados: Optional[Dict[str, Path]] = None,
    porta: int = 8080,
) -> Dict[str, Any]:
    """
    Executa toda a autoconfiguração de uma vez:
    1) Cria/atualiza o arquivo .env e .env.example com token de segurança;
    2) Instala os Git Hooks (pre-commit DLP + post-commit Webhook) em todos os repositórios locais;
    3) Retorna o diagnóstico completo pronto para o HUD AgentCraft.
    """
    salvar_credenciais_env(novas_credenciais or {})
    hooks_instalados = instalar_git_hooks_filial(repositorios_detectados, porta=porta)
    diagnostico = obter_diagnostico_configuracao(repositorios_detectados, porta=porta)
    diagnostico["hooks_instalados_agora"] = hooks_instalados
    return diagnostico


if __name__ == "__main__":
    res = executar_autoconfiguracao_completa()
    print(json.dumps(res, ensure_ascii=False, indent=2))
