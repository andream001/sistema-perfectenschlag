import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sanitizador_seguranca import censurar_dados_sensiveis

ARQUIVO_AUDITORIA = Path(__file__).resolve().parent / "auditoria_perfectenschlag.json"


def _carregar_registros() -> List[Dict[str, Any]]:
    if not ARQUIVO_AUDITORIA.exists():
        return []
    try:
        with open(ARQUIVO_AUDITORIA, "r", encoding="utf-8") as f:
            dados = json.load(f)
            return dados if isinstance(dados, list) else []
    except Exception:
        return []


def _salvar_registros(registros: List[Dict[str, Any]]) -> None:
    with open(ARQUIVO_AUDITORIA, "w", encoding="utf-8") as f:
        json.dump(registros, f, ensure_ascii=False, indent=2)


def registrar_evento_auditoria(
    agente: str,
    acao: str,
    entrada: str,
    saida: str,
    status: str = "CONCLUIDO",
    requer_autorizacao: bool = False,
    metadados: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Registra qualquer operação dos agentes no livro razão de auditoria fácil do Gerente Regional."""
    registros = _carregar_registros()
    novo_evento = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "agente": agente,
        "acao": acao,
        "entrada": censurar_dados_sensiveis(entrada),
        "saida": censurar_dados_sensiveis(saida),
        "status": status,  # CONCLUIDO | AGUARDANDO_AUTORIZACAO | AUTORIZADO | VETADO | ERRO
        "requer_autorizacao": requer_autorizacao,
        "metadados": metadados or {},
    }
    registros.insert(0, novo_evento)
    _salvar_registros(registros[:200])
    return novo_evento


def atualizar_status_auditoria(
    evento_id: str,
    novo_status: str,
    nova_saida: Optional[str] = None,
    observacao_gerente: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Permite ao Gerente Regional autorizar, revisar ou vetar um item (como posts do WUPHF)."""
    registros = _carregar_registros()
    for item in registros:
        if item.get("id") == evento_id:
            item["status"] = novo_status
            item["atualizado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if nova_saida is not None:
                item["saida"] = nova_saida
            if observacao_gerente:
                item.setdefault("metadados", {})["despacho_gerente"] = observacao_gerente
            _salvar_registros(registros)
            return item
    return None


def listar_auditoria(filtro_agente: Optional[str] = None, filtro_status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retorna a lista de auditoria filtrada para visualização rápida."""
    registros = _carregar_registros()
    if filtro_agente and filtro_agente != "TODOS":
        registros = [r for r in registros if r.get("agente") == filtro_agente]
    if filtro_status and filtro_status != "TODOS":
        registros = [r for r in registros if r.get("status") == filtro_status]
    return registros

