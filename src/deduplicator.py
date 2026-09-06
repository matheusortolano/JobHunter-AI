import hashlib
import re
import unicodedata


def normalizar_texto(texto):
    texto = texto.lower().strip()

    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        caractere
        for caractere in texto
        if not unicodedata.combining(caractere)
    )

    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


def gerar_chave_vaga(vaga):
    titulo = normalizar_texto(
        vaga.get("title", "")
    )

    empresa = normalizar_texto(
        vaga.get("company_name", "")
    )

    localizacao = normalizar_texto(
        vaga.get("location", "")
    )

    return (
        titulo,
        empresa,
        localizacao,
    )


def deduplicar_vagas(vagas):
    vagas_unicas = []
    chaves_encontradas = set()
    urls_encontradas = set()

    for vaga in vagas:
        url = vaga.get("url", "")
        chave = gerar_chave_vaga(vaga)

        if url and url in urls_encontradas:
            continue

        if chave[1] and chave in chaves_encontradas:
            continue

        if url:
            urls_encontradas.add(url)

        chaves_encontradas.add(chave)
        vagas_unicas.append(vaga)

    return vagas_unicas


def gerar_fingerprint(vaga):
    titulo, empresa, localizacao = gerar_chave_vaga(vaga)

    texto = f"{titulo}|{empresa}|{localizacao}"

    return hashlib.sha256(
        texto.encode("utf-8")
    ).hexdigest()