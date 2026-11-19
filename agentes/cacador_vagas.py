import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests

sys.path.append(str(Path(__file__).resolve().parent.parent))
from base_conhecimento import carregar_perfil_gerente, formatar_dossie_para_prompt
from sanitizador_seguranca import censurar_dados_sensiveis

try:
    import google.generativeai as genai
except ImportError:
    from base_conhecimento import genai_compat as genai

ARQUIVO_VAGAS_DESCOBERTAS = Path(__file__).resolve().parent.parent / "vagas_descobertas.json"

KEYWORDS_PADRAO_PERFIL = [
    "python", "automacao", "automação", "automation", "docker", "devops",
    "infraestrutura", "infrastructure", "linux", "api", "rest", "webhook",
    "n8n", "ia", "ai", "llm", "gemini", "whatsapp", "bot", "rpa",
    "backend", "full stack", "fullstack", "sql", "git", "ci/cd", "suporte", "ti",
]


def _limpar_html(texto: str) -> str:
    sem_tags = re.sub(r"<[^>]+>", " ", str(texto or ""))
    sem_ent = html.unescape(sem_tags)
    return re.sub(r"\s+", " ", sem_ent).strip()


def _http_get_json(url: str, timeout: int = 7) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Perfectenschlag-JobRadar/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)


def carregar_vagas_descobertas() -> List[Dict[str, Any]]:
    if not ARQUIVO_VAGAS_DESCOBERTAS.exists():
        return []
    try:
        data = json.loads(ARQUIVO_VAGAS_DESCOBERTAS.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def salvar_vagas_descobertas(vagas: List[Dict[str, Any]]) -> None:
    tmp = ARQUIVO_VAGAS_DESCOBERTAS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(vagas, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, ARQUIVO_VAGAS_DESCOBERTAS)


def _coletar_github_br(repo: str = "backend-br/vagas", limit: int = 20) -> List[Dict[str, Any]]:
    saida: List[Dict[str, Any]] = []
    try:
        itens = _http_get_json(f"https://api.github.com/repos/{repo}/issues?state=open&per_page={limit}")
        if not isinstance(itens, list):
            return []
        for it in itens:
            if not isinstance(it, dict) or it.get("pull_request"):
                continue
            titulo = str(it.get("title") or "").strip()
            url = str(it.get("html_url") or "").strip()
            raw_body = str(it.get("body") or "")
            # Extrai link direto de candidatura (Gupy/Lever/Greenhouse/Forms) ou e-mail do recrutador no corpo da issue
            urls_body = [u.rstrip(").,;\"'") for u in re.findall(r"https?://[^\s\)\]>\"']+", raw_body) if "github.com" not in u.lower()]
            emails_body = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", raw_body)
            link_candidatura = urls_body[0] if urls_body else (emails_body[0] if emails_body else url)
            body = _limpar_html(raw_body)[:1800]
            labels = [str(lb.get("name") or "") for lb in (it.get("labels") or []) if isinstance(lb, dict)]
            saida.append({
                "fonte": f"GitHub ({repo})",
                "titulo": titulo,
                "empresa": "Empresa BR (GitHub Vagas)",
                "local": "Brasil / Remoto" if "remoto" in (titulo + " ".join(labels)).lower() else "Brasil",
                "remoto": "remoto" in (titulo + " ".join(labels)).lower() or "remote" in titulo.lower(),
                "url": url,
                "link_candidatura": link_candidatura,
                "tags": labels[:6],
                "descricao": body,
                "publicado_em": str(it.get("created_at") or "")[:10],
            })
    except Exception:
        pass
    return saida


def _coletar_himalayas() -> List[Dict[str, Any]]:
    """Coleta vagas remotas tech via Himalayas API (gratuita, sem chave)."""
    saida: List[Dict[str, Any]] = []
    try:
        data = _http_get_json("https://himalayas.app/jobs/api?limit=20")
        for j in (data.get("jobs") or [])[:20]:
            saida.append({
                "fonte": "Himalayas",
                "titulo": str(j.get("title") or "").strip(),
                "empresa": str(j.get("companyName") or "").strip(),
                "local": ", ".join(j.get("locationRestrictions") or []) or "Remote Worldwide",
                "remoto": True,
                "url": str(j.get("applicationLink") or j.get("guid") or "").strip(),
                "tags": [str(t) for t in (j.get("categories") or [])[:5]],
                "descricao": _limpar_html(str(j.get("description") or j.get("excerpt") or ""))[:1800],
                "publicado_em": str(j.get("pubDate") or "")[:10],
            })
    except Exception:
        pass
    return saida


def _coletar_serpapi_google_jobs(termo: str) -> List[Dict[str, Any]]:
    """Coleta vagas do Google Jobs Brasil (Gupy, LinkedIn, Catho, InfoJobs) via SerpApi (requer SERPAPI_KEY)."""
    api_key = os.environ.get("SERPAPI_KEY", "").strip()
    if not api_key:
        return []
    saida: List[Dict[str, Any]] = []
    try:
        q = urllib.parse.quote(f"{termo or 'Desenvolvedor Python'} Brasil")
        url = f"https://serpapi.com/search.json?engine=google_jobs&q={q}&hl=pt&gl=br&api_key={urllib.parse.quote(api_key)}"
        data = _http_get_json(url, timeout=10)
        for j in (data.get("jobs_results") or [])[:20]:
            opts = j.get("apply_options") or []
            link = str(opts[0].get("link")) if opts and isinstance(opts[0], dict) and opts[0].get("link") else str(j.get("share_link") or "")
            via = str(j.get("via") or "Google Jobs").replace("via ", "").strip()
            loc = str(j.get("location") or "Brasil").strip()
            desc = _limpar_html(str(j.get("description") or ""))[:1800]
            eh_rem = "remoto" in (loc + " " + desc).lower() or "home office" in desc.lower()
            saida.append({
                "fonte": f"Google Jobs ({via})",
                "titulo": str(j.get("title") or "").strip(),
                "empresa": str(j.get("company_name") or "").strip(),
                "local": loc,
                "remoto": eh_rem,
                "url": link,
                "tags": [via, "Brasil"],
                "descricao": desc,
                "publicado_em": datetime.now().strftime("%Y-%m-%d"),
            })
    except Exception:
        pass
    return saida


def _coletar_jooble(termo: str) -> List[Dict[str, Any]]:
    """Coleta vagas no Brasil via Jooble API (requer JOOBLE_API_KEY)."""
    api_key = os.environ.get("JOOBLE_API_KEY", "").strip()
    if not api_key:
        return []
    saida: List[Dict[str, Any]] = []
    try:
        url = f"https://jooble.org/api/{urllib.parse.quote(api_key)}"
        resp = requests.post(
            url,
            json={"keywords": termo or "Python", "location": "Brazil"},
            timeout=8,
        )
        if not resp.ok:
            return []
        data = resp.json() or {}
        for j in (data.get("jobs") or [])[:20]:
            loc = str(j.get("location") or "Brasil").strip()
            desc = _limpar_html(str(j.get("snippet") or ""))[:1800]
            saida.append({
                "fonte": "Jooble BR",
                "titulo": str(j.get("title") or "").strip(),
                "empresa": str(j.get("company") or "Empresa").strip(),
                "local": loc,
                "remoto": "remoto" in (loc + " " + desc).lower() or "remote" in desc.lower(),
                "url": str(j.get("link") or "").strip(),
                "tags": ["Jooble", "Brasil"],
                "descricao": desc,
                "publicado_em": str(j.get("updated") or "")[:10],
            })
    except Exception:
        pass
    return saida


def obter_status_plataformas_vagas() -> Dict[str, bool]:
    """Retorna quais plataformas ativas de vagas estão configuradas."""
    return {
        "github_br": True,
        "remotive": True,
        "remoteok": True,
        "arbeitnow": True,
        "himalayas": True,
        "serpapi": bool(os.environ.get("SERPAPI_KEY")),
        "jooble": bool(os.environ.get("JOOBLE_API_KEY")),
    }


def _coletar_remotive(termo: str = "") -> List[Dict[str, Any]]:
    saida: List[Dict[str, Any]] = []
    try:
        q = f"?search={urllib.parse.quote(termo)}&limit=25" if termo else "?limit=25"
        data = _http_get_json(f"https://remotive.com/api/remote-jobs{q}")
        for j in (data.get("jobs") or [])[:25]:
            saida.append({
                "fonte": "Remotive",
                "titulo": str(j.get("title") or "").strip(),
                "empresa": str(j.get("company_name") or "").strip(),
                "local": str(j.get("candidate_required_location") or "Worldwide").strip(),
                "remoto": True,
                "url": str(j.get("url") or "").strip(),
                "tags": [str(t) for t in (j.get("tags") or [])[:6]],
                "descricao": _limpar_html(str(j.get("description") or ""))[:1800],
                "publicado_em": str(j.get("publication_date") or "")[:10],
            })
    except Exception:
        pass
    return saida


def _coletar_himalayas() -> List[Dict[str, Any]]:
    """Coleta vagas remotas tech via Himalayas API (gratuita, sem chave)."""
    saida: List[Dict[str, Any]] = []
    try:
        data = _http_get_json("https://himalayas.app/jobs/api?limit=20")
        for j in (data.get("jobs") or [])[:20]:
            saida.append({
                "fonte": "Himalayas",
                "titulo": str(j.get("title") or "").strip(),
                "empresa": str(j.get("companyName") or "").strip(),
                "local": ", ".join(j.get("locationRestrictions") or []) or "Remote Worldwide",
                "remoto": True,
                "url": str(j.get("applicationLink") or j.get("guid") or "").strip(),
                "tags": [str(t) for t in (j.get("categories") or [])[:5]],
                "descricao": _limpar_html(str(j.get("description") or j.get("excerpt") or ""))[:1800],
                "publicado_em": str(j.get("pubDate") or "")[:10],
            })
    except Exception:
        pass
    return saida


def _coletar_serpapi_google_jobs(termo: str) -> List[Dict[str, Any]]:
    """Coleta vagas do Google Jobs Brasil (Gupy, LinkedIn, Catho, InfoJobs) via SerpApi (requer SERPAPI_KEY)."""
    api_key = os.environ.get("SERPAPI_KEY", "").strip()
    if not api_key:
        return []
    saida: List[Dict[str, Any]] = []
    try:
        q = urllib.parse.quote(f"{termo or 'Desenvolvedor Python'} Brasil")
        url = f"https://serpapi.com/search.json?engine=google_jobs&q={q}&hl=pt&gl=br&api_key={urllib.parse.quote(api_key)}"
        data = _http_get_json(url, timeout=10)
        for j in (data.get("jobs_results") or [])[:20]:
            opts = j.get("apply_options") or []
            link = str(opts[0].get("link")) if opts and isinstance(opts[0], dict) and opts[0].get("link") else str(j.get("share_link") or "")
            via = str(j.get("via") or "Google Jobs").replace("via ", "").strip()
            loc = str(j.get("location") or "Brasil").strip()
            desc = _limpar_html(str(j.get("description") or ""))[:1800]
            eh_rem = "remoto" in (loc + " " + desc).lower() or "home office" in desc.lower()
            saida.append({
                "fonte": f"Google Jobs ({via})",
                "titulo": str(j.get("title") or "").strip(),
                "empresa": str(j.get("company_name") or "").strip(),
                "local": loc,
                "remoto": eh_rem,
                "url": link,
                "tags": [via, "Brasil"],
                "descricao": desc,
                "publicado_em": datetime.now().strftime("%Y-%m-%d"),
            })
    except Exception:
        pass
    return saida


def _coletar_jooble(termo: str) -> List[Dict[str, Any]]:
    """Coleta vagas no Brasil via Jooble API (requer JOOBLE_API_KEY)."""
    api_key = os.environ.get("JOOBLE_API_KEY", "").strip()
    if not api_key:
        return []
    saida: List[Dict[str, Any]] = []
    try:
        url = f"https://jooble.org/api/{urllib.parse.quote(api_key)}"
        resp = requests.post(
            url,
            json={"keywords": termo or "Python", "location": "Brazil"},
            timeout=8,
        )
        if not resp.ok:
            return []
        data = resp.json() or {}
        for j in (data.get("jobs") or [])[:20]:
            loc = str(j.get("location") or "Brasil").strip()
            desc = _limpar_html(str(j.get("snippet") or ""))[:1800]
            saida.append({
                "fonte": "Jooble BR",
                "titulo": str(j.get("title") or "").strip(),
                "empresa": str(j.get("company") or "Empresa").strip(),
                "local": loc,
                "remoto": "remoto" in (loc + " " + desc).lower() or "remote" in desc.lower(),
                "url": str(j.get("link") or "").strip(),
                "tags": ["Jooble", "Brasil"],
                "descricao": desc,
                "publicado_em": str(j.get("updated") or "")[:10],
            })
    except Exception:
        pass
    return saida


def obter_status_plataformas_vagas() -> Dict[str, bool]:
    """Retorna quais plataformas ativas de vagas estão configuradas."""
    return {
        "github_br": True,
        "remotive": True,
        "remoteok": True,
        "arbeitnow": True,
        "himalayas": True,
        "serpapi": bool(os.environ.get("SERPAPI_KEY")),
        "jooble": bool(os.environ.get("JOOBLE_API_KEY")),
    }


def _coletar_remoteok() -> List[Dict[str, Any]]:
    saida: List[Dict[str, Any]] = []
    try:
        data = _http_get_json("https://remoteok.com/api")
        if not isinstance(data, list):
            return []
        for j in data[1:31]:
            if not isinstance(j, dict) or not j.get("position"):
                continue
            saida.append({
                "fonte": "RemoteOK",
                "titulo": str(j.get("position") or "").strip(),
                "empresa": str(j.get("company") or "").strip(),
                "local": str(j.get("location") or "Remote").strip(),
                "remoto": True,
                "url": str(j.get("url") or "").strip(),
                "tags": [str(t) for t in (j.get("tags") or [])[:6]],
                "descricao": _limpar_html(str(j.get("description") or ""))[:1800],
                "publicado_em": str(j.get("date") or "")[:10],
            })
    except Exception:
        pass
    return saida


def _coletar_himalayas() -> List[Dict[str, Any]]:
    """Coleta vagas remotas tech via Himalayas API (gratuita, sem chave)."""
    saida: List[Dict[str, Any]] = []
    try:
        data = _http_get_json("https://himalayas.app/jobs/api?limit=20")
        for j in (data.get("jobs") or [])[:20]:
            saida.append({
                "fonte": "Himalayas",
                "titulo": str(j.get("title") or "").strip(),
                "empresa": str(j.get("companyName") or "").strip(),
                "local": ", ".join(j.get("locationRestrictions") or []) or "Remote Worldwide",
                "remoto": True,
                "url": str(j.get("applicationLink") or j.get("guid") or "").strip(),
                "tags": [str(t) for t in (j.get("categories") or [])[:5]],
                "descricao": _limpar_html(str(j.get("description") or j.get("excerpt") or ""))[:1800],
                "publicado_em": str(j.get("pubDate") or "")[:10],
            })
    except Exception:
        pass
    return saida


def _coletar_serpapi_google_jobs(termo: str) -> List[Dict[str, Any]]:
    """Coleta vagas do Google Jobs Brasil (Gupy, LinkedIn, Catho, InfoJobs) via SerpApi (requer SERPAPI_KEY)."""
    api_key = os.environ.get("SERPAPI_KEY", "").strip()
    if not api_key:
        return []
    saida: List[Dict[str, Any]] = []
    try:
        q = urllib.parse.quote(f"{termo or 'Desenvolvedor Python'} Brasil")
        url = f"https://serpapi.com/search.json?engine=google_jobs&q={q}&hl=pt&gl=br&api_key={urllib.parse.quote(api_key)}"
        data = _http_get_json(url, timeout=10)
        for j in (data.get("jobs_results") or [])[:20]:
            opts = j.get("apply_options") or []
            link = str(opts[0].get("link")) if opts and isinstance(opts[0], dict) and opts[0].get("link") else str(j.get("share_link") or "")
            via = str(j.get("via") or "Google Jobs").replace("via ", "").strip()
            loc = str(j.get("location") or "Brasil").strip()
            desc = _limpar_html(str(j.get("description") or ""))[:1800]
            eh_rem = "remoto" in (loc + " " + desc).lower() or "home office" in desc.lower()
            saida.append({
                "fonte": f"Google Jobs ({via})",
                "titulo": str(j.get("title") or "").strip(),
                "empresa": str(j.get("company_name") or "").strip(),
                "local": loc,
                "remoto": eh_rem,
                "url": link,
                "tags": [via, "Brasil"],
                "descricao": desc,
                "publicado_em": datetime.now().strftime("%Y-%m-%d"),
            })
    except Exception:
        pass
    return saida


def _coletar_jooble(termo: str) -> List[Dict[str, Any]]:
    """Coleta vagas no Brasil via Jooble API (requer JOOBLE_API_KEY)."""
    api_key = os.environ.get("JOOBLE_API_KEY", "").strip()
    if not api_key:
        return []
    saida: List[Dict[str, Any]] = []
    try:
        url = f"https://jooble.org/api/{urllib.parse.quote(api_key)}"
        resp = requests.post(
            url,
            json={"keywords": termo or "Python", "location": "Brazil"},
            timeout=8,
        )
        if not resp.ok:
            return []
        data = resp.json() or {}
        for j in (data.get("jobs") or [])[:20]:
            loc = str(j.get("location") or "Brasil").strip()
            desc = _limpar_html(str(j.get("snippet") or ""))[:1800]
            saida.append({
                "fonte": "Jooble BR",
                "titulo": str(j.get("title") or "").strip(),
                "empresa": str(j.get("company") or "Empresa").strip(),
                "local": loc,
                "remoto": "remoto" in (loc + " " + desc).lower() or "remote" in desc.lower(),
                "url": str(j.get("link") or "").strip(),
                "tags": ["Jooble", "Brasil"],
                "descricao": desc,
                "publicado_em": str(j.get("updated") or "")[:10],
            })
    except Exception:
        pass
    return saida


def obter_status_plataformas_vagas() -> Dict[str, bool]:
    """Retorna quais plataformas ativas de vagas estão configuradas."""
    return {
        "github_br": True,
        "remotive": True,
        "remoteok": True,
        "arbeitnow": True,
        "himalayas": True,
        "serpapi": bool(os.environ.get("SERPAPI_KEY")),
        "jooble": bool(os.environ.get("JOOBLE_API_KEY")),
    }


def _coletar_arbeitnow() -> List[Dict[str, Any]]:
    saida: List[Dict[str, Any]] = []
    try:
        data = _http_get_json("https://www.arbeitnow.com/api/job-board-api")
        for j in (data.get("data") or [])[:35]:
            saida.append({
                "fonte": "Arbeitnow",
                "titulo": str(j.get("title") or "").strip(),
                "empresa": str(j.get("company_name") or "").strip(),
                "local": str(j.get("location") or "").strip(),
                "remoto": bool(j.get("remote")),
                "url": str(j.get("url") or "").strip(),
                "tags": [str(t) for t in (j.get("tags") or [])[:6]],
                "descricao": _limpar_html(str(j.get("description") or ""))[:1800],
                "publicado_em": "",
            })
    except Exception:
        pass
    return saida


def _coletar_himalayas() -> List[Dict[str, Any]]:
    """Coleta vagas remotas tech via Himalayas API (gratuita, sem chave)."""
    saida: List[Dict[str, Any]] = []
    try:
        data = _http_get_json("https://himalayas.app/jobs/api?limit=20")
        for j in (data.get("jobs") or [])[:20]:
            saida.append({
                "fonte": "Himalayas",
                "titulo": str(j.get("title") or "").strip(),
                "empresa": str(j.get("companyName") or "").strip(),
                "local": ", ".join(j.get("locationRestrictions") or []) or "Remote Worldwide",
                "remoto": True,
                "url": str(j.get("applicationLink") or j.get("guid") or "").strip(),
                "tags": [str(t) for t in (j.get("categories") or [])[:5]],
                "descricao": _limpar_html(str(j.get("description") or j.get("excerpt") or ""))[:1800],
                "publicado_em": str(j.get("pubDate") or "")[:10],
            })
    except Exception:
        pass
    return saida


def _coletar_serpapi_google_jobs(termo: str) -> List[Dict[str, Any]]:
    """Coleta vagas do Google Jobs Brasil (Gupy, LinkedIn, Catho, InfoJobs) via SerpApi (requer SERPAPI_KEY)."""
    api_key = os.environ.get("SERPAPI_KEY", "").strip()
    if not api_key:
        return []
    saida: List[Dict[str, Any]] = []
    try:
        q = urllib.parse.quote(f"{termo or 'Desenvolvedor Python'} Brasil")
        url = f"https://serpapi.com/search.json?engine=google_jobs&q={q}&hl=pt&gl=br&api_key={urllib.parse.quote(api_key)}"
        data = _http_get_json(url, timeout=10)
        for j in (data.get("jobs_results") or [])[:20]:
            opts = j.get("apply_options") or []
            link = str(opts[0].get("link")) if opts and isinstance(opts[0], dict) and opts[0].get("link") else str(j.get("share_link") or "")
            via = str(j.get("via") or "Google Jobs").replace("via ", "").strip()
            loc = str(j.get("location") or "Brasil").strip()
            desc = _limpar_html(str(j.get("description") or ""))[:1800]
            eh_rem = "remoto" in (loc + " " + desc).lower() or "home office" in desc.lower()
            saida.append({
                "fonte": f"Google Jobs ({via})",
                "titulo": str(j.get("title") or "").strip(),
                "empresa": str(j.get("company_name") or "").strip(),
                "local": loc,
                "remoto": eh_rem,
                "url": link,
                "tags": [via, "Brasil"],
                "descricao": desc,
                "publicado_em": datetime.now().strftime("%Y-%m-%d"),
            })
    except Exception:
        pass
    return saida


def _coletar_jooble(termo: str) -> List[Dict[str, Any]]:
    """Coleta vagas no Brasil via Jooble API (requer JOOBLE_API_KEY)."""
    api_key = os.environ.get("JOOBLE_API_KEY", "").strip()
    if not api_key:
        return []
    saida: List[Dict[str, Any]] = []
    try:
        url = f"https://jooble.org/api/{urllib.parse.quote(api_key)}"
        resp = requests.post(
            url,
            json={"keywords": termo or "Python", "location": "Brazil"},
            timeout=8,
        )
        if not resp.ok:
            return []
        data = resp.json() or {}
        for j in (data.get("jobs") or [])[:20]:
            loc = str(j.get("location") or "Brasil").strip()
            desc = _limpar_html(str(j.get("snippet") or ""))[:1800]
            saida.append({
                "fonte": "Jooble BR",
                "titulo": str(j.get("title") or "").strip(),
                "empresa": str(j.get("company") or "Empresa").strip(),
                "local": loc,
                "remoto": "remoto" in (loc + " " + desc).lower() or "remote" in desc.lower(),
                "url": str(j.get("link") or "").strip(),
                "tags": ["Jooble", "Brasil"],
                "descricao": desc,
                "publicado_em": str(j.get("updated") or "")[:10],
            })
    except Exception:
        pass
    return saida


def obter_status_plataformas_vagas() -> Dict[str, bool]:
    """Retorna quais plataformas ativas de vagas estão configuradas."""
    return {
        "github_br": True,
        "remotive": True,
        "remoteok": True,
        "arbeitnow": True,
        "himalayas": True,
        "serpapi": bool(os.environ.get("SERPAPI_KEY")),
        "jooble": bool(os.environ.get("JOOBLE_API_KEY")),
    }


def _tem_palavra(termo: str, texto: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(termo)}(?![a-z0-9])", texto))


def _calcular_score_match(vaga: Dict[str, Any], kws_usuario: List[str]) -> int:
    texto = f"{vaga.get('titulo', '')} {' '.join(vaga.get('tags') or [])} {vaga.get('descricao', '')}".lower()
    titulo_low = str(vaga.get("titulo") or "").lower()
    local_low = str(vaga.get("local") or "").lower()

    pontos = 18
    matches = 0
    for kw in kws_usuario:
        k = kw.strip().lower()
        if not k:
            continue
        if _tem_palavra(k, titulo_low):
            pontos += 12
            matches += 1
        elif _tem_palavra(k, texto):
            pontos += 6
            matches += 1

    bonus_perfil = 0
    for kw_pad in KEYWORDS_PADRAO_PERFIL:
        if _tem_palavra(kw_pad, titulo_low):
            bonus_perfil += 7
        elif _tem_palavra(kw_pad, texto):
            bonus_perfil += 3
    pontos += min(24, bonus_perfil)

    # Penaliza cargos de áreas não-técnicas / sem relação com desenvolvimento/dados/infra
    if re.search(r"\b(patient|nurse|clinical|medical|therapist|doctor|pharmac|dental|sales\s+rep|account\s+executive|recruiter|talent\s+acquisition|customer\s+care|call\s+center|copywriter|social\s+media)\b", titulo_low):
        pontos -= 25

    # Alinhamento de senioridade (perfil Júnior / Trainee / ADS)
    if re.search(r"\b(j[uú]nior|jr\.?|trainee|est[aá]gio|intern|entry[\s\-]level)\b", titulo_low):
        pontos += 10
    elif re.search(r"\b(s[eê]nior|sr\.?|staff|principal|lead|especialista|arquitet[oa]|head|gerente|manager)\b", titulo_low):
        pontos -= 26

    # Alinhamento geográfico / remoto
    if vaga.get("remoto"):
        pontos += 8
    else:
        if any(c in local_low for c in ("maring", "campo mour", "paran")):
            pontos += 6
        elif any(c in local_low for c in ("brasil", "brazil", "são paulo", "sao paulo", "curitiba", "rio de janeiro", "bh", "floripa")):
            pontos -= 18
        elif local_low and local_low not in ("remote", "remoto", "worldwide", "anywhere"):
            pontos -= 28

    if "brasil" in local_low or "github" in str(vaga.get("fonte") or "").lower():
        pontos += 6
    if matches == 0 and bonus_perfil < 6:
        pontos = min(28, max(10, pontos - 20))
    elif matches == 0 and pontos < 45:
        pontos = max(15, pontos - 15)

    return max(10, min(95, pontos))


def _passa_filtros_extras(v: Dict[str, Any], senioridade: str, idioma: str) -> bool:
    texto = f"{v.get('titulo', '')} {' '.join(v.get('tags') or [])} {v.get('descricao', '')[:500]}".lower()

    if senioridade and senioridade != "todas":
        if senioridade == "jr":
            if not any(t in texto for t in ("junior", "júnior", "jr", "entry", "trainee", "estágio", "estagio", "pleno")):
                return False
        elif senioridade == "pleno_sr":
            if any(t in str(v.get("titulo", "")).lower() for t in ("estágio", "estagio", "intern", "trainee")):
                return False
            if not any(t in texto for t in ("pleno", "senior", "sênior", "sr", "mid", "lead", "specialist")):
                return False
        elif senioridade == "estagio":
            if not any(t in texto for t in ("estágio", "estagio", "intern", "trainee")):
                return False

    if idioma and idioma != "todos":
        eh_pt = any(p in texto for p in ("vaga", "remoto", "desenvolvedor", "requisitos", "benefícios", "beneficios", "experiência", "brasil", "salário", "clt", "pj"))
        if idioma == "pt" and not eh_pt:
            return False
        if idioma == "en" and eh_pt:
            return False

    return True


def buscar_melhores_vagas(
    palavras_chave: str = "Python, Automação, Docker, DevOps, IA",
    apenas_remoto: bool = False,
    usar_ia: bool = True,
    limite: int = 15,
    fonte: str = "todas",
    senioridade: str = "todas",
    idioma: str = "todos",
    score_minimo: int = 0,
) -> Dict[str, Any]:
    """
    Varre múltiplas fontes abertas (GitHub Vagas BR, Remotive, RemoteOK e Arbeitnow),
    aplica filtros de fonte, senioridade, idioma, remoto e score mínimo,
    e ranqueia as melhores oportunidades para o dossiê do candidato.
    """
    kws = [k.strip() for k in re.split(r"[,;]+", palavras_chave or "") if k.strip()]
    if not kws:
        kws = ["python", "automação", "docker", "devops"]

    perfil = carregar_perfil_gerente()
    termo_remotive = kws[0] if kws else "python"
    fonte_norm = (fonte or "todas").strip().lower()

    brutas: List[Dict[str, Any]] = []
    if fonte_norm in ("todas", "brasil", "github"):
        brutas.extend(_coletar_github_br("backend-br/vagas", limit=20))
        brutas.extend(_coletar_github_br("frontend-br/vagas", limit=10))
    if fonte_norm in ("todas", "brasil", "serpapi"):
        brutas.extend(_coletar_serpapi_google_jobs(termo_remotive))
    if fonte_norm in ("todas", "brasil", "jooble"):
        brutas.extend(_coletar_jooble(termo_remotive))
    if fonte_norm in ("todas", "remotive"):
        brutas.extend(_coletar_remotive(termo_remotive))
    if fonte_norm in ("todas", "remoteok"):
        brutas.extend(_coletar_remoteok())
    if fonte_norm in ("todas", "arbeitnow"):
        brutas.extend(_coletar_arbeitnow())
    if fonte_norm in ("todas", "himalayas"):
        brutas.extend(_coletar_himalayas())

    existentes = carregar_vagas_descobertas()
    urls_ja_enviadas = {v.get("url"): bool(v.get("enviada_para_esteira")) for v in existentes if v.get("url")}

    vistas_url = set()
    ranqueadas: List[Dict[str, Any]] = []
    for v in brutas:
        u = v.get("url") or ""
        if not v.get("titulo") or not u or u in vistas_url:
            continue
        if apenas_remoto and not v.get("remoto"):
            continue
        if not _passa_filtros_extras(v, senioridade=senioridade, idioma=idioma):
            continue
        vistas_url.add(u)

        score = _calcular_score_match(v, kws)
        if score < int(score_minimo or 0):
            continue
        ranqueadas.append({
            "id": str(uuid.uuid4())[:8].upper(),
            "score_match": score,
            "fonte": v["fonte"],
            "titulo": censurar_dados_sensiveis(v["titulo"]),
            "empresa": censurar_dados_sensiveis(v["empresa"] or "Empresa"),
            "local": v["local"],
            "remoto": bool(v["remoto"]),
            "url": u,
            "link_candidatura": v.get("link_candidatura") or u,
            "tags": v.get("tags") or [],
            "descricao": censurar_dados_sensiveis(v.get("descricao") or ""),
            "publicado_em": v.get("publicado_em") or datetime.now().strftime("%Y-%m-%d"),
            "motivo_match": "",
            "enviada_para_esteira": urls_ja_enviadas.get(u, False),
            "descoberta_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    ranqueadas.sort(key=lambda x: x["score_match"], reverse=True)
    top_vagas = ranqueadas[: max(5, min(40, int(limite or 15)))]

    # Enriquecimento opcional com Gemini para explicar o motivo do match do Top 8
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if usar_ia and api_key and top_vagas:
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.5-flash")
            resumo_vagas = "\n".join(
                f"{idx+1}. [{v['id']}] {v['titulo']} ({v['empresa']}) - Tags: {', '.join(v['tags'])}"
                for idx, v in enumerate(top_vagas[:8])
            )
            prompt = (
                f"Perfil do candidato: {perfil.get('nome_completo', 'Candidato')} | "
                f"Cargo alvo: {perfil.get('cargo_alvo', 'Automação/TI/Python')}.\n"
                f"Para cada vaga abaixo, escreva 1 frase curta (máximo 18 palavras) explicando por que ela combina ou o ponto de atenção.\n"
                f"Responda apenas no formato: ID|Frase\n\n{resumo_vagas}"
            )
            resp = model.generate_content(prompt)
            for ln in (resp.text or "").splitlines():
                if "|" in ln:
                    vid, frase = ln.split("|", 1)
                    vid_c = vid.strip().strip("[]")
                    for v in top_vagas:
                        if v["id"] == vid_c:
                            v["motivo_match"] = censurar_dados_sensiveis(frase.strip())
                            break
        except Exception:
            pass

    salvar_vagas_descobertas(top_vagas)
    return {
        "ok": True,
        "total_varridas": len(brutas),
        "total_selecionadas": len(top_vagas),
        "plataformas": obter_status_plataformas_vagas(),
        "vagas": top_vagas,
    }


def marcar_vaga_enviada_esteira(vaga_id: str) -> Optional[Dict[str, Any]]:
    vagas = carregar_vagas_descobertas()
    alvo: Optional[Dict[str, Any]] = None
    for v in vagas:
        if str(v.get("id", "")).upper() == str(vaga_id).strip().upper():
            v["enviada_para_esteira"] = True
            alvo = v
            break
    if alvo:
        salvar_vagas_descobertas(vagas)
    return alvo
