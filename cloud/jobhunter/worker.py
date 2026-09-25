"""JobHunter Cloud v1.1.

Fontes: Arbeitnow, Remote OK e Adzuna Brasil.
Fluxo: coleta -> deduplicação -> filtro -> score -> localização -> S3 -> Telegram.

Não usa MySQL, Gmail, SQLite ou Gemini.
Credenciais Adzuna e Telegram ficam no AWS Systems Manager Parameter Store.
"""

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import boto3
import requests
from botocore.exceptions import ClientError

ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
REMOTEOK_URL = "https://remoteok.com/api"
ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/br/search/1"

ZONE = ZoneInfo("America/Sao_Paulo")
PREFIX = "jobhunter/"
SEEN_KEY = PREFIX + "state/seen.json"
MAX_SEEN = 5000
SCORE_MINIMO = 40
MAX_TELEGRAM_ITEMS = 5

TERMOS_BUSCA_ADZUNA = [
    "python junior",
    "estágio tecnologia",
    "backend python",
    "desenvolvedor junior",
    "analista de dados",
    "power bi",
    "sap",
    "oracle",
    "automação",
    "qa",
]

TERMOS_INTERESSE = [
    "python", "backend", "back-end", "developer", "software engineer",
    "software developer", "desenvolvedor", "desenvolvedora",
    "data analyst", "data engineer", "business intelligence", "bi analyst",
    "analista de dados", "analista de bi", "power bi", "analytics",
    "automation", "automação", "sap", "oracle", "erp",
    "quality assurance", "qa engineer", "qa analyst", "software tester",
    "systems analyst", "system analyst", "analista de sistemas",
    "tecnologia da informação", "tecnologia",
]


class JobHunterError(RuntimeError):
    pass


class LimpadorHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes = []
        self.ignorar = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.ignorar += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.ignorar:
            self.ignorar -= 1

    def handle_data(self, data):
        if not self.ignorar:
            self.partes.append(data)


def limpar_html(texto):
    parser = LimpadorHTML()
    parser.feed(texto or "")
    return " ".join(unescape(" ".join(parser.partes)).split())


def now_utc():
    return datetime.now(timezone.utc)


def _json_bytes(value):
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")


def _bucket():
    value = os.getenv("JOBHUNTER_BUCKET", "").strip()
    if not value:
        raise JobHunterError("JOBHUNTER_BUCKET não configurado.")
    return value


def _secret(ssm, name, prefix):
    if not isinstance(name, str) or not name.startswith(prefix):
        raise JobHunterError("Nome de parâmetro seguro inválido.")
    try:
        response = ssm.get_parameter(Name=name, WithDecryption=True)
    except ClientError:
        raise JobHunterError("Não foi possível ler um parâmetro seguro.") from None
    parametro = response.get("Parameter", {})
    if parametro.get("Type") != "SecureString":
        raise JobHunterError("O parâmetro precisa ser SecureString.")
    value = str(parametro.get("Value", "")).strip()
    if not value:
        raise JobHunterError("Parâmetro seguro vazio.")
    return value


def _adzuna_credentials(ssm):
    app_id = _secret(
        ssm,
        os.getenv("ADZUNA_APP_ID_PARAM", ""),
        "/matheus-ai-hub/jobhunter/",
    )
    app_key = _secret(
        ssm,
        os.getenv("ADZUNA_APP_KEY_PARAM", ""),
        "/matheus-ai-hub/jobhunter/",
    )
    return app_id, app_key


def _telegram_credentials(ssm):
    token = _secret(
        ssm,
        os.getenv("TELEGRAM_TOKEN_PARAM", ""),
        "/matheus-ai-hub/daily-news/",
    )
    chat_id = _secret(
        ssm,
        os.getenv("TELEGRAM_CHAT_PARAM", ""),
        "/matheus-ai-hub/daily-news/",
    )
    return token, chat_id


def _get_json(s3, bucket, key, default=None):
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        if code in ("NoSuchKey", "404", "NotFound"):
            return default
        raise
    return json.loads(obj["Body"].read().decode("utf-8-sig"))


def _put_json(s3, bucket, key, value):
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=_json_bytes(value),
        ContentType="application/json; charset=utf-8",
        ServerSideEncryption="AES256",
    )


def normalizar_texto(texto):
    texto = (texto or "").lower().strip()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def fingerprint(vaga):
    base = "|".join([
        normalizar_texto(vaga.get("title")),
        normalizar_texto(vaga.get("company_name")),
        normalizar_texto(vaga.get("location")),
    ])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def deduplicar_vagas(vagas):
    unicas, urls, chaves = [], set(), set()
    for vaga in vagas:
        url = (vaga.get("url") or "").strip()
        chave = (
            normalizar_texto(vaga.get("title")),
            normalizar_texto(vaga.get("company_name")),
            normalizar_texto(vaga.get("location")),
        )
        if url and url in urls:
            continue
        if chave[1] and chave in chaves:
            continue
        if url:
            urls.add(url)
        chaves.add(chave)
        unicas.append(vaga)
    return unicas


def contem_termo(texto, termo):
    return re.search(
        rf"\b{re.escape(termo)}\b", texto or "", re.IGNORECASE
    ) is not None


def filtrar_vagas(vagas):
    return [
        vaga for vaga in vagas
        if any(
            contem_termo(vaga.get("title", ""), termo)
            for termo in TERMOS_INTERESSE
        )
    ]


def calcular_score(vaga):
    score = 0
    motivos = []
    titulo = (vaga.get("title") or "").lower()
    descricao = (vaga.get("description") or "").lower()

    if any(x in titulo for x in [
        "junior", "júnior", "jr", "associate", "estágio", "estagio",
        "intern", "internship", "trainee", "estagiário", "estagiaria",
        "estagiária",
    ]):
        score += 30
        motivos.append("+ Senioridade compatível")

    if any(x in titulo for x in ["pleno", "mid-level", "mid level"]):
        score -= 20
        motivos.append("- Vaga de nível Pleno")

    if any(x in titulo for x in [
        "senior", "sênior", " sr", "sr ", "sr.", "lead", "staff",
        "principal", "especialista",
    ]):
        score -= 35
        motivos.append("- Senioridade elevada")

    if any(x in titulo for x in [
        "manager", "gerente", "director", "diretor", "head"
    ]):
        score -= 30
        motivos.append("- Cargo de gestão")

    if "python" in titulo:
        score += 25
        motivos.append("+ Python no título")
    if "backend" in titulo or "back-end" in titulo:
        score += 20
        motivos.append("+ Backend no título")
    if any(x in titulo for x in [
        "software engineer", "software developer", "developer",
        "desenvolvedor", "desenvolvedora", "programador", "programadora",
    ]):
        score += 15
        motivos.append("+ Desenvolvimento de software no título")
    if any(x in titulo for x in [
        "data analyst", "business intelligence", "bi analyst",
        "analista de dados", "analista de bi",
    ]):
        score += 15
        motivos.append("+ Dados/BI no título")
    if any(x in titulo for x in ["automation", "automação"]):
        score += 15
        motivos.append("+ Automação no título")

    checks = [
        (("python",), 10, "+ Python na descrição"),
        (("sql", "mysql"), 8, "+ SQL/MySQL na descrição"),
        (("api",), 8, "+ APIs na descrição"),
        (("fastapi",), 10, "+ FastAPI na descrição"),
        (("power bi",), 8, "+ Power BI na descrição"),
        (("sap",), 8, "+ SAP na descrição"),
        (("oracle",), 8, "+ Oracle na descrição"),
        (("erp",), 5, "+ ERP na descrição"),
    ]
    for termos, pontos, motivo in checks:
        if any(t in descricao for t in termos):
            score += pontos
            motivos.append(motivo)

    local = (vaga.get("location") or "").lower()
    eh_remota = bool(vaga.get("remote")) or any(
        x in local for x in ("remote", "remoto", "home office")
    )
    if eh_remota:
        score += 10
        motivos.append("+ Vaga remota")
    else:
        motivos.append("- Vaga não remota")

    return max(0, min(score, 100)), motivos


def analisar_localizacao(vaga):
    """Presencial somente Sorocaba; híbrido SP; remoto Brasil/LATAM/global."""
    titulo = (vaga.get("title") or "").lower()
    localizacao = (vaga.get("location") or "").lower()
    descricao = (vaga.get("description") or "").lower()

    texto_local = f"{titulo} {localizacao}"
    texto_completo = f"{titulo} {localizacao} {descricao}"

    termos_remoto = ["remote", "remoto", "home office", "work from anywhere"]
    termos_hibrido = ["hybrid", "híbrido", "hibrido"]
    termos_sorocaba = ["sorocaba"]
    termos_sp = [
        "são paulo", "sao paulo", "estado de são paulo", "estado de sao paulo",
        "sp, brazil", "sp, brasil", "campinas", "jundiai", "jundiaí",
        "barueri", "alphaville", "osasco", "guarulhos",
    ]
    termos_brasil = [
        "brazil", "brasil", "latam", "latin america", "south america",
        "américa latina", "america latina", "américa do sul", "america do sul",
    ]
    termos_global = [
        "worldwide", "anywhere", "work from anywhere", "global remote",
        "remote worldwide",
    ]
    locais_genericos_remotos = {
        "remote", "remoto", "home office", "remote work", "anywhere", "worldwide", ""
    }

    eh_hibrida = any(x in texto_local for x in termos_hibrido)
    eh_remota = bool(vaga.get("remote")) or any(x in texto_local for x in termos_remoto)
    menciona_sorocaba = any(x in texto_local for x in termos_sorocaba)
    menciona_sp = menciona_sorocaba or any(x in texto_local for x in termos_sp)
    menciona_brasil = any(x in texto_completo for x in termos_brasil)
    menciona_global = any(x in texto_completo for x in termos_global)

    if eh_hibrida:
        if menciona_sp:
            return "elegivel", "Híbrido em São Paulo"
        return "inelegivel", "Híbrido fora de São Paulo"

    if eh_remota:
        if menciona_brasil:
            return "elegivel", "Remoto disponível para Brasil/Latam"
        if menciona_global:
            return "elegivel", "Remoto global"

        local_normalizado = normalizar_texto(localizacao)
        genericos = {normalizar_texto(x) for x in locais_genericos_remotos}

        # Se a API informa um lugar concreto fora do escopo permitido,
        # não tratamos como "incerto". Ex.: Kuala Lumpur, Malaysia.
        if local_normalizado and local_normalizado not in genericos:
            if not menciona_sp and not menciona_sorocaba:
                return (
                    "inelegivel",
                    "Remoto com localização explícita fora do Brasil/escopo global",
                )

        return "incerto", "Remoto, mas região permitida não está clara"

    if menciona_sorocaba:
        return "elegivel", "Presencial em Sorocaba"

    if menciona_sp:
        return "inelegivel", "Presencial em São Paulo fora de Sorocaba"

    if not localizacao:
        return "incerto", "Localização não informada"

    return "inelegivel", "Presencial fora de Sorocaba"


def _normalizar_url(url):
    if not isinstance(url, str):
        return ""
    partes = urlsplit(url.strip())
    if partes.scheme not in ("http", "https") or not partes.hostname:
        return ""
    return url.strip()


def buscar_arbeitnow(sessao):
    response = sessao.get(ARBEITNOW_URL, timeout=(10, 25))
    response.raise_for_status()
    vagas = []
    for vaga in response.json().get("data", []):
        vagas.append({
            "title": limpar_html(vaga.get("title", "")),
            "company_name": limpar_html(vaga.get("company_name", "")),
            "location": limpar_html(vaga.get("location", "")),
            "remote": bool(vaga.get("remote", False)),
            "description": limpar_html(vaga.get("description", ""))[:5000],
            "url": _normalizar_url(vaga.get("url", "")),
            "source": "Arbeitnow",
        })
    return vagas


def buscar_remoteok(sessao):
    response = sessao.get(
        REMOTEOK_URL,
        headers={"User-Agent": "MatheusAIHub-JobHunter/1.1"},
        timeout=(10, 25),
    )
    response.raise_for_status()
    vagas = []
    for vaga in response.json():
        if not vaga.get("position"):
            continue
        titulo = limpar_html(vaga.get("position", ""))
        descricao = limpar_html(vaga.get("description") or "")[:5000]
        localizacao = limpar_html(vaga.get("location") or "")
        tags = vaga.get("tags") or []
        texto = f"{titulo} {localizacao} {' '.join(map(str, tags))} {descricao}".lower()
        vagas.append({
            "title": titulo,
            "company_name": limpar_html(vaga.get("company", "")),
            "location": localizacao,
            "remote": any(
                x in texto for x in ("remote", "work from anywhere", "home office")
            ),
            "description": descricao,
            "url": _normalizar_url(vaga.get("url", "")),
            "source": "Remote OK",
        })
    return vagas


def buscar_adzuna(sessao, app_id, app_key):
    vagas = []
    urls = set()

    for termo in TERMOS_BUSCA_ADZUNA:
        response = sessao.get(
            ADZUNA_URL,
            params={
                "app_id": app_id,
                "app_key": app_key,
                "results_per_page": 50,
                "what": termo,
                "where": "São Paulo",
                "content-type": "application/json",
            },
            timeout=(10, 25),
        )
        response.raise_for_status()

        for vaga in response.json().get("results", []):
            url = _normalizar_url(vaga.get("redirect_url", ""))
            if url and url in urls:
                continue
            if url:
                urls.add(url)

            titulo = limpar_html(vaga.get("title", ""))
            descricao = limpar_html(vaga.get("description", ""))[:5000]
            localizacao = limpar_html(
                (vaga.get("location") or {}).get("display_name", "")
            )
            empresa = limpar_html(
                (vaga.get("company") or {}).get("display_name", "")
            )
            texto = f"{titulo} {descricao} {localizacao}".lower()
            remoto = any(
                x in texto for x in ("remote", "remoto", "home office")
            )

            vagas.append({
                "title": titulo,
                "company_name": empresa,
                "location": localizacao,
                "remote": remoto,
                "description": descricao,
                "url": url,
                "source": "Adzuna",
            })

    return vagas


def coletar(ssm):
    resultados = []
    fontes_ok = []
    falhas = []

    with requests.Session() as sessao:
        sessao.headers.update({"User-Agent": "MatheusAIHub-JobHunter/1.1"})

        for nome, funcao in (
            ("Arbeitnow", lambda: buscar_arbeitnow(sessao)),
            ("Remote OK", lambda: buscar_remoteok(sessao)),
        ):
            try:
                itens = funcao()
                resultados.extend(itens)
                fontes_ok.append(nome)
            except (requests.RequestException, ValueError, TypeError, json.JSONDecodeError):
                falhas.append(nome)

        try:
            app_id, app_key = _adzuna_credentials(ssm)
            itens = buscar_adzuna(sessao, app_id, app_key)
            resultados.extend(itens)
            fontes_ok.append("Adzuna")
        except (JobHunterError, requests.RequestException, ValueError, TypeError, json.JSONDecodeError):
            falhas.append("Adzuna")

    if not fontes_ok:
        raise JobHunterError("Nenhuma fonte de vagas respondeu.")

    unicas = deduplicar_vagas(resultados)
    filtradas = filtrar_vagas(unicas)

    elegiveis = []
    incertas = []
    inelegiveis = []

    for vaga in filtradas:
        vaga["score"], vaga["motivos"] = calcular_score(vaga)
        status, motivo = analisar_localizacao(vaga)
        vaga["status_localizacao"] = status
        vaga["motivo_localizacao"] = motivo
        vaga["fingerprint"] = fingerprint(vaga)

        if status == "elegivel" and vaga["score"] >= SCORE_MINIMO and vaga.get("url"):
            elegiveis.append(vaga)
        elif status == "incerto" and vaga["score"] >= SCORE_MINIMO and vaga.get("url"):
            incertas.append(vaga)
        elif status == "inelegivel":
            inelegiveis.append(vaga)

    elegiveis.sort(key=lambda v: v["score"], reverse=True)
    incertas.sort(key=lambda v: v["score"], reverse=True)

    return {
        "coletado_em": now_utc().isoformat(),
        "fontes_ok": fontes_ok,
        "fontes_com_falha": falhas,
        "total_recebido": len(resultados),
        "total_unico": len(unicas),
        "total_area": len(filtradas),
        "total_elegivel": len(elegiveis),
        "total_incerto": len(incertas),
        "total_inelegivel": len(inelegiveis),
        "vagas": elegiveis,
        "vagas_incertas": incertas,
    }


def formatar(vagas):
    if not vagas:
        return ""

    linhas = ["💼 JobHunter AI", "", "Novas vagas compatíveis encontradas:", ""]
    for indice, vaga in enumerate(vagas[:MAX_TELEGRAM_ITEMS], 1):
        bloco = (
            f"{indice}. {vaga['title'][:160]}\n"
            f"🏢 {vaga['company_name'][:100] or 'Empresa não informada'}\n"
            f"📍 {vaga['location'][:120] or 'Localização não informada'}\n"
            f"⭐ Score: {vaga['score']}/100\n"
            f"✅ {vaga['motivo_localizacao']}\n"
            f"🔗 {vaga['url']}\n"
        )
        if len("\n".join(linhas + [bloco])) + 160 > 4096:
            break
        linhas.append(bloco)

    mostradas = len(linhas) - 4
    if not mostradas:
        raise JobHunterError("Nenhuma vaga cabe com segurança na mensagem.")

    omitidas = len(vagas) - mostradas
    if omitidas:
        linhas.append(
            f"+ {omitidas} vaga(s) continuam no histórico e poderão aparecer depois."
        )
    linhas.append(
        "Ranking por regras do JobHunter; confira os requisitos antes de se candidatar."
    )
    return "\n".join(linhas).strip(), mostradas


def enviar_telegram(mensagem, token, chat_id):
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": mensagem,
                "disable_web_page_preview": True,
            },
            timeout=(10, 30),
        )
        response.raise_for_status()
        dados = response.json()
    except requests.RequestException:
        raise JobHunterError(
            "Envio ao Telegram ficou incerto. Não reenviar automaticamente."
        ) from None

    if not dados.get("ok") or not isinstance(dados.get("result"), dict):
        raise JobHunterError(
            "Telegram não confirmou o envio. Não reenviar automaticamente."
        )
    return dados["result"].get("message_id")


def executar(event, context=None, *, s3=None, ssm=None):
    if not isinstance(event, dict):
        raise JobHunterError("Evento inválido.")

    mode = event.get("mode", "preview")
    if mode not in ("preview", "run"):
        raise JobHunterError("Modo inválido.")

    ssm = ssm or boto3.client("ssm")
    dados = coletar(ssm)

    if mode == "preview":
        return {
            "phase": "preview",
            "sources": dados["fontes_ok"],
            "source_failures": dados["fontes_com_falha"],
            "received": dados["total_recebido"],
            "filtered": dados["total_area"],
            "eligible": dados["total_elegivel"],
            "uncertain": dados["total_incerto"],
            "ineligible": dados["total_inelegivel"],
            "top": [
                {
                    "title": v["title"],
                    "company": v["company_name"],
                    "location": v["location"],
                    "score": v["score"],
                    "reason": v["motivo_localizacao"],
                    "source": v["source"],
                }
                for v in dados["vagas"][:5]
            ],
            "top_uncertain": [
                {
                    "title": v["title"],
                    "company": v["company_name"],
                    "location": v["location"],
                    "score": v["score"],
                    "reason": v["motivo_localizacao"],
                    "source": v["source"],
                }
                for v in dados["vagas_incertas"][:5]
            ],
            "note": "Sem S3 e sem Telegram. Adzuna usa credenciais seguras do SSM.",
        }

    if os.getenv("JOBHUNTER_DELIVERY_ENABLED") != "1":
        raise JobHunterError("Envio desativado.")

    bucket = _bucket()
    s3 = s3 or boto3.client("s3")
    token, chat_id = _telegram_credentials(ssm)

    dia = now_utc().astimezone(ZONE).date().isoformat()
    request_id = getattr(context, "aws_request_id", "manual")
    status_key = f"{PREFIX}runs/{dia}/status.json"

    anterior = _get_json(s3, bucket, status_key, default=None)
    if anterior:
        return {
            "phase": "duplicate",
            "day": dia,
            "previous": anterior.get("phase"),
            "note": "Já houve uma execução de envio hoje.",
        }

    snapshot_key = (
        f"{PREFIX}snapshots/{now_utc().strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    _put_json(s3, bucket, snapshot_key, dados)
    _put_json(s3, bucket, PREFIX + "latest.json", dados)

    vistos = _get_json(s3, bucket, SEEN_KEY, default={"fingerprints": []})
    fingerprints = vistos.get("fingerprints", []) if isinstance(vistos, dict) else []
    conjunto_vistos = {x for x in fingerprints if isinstance(x, str)}

    novas = [
        vaga for vaga in dados["vagas"]
        if vaga["fingerprint"] not in conjunto_vistos
    ]

    status = {
        "day": dia,
        "phase": "prepared",
        "request_id": request_id,
        "updated_at": now_utc().isoformat(),
        "snapshot_key": snapshot_key,
        "eligible": len(dados["vagas"]),
        "new": len(novas),
    }
    _put_json(s3, bucket, status_key, status)

    if not novas:
        status["phase"] = "empty"
        status["updated_at"] = now_utc().isoformat()
        _put_json(s3, bucket, status_key, status)
        return {"phase": "empty", "day": dia, "eligible": len(dados["vagas"])}

    mensagem, mostradas = formatar(novas)
    selecionadas = novas[:mostradas]

    status["phase"] = "sending"
    status["shown"] = mostradas
    status["updated_at"] = now_utc().isoformat()
    _put_json(s3, bucket, status_key, status)

    try:
        message_id = enviar_telegram(mensagem, token, chat_id)
    except Exception:
        status["phase"] = "uncertain_after_send"
        status["updated_at"] = now_utc().isoformat()
        status["note"] = "Confira o Telegram antes de qualquer tentativa manual."
        _put_json(s3, bucket, status_key, status)
        raise

    # Só marca como vistas as vagas que realmente apareceram na mensagem.
    novos_ids = [v["fingerprint"] for v in selecionadas]
    combinado = list(dict.fromkeys(novos_ids + fingerprints))[:MAX_SEEN]
    _put_json(s3, bucket, SEEN_KEY, {
        "updated_at": now_utc().isoformat(),
        "fingerprints": combinado,
    })

    status["phase"] = "sent"
    status["telegram_message_id"] = message_id
    status["updated_at"] = now_utc().isoformat()
    _put_json(s3, bucket, status_key, status)

    return {
        "phase": "sent",
        "day": dia,
        "telegram_message_id": message_id,
        "new_jobs": len(novas),
        "shown": mostradas,
    }


def lambda_handler(event, context):
    try:
        return {"statusCode": 200, "body": executar(event, context)}
    except JobHunterError as error:
        return {
            "statusCode": 500,
            "body": {"phase": "error", "message": str(error)},
        }
    except Exception as error:
        return {
            "statusCode": 500,
            "body": {
                "phase": "error",
                "message": (
                    f"Falha na execução ({type(error).__name__}). Confira os logs."
                ),
            },
        }
