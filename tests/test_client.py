import pytest

from rag_referentiel.client import verification_tls
from rag_referentiel.config import Parametres


def test_sans_bundle_la_verification_reste_active():
    assert verification_tls(None) is True
    assert verification_tls("") is True


def test_bundle_existant_est_transmis_tel_quel(tmp_path):
    bundle = tmp_path / "entreprise.pem"
    bundle.write_text("-----BEGIN CERTIFICATE-----", encoding="utf-8")
    assert verification_tls(str(bundle)) == str(bundle)


def test_bundle_introuvable_echoue_plutot_que_de_retomber_sur_le_systeme(
    tmp_path,
):
    with pytest.raises(RuntimeError, match="introuvable"):
        verification_tls(str(tmp_path / "absent.pem"))


def test_le_bundle_se_lit_dans_l_environnement(monkeypatch, tmp_path):
    bundle = tmp_path / "ca.pem"
    bundle.write_text("x", encoding="utf-8")
    monkeypatch.setenv("KILI_CA_BUNDLE", str(bundle))
    assert Parametres().kili_ca_bundle == str(bundle)
