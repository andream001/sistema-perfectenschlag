"""
Currículo profissional: montagem, checagem de qualidade e exportação .docx.

- montar_curriculo_markdown(): currículo limpo a partir do perfil, sem IA
  (usado quando o Gemini falha e como referência de estrutura).
- validar_documento(): procura o que nunca pode chegar ao recrutador
  (campos censurados, jargão interno do sistema, diagnóstico de ATS, emojis...).
- gerar_docx_bytes(): converte o Markdown simples do currículo em .docx
  sem dependências externas, para anexar no e-mail ou baixar no painel.
"""
import io
import re
import zipfile
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

TITULOS = {
    "pt": {"resumo": "Resumo profissional", "competencias": "Competências técnicas", "experiencia": "Experiência profissional",
           "projetos": "Projetos", "formacao": "Formação e certificações", "idiomas": "Idiomas"},
    "en": {"resumo": "Professional summary", "competencias": "Technical skills", "experiencia": "Professional experience",
           "projetos": "Projects", "formacao": "Education and certifications", "idiomas": "Languages"},
}

# Bloqueiam: personagens, jargão agressivo e frases de controle que nunca deveriam sair do sistema
JARGAO_BLOQUEIA = [
    "gerente regional", "filial scranton", "filial regional", "dwight", "schrute", "michael scott", "toby", "recyclops",
    "neutralizador", "letalidade", "impiedos", "dizimar", "destruir o filtro", "anti-ats", "beterraba", "golden ticket",
]
# Avisam: nomes temáticos de projetos reais e termos que um recrutador pode estranhar
JARGAO_AVISO = ["perfectenschlag", "agentcraft", "dunder", "mifflin", "scranton", "wuphf", "anti-bloqueio", "anti-ban", "censurad", "confidencial"]
# Marcadores de campo não preenchido (sempre bloqueiam; ignora links Markdown como [LinkedIn](https://...))
MARCADOR_RE = re.compile(
    r"\[[^\]\n]{0,50}(PROTEGID|CENSURAD|CONFIDENCIAL|EMAIL|E-MAIL|TELEFONE|LINKEDIN|EMPRESA|NOME|INSIRA|INSERIR|PREENCHER|PREENCHIDO|VALOR\s+A\s+SER|PRETENS[AÃ]O|SUA\s+|SEU\s+)[^\]\n]{0,50}\](?!\()|_PROTEGIDO|lorem ipsum|\(preencher|XX/100",
    re.IGNORECASE,
)
SEPARADORES_IA = ["===SECAO", "===CURRICULO", "===MENSAGEM", "===DIAGNOSTICO", "NOTA_ATS", "DIAGNÓSTICO DE PALAVRAS", "DIAGNOSTICO DE PALAVRAS", "PALAVRAS-CHAVE ATS", "MODO CONTINGÊNCIA"]
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐✅❌]")


def _contatos_linha(perfil: Dict[str, Any]) -> str:
    c = perfil.get("contatos", {}) or {}
    partes = [perfil.get("localizacao", "")]
    for chave in ("email", "telefone", "linkedin", "github", "portfolio"):
        v = str(c.get(chave, "") or "").strip()
        if v:
            partes.append(v.replace("https://", "").replace("http://", "").rstrip("/"))
    return " · ".join(p for p in partes if p)


def montar_curriculo_markdown(perfil: Dict[str, Any], idioma: str = "pt", palavras_chave: Optional[List[str]] = None) -> str:
    """Monta o currículo em Markdown simples (uma coluna, sem tabelas) a partir do perfil."""
    t = TITULOS.get(idioma, TITULOS["pt"])
    linhas: List[str] = [f"# {perfil.get('nome_completo', '').strip()}"]
    if perfil.get("titulo_profissional"):
        linhas.append(f"**{perfil['titulo_profissional'].strip()}**")
    linhas.append(_contatos_linha(perfil))

    if perfil.get("resumo_executivo"):
        linhas += ["", f"## {t['resumo']}", perfil["resumo_executivo"].strip()]

    skills = list(perfil.get("competencias_tecnicas", []) or [])
    if palavras_chave:
        # Competências que a vaga cita vêm primeiro, sem inventar nenhuma nova
        kws = [k.lower() for k in palavras_chave]
        skills.sort(key=lambda s: 0 if any(k in s.lower() for k in kws) else 1)
    if skills:
        linhas += ["", f"## {t['competencias']}"] + [f"- {s}" for s in skills]

    exps = perfil.get("experiencias_profissionais", []) or []
    if exps:
        linhas += ["", f"## {t['experiencia']}"]
        for e in exps:
            cab = " · ".join(x for x in (e.get("cargo", ""), e.get("empresa", ""), e.get("periodo", "")) if x)
            linhas += ["", f"### {cab}"] + [f"- {r}" for r in e.get("realizacoes", [])]

    projs = perfil.get("projetos_destaque", []) or []
    if projs:
        linhas += ["", f"## {t['projetos']}"]
        for p in projs:
            stack = f" ({p['stack']})" if p.get("stack") else ""
            linhas.append(f"- **{p.get('nome', '')}**{stack}: {p.get('descricao', '')}")

    if perfil.get("formacao_e_certificacoes"):
        linhas += ["", f"## {t['formacao']}"] + [f"- {f}" for f in perfil["formacao_e_certificacoes"]]
    if perfil.get("idiomas"):
        linhas += ["", f"## {t['idiomas']}", " · ".join(perfil["idiomas"])]
    return "\n".join(linhas).strip() + "\n"


def validar_documento(texto: str, tipo: str = "curriculo", idioma: str = "pt") -> List[Dict[str, str]]:
    """Retorna problemas encontrados. nivel = 'bloqueia' (não pode enviar) ou 'aviso'."""
    problemas: List[Dict[str, str]] = []
    if not (texto or "").strip():
        return [{"nivel": "bloqueia", "msg": f"{'Currículo' if tipo == 'curriculo' else 'Mensagem'} vazio."}]
    low = texto.lower()

    achados = sorted({m.group(0) for m in MARCADOR_RE.finditer(texto)})
    if achados:
        problemas.append({"nivel": "bloqueia", "msg": "Campos censurados ou não preenchidos: " + ", ".join(achados[:6]) + ". Complete o perfil na aba Dossiê."})
    internos = sorted({j for j in JARGAO_BLOQUEIA if re.search(rf"\b{re.escape(j)}", low)})
    if internos:
        problemas.append({"nivel": "bloqueia", "msg": "Termos internos ou de personagem no texto: " + ", ".join(internos) + "."})
    tematicos = sorted({j for j in JARGAO_AVISO if j in low})
    if tematicos:
        problemas.append({"nivel": "aviso", "msg": "Termos que um recrutador pode estranhar: " + ", ".join(tematicos) + ". Se forem nomes de projeto, descreva o que o projeto faz."})
    sep = [s for s in SEPARADORES_IA if s.lower() in low]
    if sep:
        problemas.append({"nivel": "bloqueia", "msg": "Sobrou texto de controle da IA (" + ", ".join(sep) + ")."})
    if _EMOJI.search(texto):
        problemas.append({"nivel": "aviso", "msg": "Há emojis no texto. Em currículo e e-mail formal, tire."})

    palavras = len(re.findall(r"\w+", texto))
    if tipo == "curriculo":
        if palavras > 900:
            problemas.append({"nivel": "aviso", "msg": f"Currículo com {palavras} palavras: passa de 2 páginas. Corte para 450 a 800."})
        if palavras < 150:
            problemas.append({"nivel": "aviso", "msg": f"Currículo com só {palavras} palavras: parece incompleto."})
        if "|" in texto and re.search(r"^\s*\|.*\|\s*$", texto, flags=re.MULTILINE):
            problemas.append({"nivel": "aviso", "msg": "Tabela no currículo: parsers de ATS leem mal. Use listas."})
        if not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", texto):
            problemas.append({"nivel": "bloqueia", "msg": "Currículo sem e-mail de contato."})
        if re.search(r"\b(cpf|rg|estado civil|data de nascimento|idade:)", low):
            problemas.append({"nivel": "aviso", "msg": "Dados pessoais desnecessários (CPF, RG, idade, estado civil). Remova."})
    else:
        if palavras > 220:
            problemas.append({"nivel": "aviso", "msg": f"Mensagem com {palavras} palavras. Recrutador lê até ~150."})
    if idioma == "en":
        from agentes.formato_candidatura import detectar_idioma
        if detectar_idioma(texto) == "pt" or re.search(r"\b(experiência|competências|formação|automação|responsável)\b", low):
            problemas.append({"nivel": "bloqueia", "msg": "A vaga é em inglês, mas o texto está (ou tem trechos) em português. Traduza antes de enviar."})
    return problemas


def bloqueios(problemas: List[Dict[str, str]]) -> List[str]:
    return [p["msg"] for p in problemas if p.get("nivel") == "bloqueia"]


# ---------------------------------------------------------------- DOCX
def _runs(texto: str) -> str:
    """Converte **negrito** em runs do Word."""
    xml = []
    for i, parte in enumerate(re.split(r"\*\*(.+?)\*\*", texto)):
        if not parte:
            continue
        bold = "<w:b/>" if i % 2 else ""
        xml.append(f'<w:r><w:rPr>{bold}</w:rPr><w:t xml:space="preserve">{escape(parte)}</w:t></w:r>')
    return "".join(xml)


def _par(texto: str, estilo: str = "", espaco_depois: int = 60) -> str:
    ppr = f'<w:pStyle w:val="{estilo}"/>' if estilo else ""
    return f'<w:p><w:pPr>{ppr}<w:spacing w:after="{espaco_depois}"/></w:pPr>{_runs(texto)}</w:p>'


def gerar_docx_bytes(markdown: str, titulo: str = "Currículo") -> bytes:
    """Gera um .docx de uma coluna (amigável a ATS) a partir de Markdown simples."""
    corpo = []
    for linha in (markdown or "").splitlines():
        l = linha.rstrip()
        if not l.strip():
            continue
        if l.startswith("# "):
            corpo.append(_par(l[2:].strip(), "Title", 40))
        elif l.startswith("## "):
            corpo.append(_par(l[3:].strip(), "Heading1", 60))
        elif l.startswith("### "):
            corpo.append(_par(l[4:].strip(), "Heading2", 40))
        elif re.match(r"^\s*[-*•]\s+", l):
            corpo.append(_par(re.sub(r"^\s*[-*•]\s+", "", l), "ListBullet", 30))
        else:
            corpo.append(_par(l.strip()))
    documento = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        + "".join(corpo)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1000" w:right="1000" w:bottom="1000" w:left="1000" w:header="0" w:footer="0" w:gutter="0"/></w:sectPr>'
        "</w:body></w:document>"
    )
    fonte = '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
    estilos = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:docDefaults><w:rPrDefault><w:rPr>{fonte}<w:sz w:val="21"/><w:lang w:val="pt-BR"/></w:rPr></w:rPrDefault></w:docDefaults>'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
        f'<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr>{fonte}<w:b/><w:sz w:val="36"/></w:rPr></w:style>'
        f'<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:spacing w:before="200"/><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="1F4E8C"/></w:pBdr></w:pPr><w:rPr>{fonte}<w:b/><w:color w:val="1F4E8C"/><w:sz w:val="24"/></w:rPr></w:style>'
        f'<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:pPr><w:spacing w:before="120"/></w:pPr><w:rPr>{fonte}<w:b/><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr><w:ind w:left="360" w:hanging="240"/></w:pPr></w:style>'
        "</w:styles>"
    )
    numeracao = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/></w:lvl></w:abstractNum>'
        '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>'
    )
    tipos = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        "</Relationships>"
    )
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>'
        "</Relationships>"
    )
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>{escape(titulo)}</dc:title></cp:coreProperties>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", tipos)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", documento)
        z.writestr("word/styles.xml", estilos)
        z.writestr("word/numbering.xml", numeracao)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("docProps/core.xml", core)
    return buf.getvalue()


def nome_arquivo_cv(perfil: Dict[str, Any], cargo_empresa: str = "") -> str:
    nome = re.sub(r"[^A-Za-z0-9]+", "-", _sem_acento(perfil.get("nome_completo", "Curriculo"))).strip("-") or "Curriculo"
    return f"Curriculo-{nome}.docx"


def _sem_acento(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "")) if unicodedata.category(c) != "Mn")
