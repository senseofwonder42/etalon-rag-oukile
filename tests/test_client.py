import ssl

import certifi
import pytest

from rag_referentiel.client import ssl_verification, tls_verification
from rag_referentiel.config import Settings


def test_without_a_bundle_verification_stays_on():
    assert tls_verification(None) is True
    assert tls_verification("") is True


def test_an_existing_bundle_is_passed_through(tmp_path):
    bundle = tmp_path / "entreprise.pem"
    bundle.write_text("-----BEGIN CERTIFICATE-----", encoding="utf-8")
    assert tls_verification(str(bundle)) == str(bundle)


def test_a_missing_bundle_fails_rather_than_using_the_system_store(
    tmp_path,
):
    with pytest.raises(RuntimeError, match="introuvable"):
        tls_verification(str(tmp_path / "absent.pem"))


@pytest.mark.parametrize("variable", ["CA_BUNDLE", "KILI_CA_BUNDLE"])
def test_the_bundle_is_read_from_the_environment(
    monkeypatch, tmp_path, variable
):
    bundle = tmp_path / "ca.pem"
    bundle.write_text("x", encoding="utf-8")
    monkeypatch.setenv(variable, str(bundle))
    assert Settings().ca_bundle == str(bundle)


def test_httpx_clients_get_an_ssl_context_built_on_the_bundle():
    assert ssl_verification(None) is True
    assert isinstance(ssl_verification(certifi.where()), ssl.SSLContext)
