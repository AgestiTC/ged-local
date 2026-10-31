"""
Tests — garde SSRF des flux RSS (services.destination_publique) et décision du 31/10/2026
sur les espaces du foyer ouverts au rôle utilisateur. Aucun accès réseau réel : adresses
littérales, résolution DNS simulée, transport httpx simulé.
"""

import socket

import httpx
import pytest

from services import acces, destination_publique as dp
from services.rss_service import fetch_flux

_FLUX = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Essai</title>
<item><title>Un</title><guid>1</guid><link>https://exemple.test/1</link></item></channel></rss>"""


class TestAdressesRefusees:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", [
        "http://127.0.0.1/flux", "http://192.168.42.200:5000/x", "http://10.0.0.1/",
        "http://172.16.5.4/", "http://169.254.169.254/latest/meta-data", "http://100.64.0.1/",
        "http://0.0.0.0/", "http://[::1]/", "http://[fe80::1]/", "http://[fd00::1]/",
        "http://[::ffff:192.168.1.1]/", "http://224.0.0.1/",
    ])
    async def test_ip_non_publique(self, url):
        with pytest.raises(dp.DestinationInterdite):
            await dp.verifier_url(url)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://exemple.test/f", "gopher://x/"])
    async def test_schema_exotique(self, url):
        with pytest.raises(dp.DestinationInterdite):
            await dp.verifier_url(url)

    @pytest.mark.asyncio
    async def test_nom_qui_resout_vers_le_lan(self, monkeypatch):
        async def faux(hote, port):
            return {"192.168.42.83"}
        monkeypatch.setattr(dp, "_resoudre", faux)
        with pytest.raises(dp.DestinationInterdite, match="réseau local"):
            await dp.verifier_url("https://ged.exemple.test/flux")

    @pytest.mark.asyncio
    async def test_une_seule_adresse_locale_suffit(self, monkeypatch):
        """Un nom qui résout vers une IP publique ET une IP du LAN est refusé."""
        async def faux(hote, port):
            return {"93.184.216.34", "10.1.2.3"}
        monkeypatch.setattr(dp, "_resoudre", faux)
        with pytest.raises(dp.DestinationInterdite):
            await dp.verifier_url("https://mixte.exemple.test/")

    @pytest.mark.asyncio
    async def test_nom_introuvable(self, monkeypatch):
        async def faux(hote, port):
            raise socket.gaierror("introuvable")
        monkeypatch.setattr(dp, "_resoudre", faux)
        with pytest.raises(dp.DestinationInterdite, match="introuvable"):
            await dp.verifier_url("https://nexiste-pas.exemple.test/")


class TestAdressesAcceptees:
    @pytest.mark.asyncio
    async def test_ip_publique(self):
        await dp.verifier_url("https://93.184.216.34/flux.xml")

    @pytest.mark.asyncio
    async def test_nom_public(self, monkeypatch):
        async def faux(hote, port):
            assert port == 443
            return {"93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"}
        monkeypatch.setattr(dp, "_resoudre", faux)
        await dp.verifier_url("https://flux.exemple.test/rss")


class TestFetchFlux:
    @pytest.mark.asyncio
    async def test_flux_public_lu(self):
        transport = httpx.MockTransport(lambda req: httpx.Response(200, content=_FLUX))
        titre, items = await fetch_flux("https://93.184.216.34/rss", _transport=transport)
        assert titre == "Essai" and len(items) == 1

    @pytest.mark.asyncio
    async def test_flux_lan_refuse_sans_requete(self):
        appels = []
        transport = httpx.MockTransport(lambda req: appels.append(req) or httpx.Response(200, content=_FLUX))
        with pytest.raises(dp.DestinationInterdite):
            await fetch_flux("http://192.168.42.200:5000/rss", _transport=transport)
        assert appels == []   # refusé AVANT de partir

    @pytest.mark.asyncio
    async def test_redirection_vers_le_lan_refusee(self):
        """Un flux public qui redirige vers le NAS : le saut est contrôlé lui aussi."""
        appels = []

        def repondre(req: httpx.Request) -> httpx.Response:
            appels.append(str(req.url))
            if req.url.host == "93.184.216.34":
                return httpx.Response(302, headers={"Location": "http://192.168.42.200:5000/secret"})
            return httpx.Response(200, content=_FLUX)

        with pytest.raises(dp.DestinationInterdite):
            await fetch_flux("https://93.184.216.34/rss", _transport=httpx.MockTransport(repondre))
        assert appels == ["https://93.184.216.34/rss"]   # le NAS n'a jamais été appelé


class TestEspacesDuFoyer:
    """Décision du 31/10/2026 : Marie-Laure (rôle utilisateur) accède aux espaces du foyer."""

    @pytest.mark.parametrize("methode,chemin", [
        ("GET", "/api/emploi-domicile/fiches"), ("POST", "/api/emploi-domicile/intervenants/x/contrats"),
        ("GET", "/api/fiscalite/synthese"), ("POST", "/api/fiscalite/reponses"),
        ("GET", "/api/maison/enceintes"), ("POST", "/api/maison/diffuser"),
        ("GET", "/api/conges/regles/verification"), ("PUT", "/api/dossiers/x/conges"),
    ])
    def test_ouverts_au_role_utilisateur(self, methode, chemin):
        assert acces.classer(methode, chemin) == acces.UTILISATEUR

    @pytest.mark.parametrize("chemin", ["/api/system/config", "/api/connectors"])
    def test_leurs_reglages_restent_admin(self, chemin):
        """Le jeton Home Assistant et les comptes vivent sous /api/system et /api/connectors."""
        assert acces.classer("GET", chemin) == acces.ADMIN
