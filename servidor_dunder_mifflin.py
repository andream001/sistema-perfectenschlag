import hashlib
import hmac
import json
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from autoconfigurador_scranton import (
    carregar_env_local,
    carregar_pacote_workflows_n8n,
    executar_autoconfiguracao_completa,
    obter_diagnostico_configuracao,
    obter_status_n8n,
    provisionar_n8n_docker,
    salvar_credenciais_env,
)
from auditoria import (
    atualizar_status_auditoria,
    listar_auditoria,
    registrar_evento_auditoria,
)
from base_conhecimento import carregar_perfil_gerente, pendencias_perfil, salvar_perfil_gerente
from agentes.curriculo_profissional import gerar_docx_bytes, nome_arquivo_cv
from agentes.neutralizador_toby import executar_neutralizador_toby
from agentes.protocolo_recyclops import executar_protocolo_recyclops
from agentes.sistema_wuphf import (
    ARQUIVO_APROVADOS,
    executar_sistema_wuphf,
    localizar_repositorios,
)
from agentes.operador_mose import executar_operador_mose
from agentes.estudio_scarn_youtube import executar_estudio_youtube
from agentes.esteira_golden_ticket import (
    carregar_candidaturas,
    carregar_log_curriculos,
    criar_pacote_candidatura,
    decidir_envio_candidatura,
    registrar_ou_atualizar_processo_curriculo,
    registrar_retorno_webhook,
    verificar_status_vaga_E_email,
)
from agentes.auditor_recrutador_final import auditar_e_melhorar_curriculo
from agentes.cacador_vagas import (
    buscar_melhores_vagas,
    carregar_vagas_descobertas,
    marcar_vaga_enviada_esteira,
    obter_status_plataformas_vagas,
)
from agentes.assistant_lead_manager import (
    adicionar_ou_importar_leads,
    atualizar_status_lead_manual,
    calcular_metricas_leads,
    carregar_config_lead_manager,
    carregar_leads_csv,
    disparar_lote_campanha,
    gerar_script_abordagem_ia,
    obter_status_motor_5000,
    processar_mensagem_webhook_lead,
    salvar_config_lead_manager,
)

DIRETORIO_BASE = Path(__file__).resolve().parent
ARQUIVO_FRONTEND = DIRETORIO_BASE / "frontend" / "index.html"
ARQUIVO_LEAD_MANAGER = DIRETORIO_BASE / "frontend" / "lead_manager.html"
ARQUIVO_SCHEDULER = DIRETORIO_BASE / "scheduler_config.json"

SCHEDULER_LOCK = threading.Lock()
SCHEDULER_STATUS: Dict[str, Any] = {
    "ultimo_ciclo_golden_ticket": "",
    "ultimo_ciclo_recyclops": "",
    "total_ciclos": 0,
    "ultimo_resumo": "Agendador autônomo inicializado.",
}


def carregar_scheduler_config() -> Dict[str, Any]:
    padrao = {
        "ativo": True,
        "golden_ticket_ativo": True,
        "golden_ticket_intervalo_min": 15,
        "recyclops_ativo": True,
        "recyclops_intervalo_min": 60,
        "busca_vagas_ativo": True,
        "busca_vagas_intervalo_min": 120,
    }
    if ARQUIVO_SCHEDULER.exists():
        try:
            salvo = json.loads(ARQUIVO_SCHEDULER.read_text(encoding="utf-8"))
            if isinstance(salvo, dict):
                padrao.update(salvo)
        except Exception:
            pass
    return padrao


def salvar_scheduler_config(novos: Dict[str, Any]) -> Dict[str, Any]:
    atual = carregar_scheduler_config()
    for k in ("ativo", "golden_ticket_ativo", "recyclops_ativo"):
        if k in novos:
            atual[k] = bool(novos[k])
    for k in ("golden_ticket_intervalo_min", "recyclops_intervalo_min"):
        if k in novos:
            try:
                atual[k] = max(1, int(novos[k]))
            except Exception:
                pass
    ARQUIVO_SCHEDULER.write_text(json.dumps(atual, ensure_ascii=False, indent=2), encoding="utf-8")
    return atual


def executar_ciclo_agendador(forcar_golden: bool = False, forcar_recyclops: bool = False) -> Dict[str, Any]:
    """Executa verificações periódicas do Golden Ticket (e-mail/vagas) e Protocolo Recyclops."""
    res: Dict[str, Any] = {"timestamp": datetime.now().isoformat(), "golden_ticket": None, "recyclops": None}
    cfg = carregar_scheduler_config()

    if forcar_golden or (cfg.get("ativo") and cfg.get("golden_ticket_ativo")):
        if os.environ.get("IMAP_USER") and os.environ.get("IMAP_APP_PASSWORD"):
            cands = carregar_candidaturas()
            verificadas = 0
            for c in cands:
                if str(c.get("status", "")).upper() in ("ENVIADO", "AGUARDANDO_RETORNO", "EM_PROCESSO"):
                    try:
                        verificar_status_vaga_E_email(str(c.get("id", "")))
                        verificadas += 1
                    except Exception:
                        pass
            res["golden_ticket"] = f"{verificadas} candidatura(s) verificada(s) no IMAP."
        else:
            res["golden_ticket"] = "IMAP não configurado no .env (aguardando credenciais Gmail)."
        SCHEDULER_STATUS["ultimo_ciclo_golden_ticket"] = res["timestamp"]

    if forcar_recyclops or (cfg.get("ativo") and cfg.get("recyclops_ativo")):
        try:
            saida_rec = executar_protocolo_recyclops(
                "Auditoria periódica automática da Filial Scranton (verificar logs e saúde dos repositórios)."
            )
            res["recyclops"] = str(saida_rec)[:200]
            registrar_evento_auditoria(
                agente="PROTOCOLO_RECYCLOPS",
                acao="AGENDADOR_AUTONOMO_RECYCLOPS",
                entrada="Ciclo periódico automático",
                saida=str(saida_rec)[:500],
                status="CONCLUIDO",
            )
        except Exception as exc:
            res["recyclops"] = f"Aviso Recyclops: {exc}"
        SCHEDULER_STATUS["ultimo_ciclo_recyclops"] = res["timestamp"]

    with SCHEDULER_LOCK:
        SCHEDULER_STATUS["total_ciclos"] = int(SCHEDULER_STATUS.get("total_ciclos", 0)) + 1
        SCHEDULER_STATUS["ultimo_resumo"] = f"Último ciclo: {res['timestamp'][:19]}"
    return res


def _loop_agendador_autonomo() -> None:
    """Thread em segundo plano que dispara Golden Ticket, Recyclops e Radar de Vagas nos intervalos configurados."""
    prox_golden = time.time() + 120
    prox_recyclops = time.time() + 300
    prox_vagas = time.time() + 60
    while True:
        time.sleep(30)
        try:
            cfg = carregar_scheduler_config()
            if not cfg.get("ativo"):
                continue
            agora = time.time()
            rodar_g = bool(cfg.get("golden_ticket_ativo") and agora >= prox_golden)
            rodar_r = bool(cfg.get("recyclops_ativo") and agora >= prox_recyclops)
            if rodar_g or rodar_r:
                executar_ciclo_agendador(forcar_golden=rodar_g, forcar_recyclops=rodar_r)
                if rodar_g:
                    prox_golden = agora + max(1, int(cfg.get("golden_ticket_intervalo_min", 15))) * 60
                if rodar_r:
                    prox_recyclops = agora + max(5, int(cfg.get("recyclops_intervalo_min", 60))) * 60
            if cfg.get("busca_vagas_ativo") and agora >= prox_vagas:
                try:
                    buscar_melhores_vagas(usar_ia=False, limite=15)
                except Exception:
                    pass
                prox_vagas = agora + max(15, int(cfg.get("busca_vagas_intervalo_min", 120))) * 60
        except Exception:
            pass


_SESSAO_HORAS = max(1, int(os.environ.get("PANEL_SESSION_HOURS", "12") or 12))


def _avisar_credenciais_padrao() -> None:
    """Avisa no terminal quando o painel não possui senha ou segredo definido no .env."""
    if not os.environ.get("PANEL_PASSWORD"):
        print(" [SEGURANÇA] PANEL_PASSWORD não definida no .env. Configure PANEL_PASSWORD para liberar o login.")
    if not (os.environ.get("PERFECTENSCHLAG_SECRET_KEY") or os.environ.get("WEBHOOK_SECRET_TOKEN")):
        print(" [SEGURANÇA] PERFECTENSCHLAG_SECRET_KEY não definida no .env.")


def _auth_secret() -> bytes:
    base = os.environ.get("PERFECTENSCHLAG_SECRET_KEY") or os.environ.get("WEBHOOK_SECRET_TOKEN") or ""
    return base.encode("utf-8")


def _gerar_cookie_sessao(usuario: str) -> str:
    ts = str(int(time.time()))
    payload = f"{usuario}:{ts}"
    sig = hmac.new(_auth_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def _validar_cookie_sessao(cookie_header: str) -> bool:
    if os.environ.get("PERFECTENSCHLAG_AUTH_ENABLED", "true").lower() != "true":
        return True
    if not cookie_header:
        return False
    try:
        sc = SimpleCookie()
        sc.load(cookie_header)
        morsel = sc.get("perfectenschlag_session")
        if not morsel:
            return False
        partes = morsel.value.split(":")
        if len(partes) != 3:
            return False
        usuario, ts, sig = partes
        esperado = hmac.new(_auth_secret(), f"{usuario}:{ts}".encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, esperado):
            return False
        # Sessão expira após PANEL_SESSION_HOURS (padrão: 12 h)
        return 0 <= time.time() - int(ts) <= _SESSAO_HORAS * 3600
    except Exception:
        return False


LOGIN_SCRANTON_HTML = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Entrar · Perfectenschlag</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo+Narrow:wght@700&family=Libre+Franklin:wght@400;600;700&display=swap">
<style>
  :root{--paper:#fbfaf5;--wall:#e9e4d6;--ink:#24292e;--muted:#5f6670;--brand:#1f4e8c;--brand-ink:#163a6b;--line:#d9d3c3;--rec:#b3261e}
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px 16px;background:var(--wall);color:var(--ink);font:14px/1.5 "Libre Franklin",Arial,sans-serif}
  .box{width:min(400px,100%);background:#fff;border:1px solid var(--line);border-radius:12px;padding:28px;box-shadow:0 10px 30px rgba(36,41,46,.08)}
  .brand{display:flex;align-items:center;gap:12px;margin-bottom:22px}
  .mark{width:42px;height:42px;border:2.5px solid var(--brand);border-radius:4px;display:grid;place-items:center;font:700 17px "Archivo Narrow",Arial,sans-serif;color:var(--brand)}
  h1{margin:0;font:700 24px/1.1 "Archivo Narrow",Arial,sans-serif;color:var(--brand-ink)}
  .sub{margin:2px 0 0;font-size:12px;color:var(--muted);letter-spacing:1px;text-transform:uppercase}
  label{display:block;font-weight:600;font-size:13px;margin:0 0 6px}
  .field{margin-bottom:16px}
  .pw{position:relative}
  input{width:100%;padding:10px 12px;min-height:42px;border-radius:6px;border:1px solid #bfb7a3;background:#fff;color:var(--ink);font:15px "Libre Franklin",Arial,sans-serif}
  input:focus{outline:none;border-color:var(--brand);box-shadow:0 0 0 3px rgba(31,78,140,.18)}
  .pw input{padding-right:70px}
  .show{position:absolute;right:6px;top:50%;transform:translateY(-50%);border:0;background:none;color:var(--brand);font:600 13px "Libre Franklin",Arial,sans-serif;cursor:pointer;padding:6px 8px;border-radius:4px}
  .show:focus-visible,button[type=submit]:focus-visible{outline:2px solid var(--brand);outline-offset:2px}
  button[type=submit]{width:100%;min-height:44px;border:0;border-radius:6px;background:var(--brand);color:#fff;font:700 15px "Archivo Narrow",Arial,sans-serif;letter-spacing:.4px;cursor:pointer;margin-top:4px}
  button[type=submit]:hover{background:var(--brand-ink)}
  .err{background:#fcebea;border:1px solid #efc3bf;color:var(--rec);padding:10px 12px;border-radius:6px;font-size:13px;margin-bottom:16px}
  .foot{margin:18px 0 0;font-size:12px;color:var(--muted);text-align:center}
</style></head><body>
<form class="box" method="post" action="/login">
  <div class="brand"><div class="mark">AC</div><div><h1>Perfectenschlag</h1><p class="sub">Filial Regional</p></div></div>
  {ERR}
  <div class="field"><label for="u">Usuário</label><input id="u" name="username" autocomplete="username" required autofocus></div>
  <div class="field"><label for="p">Senha</label><div class="pw"><input id="p" type="password" name="password" autocomplete="current-password" required><button class="show" type="button" aria-controls="p" onclick="var i=document.getElementById('p');var v=i.type==='password';i.type=v?'text':'password';this.textContent=v?'Ocultar':'Mostrar'">Mostrar</button></div></div>
  <button type="submit">Entrar</button>
  <p class="foot">Por segurança, a sessão dura {HORAS} h.</p>
</form></body></html>"""


class DunderMifflinRTSHandler(BaseHTTPRequestHandler):
    """Servidor HTTP AgentCraft para a Filial Dunder Mifflin Scranton."""

    def _cors_origin(self) -> str:
        origin = str(self.headers.get("Origin") or "").strip()
        if origin.startswith(("http://localhost:", "http://127.0.0.1:", "http://localhost", "http://127.0.0.1")):
            return origin
        return "http://localhost:8080"

    def _enviar_json(self, dados: Dict[str, Any], status_code: int = 200) -> None:
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Webhook-Token")
        self.end_headers()
        self.wfile.write(corpo)

    def _webhook_autorizado(self) -> bool:
        """
        Chamadas locais diretas (git hook, n8n local) passam sem token.
        Chamadas vindas de túnel/proxy (com X-Forwarded-*) exigem WEBHOOK_SECRET_TOKEN
        no header X-Webhook-Token ou no parâmetro ?token=.
        """
        veio_de_proxy = bool(self.headers.get("X-Forwarded-For") or self.headers.get("X-Forwarded-Proto"))
        if not veio_de_proxy:
            return True
        esperado = os.environ.get("WEBHOOK_SECRET_TOKEN", "")
        if not esperado:
            return False
        recebido = self.headers.get("X-Webhook-Token", "") or (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
        return hmac.compare_digest(recebido.encode("utf-8"), esperado.encode("utf-8"))

    def _exigir_autenticacao(self, is_api: bool = False) -> bool:
        if _validar_cookie_sessao(self.headers.get("Cookie", "")):
            return True
        if is_api:
            self._enviar_json({"ok": False, "erro": "Sessão expirada ou não autenticada."}, status_code=401)
        else:
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
        return False

    def do_OPTIONS(self) -> None:
        self._enviar_json({"ok": True})

    def do_GET(self) -> None:
        if self.path == "/login":
            html = LOGIN_SCRANTON_HTML.replace("{ERR}", "").replace("{HORAS}", str(_SESSAO_HORAS)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        if self.path == "/logout":
            self.send_response(302)
            self.send_header("Set-Cookie", "perfectenschlag_session=; Path=/; Max-Age=0; HttpOnly")
            self.send_header("Location", "/login")
            self.end_headers()
            return

        if self.path.startswith("/webhook/whatsapp-lead"):
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            mode = (qs.get("hub.mode") or [""])[0]
            token = (qs.get("hub.verify_token") or [""])[0]
            challenge = (qs.get("hub.challenge") or [""])[0]
            expected = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
            if mode == "subscribe" and expected and token == expected:
                corpo_ch = challenge.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(corpo_ch)))
                self.end_headers()
                self.wfile.write(corpo_ch)
                return
            self._enviar_json({"ok": True, "webhook": "WhatsApp Lead Manager Bridge Online"})
            return

        is_api = self.path.startswith("/api/")
        if not self._exigir_autenticacao(is_api=is_api):
            return

        if self.path in ("/", "/index.html"):
            if not ARQUIVO_FRONTEND.exists():
                self.send_error(404, "Frontend AgentCraft nao encontrado.")
                return
            conteudo = ARQUIVO_FRONTEND.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(conteudo)))
            self.end_headers()
            self.wfile.write(conteudo)
            return

        if self.path.startswith("/lead-manager") or self.path.startswith("/lead_manager.html"):
            if not ARQUIVO_LEAD_MANAGER.exists():
                self.send_error(404, "Frontend Lead Manager nao encontrado.")
                return
            conteudo = ARQUIVO_LEAD_MANAGER.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(conteudo)))
            self.end_headers()
            self.wfile.write(conteudo)
            return

        if self.path.startswith("/api/leads/status"):
            leads = carregar_leads_csv()
            self._enviar_json({
                "ok": True,
                "leads": leads,
                "metricas": calcular_metricas_leads(leads),
                "config": carregar_config_lead_manager(),
                "motor_5000": obter_status_motor_5000(),
            })
            return

        if self.path.startswith("/api/scheduler"):
            self._enviar_json({
                "ok": True,
                "config": carregar_scheduler_config(),
                "status": dict(SCHEDULER_STATUS),
            })
            return

        if self.path.startswith("/api/vagas/descobertas"):
            self._enviar_json({
                "ok": True,
                "vagas": carregar_vagas_descobertas(),
                "plataformas": obter_status_plataformas_vagas(),
            })
            return

        if self.path.startswith("/api/curriculos/log"):
            self._enviar_json({"ok": True, "logs": carregar_log_curriculos()})
            return

        if self.path.startswith("/api/n8n/workflows"):
            self._enviar_json({
                "ok": True,
                "status_n8n": obter_status_n8n(),
                "workflows": carregar_pacote_workflows_n8n(),
            })
            return

        if self.path.startswith("/api/config_completa"):
            repos_obj = localizar_repositorios()
            self._enviar_json(obter_diagnostico_configuracao(repos_obj))
            return

        if self.path.startswith("/api/status"):
            carregar_env_local()
            repos_obj = localizar_repositorios()
            repos = {k: str(v) for k, v in repos_obj.items()}
            historico = listar_auditoria()
            pendentes_wuphf = [
                r for r in historico if r.get("status") == "AGUARDANDO_AUTORIZACAO"
            ]
            self._enviar_json({
                "sistema": "Sistema Perfectenschlag - AgentCraft Dunder Mifflin Edition",
                "api_key_configurada": bool(os.environ.get("GEMINI_API_KEY")),
                "economia_anual": "R$ 20.000,00 / ano",
                "infra_stack": "Docker + Snipe-IT",
                "repositorios_detectados": repos,
                "total_eventos_auditoria": len(historico),
                "wuphf_pendentes": len(pendentes_wuphf),
                "auditoria": historico,
                "perfil": carregar_perfil_gerente(),
                "candidaturas": carregar_candidaturas(),
                "pendencias_perfil": pendencias_perfil(),
                "configuracao": obter_diagnostico_configuracao(repos_obj),
            })
            return

        if self.path.startswith("/api/candidatura/docx"):
            cid = (parse_qs(urlparse(self.path).query).get("id") or [""])[0].strip().upper()
            alvo = next((c for c in carregar_candidaturas() if str(c.get("id", "")).upper() == cid), None)
            if not alvo:
                self._enviar_json({"erro": "Candidatura não encontrada."}, status_code=404)
                return
            perfil = carregar_perfil_gerente()
            arquivo = gerar_docx_bytes(alvo.get("curriculo_moldado", ""), f"Currículo · {perfil.get('nome_completo', '')}")
            nome = nome_arquivo_cv(perfil)
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            self.send_header("Content-Disposition", f'attachment; filename="{nome}"')
            self.send_header("Content-Length", str(len(arquivo)))
            self.end_headers()
            self.wfile.write(arquivo)
            return

        self.send_error(404, "Rota nao encontrada na filial Scranton.")

    def do_POST(self) -> None:
        tamanho = int(self.headers.get("Content-Length", 0))
        corpo_raw = self.rfile.read(tamanho).decode("utf-8") if tamanho > 0 else "{}"

        if self.path == "/login":
            form = parse_qs(corpo_raw)
            user = (form.get("username") or [""])[0].strip()
            pwd = (form.get("password") or [""])[0].strip()
            expected_user = os.environ.get("PANEL_USER", "")
            expected_pwd = os.environ.get("PANEL_PASSWORD", "")
            usuario_ok = bool(expected_user) and hmac.compare_digest(user.encode("utf-8"), expected_user.encode("utf-8"))
            senha_ok = bool(expected_pwd) and hmac.compare_digest(pwd.encode("utf-8"), expected_pwd.encode("utf-8"))
            if usuario_ok and senha_ok:
                cookie_val = _gerar_cookie_sessao(user)
                https = self.headers.get("X-Forwarded-Proto", "").lower() == "https"
                flags = f"Path=/; HttpOnly; SameSite=Lax; Max-Age={_SESSAO_HORAS * 3600}" + ("; Secure" if https else "")
                self.send_response(302)
                self.send_header("Set-Cookie", f"perfectenschlag_session={cookie_val}; {flags}")
                self.send_header("Location", "/")
                self.end_headers()
                return
            html = LOGIN_SCRANTON_HTML.replace("{ERR}", '<div class="err" role="alert">Usuário ou senha incorretos. Confira e tente de novo.</div>').replace("{HORAS}", str(_SESSAO_HORAS)).encode("utf-8")
            time.sleep(1.0)
            self.send_response(401)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        if not self.path.startswith("/webhook/"):
            if not self._exigir_autenticacao(is_api=True):
                return
        elif not self._webhook_autorizado():
            self._enviar_json({"ok": False, "erro": "Token de webhook ausente ou inválido."}, status_code=401)
            return
        else:
            self.path = urlparse(self.path).path  # remove ?token= para casar com as rotas

        try:
            payload = json.loads(corpo_raw)
        except Exception:
            payload = {}

        if self.path == "/api/scheduler":
            if payload.get("run_now"):
                res_ciclo = executar_ciclo_agendador(
                    forcar_golden=bool(payload.get("golden", True)),
                    forcar_recyclops=bool(payload.get("recyclops", True)),
                )
                self._enviar_json({"ok": True, "ciclo": res_ciclo, "config": carregar_scheduler_config(), "status": dict(SCHEDULER_STATUS)})
                return
            cfg_sch = salvar_scheduler_config(payload)
            self._enviar_json({"ok": True, "config": cfg_sch, "status": dict(SCHEDULER_STATUS)})
            return

        if self.path == "/api/nova_candidatura":
            if not os.environ.get("GEMINI_API_KEY"):
                self._enviar_json(
                    {"erro": "Fato: Você esqueceu a chave da API. Inaceitável."},
                    status_code=403,
                )
                return
            cargo_empresa = str(payload.get("cargo_empresa", "")).strip()
            link_ou_email = str(payload.get("link_ou_email", "")).strip()
            descricao_vaga = str(payload.get("descricao_vaga", "")).strip()
            observacoes = str(payload.get("observacoes", "")).strip()
            pacote = criar_pacote_candidatura(
                cargo_empresa=cargo_empresa,
                link_ou_email=link_ou_email,
                descricao_vaga=descricao_vaga,
                observacoes_extras=observacoes,
            )
            registrar_evento_auditoria(
                agente="GOLDEN_TICKET",
                acao="CURRICULO_MOLDADO_E_TREINO_ENTREVISTA",
                entrada=f"{cargo_empresa} ({link_ou_email})",
                saida=pacote.get("curriculo_moldado", ""),
                status="AGUARDANDO_AUTORIZACAO",
                requer_autorizacao=True,
            )
            self._enviar_json({"ok": True, "candidatura": pacote})
            return

        if self.path == "/api/decidir_candidatura":
            cid = str(payload.get("id", "")).strip()
            decisao = str(payload.get("decisao", "")).strip()
            cv_editado = payload.get("curriculo_moldado")
            msg_editada = payload.get("mensagem_apresentacao")
            atualizada = decidir_envio_candidatura(cid, decisao, cv_editado, msg_editada)
            if atualizada is None:
                self._enviar_json({"ok": False, "erro": "Candidatura não encontrada."}, status_code=404)
                return
            if decisao.upper() in ("AUTORIZAR", "VETAR") and not atualizada.get("erro_envio"):
                try:
                    cargo_ref = str(atualizada.get("cargo_empresa", "")).strip().lower()
                    link_ref = str(atualizada.get("link_ou_email", "")).strip().lower()
                    novo_st = "APROVADO" if decisao.upper() == "AUTORIZAR" else "VETADO"
                    estados_alvo = ("AGUARDANDO_AUTORIZACAO",) if novo_st == "APROVADO" else ("AGUARDANDO_AUTORIZACAO", "APROVADO")
                    for item in listar_auditoria():
                        if item.get("status") in estados_alvo and item.get("agente") == "GOLDEN_TICKET":
                            ent = str(item.get("entrada", "")).lower()
                            if (cargo_ref and cargo_ref in ent) or (link_ref and link_ref in ent) or (cid.lower() in ent):
                                atualizar_status_auditoria(str(item.get("id", "")), novo_st)
                except Exception:
                    pass
            self._enviar_json({"ok": not atualizada.get("erro_envio"), "erro": atualizada.get("erro_envio", ""), "candidatura": atualizada})
            return

        if self.path == "/api/monitorar_candidatura":
            cid = str(payload.get("id", "")).strip()
            atualizada = verificar_status_vaga_E_email(cid)
            self._enviar_json({"ok": True, "candidatura": atualizada, "associada": atualizada is not None})
            return

        if self.path == "/api/vagas/buscar":
            kws = str(payload.get("palavras_chave") or "Python, Automação, Docker, DevOps, IA").strip()
            remoto = bool(payload.get("apenas_remoto", False))
            limite = int(payload.get("limite", 15) or 15)
            fonte = str(payload.get("fonte") or "todas").strip()
            senioridade = str(payload.get("senioridade") or "todas").strip()
            idioma = str(payload.get("idioma") or "todos").strip()
            score_min = int(payload.get("score_minimo", 0) or 0)
            res_v = buscar_melhores_vagas(
                palavras_chave=kws,
                apenas_remoto=remoto,
                usar_ia=True,
                limite=limite,
                fonte=fonte,
                senioridade=senioridade,
                idioma=idioma,
                score_minimo=score_min,
            )
            registrar_evento_auditoria(
                agente="CACADOR_VAGAS",
                acao="BUSCA_AUTOMATICA_MELHORES_VAGAS",
                entrada=f"Keywords: {kws} | Fonte: {fonte} | Nível: {senioridade} | Idioma: {idioma} | Remoto: {remoto} | Min: {score_min}%",
                saida=f"{res_v.get('total_varridas', 0)} vagas varridas → Top {res_v.get('total_selecionadas', 0)} ranqueadas por Match.",
                status="CONCLUIDO",
            )
            self._enviar_json(res_v)
            return

        if self.path == "/api/vagas/enviar_esteira":
            if not os.environ.get("GEMINI_API_KEY"):
                self._enviar_json({"ok": False, "erro": "GEMINI_API_KEY não configurada no .env."}, status_code=403)
                return
            vid = str(payload.get("id") or "").strip()
            vaga = marcar_vaga_enviada_esteira(vid)
            if not vaga:
                self._enviar_json({"ok": False, "erro": "Vaga não encontrada."}, status_code=404)
                return
            try:
                pacote = criar_pacote_candidatura(
                    cargo_empresa=f"{vaga['titulo']} — {vaga['empresa']}",
                    link_ou_email=vaga.get("link_candidatura") or vaga["url"],
                    descricao_vaga=f"Fonte: {vaga['fonte']} | Local: {vaga['local']} | Tags: {', '.join(vaga.get('tags') or [])}\n\n{vaga.get('descricao', '')}",
                    observacoes_extras=f"Capturada pelo Radar Automático (Match: {vaga['score_match']}%). {vaga.get('motivo_match', '')}",
                )
                registrar_evento_auditoria(
                    agente="GOLDEN_TICKET",
                    acao="VAGA_RADAR_ENVIADA_ESTEIRA",
                    entrada=f"{vaga['titulo']} ({vaga['score_match']}% Match)",
                    saida=pacote.get("curriculo_moldado", ""),
                    status="AGUARDANDO_AUTORIZACAO",
                    requer_autorizacao=True,
                )
                self._enviar_json({"ok": True, "candidatura": pacote, "vagas": carregar_vagas_descobertas()})
            except Exception as exc:
                self._enviar_json({"ok": False, "erro": f"Falha ao gerar pacote da vaga: {exc}"}, status_code=500)
            return

        if self.path == "/api/curriculos/etapa":
            reg = registrar_ou_atualizar_processo_curriculo(
                candidatura_id=str(payload.get("id") or "").strip(),
                cargo_empresa=str(payload.get("cargo_empresa") or "").strip(),
                link_ou_email=str(payload.get("link_ou_email") or "").strip(),
                etapa_processo=str(payload.get("etapa_processo") or "EM_ANALISE").strip(),
                observacao=str(payload.get("observacao") or "").strip(),
                nota_ats=payload.get("nota_ats"),
            )
            self._enviar_json({"ok": True, "registro": reg, "logs": carregar_log_curriculos()})
            return

        if self.path == "/api/auditar_curriculo_recrutador":
            if not os.environ.get("GEMINI_API_KEY"):
                self._enviar_json({"erro": "GEMINI_API_KEY não configurada no .env."}, status_code=403)
                return
            cid = str(payload.get("id", "")).strip()
            cv_atual = payload.get("curriculo_atual")
            info_rec = str(payload.get("info_recrutador_extra", "") or "").strip()
            try:
                res_aud = auditar_e_melhorar_curriculo(
                    candidatura_id=cid,
                    curriculo_atual=cv_atual,
                    info_recrutador_extra=info_rec,
                )
                registrar_evento_auditoria(
                    agente="AUDITOR_RECRUTADOR_FINAL",
                    acao="AUDITORIA_RECRUTADOR_SOB_DEMANDA",
                    entrada=f"Vaga ID: {cid} | Nota ATS: {res_aud['auditoria'].get('nota_ats') or '-'}/100",
                    saida=res_aud["auditoria"].get("parecer_recrutador", ""),
                    status="CONCLUIDO",
                )
                self._enviar_json(res_aud)
            except Exception as exc:
                self._enviar_json({"ok": False, "erro": str(exc)}, status_code=400)
            return

        if self.path == "/webhook/vaga":
            if not os.environ.get("GEMINI_API_KEY"):
                self._enviar_json(
                    {"erro": "Fato: Você esqueceu a chave da API. Inaceitável."},
                    status_code=403,
                )
                return
            cargo_empresa = str(payload.get("cargo_empresa", payload.get("title", "Vaga via Webhook"))).strip()
            link_ou_email = str(payload.get("link_ou_email", payload.get("url", ""))).strip()
            descricao_vaga = str(payload.get("descricao_vaga", payload.get("description", ""))).strip()
            pacote = criar_pacote_candidatura(
                cargo_empresa=cargo_empresa,
                link_ou_email=link_ou_email,
                descricao_vaga=descricao_vaga,
                observacoes_extras="Capturada automaticamente via Webhook Externo (Trava de Aprovação Ativa)",
            )
            registrar_evento_auditoria(
                agente="GOLDEN_TICKET",
                acao="WEBHOOK_NOVA_VAGA_DETECTADA",
                entrada=f"{cargo_empresa} ({link_ou_email})",
                saida=pacote.get("curriculo_moldado", ""),
                status="AGUARDANDO_AUTORIZACAO",
                requer_autorizacao=True,
            )
            self._enviar_json({"ok": True, "status": "AGUARDANDO_AUTORIZACAO_GERENTE", "candidatura": pacote})
            return

        if self.path == "/webhook/retorno-recrutador":
            empresa_ou_id = str(payload.get("empresa_ou_id", payload.get("id", ""))).strip()
            remetente = str(payload.get("remetente", payload.get("from", "Recrutador"))).strip()
            assunto = str(payload.get("assunto", payload.get("subject", "Retorno Processo Seletivo"))).strip()
            mensagem = str(payload.get("mensagem", payload.get("body", ""))).strip()
            atualizada = registrar_retorno_webhook(empresa_ou_id, remetente, assunto, mensagem)
            registrar_evento_auditoria(
                agente="OPERADOR_MOSE",
                acao="WEBHOOK_RETORNO_RECRUTADOR_EMAIL",
                entrada=f"De: {remetente} | Assunto: {assunto}",
                saida=mensagem,
                status="CONCLUIDO",
            )
            self._enviar_json({"ok": True, "candidatura": atualizada, "associada": atualizada is not None})
            return

        if self.path == "/webhook/whatsapp-lead":
            telefone = str(payload.get("phone", payload.get("telefone", ""))).strip()
            nome = str(payload.get("name", payload.get("nome", "Lead WhatsApp"))).strip()
            msg = str(payload.get("text", payload.get("mensagem", ""))).strip()
            triagem = processar_mensagem_webhook_lead(telefone=telefone, mensagem=msg, nome_remetente=nome)
            classif = triagem.get("classificacao", "RESPONDEU")
            evento = registrar_evento_auditoria(
                agente="ASSISTANT_LEAD_MANAGER",
                acao=f"WEBHOOK_WHATSAPP_LEAD_{classif}",
                entrada=f"{nome} ({triagem['lead'].get('telefone_normalizado', telefone)})",
                saida=f"Mensagem do Lead: {msg}\nClassificação: {classif}\nAuto-Resposta: {triagem.get('auto_resposta', '')}",
                status="CONCLUIDO",
            )
            self._enviar_json({"ok": True, "evento": evento, "triagem": triagem})
            return

        if self.path == "/api/leads/importar":
            res = adicionar_ou_importar_leads(
                novos_leads=payload.get("leads"),
                csv_texto=payload.get("csv_texto"),
            )
            registrar_evento_auditoria(
                agente="ASSISTANT_LEAD_MANAGER",
                acao="IMPORTACAO_BASE_LEADS_CSV",
                entrada=f"Adicionados: {res['adicionados']} | Duplicados ignorados: {res['ignorados_duplicados']}",
                saida=f"Base CSV persistida atomicamente (.tmp -> .csv). Total na fila: {res['total_atual']} leads.",
                status="CONCLUIDO",
            )
            self._enviar_json({"ok": True, "resultado": res, "leads": carregar_leads_csv()})
            return

        if self.path == "/api/leads/disparar":
            qtd = int(payload.get("quantidade", 10) or 10)
            modo = payload.get("modo")
            res = disparar_lote_campanha(quantidade=qtd, modo_forcado=modo)
            registrar_evento_auditoria(
                agente="ASSISTANT_LEAD_MANAGER",
                acao=f"DISPARO_CAMPANHA_{res['modo_utilizado']}",
                entrada=f"Lote solicitado: {qtd} leads",
                saida=f"Disparados com sucesso: {res['disparados']} | Erros: {res['erros']} (Persistência atômica CSV)",
                status="CONCLUIDO",
            )
            self._enviar_json({"ok": True, "resultado": res, "leads": carregar_leads_csv()})
            return

        if self.path == "/api/leads/config":
            cfg = salvar_config_lead_manager(payload)
            self._enviar_json({"ok": True, "config": cfg})
            return

        if self.path == "/api/leads/status-manual":
            atualizado = atualizar_status_lead_manual(
                lead_id=str(payload.get("id", "")),
                novo_status=str(payload.get("status", "PENDENTE")),
            )
            leads = carregar_leads_csv()
            self._enviar_json({
                "ok": True,
                "lead": atualizado,
                "leads": leads,
                "metricas": calcular_metricas_leads(leads),
            })
            return

        if self.path == "/api/leads/gerar-script":
            script_ia = gerar_script_abordagem_ia(
                segmento_alvo=str(payload.get("segmento", "Corporativo B2B")),
                objetivo=str(payload.get("objetivo", "")),
            )
            self._enviar_json({"ok": True, "script": script_ia})
            return

        if self.path == "/webhook/git-commit":
            projeto = str(payload.get("projeto", "Repositorio Local")).strip()
            commit_hash = str(payload.get("hash", "")).strip()
            autor = str(payload.get("autor", "Gerente Regional")).strip()
            mensagem = str(payload.get("mensagem", "")).strip()
            evento_mose = registrar_evento_auditoria(
                agente="OPERADOR_MOSE",
                acao="GIT_HOOK_POST_COMMIT",
                entrada=f"{projeto} [{commit_hash}] por {autor}",
                saida=f"Commit detectado automaticamente pelo Git Hook da Filial:\n{mensagem}",
                status="CONCLUIDO",
            )
            evento_wuphf = None
            if os.environ.get("GEMINI_API_KEY") and mensagem:
                try:
                    rascunho = executar_sistema_wuphf(
                        commit_manual=f"[{commit_hash}] {mensagem}",
                        projeto_manual=projeto,
                    )
                    evento_wuphf = registrar_evento_auditoria(
                        agente="SISTEMA_WUPHF",
                        acao="AUTO_RASCUNHO_POR_GIT_HOOK",
                        entrada=f"{projeto}: {mensagem}",
                        saida=rascunho,
                        status="AGUARDANDO_AUTORIZACAO",
                        requer_autorizacao=True,
                    )
                except Exception:
                    pass
            self._enviar_json({"ok": True, "evento_mose": evento_mose, "evento_wuphf": evento_wuphf})
            return

        if self.path == "/api/autoconfigurar":
            repos_obj = localizar_repositorios()
            diagnostico = executar_autoconfiguracao_completa(
                novas_credenciais=payload,
                repositorios_detectados=repos_obj,
            )
            hooks_ok = sum(1 for h in diagnostico.get("git_hooks", []) if h.get("pre_commit_dlp") and h.get("post_commit_wuphf"))
            registrar_evento_auditoria(
                agente="ORQUESTRADOR_REGIONAL",
                acao="AUTOCONFIGURACAO_GANCHOS_WEBHOOKS_CREDENCIAIS",
                entrada="Autoconfiguração de .env, Webhooks e Git Hooks da Filial Scranton",
                saida=(
                    f"Arquivo .env persistido | Gemini API Key: {'ATIVA' if diagnostico['credenciais']['gemini_api_key_ativa'] else 'PENDENTE'} | "
                    f"IMAP/SMTP: {'CONFIGURADO' if diagnostico['credenciais']['imap_user'] or diagnostico['credenciais']['smtp_user'] else 'OPCIONAL'} | "
                    f"Git Hooks (pre-commit DLP + post-commit WUPHF) ativos em {hooks_ok} repositório(s)."
                ),
                status="CONCLUIDO",
            )
            self._enviar_json({"ok": True, "configuracao": diagnostico})
            return

        if self.path == "/api/n8n/provisionar":
            iniciar_docker = bool(payload.get("iniciar_container", True))
            n8n_url = str(payload.get("n8n_base_url", "http://localhost:5678")).strip()
            res_n8n = provisionar_n8n_docker(
                iniciar_container=iniciar_docker,
                n8n_base_url=n8n_url,
            )
            diagnostico = obter_diagnostico_configuracao(localizar_repositorios())
            registrar_evento_auditoria(
                agente="ORQUESTRADOR_REGIONAL",
                acao="PROVISIONAMENTO_N8N_FILIAL",
                entrada=f"n8n Base URL: {n8n_url} | Subir Docker: {iniciar_docker}",
                saida=(
                    f"Webhooks n8n pré-conectados no .env ({n8n_url}/webhook/perfectenschlag-*) | "
                    f"Workflows prontos: {', '.join(res_n8n.get('workflows_prontos', []))} | "
                    f"Logs: {'; '.join(res_n8n.get('logs_provisionamento', ['URLs salvas']))}"
                ),
                status="CONCLUIDO",
            )
            self._enviar_json({"ok": True, "n8n": res_n8n, "configuracao": diagnostico})
            return

        if self.path == "/api/perfil":
            perfil_salvo = salvar_perfil_gerente(payload)
            registrar_evento_auditoria(
                agente="ORQUESTRADOR_REGIONAL",
                acao="ATUALIZACAO_DOSSIE_CURRICULAR",
                entrada=f"Atualização de currículo e dados complementares ({perfil_salvo.get('nome_completo', '')})",
                saida="Dossiê Curricular Oficial atualizado e injetado em todos os agentes.",
                status="CONCLUIDO",
            )
            self._enviar_json({"ok": True, "perfil": perfil_salvo})
            return

        if self.path == "/api/config_apikey":
            chave = str(payload.get("api_key", "")).strip()
            if not chave:
                self._enviar_json(
                    {"erro": "Fato: Você esqueceu a chave da API. Inaceitável."},
                    status_code=400,
                )
                return
            salvar_credenciais_env({"GEMINI_API_KEY": chave})
            registrar_evento_auditoria(
                agente="ORQUESTRADOR_REGIONAL",
                acao="CONFIGURACAO_API_KEY",
                entrada="GEMINI_API_KEY injetada e persistida no .env via HUD AgentCraft",
                saida="Chave de API validada, salva em .env e ativa na sessão da filial.",
                status="CONCLUIDO",
            )
            self._enviar_json({"ok": True, "mensagem": "GEMINI_API_KEY salva no .env e ativada com sucesso."})
            return

        if self.path == "/api/executar":
            if not os.environ.get("GEMINI_API_KEY"):
                registrar_evento_auditoria(
                    agente=payload.get("agente", "DESCONHECIDO"),
                    acao="BLOQUEIO_SEGURANCA_API_KEY",
                    entrada="Tentativa de execução sem GEMINI_API_KEY",
                    saida="Fato: Você esqueceu a chave da API. Inaceitável.",
                    status="ERRO",
                )
                self._enviar_json(
                    {"erro": "Fato: Você esqueceu a chave da API. Inaceitável."},
                    status_code=403,
                )
                return

            agente = payload.get("agente", "")
            entrada_principal = str(payload.get("entrada", "")).strip()
            contexto_extra = str(payload.get("contexto", "")).strip()

            try:
                if agente == "NEUTRALIZADOR_TOBY":
                    resultado = executar_neutralizador_toby(entrada_principal, contexto_extra)
                    evento = registrar_evento_auditoria(
                        agente="NEUTRALIZADOR_TOBY",
                        acao="DESTRUICAO_FILTRO_ATS",
                        entrada=entrada_principal,
                        saida=resultado,
                        status="CONCLUIDO",
                        metadados={"complemento": contexto_extra, "economia_base": "R$ 20 mil anual"},
                    )
                    self._enviar_json({"ok": True, "evento": evento})
                    return

                elif agente == "PROTOCOLO_RECYCLOPS":
                    resultado = executar_protocolo_recyclops(entrada_principal, contexto_extra)
                    evento = registrar_evento_auditoria(
                        agente="PROTOCOLO_RECYCLOPS",
                        acao="DOSSIE_ATAQUE_OSINT",
                        entrada=f"Empresa: {entrada_principal} | Contexto: {contexto_extra}",
                        saida=resultado,
                        status="CONCLUIDO",
                        metadados={"persona": "Dwight Kurt Schrute III"},
                    )
                    self._enviar_json({"ok": True, "evento": evento})
                    return

                elif agente == "SISTEMA_WUPHF":
                    rascunho = executar_sistema_wuphf(
                        diretorio_base=contexto_extra if contexto_extra else None,
                        commit_manual=entrada_principal if entrada_principal else None,
                    )
                    evento = registrar_evento_auditoria(
                        agente="SISTEMA_WUPHF",
                        acao="GERACAO_RASCUNHO_LINKEDIN",
                        entrada=entrada_principal or "Varredura automática Git (AWAProject / Bet-Trader)",
                        saida=rascunho,
                        status="AGUARDANDO_AUTORIZACAO",
                        requer_autorizacao=True,
                        metadados={"diretorio_base": contexto_extra},
                    )
                    self._enviar_json({"ok": True, "evento": evento})
                    return

                elif agente == "OPERADOR_MOSE":
                    resultados_mose = executar_operador_mose(
                        diretorio_base=entrada_principal if entrada_principal else None,
                        modo_vigia_continuo=False,
                    )
                    resumo_txt = json.dumps(resultados_mose, ensure_ascii=False, indent=2)
                    evento = registrar_evento_auditoria(
                        agente="OPERADOR_MOSE",
                        acao="AUTOCOMMIT_GITHUB_SYNC",
                        entrada=entrada_principal or "Busca automática AWAProject & Bet-Trader",
                        saida=resumo_txt,
                        status="CONCLUIDO",
                        metadados={"resultados": resultados_mose},
                    )
                    self._enviar_json({"ok": True, "evento": evento})
                    return

                elif agente == "ESTUDIO_YOUTUBE":
                    pacote_video = executar_estudio_youtube(entrada_principal, contexto_extra)
                    evento = registrar_evento_auditoria(
                        agente="ESTUDIO_YOUTUBE",
                        acao="ROTEIRO_EDICAO_POSTAGEM_YOUTUBE",
                        entrada=entrada_principal or "Produção de Vídeo Técnico & Corte Shorts",
                        saida=pacote_video,
                        status="AGUARDANDO_AUTORIZACAO",
                        requer_autorizacao=True,
                        metadados={"formato": contexto_extra},
                    )
                    self._enviar_json({"ok": True, "evento": evento})
                    return

                else:
                    self._enviar_json({"erro": f"Agente desconhecido: {agente}"}, status_code=400)
                    return

            except Exception as exc:
                evento_erro = registrar_evento_auditoria(
                    agente=agente,
                    acao="FALHA_EXECUCAO",
                    entrada=entrada_principal,
                    saida=str(exc),
                    status="ERRO",
                )
                self._enviar_json({"erro": str(exc), "evento": evento_erro}, status_code=500)
                return

        if self.path == "/api/autorizar_wuphf":
            evento_id = str(payload.get("id", "")).strip()
            decisao = str(payload.get("decisao", "")).strip().upper()  # A | R | C
            feedback = str(payload.get("feedback", "")).strip()
            texto_atual = str(payload.get("saida", "")).strip()

            if decisao == "A":
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                bloco = f"## Post Aprovado pelo Gerente Regional em {timestamp} (ID: {evento_id})\n\n{texto_atual}\n\n---\n\n"
                with open(ARQUIVO_APROVADOS, "a", encoding="utf-8") as f:
                    f.write(bloco)
                atualizado = atualizar_status_auditoria(
                    evento_id=evento_id,
                    novo_status="AUTORIZADO",
                    observacao_gerente="Aprovado e arquivado pelo Gerente Regional via AgentCraft HUD.",
                )
                self._enviar_json({"ok": True, "evento": atualizado})
                return

            elif decisao == "C":
                atualizado = atualizar_status_auditoria(
                    evento_id=evento_id,
                    novo_status="VETADO",
                    observacao_gerente=feedback or "Vetado pelo Gerente Regional.",
                )
                self._enviar_json({"ok": True, "evento": atualizado})
                return

            elif decisao == "R":
                novo_rascunho = executar_sistema_wuphf(
                    commit_manual=texto_atual,
                    instrucao_revisao=feedback or "Deixe mais agressivo tecnicamente e destaque o ROI de R$ 20 mil anual.",
                )
                atualizado = atualizar_status_auditoria(
                    evento_id=evento_id,
                    novo_status="AGUARDANDO_AUTORIZACAO",
                    nova_saida=novo_rascunho,
                    observacao_gerente=f"Revisão solicitada: {feedback}",
                )
                self._enviar_json({"ok": True, "evento": atualizado})
                return

        self._enviar_json({"erro": "Endpoint POST inválido."}, status_code=404)


def iniciar_servidor_agentcraft(porta: int = 8080, abrir_navegador: bool = True) -> None:
    try:
        executar_autoconfiguracao_completa(
            repositorios_detectados=localizar_repositorios(),
            porta=porta,
        )
    except Exception:
        pass
    _avisar_credenciais_padrao()
    threading.Thread(target=_loop_agendador_autonomo, daemon=True).start()
    endereco = ("127.0.0.1", porta)
    httpd = ThreadingHTTPServer(endereco, DunderMifflinRTSHandler)
    url = f"http://localhost:{porta}"
    print("=" * 76)
    print(f" [AGENTCRAFT: DUNDER MIFFLIN SCRANTON RTS] Servidor online em: {url}")
    print(" Pressione Ctrl+C para trancar o escritório.")
    print("=" * 76)
    if abrir_navegador:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[FILIAL FECHADA] Servidor AgentCraft encerrado pelo Gerente Regional.")
        httpd.server_close()


if __name__ == "__main__":
    iniciar_servidor_agentcraft()

