import json
import os
import sys
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict

from auditoria import (
    atualizar_status_auditoria,
    listar_auditoria,
    registrar_evento_auditoria,
)
from base_conhecimento import carregar_perfil_gerente, salvar_perfil_gerente
from agentes.neutralizador_toby import executar_neutralizador_toby
from agentes.protocolo_recyclops import executar_protocolo_recyclops
from agentes.sistema_wuphf import (
    ARQUIVO_APROVADOS,
    executar_sistema_wuphf,
    localizar_repositorios,
)
from agentes.operador_mose import executar_operador_mose

DIRETORIO_BASE = Path(__file__).resolve().parent
ARQUIVO_FRONTEND = DIRETORIO_BASE / "frontend" / "index.html"


class DunderMifflinRTSHandler(BaseHTTPRequestHandler):
    """Servidor HTTP AgentCraft para a Filial Dunder Mifflin Scranton."""

    def _enviar_json(self, dados: Dict[str, Any], status_code: int = 200) -> None:
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(corpo)

    def do_OPTIONS(self) -> None:
        self._enviar_json({"ok": True})

    def do_GET(self) -> None:
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

        if self.path.startswith("/api/status"):
            repos = {k: str(v) for k, v in localizar_repositorios().items()}
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
            })
            return

        self.send_error(404, "Rota nao encontrada na filial Scranton.")

    def do_POST(self) -> None:
        tamanho = int(self.headers.get("Content-Length", 0))
        corpo_raw = self.rfile.read(tamanho).decode("utf-8") if tamanho > 0 else "{}"
        try:
            payload = json.loads(corpo_raw)
        except Exception:
            payload = {}

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
            os.environ["GEMINI_API_KEY"] = chave
            registrar_evento_auditoria(
                agente="ORQUESTRADOR_REGIONAL",
                acao="CONFIGURACAO_API_KEY",
                entrada="GEMINI_API_KEY injetada via HUD AgentCraft",
                saida="Chave de API validada e ativa na sessão da filial.",
                status="CONCLUIDO",
            )
            self._enviar_json({"ok": True, "mensagem": "GEMINI_API_KEY ativada com sucesso."})
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
    endereco = ("127.0.0.1", porta)
    httpd = HTTPServer(endereco, DunderMifflinRTSHandler)
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

