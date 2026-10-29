"""Pagamentos por Referência Multicaixa.

O aluno recebe uma Entidade + Referência + Montante e paga no ATM, na app
Multicaixa Express ou no internet banking do seu banco. O fornecedor (ProxyPay)
avisa a plataforma por webhook quando o pagamento entra.

- ProxyPayProvider: API v2 da ProxyPay (https://developer.proxypay.co.ao).
- SandboxProvider: gera referências fictícias para desenvolvimento e testes.
"""

import hashlib
import hmac
import json
import secrets
import urllib.error
import urllib.request
from datetime import date, timedelta

REFERENCE_DAYS = 3  # validade de cada referência


class PaymentError(Exception):
    pass


class SandboxProvider:
    name = "sandbox"

    def __init__(self, entity="00000"):
        self.entity = entity

    def create_reference(self, booking_id, amount, callback_url=None):
        reference = str(900_000_000 + secrets.randbelow(99_999_999))
        expires = (date.today() + timedelta(days=REFERENCE_DAYS)).isoformat()
        return {"entity": self.entity, "reference": reference, "expires": expires}


class ProxyPayProvider:
    name = "proxypay"
    URLS = {
        "sandbox": "https://api.sandbox.proxypay.co.ao",
        "production": "https://api.proxypay.co.ao",
    }

    def __init__(self, api_key, entity, environment="sandbox", timeout=15):
        self.api_key = api_key
        self.entity = entity
        self.base_url = self.URLS[environment]
        self.timeout = timeout

    def _request(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers={
            "Authorization": f"Token {self.api_key}",
            "Accept": "application/vnd.proxypay.v2+json",
            **({"Content-Type": "application/json"} if data else {}),
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                text = res.read().decode()
        except (urllib.error.URLError, TimeoutError) as e:
            raise PaymentError(f"ProxyPay indisponível: {e}") from e
        return json.loads(text) if text else None

    def create_reference(self, booking_id, amount, callback_url=None):
        ref_id = self._request("POST", "/reference_ids")
        if isinstance(ref_id, list):
            ref_id = ref_id[0]
        elif isinstance(ref_id, dict):
            ref_id = ref_id.get("id")
        if not ref_id:
            raise PaymentError("Resposta inesperada da ProxyPay ao reservar a referência.")
        expires = (date.today() + timedelta(days=REFERENCE_DAYS)).isoformat()
        custom = {"booking_id": str(booking_id)}
        if callback_url:
            custom["callback_url"] = callback_url
        self._request("PUT", f"/references/{ref_id}", {
            "amount": float(amount),
            "end_datetime": expires,
            "custom_fields": custom,
        })
        return {"entity": self.entity, "reference": str(ref_id), "expires": expires}


def verify_proxypay_signature(raw_body, signature, api_key):
    """A ProxyPay assina o corpo do webhook com HMAC-SHA256 (hex) usando a chave da API."""
    if not api_key or not signature:
        return False
    expected = hmac.new(api_key.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def get_provider(config):
    if config.get("PROXYPAY_API_KEY"):
        return ProxyPayProvider(config["PROXYPAY_API_KEY"], config["PROXYPAY_ENTITY"],
                                config.get("PROXYPAY_ENV", "sandbox"))
    if config.get("PAYMENTS_SANDBOX"):
        return SandboxProvider()
    return None
