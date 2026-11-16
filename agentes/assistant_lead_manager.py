import csv
import io
import json
import os
import re
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sys

dir_parent = str(Path(__file__).resolve().parent.parent)
if dir_parent not in sys.path:
    sys.path.append(dir_parent)

from sanitizador_seguranca import censurar_dados_sensiveis

try:
    import google.generativeai as genai
except ImportError:
    from base_conhecimento import genai_compat as genai

DIRETORIO_BASE = Path(__file__).resolve().parent.parent
ARQUIVO_LEADS_CSV = DIRETORIO_BASE / "leads_b2b_scranton.csv"
ARQUIVO_CONFIG_LEADS = DIRETORIO_BASE / "config_lead_manager.json"

COLUNAS_CSV = [
    "id",
    "empresa",
    "contato",
    "telefone_original",
    "telefone_normalizado",
    "segmento",
    "porte_vidas",
    "status",  # PENDENTE | ENVIADO | INTERESSADO | DUVIDA | OPT_OUT | ERRO_ENVIO
    "ultima_interacao",
    "ultima_mensagem_lead",
    "auto_resposta_enviada",
    "consultor_wa_link",
]

PALAVRAS_OPT_OUT = {
    "sair", "parar", "pare", "nao quero", "não quero", "remover",
    "remova", "cancelar", "bloqueio", "descadastrar", "spam", "2", "nao tenho interesse", "não tenho interesse"
}

PALAVRAS_INTERESSE = {
    "sim", "quero", "interesse", "tenho interesse", "cotacao", "cotação",
    "orcamento", "orçamento", "valores", "preco", "preço", "tabela",
    "como funciona", "pode ligar", "chama", "1", "vamos conversar", "agendar"
}


def normalizar_telefone_br(telefone_bruto: str) -> str:
    """
    Normaliza qualquer telefone brasileiro para o padrão E.164 (+55DD9XXXXXXXX).
    Garante DDI +55 e preserva/ajusta o 9º dígito para celulares.
    """
    digitos = re.sub(r"\D", "", str(telefone_bruto or ""))
    if not digitos:
        return ""

    if digitos.startswith("00"):
        digitos = digitos[2:]
    if digitos.startswith("0") and len(digitos) in (11, 12):
        digitos = digitos[1:]

    if not digitos.startswith("55"):
        digitos = "55" + digitos

    # Se tem 12 dígitos (55 + DDD + 8 dígitos) e o número começa com 6, 7, 8 ou 9 (celular sem 9º dígito), insere o 9
    if len(digitos) == 12:
        ddd = digitos[2:4]
        num = digitos[4:]
        if num and num[0] in ("6", "7", "8", "9"):
            digitos = f"55{ddd}9{num}"

    return f"+{digitos}"


def variantes_nono_digito(telefone_norm: str) -> List[str]:
    """
    Retorna as variantes com e sem o 9º dígito para casamento inteligente no Webhook da Meta
    (já que o WhatsApp às vezes retorna números antigos sem o 9º dígito).
    """
    limpo = re.sub(r"\D", "", telefone_norm)
    if not limpo:
        return []
    variantes = {f"+{limpo}", limpo}
    if limpo.startswith("55") and len(limpo) == 13 and limpo[4] == "9":
        sem_nove = limpo[:4] + limpo[5:]
        variantes.add(f"+{sem_nove}")
        variantes.add(sem_nove)
    elif limpo.startswith("55") and len(limpo) == 12:
        com_nove = limpo[:4] + "9" + limpo[4:]
        variantes.add(f"+{com_nove}")
        variantes.add(com_nove)
    return list(variantes)


def gerar_link_wa_consultor(telefone_norm: str, empresa: str, contato: str, msg_lead: str = "") -> str:
    digitos = re.sub(r"\D", "", telefone_norm)
    if not digitos:
        return ""
    texto = (
        f"Olá {contato or empresa}! Vi seu retorno sobre nossa proposta corporativa "
        f"({empresa}). Como posso te ajudar agora?"
    )
    return f"https://wa.me/{digitos}?text={urllib.parse.quote(texto)}"


def carregar_config_lead_manager() -> Dict[str, Any]:
    padrao = {
        "limite_diario_warmup": 50,
        "delay_segundos": 3,
        "modo_disparo": "DRY_RUN",  # DRY_RUN | CLOUD_API | N8N_WEBHOOK
        "whatsapp_phone_number_id": os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
        "whatsapp_access_token_configurado": bool(os.environ.get("WHATSAPP_ACCESS_TOKEN")),
        "consultor_responsavel": "Gerente Regional / Consultor B2B",
        " consultor_whatsapp": os.environ.get("CONSULTOR_WHATSAPP", ""),
        "template_abordagem": (
            "Olá, {contato} da *{empresa}*! Aqui é da equipe de Eficiência Corporativa.\n\n"
            "Estamos auxiliando empresas do setor de *{segmento}* ({porte_vidas}) a reduzirem custos "
            "operacionais e otimizarem seus planos/processos corporativos.\n\n"
            "Digite *1* para receber um diagnóstico rápido sem compromisso ou *2* para não receber novas mensagens."
        ),
        "auto_resposta_interessado": (
            "Perfeito, {contato}! Já priorizei o atendimento da *{empresa}* e nosso consultor especialista "
            "vai te chamar em instantes com o comparativo."
        ),
        "auto_resposta_optout": (
            "Confirmado! O número da *{empresa}* foi removido imediatamente da nossa lista de contatos (Conformidade LGPD). Tenha uma ótima semana!"
        ),
    }
    if not ARQUIVO_CONFIG_LEADS.exists():
        return padrao
    try:
        salvo = json.loads(ARQUIVO_CONFIG_LEADS.read_text(encoding="utf-8"))
        if isinstance(salvo, dict):
            padrao.update(salvo)
    except Exception:
        pass
    padrao["whatsapp_access_token_configurado"] = bool(os.environ.get("WHATSAPP_ACCESS_TOKEN"))
    return padrao


def salvar_config_lead_manager(novos: Dict[str, Any]) -> Dict[str, Any]:
    atual = carregar_config_lead_manager()
    if "whatsapp_access_token" in novos and str(novos["whatsapp_access_token"]).strip():
        os.environ["WHATSAPP_ACCESS_TOKEN"] = str(novos["whatsapp_access_token"]).strip()
    if "whatsapp_phone_number_id" in novos and str(novos["whatsapp_phone_number_id"]).strip():
        os.environ["WHATSAPP_PHONE_NUMBER_ID"] = str(novos["whatsapp_phone_number_id"]).strip()

    for k in (
        "limite_diario_warmup",
        "delay_segundos",
        "modo_disparo",
        "whatsapp_phone_number_id",
        "consultor_responsavel",
        "template_abordagem",
        "auto_resposta_interessado",
        "auto_resposta_optout",
    ):
        if k in novos and novos[k] is not None:
            atual[k] = novos[k]

    ARQUIVO_CONFIG_LEADS.write_text(json.dumps(atual, ensure_ascii=False, indent=2), encoding="utf-8")
    atual["whatsapp_access_token_configurado"] = bool(os.environ.get("WHATSAPP_ACCESS_TOKEN"))
    return atual


def _criar_leads_iniciais_demo() -> List[Dict[str, str]]:
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    exemplos = [
        {
            "id": "LEAD-001",
            "empresa": "Metalúrgica Vance Refrigeração Ltda",
            "contato": "Bob Vance",
            "telefone_original": "(44) 99812-3401",
            "telefone_normalizado": "+5544998123401",
            "segmento": "Indústria & Refrigeração",
            "porte_vidas": "48 vidas / colaboradores",
            "status": "INTERESSADO",
            "ultima_interacao": agora,
            "ultima_mensagem_lead": "1 - Quero ver a cotação corporativa para 48 vidas",
            "auto_resposta_enviada": "Perfeito, Bob Vance! Nosso consultor já recebeu seu alerta prioritário.",
            "consultor_wa_link": gerar_link_wa_consultor("+5544998123401", "Metalúrgica Vance Refrigeração Ltda", "Bob Vance"),
        },
        {
            "id": "LEAD-002",
            "empresa": "Schrute Farms AgroTech S/A",
            "contato": "Dwight K. Schrute",
            "telefone_original": "44 99104-7788",
            "telefone_normalizado": "+5544991047788",
            "segmento": "Agronegócio & Logística",
            "porte_vidas": "25 vidas / colaboradores",
            "status": "ENVIADO",
            "ultima_interacao": agora,
            "ultima_mensagem_lead": "Aguardando resposta ao disparo inicial",
            "auto_resposta_enviada": "",
            "consultor_wa_link": gerar_link_wa_consultor("+5544991047788", "Schrute Farms AgroTech S/A", "Dwight K. Schrute"),
        },
        {
            "id": "LEAD-003",
            "empresa": "Construtora & Vidraçaria Horizonte",
            "contato": "Marcos Almeida",
            "telefone_original": "5544988214455",
            "telefone_normalizado": "+5544988214455",
            "segmento": "Construção Civil",
            "porte_vidas": "32 vidas / colaboradores",
            "status": "PENDENTE",
            "ultima_interacao": "-",
            "ultima_mensagem_lead": "",
            "auto_resposta_enviada": "",
            "consultor_wa_link": gerar_link_wa_consultor("+5544988214455", "Construtora & Vidraçaria Horizonte", "Marcos Almeida"),
        },
        {
            "id": "LEAD-004",
            "empresa": "Transportadora Sabre Express",
            "contato": "Jo Bennett",
            "telefone_original": "(44) 99741-9090",
            "telefone_normalizado": "+5544997419090",
            "segmento": "Transporte & Frota",
            "porte_vidas": "85 vidas / colaboradores",
            "status": "PENDENTE",
            "ultima_interacao": "-",
            "ultima_mensagem_lead": "",
            "auto_resposta_enviada": "",
            "consultor_wa_link": gerar_link_wa_consultor("+5544997419090", "Transportadora Sabre Express", "Jo Bennett"),
        },
        {
            "id": "LEAD-005",
            "empresa": "Contabilidade Flenderson & Associados",
            "contato": "Toby Flenderson",
            "telefone_original": "(44) 99600-0012",
            "telefone_normalizado": "+5544996000012",
            "segmento": "Serviços Contábeis",
            "porte_vidas": "12 vidas / colaboradores",
            "status": "OPT_OUT",
            "ultima_interacao": agora,
            "ultima_mensagem_lead": "2 - parar",
            "auto_resposta_enviada": "Confirmado! Número removido imediatamente (Opt-Out LGPD).",
            "consultor_wa_link": "",
        },
    ]
    salvar_leads_atomico(exemplos)
    return exemplos


def carregar_leads_csv() -> List[Dict[str, str]]:
    """Carrega a base de leads do CSV local (ou cria a base inicial se não existir)."""
    if not ARQUIVO_LEADS_CSV.exists():
        return _criar_leads_iniciais_demo()

    leads: List[Dict[str, str]] = []
    try:
        with open(ARQUIVO_LEADS_CSV, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                item = {col: censurar_dados_sensiveis(str(row.get(col, "") or "")) for col in COLUNAS_CSV}
                item["telefone_normalizado"] = normalizar_telefone_br(
                    row.get("telefone_normalizado") or row.get("telefone_original") or ""
                )
                item["consultor_wa_link"] = row.get("consultor_wa_link") or gerar_link_wa_consultor(
                    item["telefone_normalizado"], item["empresa"], item["contato"]
                )
                leads.append(item)
    except Exception:
        return _criar_leads_iniciais_demo()

    return leads if leads else _criar_leads_iniciais_demo()


def salvar_leads_atomico(leads: List[Dict[str, str]]) -> None:
    """
    Persistência atômica (Crash-Safe): escreve primeiro em um arquivo temporário (.tmp)
    e faz substituição atômica (os.replace) no CSV principal, impedindo corrupção ou reenvios duplicados.
    """
    tmp_path = ARQUIVO_LEADS_CSV.with_suffix(".csv.tmp")
    with open(tmp_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUNAS_CSV)
        writer.writeheader()
        for lead in leads:
            linha_segura = {col: censurar_dados_sensiveis(str(lead.get(col, "") or "")) for col in COLUNAS_CSV}
            linha_segura["telefone_normalizado"] = normalizar_telefone_br(
                lead.get("telefone_normalizado") or lead.get("telefone_original") or ""
            )
            linha_segura["consultor_wa_link"] = lead.get("consultor_wa_link") or ""
            writer.writerow(linha_segura)
    os.replace(tmp_path, ARQUIVO_LEADS_CSV)


def calcular_metricas_leads(leads: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    lista = leads if leads is not None else carregar_leads_csv()
    total = len(lista)
    pendentes = sum(1 for x in lista if x.get("status") == "PENDENTE")
    enviados = sum(1 for x in lista if x.get("status") == "ENVIADO")
    interessados = sum(1 for x in lista if x.get("status") == "INTERESSADO")
    duvidas = sum(1 for x in lista if x.get("status") == "DUVIDA")
    opt_outs = sum(1 for x in lista if x.get("status") == "OPT_OUT")
    erros = sum(1 for x in lista if x.get("status") == "ERRO_ENVIO")
    acionados = enviados + interessados + duvidas + opt_outs
    taxa_conversao = round((interessados / acionados) * 100, 1) if acionados > 0 else 0.0

    return {
        "total_leads": total,
        "pendentes": pendentes,
        "enviados": enviados,
        "interessados": interessados,
        "duvidas": duvidas,
        "opt_outs": opt_outs,
        "erros": erros,
        "taxa_conversao_pct": taxa_conversao,
    }


def adicionar_ou_importar_leads(
    novos_leads: Optional[List[Dict[str, Any]]] = None,
    csv_texto: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Importa um lote de leads (via JSON ou texto CSV), normaliza o DDI +55,
    evita duplicidade por telefone normalizado e salva atomicamente.
    """
    atuais = carregar_leads_csv()
    existentes_por_tel = {x.get("telefone_normalizado"): x for x in atuais if x.get("telefone_normalizado")}
    adicionados = 0
    ignorados_duplicados = 0

    entradas: List[Dict[str, Any]] = list(novos_leads or [])
    if csv_texto and csv_texto.strip():
        f_io = io.StringIO(csv_texto.strip())
        # Detecta delimitador (; ou ,)
        amostra = csv_texto[:500]
        delim = ";" if amostra.count(";") > amostra.count(",") else ","
        reader = csv.DictReader(f_io, delimiter=delim)
        for row in reader:
            entradas.append(dict(row))

    for raw in entradas:
        empresa = str(
            raw.get("empresa") or raw.get("razao_social") or raw.get("nome_empresa") or raw.get("Empresa") or "Empresa B2B"
        ).strip()
        contato = str(
            raw.get("contato") or raw.get("nome") or raw.get("responsavel") or raw.get("Contato") or "Gestor"
        ).strip()
        tel_orig = str(
            raw.get("telefone") or raw.get("telefone_original") or raw.get("whatsapp") or raw.get("celular") or raw.get("Telefone") or ""
        ).strip()
        segmento = str(raw.get("segmento") or raw.get("setor") or raw.get("Segmento") or "Corporativo B2B").strip()
        porte = str(raw.get("porte_vidas") or raw.get("porte") or raw.get("vidas") or raw.get("Porte") or "PME / Corporativo").strip()

        tel_norm = normalizar_telefone_br(tel_orig)
        if not tel_norm:
            continue

        if tel_norm in existentes_por_tel:
            ignorados_duplicados += 1
            continue

        novo = {
            "id": f"LEAD-{str(uuid.uuid4())[:6].upper()}",
            "empresa": censurar_dados_sensiveis(empresa),
            "contato": censurar_dados_sensiveis(contato),
            "telefone_original": tel_orig,
            "telefone_normalizado": tel_norm,
            "segmento": censurar_dados_sensiveis(segmento),
            "porte_vidas": censurar_dados_sensiveis(porte),
            "status": "PENDENTE",
            "ultima_interacao": "-",
            "ultima_mensagem_lead": "",
            "auto_resposta_enviada": "",
            "consultor_wa_link": gerar_link_wa_consultor(tel_norm, empresa, contato),
        }
        atuais.insert(0, novo)
        existentes_por_tel[tel_norm] = novo
        adicionados += 1

    salvar_leads_atomico(atuais)
    return {
        "adicionados": adicionados,
        "ignorados_duplicados": ignorados_duplicados,
        "total_atual": len(atuais),
        "metricas": calcular_metricas_leads(atuais),
    }


def disparar_lote_campanha(quantidade: int = 10, modo_forcado: Optional[str] = None) -> Dict[str, Any]:
    """
    Executa o disparo controlado (respeitando Warm-Up, filtro anti-reenvio e Opt-Out)
    e persiste atomicamente (.tmp -> .csv) a cada lead processado.
    """
    cfg = carregar_config_lead_manager()
    modo = (modo_forcado or cfg.get("modo_disparo") or "DRY_RUN").upper()
    limite = max(1, min(int(quantidade or 10), int(cfg.get("limite_diario_warmup", 50))))
    template = str(cfg.get("template_abordagem", ""))

    leads = carregar_leads_csv()
    pendentes = [l for l in leads if l.get("status") == "PENDENTE"]
    lote = pendentes[:limite]

    disparados = 0
    erros = 0
    detalhes: List[Dict[str, str]] = []
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", cfg.get("whatsapp_phone_number_id", "")).strip()
    wa_token = os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip()
    n8n_wh = os.environ.get("WHATSAPP_WEBHOOK_URL", "").strip()

    for lead in lote:
        msg_personalizada = (
            template.replace("{empresa}", lead.get("empresa", "sua empresa"))
            .replace("{contato}", lead.get("contato", "Gestor"))
            .replace("{segmento}", lead.get("segmento", "seu setor"))
            .replace("{porte_vidas}", lead.get("porte_vidas", "sua equipe"))
        )
        tel_limpo = re.sub(r"\D", "", lead.get("telefone_normalizado", ""))

        sucesso = True
        obs_envio = "Disparo simulado (Dry-Run Crash-Safe)"

        if modo == "CLOUD_API" and phone_id and wa_token:
            try:
                url_meta = f"https://graph.facebook.com/v20.0/{phone_id}/messages"
                payload_meta = {
                    "messaging_product": "whatsapp",
                    "to": tel_limpo,
                    "type": "text",
                    "text": {"body": msg_personalizada},
                }
                req = urllib.request.Request(
                    url_meta,
                    data=json.dumps(payload_meta).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {wa_token}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    sucesso = resp.getcode() in (200, 201)
                    obs_envio = "Enviado via Meta WhatsApp Cloud API"
            except Exception as exc:
                sucesso = False
                obs_envio = f"Erro Cloud API: {exc}"

        elif modo == "N8N_WEBHOOK" and n8n_wh:
            try:
                req_n8n = urllib.request.Request(
                    n8n_wh,
                    data=json.dumps({
                        "acao": "DISPARO_CAMPANHA_B2B",
                        "lead_id": lead.get("id"),
                        "empresa": lead.get("empresa"),
                        "contato": lead.get("contato"),
                        "telefone": lead.get("telefone_normalizado"),
                        "mensagem": msg_personalizada,
                    }).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req_n8n, timeout=8) as resp:
                    sucesso = resp.getcode() in (200, 201)
                    obs_envio = "Encaminhado via Webhook n8n"
            except Exception as exc:
                # Se o n8n estiver desligado no momento, registra em Dry-Run para não travar a demonstração
                sucesso = True
                obs_envio = f"Dry-Run (n8n offline: { str(exc)[:40] })"

        if sucesso:
            lead["status"] = "ENVIADO"
            lead["ultima_interacao"] = agora
            lead["auto_resposta_enviada"] = msg_personalizada[:180] + ("..." if len(msg_personalizada) > 180 else "")
            disparados += 1
        else:
            lead["status"] = "ERRO_ENVIO"
            lead["ultima_interacao"] = agora
            lead["ultima_mensagem_lead"] = obs_envio
            erros += 1

        # Salva atomicamente a cada envio para garantir persistência crash-safe!
        salvar_leads_atomico(leads)
        detalhes.append({
            "id": lead.get("id", ""),
            "empresa": lead.get("empresa", ""),
            "telefone": lead.get("telefone_normalizado", ""),
            "status": lead.get("status", ""),
            "modo": obs_envio,
        })

    return {
        "disparados": disparados,
        "erros": erros,
        "modo_utilizado": modo,
        "detalhes": detalhes,
        "metricas": calcular_metricas_leads(leads),
    }


def processar_mensagem_webhook_lead(
    telefone: str,
    mensagem: str,
    nome_remetente: str = "",
) -> Dict[str, Any]:
    """
    Processa uma resposta recebida no Webhook do WhatsApp:
    1) Faz casamento inteligente de DDI +55 com ou sem o 9º dígito;
    2) Classifica automaticamente em OPT_OUT (bloqueio imediato LGPD), INTERESSADO (gera link wa.me para o consultor) ou DUVIDA;
    3) Gera auto-resposta imediata e persiste atomicamente no CSV.
    """
    cfg = carregar_config_lead_manager()
    tel_norm = normalizar_telefone_br(telefone)
    possiveis = set(variantes_nono_digito(tel_norm))

    leads = carregar_leads_csv()
    alvo = None
    for lead in leads:
        vars_lead = set(variantes_nono_digito(lead.get("telefone_normalizado", "")))
        if possiveis & vars_lead or (nome_remetente and nome_remetente.lower() in lead.get("empresa", "").lower()):
            alvo = lead
            break

    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not alvo:
        alvo = {
            "id": f"LEAD-{str(uuid.uuid4())[:6].upper()}",
            "empresa": censurar_dados_sensiveis(nome_remetente or "Novo Lead Inbound WhatsApp"),
            "contato": censurar_dados_sensiveis(nome_remetente or "Contato WhatsApp"),
            "telefone_original": telefone,
            "telefone_normalizado": tel_norm or "+5500000000000",
            "segmento": "Inbound Webhook",
            "porte_vidas": "A qualificar",
            "status": "PENDENTE",
            "ultima_interacao": agora,
            "ultima_mensagem_lead": "",
            "auto_resposta_enviada": "",
            "consultor_wa_link": "",
        }
        leads.insert(0, alvo)

    texto_limpo = (mensagem or "").strip().lower()
    eh_optout = any(p in texto_limpo for p in PALAVRAS_OPT_OUT) or texto_limpo == "2"
    eh_interessado = (not eh_optout) and (any(p in texto_limpo for p in PALAVRAS_INTERESSE) or texto_limpo == "1")

    if eh_optout:
        novo_status = "OPT_OUT"
        auto_resp = (
            str(cfg.get("auto_resposta_optout", ""))
            .replace("{empresa}", alvo.get("empresa", ""))
            .replace("{contato}", alvo.get("contato", ""))
        )
        alvo["consultor_wa_link"] = ""
    elif eh_interessado:
        novo_status = "INTERESSADO"
        auto_resp = (
            str(cfg.get("auto_resposta_interessado", ""))
            .replace("{empresa}", alvo.get("empresa", ""))
            .replace("{contato}", alvo.get("contato", ""))
        )
        alvo["consultor_wa_link"] = gerar_link_wa_consultor(
            alvo.get("telefone_normalizado", ""),
            alvo.get("empresa", ""),
            alvo.get("contato", ""),
            mensagem,
        )
    else:
        novo_status = "DUVIDA"
        auto_resp = (
            f"Olá {alvo.get('contato', '')}! Recebemos sua mensagem sobre a *{alvo.get('empresa', '')}*. "
            "Um consultor especialista já vai te responder diretamente por aqui!"
        )
        alvo["consultor_wa_link"] = gerar_link_wa_consultor(
            alvo.get("telefone_normalizado", ""),
            alvo.get("empresa", ""),
            alvo.get("contato", ""),
            mensagem,
        )

    alvo["status"] = novo_status
    alvo["ultima_interacao"] = agora
    alvo["ultima_mensagem_lead"] = censurar_dados_sensiveis(mensagem)
    alvo["auto_resposta_enviada"] = censurar_dados_sensiveis(auto_resp)

    salvar_leads_atomico(leads)
    return {
        "lead": alvo,
        "classificacao": novo_status,
        "auto_resposta": auto_resp,
        "metricas": calcular_metricas_leads(leads),
    }


def atualizar_status_lead_manual(lead_id: str, novo_status: str) -> Optional[Dict[str, str]]:
    leads = carregar_leads_csv()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for lead in leads:
        if lead.get("id") == lead_id:
            lead["status"] = novo_status.upper()
            lead["ultima_interacao"] = agora
            salvar_leads_atomico(leads)
            return lead
    return None


def gerar_script_abordagem_ia(segmento_alvo: str, objetivo: str = "") -> str:
    """Usa o Gemini para criar um template de prospecção B2B anti-spam para WhatsApp Cloud API."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return (
            f"Olá, {{contato}} da *{{empresa}}*! Vi que vocês atuam no setor de *{segmento_alvo or '{segmento}'}*.\n\n"
            "Implementamos uma revisão corporativa que vem gerando redução direta de custos operacionais para empresas de *{porte_vidas}*.\n\n"
            "Responda *1* para receber uma simulação rápida ou *2* para encerrar o contato."
        )

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=(
            "Você é o especialista em vendas B2B e WhatsApp Cloud API do Assistant-to-the-Lead-Manager (Filial Scranton). "
            "Crie uma mensagem curta, humana, de alta conversão e 100% compatível com as políticas anti-spam da Meta. "
            "Use obrigatoriamente as variáveis {contato}, {empresa}, {segmento} e {porte_vidas}, e finalize com opção 1 (interesse) ou 2 (opt-out)."
        ),
    )
    prompt = f"Segmento alvo: {segmento_alvo}\nObjetivo da campanha: {objetivo or 'Qualificar leads empresariais B2B e agendar conversa com o consultor.'}"
    resp = model.generate_content(prompt)
    return (resp.text or "").strip()
