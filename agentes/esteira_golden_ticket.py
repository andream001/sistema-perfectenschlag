import imaplib
import json
import os
import re
import smtplib
import sys
import urllib.request
import uuid
from datetime import datetime
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from typing import Any, Dict, List, Optional
sys.path.append(str(Path(__file__).resolve().parent.parent))
from base_conhecimento import carregar_perfil_gerente, formatar_dossie_para_prompt, pendencias_perfil
from agentes.formato_candidatura import avaliar_formato_candidatura, resumo_formato_para_prompt
from agentes.curriculo_profissional import (
    bloqueios,
    gerar_docx_bytes,
    montar_curriculo_markdown,
    nome_arquivo_cv,
    validar_documento,
)
from sanitizador_seguranca import censurar_dados_sensiveis

try:
    import google.generativeai as genai
except ImportError:
    from base_conhecimento import genai_compat as genai

ARQUIVO_CANDIDATURAS = Path(__file__).resolve().parent.parent / "candidaturas_golden_ticket.json"
ARQUIVO_LOG_CURRICULOS = Path(__file__).resolve().parent.parent / "curriculos_enviados_log.json"
ETAPAS_PROCESSO_VALIDAS = (
    "ENVIADO",
    "AUTORIZADO_MANUAL",
    "EM_ANALISE",
    "ENTREVISTA_AGENDADA",
    "TESTE_TECNICO",
    "PROPOSTA",
    "FINALIZADO_SEM_RETORNO",
    "VETADO",
)

SECOES = ("DIAGNOSTICO", "CURRICULO", "MENSAGEM", "ENTREVISTA", "ACOMPANHAMENTO")

SYSTEM_PROMPT_GOLDEN_TICKET = """Você é um recrutador técnico sênior e consultor de carreira em tecnologia.
Seu trabalho é preparar uma candidatura real, que será lida por um recrutador humano e por um sistema de triagem (ATS).

REGRAS QUE NÃO PODEM SER QUEBRADAS
1. Use somente fatos do dossiê do candidato. Não invente empresa, cargo, data, número, certificação nem tecnologia.
   Se a vaga pede algo que o candidato não tem, não escreva que ele tem: registre o ponto no DIAGNÓSTICO.
   - Em inglês, traduza Análise e Desenvolvimento de Sistemas (Tecnólogo) como "Associate / Technologist Degree in Systems Analysis and Development (ADS)" — NUNCA use "B.S." ou "Bachelor of Science".
   - Mantenha exatamente o nível de idiomas do dossiê (ex.: Técnico Intermediário / Technical Intermediate) — NUNCA eleve o nível.
   - Mantenha a localização real do dossiê; NUNCA afirme disponibilidade presencial ou híbrida em outra cidade (ex.: São Paulo, Rio de Janeiro, Curitiba) nem repita a cidade da vaga como se o candidato morasse lá ou estivesse disponível para modelo híbrido/presencial lá.
   - Use verbos fiéis ao dossiê ("desenvolvi", "implementei", "automatizei", "reduzi"); NUNCA escreva "liderei" nem "economia para clientes" se o dossiê não disser isso.
   - Ao mencionar o currículo anexo na mensagem, escreva apenas "meu currículo em anexo" — NUNCA escreva "currículo em PDF", pois o arquivo anexado é `.docx`.
   - Use o título profissional real do dossiê (adaptado com honestidade); não copie um título de vaga incompatível.
2. Números (economia, percentuais, prazos) só aparecem se estiverem no dossiê, com o mesmo valor. Não repita o mesmo número em todas as seções.
3. O CURRÍCULO e a MENSAGEM vão para fora. Neles é proibido: marcadores como [EMAIL_PROTEGIDO] ou [VALOR A SER PREENCHIDO], nomes de agentes ou personagens,
   termos internos do sistema, comentários sobre ATS, notas, emojis e texto em caixa alta para ênfase. Escreva links de contato como URL simples (ex.: linkedin.com/in/andrebunhak), sem colchetes [LinkedIn](...).
4. Tom profissional, objetivo e sóbrio. Nada de adjetivos como "implacável", "letal", "elite", "dominante".
5. Escreva no idioma indicado em FORMATO DA CANDIDATURA e mantenha as experiências em ordem cronológica reversa (mais recente primeiro).

COMO ESCREVER O CURRÍCULO (Markdown simples, uma coluna, sem tabelas)
- "# Nome completo", na linha seguinte "**Título alinhado à vaga**", depois uma linha com cidade · e-mail · telefone · LinkedIn · GitHub.
- "## Resumo profissional": 3 a 4 linhas, com o cargo da vaga e 2 ou 3 competências que ela pede e que o candidato tem.
- "## Competências técnicas": lista agrupada (ex.: "Linguagens: ...", "Infraestrutura: ..."), priorizando os termos exatos da vaga que constam no dossiê.
- "## Experiência profissional": "### Cargo · Empresa · período" e de 3 a 5 bullets por experiência, cada um começando com verbo no passado e dizendo o resultado.
- "## Projetos", "## Formação" e "## Idiomas" quando houver dados.
- Entre 450 e 800 palavras (1 a 2 páginas).

COMO ESCREVER A MENSAGEM
- Se o canal for e-mail: corpo de e-mail com saudação, 3 parágrafos curtos (até 150 palavras no total) e assinatura com nome e telefone. Não inclua o assunto.
- Se for plataforma ou formulário: texto de até 120 palavras para o campo de carta de apresentação ou "informações adicionais".

RESPONDA EXATAMENTE COM ESTAS 5 SEÇÕES, NESTA ORDEM:
===DIAGNOSTICO===
Aderência (0 a 100) com uma frase de justificativa; requisitos atendidos; requisitos que faltam ou estão fracos; palavras-chave da vaga usadas no currículo.
===CURRICULO===
O currículo completo, pronto para enviar.
===MENSAGEM===
A mensagem de apresentação.
===ENTREVISTA===
Apresentação de 60 segundos; 5 perguntas prováveis com respostas no formato STAR usando só fatos do dossiê; 3 perguntas inteligentes para o candidato fazer ao entrevistador (sobre time, desafios e expectativas do cargo).
===ACOMPANHAMENTO===
Quando e como fazer follow-up, e o que vigiar no e-mail ou na plataforma."""


def _separar_secoes(texto: str) -> Dict[str, str]:
    """Divide a resposta da IA nas 5 seções. Aceita os separadores antigos por compatibilidade."""
    texto = texto or ""
    antigos = {
        "===SECAO_CURRICULO_MOLDADO===": "===CURRICULO===",
        "===SECAO_PREPARACAO_ENTREVISTA===": "===ENTREVISTA===",
        "===SECAO_PLANO_MONITORAMENTO===": "===ACOMPANHAMENTO===",
    }
    for velho, novo in antigos.items():
        texto = texto.replace(velho, novo)
    partes = re.split(r"^\s*===\s*(DIAGNOSTICO|DIAGNÓSTICO|CURRICULO|CURRÍCULO|MENSAGEM|ENTREVISTA|ACOMPANHAMENTO)\s*===\s*$", texto, flags=re.MULTILINE | re.IGNORECASE)
    out: Dict[str, str] = {k: "" for k in SECOES}
    for i in range(1, len(partes) - 1, 2):
        chave = partes[i].upper().replace("Ó", "O").replace("Í", "I")
        out[chave] = partes[i + 1].strip()
    if not any(out.values()):
        out["CURRICULO"] = texto.strip()
    # Remove cercas de código que alguns modelos colocam em volta do Markdown
    for k, v in out.items():
        out[k] = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", v.strip())
    return out


def _palavras_chave_vaga(texto: str) -> List[str]:
    candidatas = ("Python", "Docker", "Kubernetes", "API", "REST", "SQL", "PostgreSQL", "MySQL", "Git", "Linux", "AWS", "Azure",
                  "GCP", "FastAPI", "Flask", "Django", "Redis", "n8n", "RPA", "IA", "LLM", "CI/CD", "Terraform", "Snipe-IT", "ITAM",
                  "DevOps", "Automação", "Automation", "Power BI", "Excel", "C", "Node", "JavaScript", "TypeScript")
    low = f" {texto.lower()} "
    return [k for k in candidatas if re.search(rf"(?<![a-z0-9]){re.escape(k.lower())}(?![a-z0-9])", low)]


def avaliar_qualidade_candidatura(c: Dict[str, Any]) -> Dict[str, Any]:
    """Checa currículo, mensagem e perfil. Grava em c['qualidade'] e devolve o resultado."""
    fmt = c.get("formato_candidatura") or {}
    idioma = fmt.get("idioma_curriculo", "pt")
    exigencias = fmt.get("exigencias") or []
    msg_txt = (c.get("mensagem_apresentacao") or "").strip()
    cv_txt = (c.get("curriculo_moldado") or "").strip()

    prob_cv = validar_documento(cv_txt, "curriculo", idioma)
    prob_msg = validar_documento(msg_txt, "mensagem", idioma) if msg_txt else []
    pend = pendencias_perfil()
    bloq = bloqueios(prob_cv) + [f"Mensagem: {b}" for b in bloqueios(prob_msg)]
    extras: List[str] = []

    if c.get("gerado_por_ia") is False:
        extras.append("Currículo montado sem IA, direto do perfil: o texto não foi adaptado a esta vaga.")

    if not msg_txt:
        if fmt.get("envio_automatico_permitido") or "Carta de apresentação" in exigencias:
            bloq.append(
                "Sem mensagem de apresentação (obrigatória para envio por e-mail ou quando a vaga pede carta de apresentação)."
            )
        else:
            extras.append("Sem mensagem de apresentação.")

    if "Pretensão salarial" in exigencias:
        msg_low = msg_txt.lower()
        # Remove menções à métrica de economia (R$ 20.000/ano) para não confundir com pretensão salarial
        msg_sem_economia = re.sub(r"economia[^.\n]{0,60}", "", msg_low)
        tem_placeholder_valor = bool(re.search(r"\[[^\]]*(valor|preench|pretens|sal[aá]ri)[^\]]*\]", msg_low))
        tem_pretensao = (not tem_placeholder_valor) and bool(
            re.search(
                r"(r\$\s*\d[\d.,]*|usd\s*\d[\d.,]*|\$\s*\d[\d.,]*|\b\d{1,2}\.\d{3}(?:,\d{2})?\b|\b\d{4,5}\s*(?:reais|brl|usd|/\s*m[eê]s|mensais)|\b\d+\s*k(?:\s*/\s*m[eê]s|\s*reais|\s*brl|\s*usd)?\b)",
                msg_sem_economia,
            )
        )
        if not tem_pretensao:
            bloq.append("A vaga pede pretensão salarial: informe um valor monetário real na mensagem (ex.: R$ 4.500/mês) antes de autorizar.")

    if fmt.get("envio_automatico_permitido") and re.search(r"\bpdf\b", msg_txt, flags=re.IGNORECASE):
        extras.append("A mensagem menciona 'PDF', mas o anexo automático enviado por e-mail é .docx. Ajuste o texto ou envie manualmente em PDF.")

    qualidade = {
        "verificado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pronto_para_envio": not bloq,
        "bloqueios": bloq,
        "avisos": extras + [p["msg"] for p in prob_cv if p["nivel"] == "aviso"] + [f"Mensagem: {p['msg']}" for p in prob_msg if p["nivel"] == "aviso"],
        "pendencias_perfil": pend,
    }
    c["qualidade"] = qualidade
    return qualidade


def verificar_api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Fato: Você esqueceu a chave da API. Inaceitável.")
        sys.exit(1)
    return api_key


def carregar_candidaturas() -> List[Dict[str, Any]]:
    if not ARQUIVO_CANDIDATURAS.exists():
        return []
    try:
        with open(ARQUIVO_CANDIDATURAS, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def salvar_candidaturas(lista: List[Dict[str, Any]]) -> None:
    with open(ARQUIVO_CANDIDATURAS, "w", encoding="utf-8") as f:
        json.dump(lista, f, ensure_ascii=False, indent=2)


def carregar_log_curriculos() -> List[Dict[str, Any]]:
    if not ARQUIVO_LOG_CURRICULOS.exists():
        return []
    try:
        data = json.loads(ARQUIVO_LOG_CURRICULOS.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def salvar_log_curriculos(lista: List[Dict[str, Any]]) -> None:
    tmp = ARQUIVO_LOG_CURRICULOS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(lista, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, ARQUIVO_LOG_CURRICULOS)


def registrar_ou_atualizar_processo_curriculo(
    candidatura_id: str,
    cargo_empresa: str = "",
    link_ou_email: str = "",
    etapa_processo: str = "ENVIADO",
    observacao: str = "",
    nota_ats: Optional[int] = None,
) -> Dict[str, Any]:
    """Registra ou atualiza no log persistente um currículo enviado e a etapa atual do processo seletivo."""
    etapa = str(etapa_processo or "ENVIADO").strip().upper()
    if etapa not in ETAPAS_PROCESSO_VALIDAS:
        etapa = "EM_ANALISE"

    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logs = carregar_log_curriculos()
    existente = next((x for x in logs if str(x.get("id", "")).upper() == str(candidatura_id).strip().upper()), None)

    if existente:
        existente["etapa_processo"] = etapa
        existente["ultima_atualizacao"] = agora
        if cargo_empresa:
            existente["cargo_empresa"] = censurar_dados_sensiveis(cargo_empresa)
        if link_ou_email:
            existente["link_ou_email"] = link_ou_email
        if nota_ats is not None:
            existente["nota_ats"] = nota_ats
        if observacao:
            existente.setdefault("historico_etapas", []).insert(0, f"[{agora}] {etapa}: {censurar_dados_sensiveis(observacao)}")
        else:
            existente.setdefault("historico_etapas", []).insert(0, f"[{agora}] Etapa alterada para {etapa}")
        salvar_log_curriculos(logs)
        return existente

    novo = {
        "id": str(candidatura_id).strip().upper(),
        "cargo_empresa": censurar_dados_sensiveis(cargo_empresa or "Vaga"),
        "link_ou_email": link_ou_email,
        "enviado_em": agora,
        "ultima_atualizacao": agora,
        "etapa_processo": etapa,
        "nota_ats": nota_ats,
        "historico_etapas": [f"[{agora}] {etapa}: {censurar_dados_sensiveis(observacao) or 'Currículo enviado / registrado'}"],
    }
    logs.insert(0, novo)
    salvar_log_curriculos(logs)
    return novo


def criar_pacote_candidatura(
    cargo_empresa: str,
    link_ou_email: str,
    descricao_vaga: str,
    observacoes_extras: str = "",
) -> Dict[str, Any]:
    """
    Avalia o formato da vaga, gera currículo, mensagem e preparação de entrevista,
    checa a qualidade e deixa tudo travado em AGUARDANDO_AUTORIZACAO_ENVIO.
    """
    api_key = verificar_api_key()
    genai.configure(api_key=api_key)

    perfil = carregar_perfil_gerente()
    dossie = formatar_dossie_para_prompt()
    formato = avaliar_formato_candidatura(link_ou_email, descricao_vaga, cargo_empresa)
    kws = _palavras_chave_vaga(f"{cargo_empresa}\n{descricao_vaga}")

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=SYSTEM_PROMPT_GOLDEN_TICKET,
    )

    idioma_alvo = formato.get("idioma_curriculo", "pt")
    aviso_idioma = (
        "\nCRITICAL: THIS JOB IS IN ENGLISH. Write 100% of ===CURRICULO=== and ===MENSAGEM=== in natural, professional ENGLISH (zero Portuguese words or sentences)."
        if idioma_alvo == "en"
        else ""
    )

    prompt = f"""VAGA
Cargo e empresa: {cargo_empresa}
Link ou e-mail: {link_ou_email}
Observações do candidato: {observacoes_extras or 'nenhuma'}

DESCRIÇÃO DA VAGA:
{descricao_vaga}

FORMATO DA CANDIDATURA (avaliado pelo sistema):
{resumo_formato_para_prompt(formato)}

{dossie}
{aviso_idioma}
Responda de forma completa (sem cortar frases) com as 5 seções: ===DIAGNOSTICO===, ===CURRICULO===, ===MENSAGEM===, ===ENTREVISTA===, ===ACOMPANHAMENTO===."""

    gerado_por_ia = True
    try:
        response = model.generate_content(prompt)
        secoes = _separar_secoes(response.text or "")
        if not secoes["CURRICULO"]:
            raise ValueError("a resposta veio sem a seção de currículo")
        # Se a vaga é em inglês mas o modelo devolveu o currículo em português, tenta novamente com gemini-3-flash-preview
        if idioma_alvo == "en" and any("inglês" in b.lower() for b in bloqueios(validar_documento(secoes["CURRICULO"], "curriculo", "en"))):
            try:
                model_en = genai.GenerativeModel(
                    model_name="gemini-3-flash-preview",
                    system_instruction=SYSTEM_PROMPT_GOLDEN_TICKET,
                )
                resp_en = model_en.generate_content(
                    prompt + "\n\nATTENTION: Previous draft was in Portuguese. Rewrite ===CURRICULO=== and ===MENSAGEM=== 100% in ENGLISH."
                )
                secoes_en = _separar_secoes(resp_en.text or "")
                if secoes_en["CURRICULO"]:
                    secoes = secoes_en
            except Exception:
                pass
    except Exception as exc_ia:
        # Plano B: currículo montado direto do perfil, sem inventar nada e sem texto de controle
        gerado_por_ia = False
        idioma = formato.get("idioma_curriculo", "pt")
        secoes = {
            "DIAGNOSTICO": f"A IA não respondeu ({exc_ia}). Currículo montado a partir do perfil, sem adaptação de texto à vaga.\n"
                           f"Palavras-chave da vaga encontradas no perfil: {', '.join(kws) or 'nenhuma identificada'}.",
            "CURRICULO": montar_curriculo_markdown(perfil, idioma, kws),
            "MENSAGEM": "",
            "ENTREVISTA": "Gere novamente quando a IA estiver disponível.",
            "ACOMPANHAMENTO": "Follow-up educado após 5 a 7 dias úteis sem resposta.",
        }

    nova_candidatura = {
        "id": str(uuid.uuid4())[:8].upper(),
        "criado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cargo_empresa": censurar_dados_sensiveis(cargo_empresa),
        "link_ou_email": link_ou_email.strip(),
        "descricao_vaga": censurar_dados_sensiveis(descricao_vaga),
        "status": "AGUARDANDO_AUTORIZACAO_ENVIO",  # AGUARDANDO_AUTORIZACAO_ENVIO | AUTORIZADO_EM_MONITORAMENTO | ENTREVISTA_CONVOCADA | VETADO
        "gerado_por_ia": gerado_por_ia,
        "formato_candidatura": formato,
        "diagnostico": censurar_dados_sensiveis(secoes["DIAGNOSTICO"]),
        # Currículo e mensagem guardam os dados reais: são o que vai para o recrutador.
        "curriculo_moldado": secoes["CURRICULO"].strip(),
        "mensagem_apresentacao": (
            re.sub(r"\b(?:em\s+formato\s+pdf|no\s+formato\s+pdf|em\s+pdf)\b", "em anexo", secoes["MENSAGEM"].strip(), flags=re.IGNORECASE)
            if formato.get("envio_automatico_permitido")
            else secoes["MENSAGEM"].strip()
        ),
        "preparacao_entrevista": censurar_dados_sensiveis(secoes["ENTREVISTA"]),
        "plano_monitoramento": censurar_dados_sensiveis(secoes["ACOMPANHAMENTO"]),
        "ultimo_check_monitoramento": "Ainda não enviado (aguardando sua autorização)",
        "alertas_monitoramento": [],
    }
    avaliar_qualidade_candidatura(nova_candidatura)

    todas = carregar_candidaturas()
    todas.insert(0, nova_candidatura)
    salvar_candidaturas(todas)
    return nova_candidatura


def _termo_busca_email(c: Dict[str, Any]) -> str:
    """Nome da empresa (parte depois de '—', '-' ou '@') para buscar no assunto dos e-mails."""
    ce = str(c.get("cargo_empresa", ""))
    for sep in ("—", " - ", " @ ", " | "):
        if sep in ce:
            emp = ce.split(sep)[-1].strip()
            if emp:
                return emp.replace('"', "")[:40]
    palavras = [p for p in re.findall(r"[\wÀ-ÿ]+", ce) if len(p) > 3]
    return (palavras[-1] if palavras else ce.split()[0] if ce else "vaga").replace('"', "")


def verificar_status_vaga_E_email(candidatura_id: str) -> Dict[str, Any]:
    """
    Vigia a vaga verificando:
    1) Se o link da plataforma continua ativo (HTTP check);
    2) Se há novos e-mails sobre a vaga na caixa IMAP (quando IMAP_USER e IMAP_PASSWORD estão configurados no ambiente).
    """
    todas = carregar_candidaturas()
    alvo = next((c for c in todas if c.get("id") == candidatura_id), None)
    if not alvo:
        return {"erro": "Candidatura não encontrada."}

    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    relatorio_checks: List[str] = []

    link = alvo.get("link_ou_email", "")
    if link.startswith("http://") or link.startswith("https://"):
        try:
            req = urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                code = resp.getcode()
                relatorio_checks.append(f"[{agora}] Plataforma verificada (HTTP {code}): Página da vaga online e ativa.")
        except Exception as e:
            relatorio_checks.append(f"[{agora}] Aviso na URL da plataforma: {e}")
    elif "@" in link:
        relatorio_checks.append(f"[{agora}] Destinatário de e-mail registrado ({link}). Monitorando respostas.")

    # Verificação opcional via IMAP se o Gerente configurou IMAP_USER e IMAP_APP_PASSWORD
    imap_user = os.environ.get("IMAP_USER")
    imap_pass = os.environ.get("IMAP_APP_PASSWORD")
    imap_host = os.environ.get("IMAP_HOST", "imap.gmail.com")

    if imap_user and imap_pass:
        try:
            mail = imaplib.IMAP4_SSL(imap_host)
            mail.login(imap_user, imap_pass)
            mail.select("inbox")
            termo_busca = _termo_busca_email(alvo)
            _, msg_nums = mail.search(None, f'(UNSEEN SUBJECT "{termo_busca}")')
            ids = msg_nums[0].split() if msg_nums and msg_nums[0] else []
            relatorio_checks.append(
                f"[{agora}] Caixa de E-mail ({imap_user}) inspecionada: {len(ids)} novo(s) e-mail(s) não lido(s) mencionando '{termo_busca}'."
            )
            mail.logout()
        except Exception as exc:
            relatorio_checks.append(f"[{agora}] Falha ao checar IMAP: {exc}")
    else:
        relatorio_checks.append(
            f"[{agora}] Vigia de E-mail: Pronto (Configure IMAP_USER/IMAP_APP_PASSWORD ou use o conector Gmail para leitura automática da inbox)."
        )

    alvo["ultimo_check_monitoramento"] = agora
    alvo.setdefault("alertas_monitoramento", []).extend(relatorio_checks)
    salvar_candidaturas(todas)
    return alvo


def decidir_envio_candidatura(
    candidatura_id: str,
    decisao: str,
    curriculo_editado: Optional[str] = None,
    mensagem_editada: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Aplica a decisão do Gerente Regional:
    - 'AUTORIZAR': Libera o envio, muda para AUTORIZADO_EM_MONITORAMENTO e dispara SMTP se configurado.
    - 'VETAR': Cancela a candidatura.
    - 'SALVAR_EDICAO': Atualiza o texto do currículo moldado antes de enviar.
    """
    todas = carregar_candidaturas()
    for c in todas:
        if c.get("id") == candidatura_id:
            if curriculo_editado:
                # Não censurar aqui: este texto é o que vai para o recrutador
                c["curriculo_moldado"] = curriculo_editado
            if mensagem_editada is not None:
                c["mensagem_apresentacao"] = mensagem_editada
            if curriculo_editado or mensagem_editada is not None:
                avaliar_qualidade_candidatura(c)

            dec = decisao.upper()
            if dec == "AUTORIZAR":
                if not c.get("formato_candidatura"):
                    c["formato_candidatura"] = avaliar_formato_candidatura(c.get("link_ou_email", ""), c.get("descricao_vaga", ""), c.get("cargo_empresa", ""))
                qualidade = avaliar_qualidade_candidatura(c)
                if not qualidade["pronto_para_envio"]:
                    salvar_candidaturas(todas)
                    c["erro_envio"] = "Envio bloqueado: corrija os itens abaixo e autorize de novo."
                    return c
                c.pop("erro_envio", None)
                fmt = c["formato_candidatura"]
                c["status"] = "AUTORIZADO_EM_MONITORAMENTO"
                c["autorizado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                c["ultimo_check_monitoramento"] = (
                    f"Autorizada em {c['autorizado_em']} "
                    f"({'envio por e-mail' if fmt.get('envio_automatico_permitido') else 'candidatura manual em ' + str(fmt.get('plataforma') or 'plataforma')})"
                )
                c.setdefault("alertas_monitoramento", []).append(
                    f"[{c['autorizado_em']}] Candidatura autorizada. Canal: {fmt.get('plataforma')}."
                )
                nota_aud = (c.get("auditoria_recrutador_final") or {}).get("nota_ats")
                registrar_ou_atualizar_processo_curriculo(
                    candidatura_id=str(c.get("id", "")),
                    cargo_empresa=str(c.get("cargo_empresa", "")),
                    link_ou_email=str(c.get("link_ou_email", "")),
                    etapa_processo=("ENVIADO" if fmt.get("envio_automatico_permitido") else "AUTORIZADO_MANUAL"),
                    observacao=("Enviada por e-mail." if fmt.get("envio_automatico_permitido") else f"Autorizada para candidatura manual em {fmt.get('plataforma')}."),
                    nota_ats=nota_aud,
                )

                destinatario = str(fmt.get("email_destino") or "").strip()
                smtp_user = os.environ.get("SMTP_USER", "").strip()
                smtp_pass = os.environ.get("SMTP_APP_PASSWORD", "").strip()
                smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
                smtp_port = int(os.environ.get("SMTP_PORT", "587") or 587)

                if not fmt.get("envio_automatico_permitido"):
                    c["alertas_monitoramento"].append(
                        f"[{c['autorizado_em']}] Este canal não aceita envio por e-mail. Candidate-se em {fmt.get('plataforma')} "
                        f"com o currículo (.docx) e a mensagem de apresentação. Passos: " + " | ".join(fmt.get("como_aplicar", []))
                    )
                elif smtp_user and smtp_pass and destinatario:
                    try:
                        perfil = carregar_perfil_gerente()
                        nome = perfil.get("nome_completo", "").strip()
                        cargo = str(c.get("cargo_empresa", "Vaga")).split("—")[0].strip()
                        assunto = fmt.get("assunto_pedido") or (f"Candidatura · {cargo} · {nome}" if nome else f"Candidatura · {cargo}")
                        msg = MIMEMultipart()
                        msg["From"] = formataddr((nome, smtp_user)) if nome else smtp_user
                        msg["To"] = destinatario
                        msg["Subject"] = assunto
                        msg["Reply-To"] = (perfil.get("contatos", {}) or {}).get("email") or smtp_user
                        msg.attach(MIMEText(c.get("mensagem_apresentacao", ""), "plain", "utf-8"))
                        anexo = MIMEApplication(
                            gerar_docx_bytes(c.get("curriculo_moldado", ""), f"Currículo · {nome}"),
                            _subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
                        )
                        anexo.add_header("Content-Disposition", "attachment", filename=nome_arquivo_cv(perfil))
                        msg.attach(anexo)
                        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as srv:
                            srv.starttls()
                            srv.login(smtp_user, smtp_pass)
                            srv.send_message(msg)
                        c["alertas_monitoramento"].append(
                            f"[{c['autorizado_em']}] E-mail enviado para {destinatario} com o currículo anexado (assunto: {assunto})."
                        )
                    except Exception as exc_smtp:
                        c["alertas_monitoramento"].append(
                            f"[{c['autorizado_em']}] Falha no envio por e-mail ({smtp_host}): {exc_smtp}"
                        )
                else:
                    c["alertas_monitoramento"].append(
                        f"[{c['autorizado_em']}] SMTP não configurado: envie você mesmo para {destinatario} com o currículo anexado."
                    )

                wh_url = os.environ.get("GOLDEN_TICKET_WEBHOOK_URL", "").strip()
                if wh_url and fmt.get("envio_automatico_permitido") and destinatario:
                    try:
                        payload_wh = json.dumps({
                            "acao": "ENVIAR_CANDIDATURA_APROVADA",
                            "id": c.get("id"),
                            "cargo_empresa": c.get("cargo_empresa"),
                            "canal": fmt.get("canal"),
                            "destinatario": destinatario,
                            "curriculo_moldado": c.get("curriculo_moldado"),
                            "mensagem_apresentacao": c.get("mensagem_apresentacao"),
                            "autorizado_em": c["autorizado_em"],
                        }).encode("utf-8")
                        req_wh = urllib.request.Request(
                            wh_url,
                            data=payload_wh,
                            headers={"Content-Type": "application/json; charset=utf-8"},
                            method="POST",
                        )
                        urllib.request.urlopen(req_wh, timeout=10)
                        c["alertas_monitoramento"].append(
                            f"[{c['autorizado_em']}] Webhook de envio disparado ({wh_url[:45]})."
                        )
                    except Exception as exc_wh:
                        c["alertas_monitoramento"].append(
                            f"[{c['autorizado_em']}] Falha no webhook de envio: {exc_wh}"
                        )
            elif dec == "VETAR":
                c["status"] = "VETADO"
                c["ultimo_check_monitoramento"] = "Candidatura vetada."
                logs_atuais = carregar_log_curriculos()
                if any(str(x.get("id", "")).upper() == str(c.get("id", "")).upper() for x in logs_atuais):
                    registrar_ou_atualizar_processo_curriculo(
                        candidatura_id=str(c.get("id", "")),
                        cargo_empresa=str(c.get("cargo_empresa", "")),
                        link_ou_email=str(c.get("link_ou_email", "")),
                        etapa_processo="VETADO",
                        observacao="Candidatura vetada pelo candidato.",
                    )
            elif dec == "ENTREVISTA":
                c["status"] = "ENTREVISTA_CONVOCADA"
                c.setdefault("alertas_monitoramento", []).append(
                    f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🎯 Entrevista marcada. Preparação de entrevista disponível."
                )

            salvar_candidaturas(todas)
            return c
    return None


def registrar_retorno_webhook(
    empresa_ou_id: str,
    remetente: str,
    assunto: str,
    mensagem: str,
) -> Optional[Dict[str, Any]]:
    """
    Recebe um evento externo via Webhook (n8n, Make, Google Apps Script ou Evolution API)
    avisando que um recrutador respondeu por e-mail/WhatsApp ou que o status na plataforma mudou.
    """
    todas = carregar_candidaturas()
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    termo = (empresa_ou_id or "").strip().lower()

    dominio_rem = (remetente.split("@")[-1].lower().strip(" >") if "@" in (remetente or "") else "")
    alvo = None
    for c in todas:
        link = c.get("link_ou_email", "").lower()
        if termo and (c.get("id", "").lower() == termo or (len(termo) >= 3 and (termo in c.get("cargo_empresa", "").lower() or termo in link))):
            alvo = c
            break
        if dominio_rem and dominio_rem not in ("gmail.com", "outlook.com", "hotmail.com", "yahoo.com") and dominio_rem in link:
            alvo = c
            break

    # Sem correspondência clara, não anexa a resposta à candidatura errada
    if not alvo:
        return None

    resumo_seguro = censurar_dados_sensiveis(f"De: {remetente} | Assunto: {assunto} | Msg: {mensagem[:300]}")
    alvo.setdefault("alertas_monitoramento", []).append(
        f"[{agora}] 🔔 WEBHOOK RECEBIDO -> {resumo_seguro}"
    )
    alvo["ultimo_check_monitoramento"] = agora

    texto_comb = f"{assunto} {mensagem}".lower()
    negativo = any(k in texto_comb for k in ("infelizmente", "não seguiremos", "nao seguiremos", "unfortunately", "not move forward", "outro candidato", "encerrad"))
    convite = re.search(r"(agendar|marcar|convid\w*|disponibilidade)[^.]{0,60}(entrevista|conversa|bate-papo|call)|(schedule|invite)[^.]{0,40}(interview|call)|entrevista (agendada|marcada|confirmada)|pr[oó]xima etapa", texto_comb)
    if convite and not negativo:
        alvo["status"] = "ENTREVISTA_CONVOCADA"

    salvar_candidaturas(todas)
    return alvo


