# 🤝 Passation — ajouts dans des fichiers en cours d'édition

> Rédigé par la session IA. Ces changements touchent des fichiers que **tu** édites
> (`DuplicatesPage.tsx`, `organize.py`, `SettingsPage.tsx`). Les nº 1-2 sont **implémentés dans
> l'arbre de travail** (fonctionnels en live) mais **non commités** ; le nº 3 a son **backend déjà
> livré** (branche `feat/normalisation-acronymes`) et n'attend que l'UI. Merci de les **intégrer à
> ton prochain commit** de ces fichiers. Rien d'urgent, aucune dépendance : chacun est autonome.

---

## 1. `frontend/src/pages/DuplicatesPage.tsx` — bouton 👁 Aperçu

Ajoute un bouton **Aperçu** par ligne de doublon (onglet « Fichiers indexés »), réutilisant
le composant existant `DocumentPreview`. 5 petits changements dans le composant `IndexedDuplicates` :

**a) Imports (haut du fichier)**
```diff
-import { Copy, FolderInput, Loader2, RefreshCw, ShieldCheck, Database, FolderSearch, Folder, Trash2, Sparkles, Info } from 'lucide-react'
+import { Copy, FolderInput, Loader2, RefreshCw, ShieldCheck, Database, FolderSearch, Folder, Trash2, Sparkles, Info, Eye } from 'lucide-react'
 import { clsx } from 'clsx'
 import {
-  duplicatesApi, corbeilleApi, sourcesApi,
+  duplicatesApi, corbeilleApi, sourcesApi, documentsApi,
   type DuplicatesResponse, type IndexedDupResponse, type Source,
 } from '../api'
 import SmbFolderPicker from '../components/ged/SmbFolderPicker'
+import DocumentPreview from '../components/ged/DocumentPreview'
 import { useToast } from '../components/common/Toast'
+import type { Document } from '../types'
```

**b) État (dans `IndexedDuplicates`, après `const [confirmOpen, ...]`)**
```tsx
  const [apercu, setApercu] = useState<Document | null>(null)   // doc affiché en aperçu (modal)
```

**c) Handler (après `const toggle = ...`)**
```tsx
  // Aperçu : charge le document complet puis ouvre le composant DocumentPreview.
  const ouvrirApercu = async (id: string) => {
    try { setApercu(await documentsApi.get(id)) }
    catch { toast.error('Aperçu impossible (document introuvable ?)') }
  }
```

**d) Bouton dans la ligne** — remplace le `<button ...corbeille>` seul par un groupe 👁 + 🗑 :
```tsx
                  <div className="justify-self-end flex items-center gap-1">
                    <button type="button" title="Aperçu du fichier"
                      onClick={e => { e.stopPropagation(); ouvrirApercu(f.id) }}
                      className="p-1 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded">
                      <Eye size={14} />
                    </button>
                    <button type="button" title="Envoyer ce fichier à la corbeille"
                      onClick={e => { e.stopPropagation(); setSelected(new Set([f.id])); setConfirmOpen(true) }}
                      className="p-1 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded">
                      <Trash2 size={14} />
                    </button>
                  </div>
```

**e) Modal (avant le bloc `{/* Confirmation */}`)**
```tsx
      {/* Aperçu (réutilise le composant DocumentPreview de la GED) */}
      {apercu && <DocumentPreview doc={apercu} onClose={() => setApercu(null)} />}
```

---

## 2. `backend/routers/organize.py` — réorg classe aussi par tags

Aujourd'hui la réorganisation groupe **uniquement par `categorie`** → les docs sans catégorie
mais riches en **tags** (ex. scans OCR) finissent en « Non classé ». Ce patch ajoute un repli
**catégorie → sous-catégorie → premier tag significatif**.

**a) Helper (après `def _annee(...)`)**
```python
# Tags d'extension (type de fichier) — pas des thèmes de classement, à ignorer.
_TAGS_EXT = {"pdf", "docx", "xlsx", "pptx", "ppsx", "doc", "xls", "ppt", "jpg", "jpeg",
             "png", "gif", "bmp", "webp", "tif", "tiff", "txt", "csv", "zip"}


def _cle_classement(doc: Document) -> str:
    """
    Clé de rangement : **catégorie** IA si présente, sinon **sous-catégorie**, sinon le
    premier **tag** significatif (hors tag d'extension). Permet de classer les documents
    riches en tags mais sans catégorie formelle (ex. scans OCR). « non-classé » en dernier.
    """
    m = doc.metadonnees_ia
    if not m:
        return "non-classé"
    if m.categorie:
        return m.categorie
    if m.sous_categorie:
        return m.sous_categorie
    for t in (m.tags or []):
        if t and t.strip().lower() not in _TAGS_EXT:
            return t.strip()
    return "non-classé"
```

**b) Dans `propose()` — collecte des clés**
```diff
-    # Catégories distinctes
-    cats = sorted({(d.metadonnees_ia.categorie if d.metadonnees_ia and d.metadonnees_ia.categorie else "non-classé")
-                   for d in docs})
+    # Clés de classement distinctes (catégorie > sous-catégorie > tag significatif)
+    cats = sorted({_cle_classement(d) for d in docs})
```

**c) Dans `propose()` — cible par doc**
```diff
     for d in docs:
-        cat = d.metadonnees_ia.categorie if d.metadonnees_ia and d.metadonnees_ia.categorie else "non-classé"
+        cat = _cle_classement(d)
         cible = _cible_cat(cat)
```

> Validé : `categorie → contrat` · `tags ['pdf','carburant'] → carburant` · `sous_cat → notes-de-frais` · `['pdf'] → non-classé`.
> Idée d'amélioration ultérieure (non incluse) : passer aussi les **tags** au LLM dans `_proposer_dossiers`
> pour des noms de dossiers plus fins que la seule clé.

---

## 3. `SettingsPage.tsx` — section « Normalisation des tags/catégories » (acronymes + bouton)

**Backend déjà livré & poussé** (commit `19096f9`, branche `feat/normalisation-acronymes`) :
- Config `acronymes` = JSON `[{sigle, definition}]` (31 par défaut), exposée par `GET /api/system/config`
  et modifiable par `PUT /api/system/config` (comme `admin_links`).
- `POST /api/system/normaliser-metadata` : fusionne accents+casse des tags/catégories (acronyme connu →
  MAJUSCULES ; sinon forme accentuée > fréquente). Sauvegarde `storage/backup-normalisation.json`. Réversible/idempotent.

**À faire côté UI** (dans ton `SettingsPage.tsx` refactoré, section Maintenance ou une nouvelle carte) :

**a) `frontend/src/api/index.ts`** — dans `systemApi` :
```ts
  // Lance la normalisation casse/accents des tags & catégories → { ok, resume }
  normaliserMetadata: () =>
    apiClient.post<{ ok: boolean; resume: Record<string, number | string> }>('/system/normaliser-metadata').then(r => r.data),
```
Les acronymes se lisent/écrivent via l'endpoint config existant : `systemApi.getConfig()` → `config.acronymes.valeur`
(chaîne JSON à `JSON.parse`), et `systemApi.updateConfig({ acronymes: JSON.stringify(liste) })`.

**b) Section Paramètres** — un tableau éditable **Sigle | Définition** (+ ajouter/supprimer une ligne),
enregistré via `updateConfig({ acronymes })`, et un bouton **« Normaliser les tags/catégories »** :
```tsx
const [acronymes, setAcronymes] = useState<{ sigle: string; definition: string }[]>([])
const [normalisant, setNormalisant] = useState(false)
// charger : JSON.parse(config.acronymes?.valeur ?? '[]')
const enregistrerAcronymes = () => systemApi.updateConfig({ acronymes: JSON.stringify(acronymes) })
const normaliser = async () => {
  setNormalisant(true)
  try {
    const { resume } = await systemApi.normaliserMetadata()
    toast.success(`Normalisé : ${resume.docs_tags_maj} docs (tags), ${resume.variantes_tags_fusionnees} variantes fusionnées`)
  } catch (e) { toast.error(extractApiError(e)) } finally { setNormalisant(false) }
}
```
UI : tableau des acronymes (input Sigle + input Définition + 🗑 par ligne), bouton « + Ajouter », bouton
« Enregistrer », puis bouton « ✨ Normaliser les tags/catégories » (état `normalisant`). Colonne **Définition**
= explication libre (ex. « IBAN → International Bank Account Number »).

> Note : le backend force en MAJUSCULES uniquement les sigles présents dans ce dictionnaire ; les extensions
> (pdf, xlsx…) et mots communs restent inchangés. Réversible via `storage/backup-normalisation.json`.
