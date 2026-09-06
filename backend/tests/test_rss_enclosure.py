"""
Extraction de l'audio d'un flux podcast (`<enclosure>`).

Le parseur RSS servait la veille, qui n'a que faire du média attaché : il jetait donc
l'`<enclosure>`. Or **un podcast EST un flux RSS dont chaque item porte son audio** — c'est
exactement ce champ qu'il faut pour lister les épisodes, puis les envoyer sur une enceinte.

Les cas testés sont ceux qui cassent en vrai : les deux dialectes (RSS 2.0 et Atom, qui ne
déclarent pas l'audio de la même façon), un flux d'articles sans audio, et des valeurs
illisibles — un éditeur qui écrit `length="inconnu"` ne doit pas faire tomber la lecture.
"""

import xml.etree.ElementTree as ET

from services.rss_service import _enclosure, parse_feed


def _el(xml: str) -> ET.Element:
    return ET.fromstring(xml)


class TestEnclosure:
    def test_rss2_avec_duree_hms(self):
        it = _el("""<item xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
            <title>Episode 12</title>
            <enclosure url="https://cdn.exemple.fr/ep12.mp3" type="audio/mpeg" length="48210944"/>
            <itunes:duration>1:02:03</itunes:duration></item>""")
        assert _enclosure(it) == {
            "audio_url": "https://cdn.exemple.fr/ep12.mp3", "audio_type": "audio/mpeg",
            "audio_octets": 48210944, "duree": 3723,
        }

    def test_duree_en_secondes_simples(self):
        it = _el("""<item xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
            <enclosure url="https://x/y.mp3" type="audio/mpeg" length="1"/>
            <itunes:duration>1800</itunes:duration></item>""")
        assert _enclosure(it)["duree"] == 1800

    def test_atom_link_rel_enclosure(self):
        """Atom n'a pas de <enclosure> : l'audio passe par <link rel="enclosure">."""
        e = _el("""<entry xmlns="http://www.w3.org/2005/Atom">
            <link rel="alternate" href="https://exemple.fr/page"/>
            <link rel="enclosure" href="https://cdn.exemple.fr/a.m4a" type="audio/mp4" length="1234"/>
            </entry>""")
        r = _enclosure(e)
        assert r["audio_url"] == "https://cdn.exemple.fr/a.m4a"     # pas le lien « alternate »
        assert r["audio_type"] == "audio/mp4"

    def test_article_sans_audio_rend_un_dict_vide(self):
        """Un flux d'articles n'est pas une anomalie : on ne doit rien inventer."""
        assert _enclosure(_el("<item><title>Un article</title><link>https://e.fr</link></item>")) == {}

    def test_valeurs_illisibles_ne_font_pas_tomber(self):
        it = _el("""<item xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
            <enclosure url="https://x/y.mp3" type="audio/mpeg" length="inconnu"/>
            <itunes:duration>bizarre</itunes:duration></item>""")
        r = _enclosure(it)
        assert r["audio_url"] == "https://x/y.mp3"
        assert r["audio_octets"] == 0 and r["duree"] is None


class TestFluxComplet:
    def test_les_episodes_portent_leur_audio(self):
        flux = b"""<?xml version="1.0"?>
        <rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
          <channel>
            <title>La Matrescence</title>
            <item><title>Ep 2</title><pubDate>Tue, 02 Sep 2026 08:00:00 +0000</pubDate>
              <enclosure url="https://cdn/2.mp3" type="audio/mpeg" length="200"/></item>
            <item><title>Ep 1</title><pubDate>Mon, 01 Sep 2026 08:00:00 +0000</pubDate>
              <enclosure url="https://cdn/1.mp3" type="audio/mpeg" length="100"/></item>
          </channel></rss>"""
        titre, items = parse_feed(flux)
        assert titre == "La Matrescence"
        # Les plus récents d'abord — c'est l'ordre qu'on veut proposer à l'écoute.
        assert [i["titre"] for i in items] == ["Ep 2", "Ep 1"]
        assert [i["audio_url"] for i in items] == ["https://cdn/2.mp3", "https://cdn/1.mp3"]

    def test_la_veille_reste_intacte(self):
        """
        Le même parseur sert la veille RSS. Ajouter des clés ne doit rien changer aux siennes :
        elle lit `guid`, `titre`, `url`, `auteur`, `resume`, `date_pub` et rien d'autre.
        """
        _, items = parse_feed(b"""<?xml version="1.0"?><rss version="2.0"><channel>
          <item><title>Article</title><link>https://e.fr/a</link>
            <description>Texte</description><guid>g-1</guid></item>
        </channel></rss>""")
        it = items[0]
        for cle in ("guid", "titre", "url", "auteur", "resume", "date_pub"):
            assert cle in it
        assert "audio_url" not in it        # pas d'audio → pas de clé parasite
