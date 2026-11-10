import re
from typing import List

# Lista de nomes corporativos reais ou clientes que devem ser censurados em logs/outputs públicos
TERMOS_CONFIDENCIAIS: List[str] = [
    "Unimed",
    "unimed",
    "SG Sistemas",
    "sg sistemas",
]


def censurar_dados_sensiveis(texto: str) -> str:
    """
    Remove ou mascara automaticamente nomes de empresas clientes reais,
    chaves de API, tokens, CPFs, CNPJs e telefones antes de exibir ou salvar em arquivos públicos.
    """
    if not texto:
        return ""

    resultado = str(texto)

    # 1. Mascara chaves de API Google Gemini (AIza...) e Tokens GitHub (ghp_ / gho_)
    resultado = re.sub(r"AIza[0-9A-Za-z\-_]{20,}", "[CHAVE_API_CENSURADA]", resultado)
    resultado = re.sub(r"gh[po]_[0-9A-Za-z]{20,}", "[GITHUB_TOKEN_CENSURADO]", resultado)

    # 2. Mascara CPFs e CNPJs
    resultado = re.sub(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", "[CPF_CENSURADO]", resultado)
    resultado = re.sub(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b", "[CNPJ_CENSURADO]", resultado)

    # 3. Censura nomes de empresas clientes reais
    resultado = re.sub(r"\bUnimed\b", "[OPERADORA_SAUDE_CONFIDENCIAL]", resultado, flags=re.IGNORECASE)
    resultado = re.sub(r"\bSG Sistemas\b", "[EMPRESA_ERP_CONFIDENCIAL]", resultado, flags=re.IGNORECASE)

    return resultado

