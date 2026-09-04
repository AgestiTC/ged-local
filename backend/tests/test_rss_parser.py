"""
Tests — parseur de flux RSS/Atom (services.rss_service.parse_feed)
=================================================================
Parsing pur (aucune sortie réseau, aucune DB) : on vérifie l'extraction RSS 2.0
et Atom, le nettoyage HTML du résumé, les dates (RFC 822 / ISO 8601) et le repli
du `guid` sur le lien quand `<guid>`/`<id>` est absent (indispensable à la dédup).
"""

from services.rss_service import parse_feed

RSS = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Blog Parent</title>
    <item>
      <title>Le sommeil de bebe</title>
      <link>https://ex.fr/sommeil</link>
      <description>&lt;p&gt;Un &lt;b&gt;article&lt;/b&gt; utile&lt;/p&gt;</description>
      <guid>abc-1</guid>
      <pubDate>Wed, 02 Sep 2026 10:00:00 +0000</pubDate>
      <dc:creator>Marie</dc:creator>
    </item>
    <item>
      <title>Diversification</title>
      <link>https://ex.fr/diversif</link>
      <pubDate>Tue, 01 Sep 2026 08:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""

ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Chaine YouTube</title>
  <entry>
    <title>Video eveil</title>
    <link rel="alternate" href="https://yt/x"/>
    <id>yt:1</id>
    <published>2026-09-03T12:00:00Z</published>
    <summary>Description de la video</summary>
    <author><name>La chaine</name></author>
  </entry>
</feed>"""


def test_rss_extraction():
    titre, items = parse_feed(RSS)
    assert titre == "Blog Parent"
    assert len(items) == 2
    # Tri récents d'abord : l'article du 02/09 passe avant celui du 01/09.
    premier = items[0]
    assert premier["titre"] == "Le sommeil de bebe"
    assert premier["url"] == "https://ex.fr/sommeil"
    assert premier["auteur"] == "Marie"
    assert premier["guid"] == "abc-1"
    # Le HTML du résumé est retiré.
    assert premier["resume"] == "Un article utile"
    assert premier["date_pub"] is not None
    assert premier["date_pub"].year == 2026 and premier["date_pub"].month == 9


def test_rss_guid_fallback_sur_lien():
    """Sans <guid>, la dédup doit retomber sur le lien."""
    _, items = parse_feed(RSS)
    sans_guid = [i for i in items if i["titre"] == "Diversification"][0]
    assert sans_guid["guid"] == "https://ex.fr/diversif"


def test_atom_extraction():
    titre, items = parse_feed(ATOM)
    assert titre == "Chaine YouTube"
    assert len(items) == 1
    it = items[0]
    assert it["titre"] == "Video eveil"
    assert it["url"] == "https://yt/x"           # href de <link rel="alternate">
    assert it["auteur"] == "La chaine"
    assert it["resume"] == "Description de la video"
    assert it["date_pub"] is not None
    assert it["guid"] == "yt:1"
