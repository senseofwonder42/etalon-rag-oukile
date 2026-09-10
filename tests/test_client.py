import pytest

from rag_referentiel.client import tls_verification
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


def test_the_bundle_is_read_from_the_environment(monkeypatch, tmp_path):
    bundle = tmp_path / "ca.pem"
    bundle.write_text("x", encoding="utf-8")
    monkeypatch.setenv("KILI_CA_BUNDLE", str(bundle))
    assert Settings().kili_ca_bundle == str(bundle)
