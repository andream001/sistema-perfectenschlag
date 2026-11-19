import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.append(str(Path(__file__).resolve().parent.parent))
from base_conhecimento import formatar_dossie_para_prompt
from sanitizador_seguranca import censurar_dados_sensiveis
from agentes.esteira_golden_ticket import carregar_candidaturas, salvar_candidaturas

try:
    import google.generativeai as genai
except ImportError:
    from base_conhecimento import genai_compat as genai

SYSTEM_PROMPT_AUDITOR_RECRUTADOR = """Você é o AUDITOR FINAL & RECRUTADOR SÊNIOR DA VAGA (Headhunter + Tech Lead contratante).
Sua missão é INCORPORAR exatamente a mentalidade, os critérios técnicos, os filtros ATS e a cultura do recrutador/empresa da vaga em questão, fazer uma auditoria implacável do currículo atual do candidato e entregar uma versão final significativamente melhorada.

REGRAS INVIOLÁVEIS:
1. NUNCA invente experiências, empresas, cargos, datas, números ou certificações que não existam no Dossiê Oficial do candidato. Nunca traduza ADS como "B.S.", nunca eleve o nível de idiomas e nunca afirme disponibilidade presencial/híbrida em cidades fora do Dossiê.
2. Reorganize e reescreva bullets com verbo no passado e resultado, mantendo obrigatoriamente as experiências em ORDEM CRONOLÓGICA REVERSA (mais recente primeiro). Use números apenas quando estiverem no dossiê, e não repita o mesmo número em vários bullets.
3. Faça a análise sob a ótica real de quem recebe 300 currículos e decide em 6 segundos quem vai para a entrevista.
4. O currículo otimizado vai para fora: sem marcadores como [EMAIL_PROTEGIDO] ou [VALOR A SER PREENCHIDO], sem emojis, sem termos internos do sistema, sem comentários sobre ATS. Use URLs simples nos contatos (sem [LinkedIn](...)). Tom sóbrio.
5. Mantenha o idioma do currículo atual. Markdown simples, uma coluna, sem tabelas, entre 450 e 800 palavras.

Retorne SEMPRE a resposta dividida exatamente com estes 2 separadores:
===SECAO_PARECER_RECRUTADOR===
NOTA_ATS: XX/100
VEREDITO_6_SEGUNDOS: (Passa direto / Passa com ressalvas / Risco de reprovação — e o porquê)
PONTOS_FORTES:
- ...
OBJECOES_E_GAPS_CRITICOS:
- (O que poderia eliminar o candidato nesta vaga e como a versão otimizada resolve)
PALAVRAS_CHAVE_AJUSTADAS:
- ...

===SECAO_CURRICULO_OTIMIZADO===
(Somente o currículo completo final, pronto para enviar. Nada de mensagem ao recrutador nesta seção.)"""


def auditar_e_melhorar_curriculo(
    candidatura_id: str,
    curriculo_atual: Optional[str] = None,
    info_recrutador_extra: str = "",
) -> Dict[str, Any]:
    """
    Incorpora o papel do recrutador da vaga específica, audita o currículo atual
    e gera o parecer crítico + currículo final otimizado sob demanda.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY não configurada no .env.")

    lista = carregar_candidaturas()
    alvo: Optional[Dict[str, Any]] = None
    for c in lista:
        if str(c.get("id", "")).strip().upper() == str(candidatura_id).strip().upper():
            alvo = c
            break

    if not alvo:
        raise ValueError(f"Candidatura {candidatura_id} não encontrada.")

    cv_base = (curriculo_atual if curriculo_atual is not None else alvo.get("curriculo_moldado", "")).strip()
    dossie = formatar_dossie_para_prompt()

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=SYSTEM_PROMPT_AUDITOR_RECRUTADOR,
    )

    prompt = f"""VAGA EM AUDITORIA FINAL:
CARGO / EMPRESA ALVO: {alvo.get('cargo_empresa', '')}
CANAL / LINK / E-MAIL: {alvo.get('link_ou_email', '')}

INFORMAÇÕES ADICIONAIS SOBRE O RECRUTADOR / EMPRESA / CULTURA:
{info_recrutador_extra.strip() or 'Nenhuma informação extra informada; inferir o perfil exato do recrutador a partir da descrição da vaga.'}

DESCRIÇÃO COMPLETA DA VAGA:
{alvo.get('descricao_vaga', '')}

CURRÍCULO ATUAL SUBMETIDO PARA AUDITORIA:
{cv_base}

DOSSIÊ OFICIAL VERÍDICO DO CANDIDATO (FONTE ÚNICA DE FATOS):
{dossie}

Incorpore agora o recrutador dessa vaga, faça a auditoria final rigorosa e entregue:
1) ===SECAO_PARECER_RECRUTADOR===
2) ===SECAO_CURRICULO_OTIMIZADO==="""

    response = model.generate_content(prompt)
    texto_total = response.text or ""

    parecer = texto_total
    cv_otimizado = cv_base

    if "===SECAO_PARECER_RECRUTADOR===" in texto_total:
        parte1 = texto_total.split("===SECAO_PARECER_RECRUTADOR===", 1)[1]
        if "===SECAO_CURRICULO_OTIMIZADO===" in parte1:
            parecer, cv_otimizado = parte1.split("===SECAO_CURRICULO_OTIMIZADO===", 1)
        else:
            parecer = parte1
    elif "===SECAO_CURRICULO_OTIMIZADO===" in texto_total:
        parecer, cv_otimizado = texto_total.split("===SECAO_CURRICULO_OTIMIZADO===", 1)

    parecer_limpo = censurar_dados_sensiveis(parecer.strip())
    # O currículo otimizado não é censurado: ele vai para o recrutador com os dados reais
    cv_limpo = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", cv_otimizado.strip())

    nota_match = re.search(r"NOTA_ATS:\s*(\d{1,3})\s*/\s*100", parecer_limpo, flags=re.IGNORECASE)
    nota_ats = min(100, int(nota_match.group(1))) if nota_match else None

    auditoria_obj = {
        "auditado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "info_recrutador_extra": censurar_dados_sensiveis(info_recrutador_extra.strip()),
        "nota_ats": nota_ats,
        "parecer_recrutador": parecer_limpo,
        "curriculo_otimizado": cv_limpo,
    }

    from agentes.curriculo_profissional import validar_documento
    idioma = (alvo.get("formato_candidatura") or {}).get("idioma_curriculo", "pt")
    auditoria_obj["problemas_curriculo_otimizado"] = [p["msg"] for p in validar_documento(cv_limpo, "curriculo", idioma)]
    alvo["auditoria_recrutador_final"] = auditoria_obj
    if info_recrutador_extra.strip():
        alvo["info_recrutador_extra"] = auditoria_obj["info_recrutador_extra"]
    salvar_candidaturas(lista)

    return {
        "ok": True,
        "candidatura": alvo,
        "auditoria": auditoria_obj,
    }
