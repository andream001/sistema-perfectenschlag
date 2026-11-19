import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from autoconfigurador_scranton import carregar_env_local
    carregar_env_local()
except Exception:
    pass


class _CompatResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _CompatGenerativeModel:
    def __init__(
        self,
        model_name: str = "gemini-flash-lite-latest",
        system_instruction: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        self.model_name = model_name
        self.system_instruction = system_instruction

    def generate_content(self, prompt: str, **kwargs: Any) -> _CompatResponse:
        import urllib.error
        api_key = _CompatGenAI._api_key or os.environ.get("GEMINI_API_KEY", "")
        preferidos = (
            "gemini-flash-lite-latest",
            "gemini-3-flash-preview",
            "gemini-flash-latest",
            "gemini-3.1-flash-lite-preview",
            "gemma-4-26b-a4b-it",
        )
        modelos_tentar: list[str] = list(preferidos)
        if self.model_name and self.model_name not in modelos_tentar and self.model_name != "gemini-2.5-flash":
            modelos_tentar.insert(0, self.model_name)

        payload: Dict[str, Any] = {
            "contents": [{"parts": [{"text": str(prompt)}]}],
            "generationConfig": {"maxOutputTokens": 4096, "temperature": 0.35},
        }
        if self.system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": str(self.system_instruction)}]
            }
        body_bytes = json.dumps(payload).encode("utf-8")
        # A chave vai no cabeçalho, nunca na URL (URLs aparecem em logs e mensagens de erro)
        cabecalhos = {"Content-Type": "application/json"}
        if api_key:
            cabecalhos["x-goog-api-key"] = api_key

        last_err: Optional[Exception] = None
        dados: Dict[str, Any] = {}
        for mod in modelos_tentar:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{mod}:generateContent"
            )
            req = urllib.request.Request(
                url,
                data=body_bytes,
                headers=cabecalhos,
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=25) as resp:
                    dados = json.loads(resp.read().decode("utf-8"))
                _CompatGenAI._ultimo_status = {"ok": True, "modelo": mod, "erro": ""}
                break
            except urllib.error.HTTPError as he:
                last_err = he
                if he.code in (400, 404, 429, 500, 503, 504):
                    continue
                _CompatGenAI._ultimo_status = {"ok": False, "modelo": mod, "erro": str(he)}
                raise
            except (urllib.error.URLError, TimeoutError, OSError) as net_err:
                last_err = net_err
                continue
        else:
            _CompatGenAI._ultimo_status = {"ok": False, "modelo": "", "erro": str(last_err or "Timeout Gemini")}
            if last_err:
                raise last_err

        candidatos = dados.get("candidates", [])
        if candidatos:
            partes = candidatos[0].get("content", {}).get("parts", [])
            texto = "".join(p.get("text", "") for p in partes)
            return _CompatResponse(texto)
        return _CompatResponse("")


class _CompatGenAI:
    _api_key: str = ""
    _ultimo_status: Dict[str, Any] = {"ok": True, "modelo": "", "erro": ""}
    GenerativeModel = _CompatGenerativeModel

    @classmethod
    def configure(cls, api_key: str = "", **kwargs: Any) -> None:
        cls._api_key = api_key


genai_compat = _CompatGenAI()


ARQUIVO_PERFIL = Path(__file__).resolve().parent / "perfil_gerente.json"
# Dados reais (nome, e-mail, telefone, empresas): ficam só neste arquivo local, fora do Git.
ARQUIVO_PERFIL_LOCAL = Path(__file__).resolve().parent / "perfil_gerente.local.json"

# Marcadores que indicam campo censurado ou não preenchido
MARCADORES_PENDENTES = ("PROTEGIDO", "CENSURAD", "CONFIDENCIAL", "Gerente Regional", "Perfil Público")


def _ler_json(caminho: Path) -> Dict[str, Any]:
    if not caminho.exists():
        return {}
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _mesclar(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _mesclar(out[k], v)
        elif v not in (None, "", [], {}):
            out[k] = v
    return out


def carregar_perfil_publico() -> Dict[str, Any]:
    """Perfil versionado no Git (sem dados pessoais)."""
    return _ler_json(ARQUIVO_PERFIL)


def carregar_perfil_gerente() -> Dict[str, Any]:
    """Perfil completo: o público com os dados reais do arquivo local por cima."""
    return _mesclar(carregar_perfil_publico(), _ler_json(ARQUIVO_PERFIL_LOCAL))


def salvar_perfil_gerente(novos_dados: Dict[str, Any]) -> Dict[str, Any]:
    """Salva as edições do painel no arquivo LOCAL, para dados reais nunca irem para o Git."""
    local = _mesclar(_ler_json(ARQUIVO_PERFIL_LOCAL), novos_dados or {})
    tmp = ARQUIVO_PERFIL_LOCAL.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(local, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, ARQUIVO_PERFIL_LOCAL)
    return carregar_perfil_gerente()


def _pendente(valor: Any) -> bool:
    texto = str(valor or "").strip()
    return not texto or any(m.lower() in texto.lower() for m in MARCADORES_PENDENTES)


def pendencias_perfil(perfil: Optional[Dict[str, Any]] = None) -> List[str]:
    """Lista o que falta no perfil para gerar um currículo enviável."""
    p = perfil if perfil is not None else carregar_perfil_gerente()
    contatos = p.get("contatos", {}) or {}
    falta: List[str] = []
    if _pendente(p.get("nome_completo")):
        falta.append("Nome completo")
    if _pendente(contatos.get("email")):
        falta.append("E-mail de contato")
    if _pendente(contatos.get("telefone")):
        falta.append("Telefone")
    if _pendente(contatos.get("linkedin")):
        falta.append("Link do LinkedIn")
    for exp in p.get("experiencias_profissionais", []) or []:
        rotulo = exp.get("cargo") or "experiência"
        if _pendente(exp.get("empresa")):
            falta.append(f"Empresa da experiência \"{rotulo}\"")
        periodo = str(exp.get("periodo", ""))
        if not re.search(r"\d{4}", periodo):
            falta.append(f"Período com ano de início da experiência \"{rotulo}\" (hoje: \"{periodo or 'vazio'}\")")
    if not p.get("formacao_e_certificacoes"):
        falta.append("Formação acadêmica")
    elif not any(re.search(r"\d{4}", str(f)) for f in p.get("formacao_e_certificacoes", [])):
        falta.append("Instituição e ano na formação acadêmica")
    return falta


def formatar_dossie_para_prompt() -> str:
    """Converte todo o perfil curricular e informações complementares em texto estruturado para os agentes."""
    p = carregar_perfil_gerente()
    if not p:
        return (
            "MARCOS PADRÃO: Economia de R$ 20 mil anual com automação + "
            "Implantação Docker/Snipe-IT + Projetos AWAProject e Bet-Trader."
        )

    contatos = p.get("contatos", {})
    if isinstance(contatos, dict):
        contatos_str = " | ".join(f"{k.upper()}: {v}" for k, v in contatos.items() if v)
    else:
        contatos_str = str(contatos or "")

    def _lista(v: Any) -> List[str]:
        if isinstance(v, list):
            return [str(x) for x in v if str(x).strip()]
        return [x.strip(" -•\t") for x in str(v or "").splitlines() if x.strip()]

    for chave in ("marcos_obrigatorios", "competencias_tecnicas", "formacao_e_certificacoes", "idiomas"):
        p[chave] = _lista(p.get(chave))
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
        "=== DOSSIÊ DO CANDIDATO (fonte única de fatos) ===",
        f"NOME: {p.get('nome_completo', 'Gerente Regional')}",
        f"TÍTULO ALVO: {p.get('titulo_profissional', '')}",
        f"LOCALIZAÇÃO: {p.get('localizacao', '')}",
        f"CONTATOS: {contatos_str or 'Não informado'}",
        f"\nRESUMO EXECUTIVO:\n{p.get('resumo_executivo', '')}",
        f"\nRESULTADOS QUE DEVEM APARECER:\n{marcos}",
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

