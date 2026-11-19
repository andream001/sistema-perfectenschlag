"""
Avaliação do formato de candidatura de uma vaga.

Lê o link (ou e-mail) e a descrição da vaga e responde, sem usar IA:
- por onde a candidatura é feita (e-mail, Gupy, LinkedIn, Greenhouse...);
- em que idioma e formato o currículo deve ir;
- o que a vaga pede além do currículo (carta, portfólio, pretensão salarial...);
- se o sistema pode enviar sozinho por e-mail ou se a candidatura é manual.

O resultado alimenta o prompt de geração do currículo e trava o envio por SMTP
quando o canal não é e-mail.
"""
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

# Plataformas conhecidas: domínio -> (nome, como aplicar, observações de formato)
PLATAFORMAS: List[Dict[str, Any]] = [
    {
        "dominios": ["gupy.io"],
        "nome": "Gupy",
        "tipo": "ATS_BR",
        "passos": [
            "Entre na vaga pela Gupy e use o mesmo e-mail do seu cadastro.",
            "Revise campo a campo o que a Gupy importou do currículo: o parser costuma errar datas e cargos.",
            "Responda às perguntas da vaga de forma coerente com o currículo (anos de experiência, ferramentas).",
            "Reserve tempo para testes de lógica, fit cultural ou gravação de vídeo, que são comuns na Gupy.",
        ],
        "formato_cv": "PDF de 1 a 2 páginas, uma coluna, sem tabelas, ícones ou foto.",
        "observacoes": "A Gupy ranqueia pelo texto do perfil, não só pelo PDF: copie o resumo e as competências para o perfil.",
    },
    {
        "dominios": ["linkedin.com"],
        "nome": "LinkedIn",
        "tipo": "LINKEDIN",
        "passos": [
            "Abra a vaga no LinkedIn e veja se é 'Candidatura simplificada' ou se redireciona para o site da empresa.",
            "Na candidatura simplificada, envie o PDF (até 2 MB) e responda às perguntas de triagem com números que batam com o currículo.",
            "Se redirecionar, reavalie o formato pelo site de destino.",
            "Depois de aplicar, mande uma mensagem curta para quem publicou a vaga, se o nome aparecer.",
        ],
        "formato_cv": "PDF de 1 a 2 páginas; o título do perfil do LinkedIn deve repetir o cargo alvo.",
        "observacoes": "O recrutador abre o seu perfil: deixe título, resumo e experiências alinhados ao currículo enviado.",
    },
    {
        "dominios": ["greenhouse.io", "boards.greenhouse.io", "job-boards.greenhouse.io"],
        "nome": "Greenhouse",
        "tipo": "ATS_INTL",
        "passos": [
            "Preencha o formulário da vaga e envie o currículo em PDF.",
            "Use o campo de carta de apresentação: é opcional, mas pesa em vagas concorridas.",
            "Responda às perguntas personalizadas (autorização de trabalho, fuso, pretensão) com precisão.",
        ],
        "formato_cv": "PDF de 1 a 2 páginas, uma coluna, no idioma da vaga.",
        "observacoes": "Greenhouse mostra o PDF ao recrutador quase sem processar: o visual do documento importa.",
    },
    {
        "dominios": ["lever.co", "jobs.lever.co"],
        "nome": "Lever",
        "tipo": "ATS_INTL",
        "passos": [
            "Envie o currículo em PDF; a Lever preenche nome, e-mail e telefone a partir dele.",
            "Preencha links (LinkedIn, GitHub, portfólio) e o campo 'Additional information' com 3 a 4 frases.",
        ],
        "formato_cv": "PDF de 1 a 2 páginas, no idioma da vaga.",
        "observacoes": "O campo 'Additional information' funciona como carta curta: use a mensagem de apresentação gerada.",
    },
    {
        "dominios": ["myworkdayjobs.com", "workday.com"],
        "nome": "Workday",
        "tipo": "ATS_INTL",
        "passos": [
            "Crie a conta da empresa no Workday (cada empresa tem a sua).",
            "Revise tudo o que o Workday importou do currículo: datas e descrições costumam sair erradas.",
            "Separe 20 a 30 minutos: o formulário é longo e não salva bem rascunhos.",
        ],
        "formato_cv": "DOCX ou PDF simples; o parser do Workday lê melhor documentos sem colunas.",
        "observacoes": "O que vale é o que fica nos campos do Workday, não o arquivo anexado.",
    },
    {
        "dominios": ["smartrecruiters.com", "recruitee.com", "ashbyhq.com", "jobs.ashbyhq.com", "teamtailor.com", "breezy.hr", "workable.com", "apply.workable.com", "pinpointhq.com"],
        "nome": "ATS da empresa",
        "tipo": "ATS_INTL",
        "passos": [
            "Preencha o formulário da vaga e envie o currículo em PDF.",
            "Use a mensagem de apresentação no campo de carta ou observações, se existir.",
        ],
        "formato_cv": "PDF de 1 a 2 páginas, no idioma da vaga.",
        "observacoes": "",
    },
    {
        "dominios": ["solides.com.br", "vagas.solides.com.br", "inhire.app", "kenoby.com", "abler.com.br", "quickin.io", "pandape.com.br"],
        "nome": "ATS brasileiro",
        "tipo": "ATS_BR",
        "passos": [
            "Faça o cadastro na plataforma e revise os campos importados do currículo.",
            "Complete o perfil comportamental ou testes, se a plataforma pedir.",
        ],
        "formato_cv": "PDF de 1 a 2 páginas, uma coluna.",
        "observacoes": "",
    },
    {
        "dominios": ["vagas.com.br", "catho.com.br", "infojobs.com.br", "indeed.com", "br.indeed.com", "glassdoor.com", "glassdoor.com.br", "programathor.com.br", "geekhunter.com.br", "trampos.co"],
        "nome": "Portal de vagas",
        "tipo": "PORTAL",
        "passos": [
            "Candidate-se pelo portal com o perfil atualizado.",
            "Confira se o portal redireciona para o site da empresa; se sim, siga o formato de lá.",
        ],
        "formato_cv": "PDF de 1 a 2 páginas; mantenha o perfil do portal coerente com o arquivo.",
        "observacoes": "Portais costumam montar o currículo a partir do perfil: atualize o perfil antes de aplicar.",
    },
    {
        "dominios": ["remotive.com", "remoteok.com", "remoteok.io", "arbeitnow.com", "himalayas.app", "weworkremotely.com"],
        "nome": "Agregador de vagas remotas",
        "tipo": "AGREGADOR",
        "passos": [
            "Abra o link: agregadores quase sempre redirecionam para o ATS da empresa.",
            "Siga o formato do site de destino (normalmente Greenhouse, Lever ou Ashby).",
        ],
        "formato_cv": "PDF em inglês, 1 a 2 páginas, sem foto e sem dados pessoais além de contato e cidade.",
        "observacoes": "Vagas remotas internacionais pedem fuso horário, autorização de trabalho ou contrato como PJ/contractor.",
    },
    {
        "dominios": ["github.com"],
        "nome": "Issue no GitHub (comunidade de vagas)",
        "tipo": "GITHUB",
        "passos": [
            "Leia a seção 'Como se candidatar' do issue: ela diz se é por e-mail, formulário ou link.",
            "Se for e-mail, use exatamente o assunto pedido no issue.",
            "Não comente no issue para se candidatar, a menos que o texto peça isso.",
        ],
        "formato_cv": "PDF de 1 a 2 páginas; inclua o link do GitHub no topo.",
        "observacoes": "",
    },
    {
        "dominios": ["forms.gle", "docs.google.com", "typeform.com", "form.jotform.com", "jotform.com"],
        "nome": "Formulário online",
        "tipo": "FORMULARIO",
        "passos": [
            "Abra o formulário e veja todos os campos antes de começar.",
            "Use o resumo e a mensagem de apresentação nos campos de texto livre.",
            "Se pedir link do currículo, use um link de leitura pública (Google Drive) do PDF.",
        ],
        "formato_cv": "PDF com link público de visualização, se o formulário não aceitar anexo.",
        "observacoes": "",
    },
]

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Itens que a vaga pode exigir além do currículo
EXIGENCIAS = [
    ("carta_apresentacao", r"carta de apresenta|cover letter|motivation letter|carta de motiva", "Carta de apresentação"),
    ("portfolio", r"portf[oó]lio|portfolio|github|repo(s|sit[oó]rios?)? p[uú]blicos?", "Portfólio ou GitHub"),
    ("pretensao", r"pretens[aã]o salarial|salary expectation|expectativa salarial|faixa salarial desejada", "Pretensão salarial"),
    ("ingles", r"ingl[eê]s (avan[cç]ado|fluente|intermedi[aá]rio)|fluent english|english (proficiency|fluency)|advanced english|business english", "Inglês exigido"),
    ("teste_tecnico", r"teste t[eé]cnico|desafio t[eé]cnico|take[- ]home|coding challenge|live coding|case t[eé]cnico", "Teste ou desafio técnico"),
    ("video", r"v[ií]deo de apresenta|video introduction|grave um v[ií]deo", "Vídeo de apresentação"),
    ("referencias", r"refer[eê]ncias profissionais|references", "Referências profissionais"),
    ("disponibilidade", r"disponibilidade (imediata|para in[ií]cio)|start date|notice period", "Disponibilidade de início"),
    ("pdf", r"\bem pdf\b|formato pdf|\bpdf format\b|as a pdf", "Currículo em PDF"),
]

_MODALIDADES = [
    ("Remoto", r"\b100% remot|\bremot[oa]\b|\bremote\b|home office|anywhere"),
    ("Híbrido", r"h[ií]brid|hybrid"),
    ("Presencial", r"presencial|on[- ]site|in[- ]office"),
]
_CONTRATOS = [
    ("CLT", r"\bclt\b"),
    ("PJ", r"\bpj\b|pessoa jur[ií]dica"),
    ("Contractor", r"\bcontractor\b|\bfreelanc"),
    ("Estágio", r"est[aá]gio|internship"),
]

_PT = {"de", "para", "com", "que", "uma", "você", "voce", "vaga", "experiência", "experiencia", "conhecimento", "empresa", "não", "nao", "são", "sao", "requisitos", "desejável", "desejavel"}
_EN = {"the", "and", "with", "you", "we", "our", "experience", "requirements", "team", "will", "are", "for", "is", "role", "skills", "years"}


def detectar_idioma(texto: str) -> str:
    """Retorna 'en' ou 'pt' pela contagem de palavras funcionais."""
    palavras = re.findall(r"[a-zA-ZÀ-ÿ]+", (texto or "").lower())
    pt = sum(1 for w in palavras if w in _PT)
    en = sum(1 for w in palavras if w in _EN)
    return "en" if en > pt * 1.3 and en >= 5 else "pt"


def _dominio(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        host = ""
    return host[4:] if host.startswith("www.") else host


def _plataforma_por_dominio(host: str) -> Optional[Dict[str, Any]]:
    for p in PLATAFORMAS:
        for d in p["dominios"]:
            if host == d or host.endswith("." + d):
                return p
    return None


def _assunto_pedido(texto: str) -> str:
    """Extrai o assunto de e-mail que a vaga manda usar, se houver."""
    padroes = [
        r"(?:assunto|t[ií]tulo do e-?mail|subject(?: line)?)\s*(?:do e-?mail)?\s*[:\-–]?\s*[\"“'«]([^\"”'»\n]{3,120})[\"”'»]",
        r"(?:com o assunto|no assunto|in the subject(?: line)?)\s*[:\-–]?\s*[\"“'«]([^\"”'»\n]{3,120})[\"”'»]",
        r"(?:assunto|subject)\s*:\s*([^\n]{3,120})",
    ]
    for p in padroes:
        m = re.search(p, texto or "", flags=re.IGNORECASE)
        if m:
            return m.group(1).strip().strip(".")
    return ""


def _prazo(texto: str) -> str:
    m = re.search(r"(?:at[eé]|prazo[^\n]{0,20}?|deadline[^\n]{0,10}?|until)\s*(?:o dia\s*)?(\d{1,2}/\d{1,2}(?:/\d{2,4})?)", texto or "", flags=re.IGNORECASE)
    return m.group(1) if m else ""


def avaliar_formato_candidatura(link_ou_email: str, descricao_vaga: str = "", cargo_empresa: str = "") -> Dict[str, Any]:
    """Avalia por onde e em que formato a candidatura deve ser feita."""
    canal_bruto = (link_ou_email or "").strip()
    texto = f"{cargo_empresa}\n{descricao_vaga}"
    texto_low = texto.lower()
    idioma = detectar_idioma(descricao_vaga or cargo_empresa)

    email_canal = ""
    host = ""
    if canal_bruto.lower().startswith(("http://", "https://")):
        host = _dominio(canal_bruto)
    elif _EMAIL_RE.fullmatch(canal_bruto.replace("mailto:", "")):
        email_canal = canal_bruto.replace("mailto:", "")
    # E-mail citado dentro da descrição ("envie para vagas@...")
    emails_na_vaga = [e for e in _EMAIL_RE.findall(descricao_vaga or "") if not e.lower().startswith(("noreply", "no-reply"))]
    if not email_canal and not host and emails_na_vaga:
        email_canal = emails_na_vaga[0]

    alertas: List[str] = []
    plataforma = _plataforma_por_dominio(host) if host else None
    # Vaga publicada num issue ou site que manda enviar por e-mail: o canal real é o e-mail
    if host and emails_na_vaga and (plataforma is None or plataforma["tipo"] == "GITHUB"):
        email_canal = emails_na_vaga[0]
        alertas.append(f"A vaga foi publicada em {host}, mas pede envio por e-mail para {email_canal}.")

    if email_canal:
        canal, nome = "EMAIL", "E-mail direto ao recrutador"
        passos = [
            f"Enviar para {email_canal} com o currículo em PDF anexado.",
            "Corpo do e-mail curto (até 150 palavras): cargo, 2 resultados que batem com a vaga e convite para conversa.",
            "Assunto com cargo e seu nome, ou exatamente o assunto que a vaga pedir.",
        ]
        formato_cv = "PDF de 1 a 2 páginas anexado; nada de currículo colado no corpo do e-mail."
        obs = "E-mail é o único canal em que o sistema pode enviar a candidatura sozinho, depois da sua autorização."
    elif plataforma:
        canal, nome = plataforma["tipo"], plataforma["nome"]
        passos = list(plataforma["passos"])
        formato_cv = plataforma["formato_cv"]
        obs = plataforma["observacoes"]
    elif host:
        canal, nome = "SITE_EMPRESA", f"Site da empresa ({host})"
        passos = [
            "Abra o link e identifique o formulário de candidatura.",
            "Se o site pedir e-mail, cadastre aqui o e-mail do recrutador para o envio automático.",
        ]
        formato_cv = "PDF de 1 a 2 páginas, uma coluna."
        obs = "Domínio desconhecido: confirme manualmente como a empresa recebe currículos."
    else:
        canal, nome = "DESCONHECIDO", "Canal não informado"
        passos = ["Informe o link da vaga ou o e-mail do recrutador para definir o formato."]
        formato_cv = "PDF de 1 a 2 páginas, uma coluna."
        obs = ""
        alertas.append("Sem link nem e-mail: não dá para saber como se candidatar.")

    if idioma == "en":
        formato_cv += " Currículo e mensagem em inglês."
        alertas.append("Vaga em inglês: envie o currículo em inglês, sem foto, CPF, idade ou estado civil.")

    exigencias = [rotulo for _, padrao, rotulo in EXIGENCIAS if re.search(padrao, texto_low)]
    modalidade = next((m for m, p in _MODALIDADES if re.search(p, texto_low)), "")
    contrato = next((c for c, p in _CONTRATOS if re.search(p, texto_low)), "")
    assunto_pedido = _assunto_pedido(descricao_vaga)
    prazo = _prazo(descricao_vaga)

    if "Carta de apresentação" in exigencias:
        alertas.append("A vaga pede carta de apresentação: use a mensagem gerada como base e personalize.")
    if "Pretensão salarial" in exigencias:
        alertas.append("A vaga pede pretensão salarial: defina o valor antes de autorizar o envio.")
    if "Vídeo de apresentação" in exigencias:
        alertas.append("A vaga pede vídeo de apresentação: isso precisa ser gravado por você.")
    if prazo:
        alertas.append(f"Prazo citado na vaga: {prazo}.")
    if canal == "EMAIL" and assunto_pedido:
        alertas.append(f"A vaga define o assunto do e-mail: \"{assunto_pedido}\".")

    checklist = ["Currículo revisado e sem campos pendentes", "Links (LinkedIn, GitHub) funcionando"]
    checklist += [f"{e}" for e in exigencias if e not in ("Currículo em PDF",)]
    if canal != "EMAIL":
        checklist.append(f"Candidatura feita manualmente em: {nome}")

    return {
        "canal": canal,
        "plataforma": nome,
        "dominio": host,
        "email_destino": email_canal,
        "envio_automatico_permitido": canal == "EMAIL",
        "idioma_curriculo": idioma,
        "formato_curriculo": formato_cv,
        "como_aplicar": passos,
        "exigencias": exigencias,
        "modalidade": modalidade,
        "contrato": contrato,
        "assunto_pedido": assunto_pedido,
        "prazo": prazo,
        "alertas": alertas,
        "checklist": checklist,
        "observacoes": obs,
    }


def resumo_formato_para_prompt(fmt: Dict[str, Any]) -> str:
    """Texto curto com as regras de formato, para orientar a IA."""
    linhas = [
        f"Canal de candidatura: {fmt.get('plataforma')} ({fmt.get('canal')}).",
        f"Idioma do currículo e da mensagem: {'inglês' if fmt.get('idioma_curriculo') == 'en' else 'português do Brasil'}.",
        f"Formato esperado: {fmt.get('formato_curriculo')}",
    ]
    if fmt.get("exigencias"):
        linhas.append("A vaga pede também: " + ", ".join(fmt["exigencias"]) + ".")
    if fmt.get("modalidade") or fmt.get("contrato"):
        linhas.append(f"Modalidade/contrato citados: {fmt.get('modalidade') or '-'} / {fmt.get('contrato') or '-'}.")
    if fmt.get("assunto_pedido"):
        linhas.append(f"Assunto obrigatório do e-mail: {fmt['assunto_pedido']}")
    return "\n".join(linhas)
