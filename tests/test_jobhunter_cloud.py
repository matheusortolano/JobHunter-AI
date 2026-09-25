import importlib.util
import json
import os
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "jobhunter_worker", ROOT / "cloud" / "jobhunter" / "worker.py"
)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def vaga(**overrides):
    base = {
        "title": "Junior Python Developer",
        "company_name": "Empresa",
        "location": "Sorocaba, SP",
        "remote": False,
        "description": "Python SQL API",
        "url": "https://example.com/job",
        "source": "Teste",
    }
    base.update(overrides)
    return base


class FakeS3:
    def __init__(self):
        self.data = {}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.data[(Bucket, Key)] = bytes(Body)
        return {}

    def get_object(self, Bucket, Key):
        key = (Bucket, Key)
        if key not in self.data:
            from botocore.exceptions import ClientError
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                "GetObject",
            )
        return {"Body": BytesIO(self.data[key])}


class FakeSSM:
    def get_parameter(self, Name, WithDecryption):
        values = {
            "/matheus-ai-hub/jobhunter/adzuna-app-id": "app-id",
            "/matheus-ai-hub/jobhunter/adzuna-app-key": "app-key",
            "/matheus-ai-hub/daily-news/telegram-token": "bot-token",
            "/matheus-ai-hub/daily-news/telegram-chat-id": "chat-id",
        }
        return {
            "Parameter": {
                "Type": "SecureString",
                "Value": values[Name],
            }
        }


ENV = {
    "JOBHUNTER_BUCKET": "bucket",
    "JOBHUNTER_DELIVERY_ENABLED": "1",
    "ADZUNA_APP_ID_PARAM": "/matheus-ai-hub/jobhunter/adzuna-app-id",
    "ADZUNA_APP_KEY_PARAM": "/matheus-ai-hub/jobhunter/adzuna-app-key",
    "TELEGRAM_TOKEN_PARAM": "/matheus-ai-hub/daily-news/telegram-token",
    "TELEGRAM_CHAT_PARAM": "/matheus-ai-hub/daily-news/telegram-chat-id",
}


class TestJobHunterCloudV11(unittest.TestCase):
    def test_presencial_sorocaba_elegivel(self):
        self.assertEqual(
            worker.analisar_localizacao(vaga(location="Sorocaba, SP"))[0],
            "elegivel",
        )

    def test_presencial_sao_paulo_inelegivel(self):
        self.assertEqual(
            worker.analisar_localizacao(vaga(location="São Paulo, Estado de São Paulo"))[0],
            "inelegivel",
        )

    def test_hibrido_sao_paulo_elegivel(self):
        self.assertEqual(
            worker.analisar_localizacao(vaga(location="São Paulo - Hybrid"))[0],
            "elegivel",
        )

    def test_remoto_brasil_elegivel(self):
        self.assertEqual(
            worker.analisar_localizacao(
                vaga(location="Remote", remote=True, description="Available in Brazil")
            )[0],
            "elegivel",
        )

    def test_remoto_global_elegivel(self):
        self.assertEqual(
            worker.analisar_localizacao(
                vaga(location="Worldwide", remote=True)
            )[0],
            "elegivel",
        )

    def test_remote_malaysia_inelegivel(self):
        status, motivo = worker.analisar_localizacao(
            vaga(
                location="Kuala Lumpur, Malaysia",
                remote=True,
                description="Remote role",
            )
        )
        self.assertEqual(status, "inelegivel")
        self.assertIn("fora do Brasil", motivo)

    def test_remote_generico_incerto(self):
        self.assertEqual(
            worker.analisar_localizacao(vaga(location="Remote", remote=True))[0],
            "incerto",
        )

    def test_adzuna_normaliza_resultado(self):
        class Response:
            def raise_for_status(self): pass
            def json(self):
                return {
                    "results": [{
                        "title": "Desenvolvedor Python Júnior",
                        "description": "Python SQL",
                        "redirect_url": "https://example.com/adzuna",
                        "location": {"display_name": "São Paulo, Estado de São Paulo"},
                        "company": {"display_name": "Empresa X"},
                    }]
                }

        class Session:
            def get(self, *args, **kwargs):
                return Response()

        vagas = worker.buscar_adzuna(Session(), "id", "key")
        self.assertTrue(vagas)
        self.assertEqual(vagas[0]["source"], "Adzuna")

    def test_coleta_inclui_tres_fontes(self):
        with patch.object(worker, "buscar_arbeitnow", return_value=[vaga(source="Arbeitnow")]):
            with patch.object(worker, "buscar_remoteok", return_value=[]):
                with patch.object(
                    worker, "buscar_adzuna",
                    return_value=[
                        vaga(
                            source="Adzuna",
                            location="Sorocaba, SP",
                            url="https://example.com/adz",
                        )
                    ],
                ):
                    class DummyHeaders:
                        def update(self, *args, **kwargs):
                            pass

                    class DummySession:
                        def __init__(self):
                            self.headers = DummyHeaders()

                        def __enter__(self):
                            return self

                        def __exit__(self, exc_type, exc, tb):
                            return False

                    with patch.object(worker.requests, "Session", return_value=DummySession()):
                        with patch.dict(os.environ, ENV, clear=False):
                            dados = worker.coletar(FakeSSM())
        self.assertIn("Adzuna", dados["fontes_ok"])

    def test_preview_mostra_diagnostico(self):
        dados = {
            "fontes_ok": ["Arbeitnow", "Remote OK", "Adzuna"],
            "fontes_com_falha": [],
            "total_recebido": 500,
            "total_unico": 450,
            "total_area": 60,
            "total_elegivel": 5,
            "total_incerto": 2,
            "total_inelegivel": 30,
            "vagas": [
                dict(
                    vaga(),
                    score=80,
                    motivo_localizacao="Presencial em Sorocaba",
                )
            ],
            "vagas_incertas": [],
        }
        with patch.object(worker, "coletar", return_value=dados):
            result = worker.executar({"mode": "preview"}, ssm=FakeSSM())
        self.assertEqual(result["eligible"], 5)
        self.assertEqual(result["uncertain"], 2)
        self.assertEqual(result["sources"][-1], "Adzuna")

    def test_run_desativado_nao_envia(self):
        dados = {
            "fontes_ok": ["Adzuna"],
            "fontes_com_falha": [],
            "total_recebido": 1,
            "total_unico": 1,
            "total_area": 1,
            "total_elegivel": 0,
            "total_incerto": 0,
            "total_inelegivel": 1,
            "vagas": [],
            "vagas_incertas": [],
        }
        with patch.object(worker, "coletar", return_value=dados):
            with patch.dict(
                os.environ,
                {**ENV, "JOBHUNTER_DELIVERY_ENABLED": "0"},
                clear=False,
            ):
                with self.assertRaises(worker.JobHunterError):
                    worker.executar(
                        {"mode": "run"}, s3=FakeS3(), ssm=FakeSSM()
                    )

    def test_run_marca_somente_vagas_mostradas(self):
        vagas = []
        for i in range(7):
            vagas.append(
                dict(
                    vaga(
                        title=f"Junior Python Developer {i}",
                        url=f"https://example.com/{i}",
                    ),
                    score=80 - i,
                    motivo_localizacao="Presencial em Sorocaba",
                    fingerprint=f"fp-{i}",
                )
            )
        dados = {
            "fontes_ok": ["Adzuna"],
            "fontes_com_falha": [],
            "total_recebido": 7,
            "total_unico": 7,
            "total_area": 7,
            "total_elegivel": 7,
            "total_incerto": 0,
            "total_inelegivel": 0,
            "vagas": vagas,
            "vagas_incertas": [],
        }
        s3 = FakeS3()
        with patch.object(worker, "coletar", return_value=dados):
            with patch.object(worker, "enviar_telegram", return_value=77):
                with patch.dict(os.environ, ENV, clear=False):
                    result = worker.executar(
                        {"mode": "run"}, s3=s3, ssm=FakeSSM()
                    )
        self.assertEqual(result["shown"], 5)
        seen = json.loads(s3.data[("bucket", worker.SEEN_KEY)])
        self.assertEqual(len(seen["fingerprints"]), 5)
        self.assertNotIn("fp-6", seen["fingerprints"])

    def test_segunda_execucao_mesmo_dia_bloqueada(self):
        dados = {
            "fontes_ok": ["Adzuna"],
            "fontes_com_falha": [],
            "total_recebido": 0,
            "total_unico": 0,
            "total_area": 0,
            "total_elegivel": 0,
            "total_incerto": 0,
            "total_inelegivel": 0,
            "vagas": [],
            "vagas_incertas": [],
        }
        s3 = FakeS3()
        day = worker.now_utc().astimezone(worker.ZONE).date().isoformat()
        s3.put_object(
            Bucket="bucket",
            Key=f"jobhunter/runs/{day}/status.json",
            Body=json.dumps({"phase": "sent"}).encode(),
        )
        with patch.object(worker, "coletar", return_value=dados):
            with patch.dict(os.environ, ENV, clear=False):
                result = worker.executar(
                    {"mode": "run"}, s3=s3, ssm=FakeSSM()
                )
        self.assertEqual(result["phase"], "duplicate")

    def test_formatador_preserva_link(self):
        msg, shown = worker.formatar([
            dict(vaga(), score=80, motivo_localizacao="Presencial em Sorocaba")
        ])
        self.assertEqual(shown, 1)
        self.assertIn("https://example.com/job", msg)
        self.assertLessEqual(len(msg), 4096)


if __name__ == "__main__":
    unittest.main()
