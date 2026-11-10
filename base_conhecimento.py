import json
from pathlib import Path
from typing import Any, Dict

ARQUIVO_PERFIL = Path(__file__).resolve().parent / "perfil_gerente.json"


def carregar_perfil_gerente() -> Dict[str, Any]:
    """Carrega os dados curriculares e informações complementares do Gerente Regional."""
    if not ARQUIVO_PERFIL.exists():
        return {}
    try:
        with open(ARQUIVO_PERFIL, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def salvar_perfil_gerente(novos_dados: Dict[str, Any]) -> Dict[str, Any]:
    """Atualiza e persiste o dossiê curricular completo do Gerente Regional."""
    atual = carregar_perfil_gerente()
    atual.update(novos_dados)
    with open(ARQUIVO_PERFIL, "w", encoding="utf-8") as f:
        json.dump(atual, f, ensure_ascii=False, indent=2)
    return atual


def formatar_dossie_para_prompt() -> str:
    """Converte todo o perfil curricular e informações complementares em texto estruturado para os agentes."""
    p = carregar_perfil_gerente()
    if not p:
        return (
            "MARCOS PADRÃO: Economia de R$ 20 mil anual com automação + "
            "Implantação Docker/Snipe-IT + Projetos AWAProject e Bet-Trader."
        )

    contatos = p.get("contatos", {})
    contatos_str = " | ".join(
        f"{k.upper()}: {v}" for k, v in contatos.items() if v
    )

    marcos = "\n".join(f"  - {m}" for m in p.get("marcos_obrigatorios", []))

    exps = []
    for exp in p.get("experiencias_profissionais", []):
        real = "\n".join(f"    * {r}" for r in exp.get("realizacoes", []))
        exps.append(
            f"  - {exp.get('cargo', '')} @ {exp.get('empresa', '')} ({exp.get('periodo', '')}):\n{real}"
        )
    exps_str = "\n".join(exps)

    projs = "\n".join(
        f"  - {pr.get('nome', '')} [{pr.get('stack', '')}]: {pr.get('descricao', '')}"
        for pr in p.get("projetos_destaque", [])
    )

    skills = ", ".join(p.get("competencias_tecnicas", []))
    formacao = "\n".join(f"  - {f}" for f in p.get("formacao_e_certificacoes", []))
    idiomas = ", ".join(p.get("idiomas", []))

    bruto = p.get("curriculo_bruto_integral", "").strip()
    complementares = p.get("informacoes_complementares", "").strip()

    partes = [
        "=== DOSSIÊ CURRICULAR OFICIAL DO GERENTE REGIONAL ===",
        f"NOME: {p.get('nome_completo', 'Gerente Regional')}",
        f"TÍTULO ALVO: {p.get('titulo_profissional', '')}",
        f"LOCALIZAÇÃO: {p.get('localizacao', '')}",
        f"CONTATOS: {contatos_str or 'Não informado'}",
        f"\nRESUMO EXECUTIVO:\n{p.get('resumo_executivo', '')}",
        f"\nMARCOS OBRIGATÓRIOS DE ALTA LETALIDADE:\n{marcos}",
        f"\nEXPERIÊNCIA PROFISSIONAL:\n{exps_str}",
        f"\nPROJETOS ESTRATÉGICOS:\n{projs}",
        f"\nCOMPETÊNCIAS TÉCNICAS:\n{skills}",
    ]
    if formacao:
        partes.append(f"\nFORMAÇÃO & CERTIFICAÇÕES:\n{formacao}")
    if idiomas:
        partes.append(f"\nIDIOMAS: {idiomas}")
    if complementares:
        partes.append(f"\nINFORMAÇÕES COMPLEMENTARES & DIRETRIZES:\n{complementares}")
    if bruto:
        partes.append(f"\nCONTEÚDO INTEGRAL DE CURRÍCULO / DOCUMENTOS ANEXADOS:\n{bruto}")

    return "\n".join(partes)

