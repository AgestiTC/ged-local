# Connecteur reMarkable — mise en route

Indexe les **PDF/EPUB et notes** d'un compte **reMarkable Cloud** dans la GED (lecture seule).

> ⚠️ L'API cloud reMarkable est **non officielle** (reverse-engineerée par la communauté, cf.
> `rmapi`) et peut évoluer. Ce connecteur suit les endpoints historiques — **à valider** sur ton
> compte. Les notes natives (`.rm`) ne sont pas converties en texte (seuls les PDF/EPUB uploadés
> donnent du texte indexable) ; les autres sont catalogués.

## Appairage (une fois)

**Paramètres → Connecteurs cloud → reMarkable → « Appairer un reMarkable »** :

1. Ouvre **https://my.remarkable.com/device/desktop** (connecté à ton compte reMarkable).
2. Recopie le **code à usage unique** affiché (8 caractères).
3. Colle-le dans Matothèque + un nom de compte → **Appairer**.

Le connecteur échange ce code contre un **device token durable** (chiffré en local). Plus besoin
du code ensuite : un jeton de session est dérivé automatiquement à chaque accès.

## Indexer

Bouton **« Indexer »** sur le compte → tâche durable : parcours des documents, téléchargement,
extraction (Tika) et enrichissement, comme les autres connecteurs. Le contenu apparaît en **GED**
et dans **Paramètres → Dossiers indexés** (préfixe `remarkable://<id>/…`).

## Dépannage

- **Appairage refusé** : le code est à **usage unique** et expire vite — régénère-en un.
- **Pastille rouge** après un temps : ré-appaire (le device token peut être révoqué côté reMarkable).
