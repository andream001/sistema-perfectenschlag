import imaplib
import json
import os
import smtplib
import sys
import urllib.request
import uuid
from datetime import datetime
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional
sys.path.append(str(Path(__file__).resolve().parent.parent))
from base_conhecimento import formatar_dossie_para_prompt
from sanitizador_seguranca import censurar_dados_sensiveis

try:
    import google.generativeai as genai
except ImportError:
    from base_conhecimento import genai_compat as genai

ARQUIVO_CANDIDATURAS = Path(__file__).resolve().parent.parent / "candidaturas_golden_ticket.json"

SYSTEM_PROMPT_GOLDEN_TICKET = """Você é o Comitê Integrado da OPERAÇÃO GOLDEN TICKET da Filial Scranton, composto por:
1. NEUTRALIZADOR TOBY (Especialista Anti-ATS): Molda o currículo cirurgicamente para a vaga inserida e redige o e-mail/mensagem de abordagem ao recrutador.
2. PROTOCOLO RECYCLOPS & TREINADOR DE ENTREVISTA (Dwight Schrute & Michael Scott): Prepara o candidato para a entrevista dessa vaga específica, antecipando as perguntas do recrutador com respostas no formato STAR e criando as 3 perguntas interrogatórias impiedosas.
3. VIGIA DE CANDIDATURA (Pam Beesly): Define os gatilhos de monitoramento de e-mail e da plataforma da vaga.

REGRA DE OURO INVIOLÁVEL:
NADA é enviado ao recrutador ou publicado na plataforma sem a AUTORIZAÇÃO EXPRESSA do Gerente Regional.

Retorne SEMPRE a resposta dividida exatamente com estes 3 separadores:
===SECAO_CURRICULO_MOLDADO===
(Diagnóstico de palavras-chave ATS + Currículo Completo moldado sob medida para esta vaga + E-mail/Mensagem curta de apresentação para o recrutador)

===SECAO_PREPARACAO_ENTREVISTA===
(1. Como se apresentar em 60 segundos para esta vaga;
 2. As 4 perguntas técnicas/comportamentais mais prováveis que farão nesta vaga + Respostas exatas usando a economia de R$ 20 mil/ano, Docker/Snipe-IT e os projetos do GitHub;
 3. As 3 Perguntas Interrogatórias Impiedosas do Dwight para fazer ao entrevistador no final)

===SECAO_PLANO_MONITORAMENTO===
(Termos-chave de assunto/remetente para vigiar no e-mail, checklist de acompanhamento da plataforma e timing ideal de follow-up caso o RH demore a responder)"""


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


def criar_pacote_candidatura(
    cargo_empresa: str,
    link_ou_email: str,
    descricao_vaga: str,
    observacoes_extras: str = "",
) -> Dict[str, Any]:
    """
    Recebe a vaga, molda o currículo, cria o guia completo de entrevista e inicia o monitoramento,
    mantendo o status travado em AGUARDANDO_AUTORIZACAO_ENVIO até o aval do Gerente Regional.
    """
    api_key = verificar_api_key()
    genai.configure(api_key=api_key)

    dossie = formatar_dossie_para_prompt()

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=SYSTEM_PROMPT_GOLDEN_TICKET,
    )

    prompt = f"""VAGA INSERIDA PELO GERENTE REGIONAL:
CARGO / EMPRESA ALVO: {cargo_empresa}
LINK DA PLATAFORMA OU E-MAIL DO RECRUTADOR: {link_ou_email}
OBSERVAÇÕES EXTRAS: {observacoes_extras}

DESCRIÇÃO COMPLETA DA VAGA:
{descricao_vaga}

DOSSIÊ OFICIAL DO CANDIDATO:
{dossie}

Gere imediatamente as 3 seções (===SECAO_CURRICULO_MOLDADO===, ===SECAO_PREPARACAO_ENTREVISTA=== e ===SECAO_PLANO_MONITORAMENTO===)."""

    response = model.generate_content(prompt)
    texto_total = response.text or ""

    curriculo_moldado = texto_total
    prep_entrevista = "Preparação de entrevista incluída no dossiê principal."
    plano_monitoramento = "Monitoramento ativo configurado."

    if "===SECAO_CURRICULO_MOLDADO===" in texto_total:
        partes1 = texto_total.split("===SECAO_CURRICULO_MOLDADO===", 1)[1]
        if "===SECAO_PREPARACAO_ENTREVISTA===" in partes1:
            curriculo_moldado, resto = partes1.split("===SECAO_PREPARACAO_ENTREVISTA===", 1)
            if "===SECAO_PLANO_MONITORAMENTO===" in resto:
                prep_entrevista, plano_monitoramento = resto.split("===SECAO_PLANO_MONITORAMENTO===", 1)
            else:
                prep_entrevista = resto
        else:
            curriculo_moldado = partes1

    nova_candidatura = {
        "id": str(uuid.uuid4())[:8].upper(),
        "criado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cargo_empresa": censurar_dados_sensiveis(cargo_empresa),
        "link_ou_email": link_ou_email.strip(),
        "descricao_vaga": censurar_dados_sensiveis(descricao_vaga),
        "status": "AGUARDANDO_AUTORIZACAO_ENVIO",  # AGUARDANDO_AUTORIZACAO_ENVIO | AUTORIZADO_EM_MONITORAMENTO | ENTREVISTA_CONVOCADA | VETADO
        "curriculo_moldado": censurar_dados_sensiveis(curriculo_moldado.strip()),
        "preparacao_entrevista": censurar_dados_sensiveis(prep_entrevista.strip()),
        "plano_monitoramento": censurar_dados_sensiveis(plano_monitoramento.strip()),
        "ultimo_check_monitoramento": "Ainda não enviado (Aguardando sua autorização)",
        "alertas_monitoramento": [],
    }

    todas = carregar_candidaturas()
    todas.insert(0, nova_candidatura)
    salvar_candidaturas(todas)
    return nova_candidatura


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
            termo_busca = alvo.get("cargo_empresa", "").split()[0]
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
                c["curriculo_moldado"] = censurar_dados_sensiveis(curriculo_editado)

            dec = decisao.upper()
            if dec == "AUTORIZAR":
                c["status"] = "AUTORIZADO_EM_MONITORAMENTO"
                c["autorizado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                c.setdefault("alertas_monitoramento", []).append(
                    f"[{c['autorizado_em']}] ✅ ENVIO AUTORIZADO PELO GERENTE REGIONAL. Monitoramento contínuo iniciado."
                )

                destinatario = str(c.get("link_ou_email", "")).strip()
                smtp_user = os.environ.get("SMTP_USER", "").strip()
                smtp_pass = os.environ.get("SMTP_APP_PASSWORD", "").strip()
                smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
                smtp_port = int(os.environ.get("SMTP_PORT", "587") or 587)

                if smtp_user and smtp_pass and "@" in destinatario and not destinatario.startswith("http"):
                    try:
                        msg = MIMEMultipart()
                        msg["From"] = smtp_user
                        msg["To"] = destinatario
                        msg["Subject"] = f"Candidatura: {c.get('cargo_empresa', 'Vaga Técnica')}"
                        msg.attach(MIMEText(c.get("curriculo_moldado", ""), "plain", "utf-8"))
                        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as srv:
                            srv.starttls()
                            srv.login(smtp_user, smtp_pass)
                            srv.send_message(msg)
                        c["alertas_monitoramento"].append(
                            f"[{c['autorizado_em']}] 📧 E-mail enviado automaticamente via SMTP ({smtp_user} -> {destinatario})."
                        )
                    except Exception as exc_smtp:
                        c["alertas_monitoramento"].append(
                            f"[{c['autorizado_em']}] ⚠️ Aviso SMTP ({smtp_host}): {exc_smtp}"
                        )

                wh_url = os.environ.get("GOLDEN_TICKET_WEBHOOK_URL", "").strip()
                if wh_url:
                    try:
                        payload_wh = json.dumps({
                            "acao": "ENVIAR_CANDIDATURA_APROVADA",
                            "id": c.get("id"),
                            "cargo_empresa": c.get("cargo_empresa"),
                            "destinatario": destinatario,
                            "curriculo_moldado": c.get("curriculo_moldado"),
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
                            f"[{c['autorizado_em']}] 🔌 Webhook Golden Ticket disparado pelo servidor ({wh_url[:45]})."
                        )
                    except Exception as exc_wh:
                        c["alertas_monitoramento"].append(
                            f"[{c['autorizado_em']}] ⚠️ Aviso no Webhook de saída: {exc_wh}"
                        )
            elif dec == "VETAR":
                c["status"] = "VETADO"
            elif dec == "ENTREVISTA":
                c["status"] = "ENTREVISTA_CONVOCADA"
                c.setdefault("alertas_monitoramento", []).append(
                    f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🎯 ENTREVISTA MARCADADA! Kit de Guerra Recyclops ativado."
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

    alvo = None
    for c in todas:
        if c.get("id", "").lower() == termo or termo in c.get("cargo_empresa", "").lower() or termo in c.get("link_ou_email", "").lower():
            alvo = c
            break

    if not alvo and todas:
        alvo = todas[0]

    if not alvo:
        return None

    resumo_seguro = censurar_dados_sensiveis(f"De: {remetente} | Assunto: {assunto} | Msg: {mensagem[:300]}")
    alvo.setdefault("alertas_monitoramento", []).append(
        f"[{agora}] 🔔 WEBHOOK RECEBIDO -> {resumo_seguro}"
    )
    alvo["ultimo_check_monitoramento"] = agora

    texto_comb = f"{assunto} {mensagem}".lower()
    if any(k in texto_comb for k in ("entrevista", "interview", "bate-papo", "agenda", "reunião", "reuniao", "avançou")):
        alvo["status"] = "ENTREVISTA_CONVOCADA"

    salvar_candidaturas(todas)
    return alvo


