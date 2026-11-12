# JobHunter — early career en corporate finance en Suisse

Stages (y compris summer / off-cycle et working student), graduate programmes et postes analyst / junior / associate en **M&A / investment banking, private equity / VC et asset management**, en Suisse.

Chaque jour, le système :

1. visite les **sites carrières de ~350 sociétés suisses** (`firms.yaml`) : private equity, private markets, VC, boutiques M&A, Big 4, banques privées et cantonales, gérants d'actifs, family offices. La liste vient des annuaires **SECA** (Swiss Private Equity & Corporate Finance Association) et **AMAS** (Asset Management Association Switzerland), complétés à la main ;
2. lance des recherches **LinkedIn / Indeed** (JobSpy) ciblées early career ;
3. ne garde que les offres **de début de carrière**, **en corporate finance / investissement**, **en Suisse** et **pas rédigées en allemand**, avec un **niveau** (Stage / Internship, Graduate programme, Analyst / Junior, Associate) et un **domaine** (M&A / IB, PE / VC, Asset Management, Wealth Management) ;
4. fusionne les doublons (la même offre sur LinkedIn et sur le site de la société) ;
5. produit `output/offres_corporate_finance_suisse.xlsx` avec les onglets *Nouveaux*, *Stages*, *Graduate programmes*, *Analyst - Junior - Associate*, *Toutes les offres actives* et **Couverture sites**, qui indique pour chaque société comment son site a été lu, combien d'éléments ont été trouvés et les éventuels problèmes.

## Comment les sites carrières sont lus

Pour chaque société, dans l'ordre :

1. **API de l'ATS** si on la connaît (Workday, Greenhouse, Lever, Ashby, SmartRecruiters, Personio, Recruitee, Workable). C'est rapide et complet.
2. Sinon, la page d'accueil est ouverte dans un **vrai navigateur sans fenêtre** (Chromium via Playwright) pour trouver la page carrière. Celle-ci est ensuite affichée comme pour un visiteur : le JavaScript s'exécute et la page charge ses offres. Le système récupère alors :
   - les requêtes réseau, iframes et liens, pour **repérer l'ATS**. S'il en trouve un, il passe par son API ;
   - les **portails sans API** (SuccessFactors, Umantis, Abacus, Softgarden, Teamtailor, Oracle, Taleo…), qui sont ouverts à leur tour ;
   - sinon, les **offres affichées**, tirées en priorité des données **schema.org JobPosting** (le JSON-LD que les sites publient pour Google Jobs), puis des données JSON reçues par la page, des liens et, pour les petites structures, du texte. Si la page n'est qu'une vitrine, il suit le lien « Open positions / Offres d'emploi ».
3. Pour que ça marche sur un maximum de sites :
   - les **bandeaux cookies** sont refusés (bouton « Reject all / Tout refuser / Nur notwendige ») : jamais accepter, juste fermer ce qui masque la page ;
   - les boutons **« Load more / Voir plus »** sont cliqués (jusqu'à 6 fois) pour avoir toute la liste ;
   - les liens sont lus aussi dans les **web components** (shadow DOM) et dans le **code de la page** (menus en JSON, ex. Julius Bär) ;
   - un lien « Karriere / Careers » vers le **site du groupe** est accepté (ex. Baloise AM → helvetia-baloise.com) ;
   - si aucun lien carrière n'existe, le **sitemap** du site (robots.txt → sitemap.xml) est lu : il donne la page carrière, voire directement les offres ; puis ~20 chemins usuels (/careers, /karriere, /fr/carrieres, /join-us…) ;
   - certificat expiré, www. manquant, vieux TLS : les autres écritures de l'adresse sont essayées ;
   - les **fiches des offres prometteuses** (6 max. par société) sont ouvertes pour lire le vrai lieu, la date, la description (ce qui permet d'écarter les annonces en allemand) et les offres expirées.
4. La méthode qui a fonctionné est **mémorisée 30 jours**. Les passages suivants vont donc directement au bon endroit.

Trois navigateurs travaillent en parallèle, chacun sur une société différente. Images, polices et vidéos ne sont pas chargées, et chaque site reçoit quelques pages par jour au maximum.

Les très grands groupes (Goldman Sachs, J.P. Morgan, BlackRock, KKR…) ont des portails mondiaux non filtrables par pays. Ils sont marqués `site: false` et leurs postes suisses viennent de LinkedIn / Indeed. La société est quand même reconnue, ce qui sert au domaine et au score.

## Installation

```bash
cd jobhunter
python3 -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium   # navigateur (LANCER.bat le fait tout seul)
python -m pytest tests -q          # 76 tests hors-ligne, doivent tous passer
```

## Utilisation

```bash
python run.py                      # passage complet
python run.py --no-jobspy          # seulement les sites carrières
python run.py --no-sites           # seulement LinkedIn / Indeed
python run.py --only "Capvis"      # tester une société (ou toutes celles dont le nom contient ce texte)
python run.py seed-seca            # ré-importer l'annuaire SECA (data/seca_members.csv)
python tools/build_firms.py data/seca_members.csv > firms.yaml   # régénérer la liste
```

Au premier passage, toutes les offres sont « nouvelles ». Ensuite, seules les vraies nouveautés apparaissent dans l'onglet *Nouveaux*.

## Personnaliser (`config.yaml`)

- **`firms.yaml`** : une entrée par société (`name`, `website`, `category`). Pour corriger un site mal lu (voir l'onglet *Couverture sites*), ajoute `careers_url:` (la bonne page) ou `ats:` + `slug:`/`url:`. `site: false` désactive la visite. `aliases:` sert à reconnaître la société sur LinkedIn.
- **`jobspy.search_terms`** : les recherches LinkedIn/Indeed. Chaque terme ajoute environ 3 requêtes par site, donc il vaut mieux viser juste que tout lister.
- **`filters.levels`** et **`filters.domains`** : supprime une ligne pour exclure un niveau (par exemple *Associate*) ou un domaine (par exemple *Wealth Management*).
- **`filters.exclude_title`** : fonctions à écarter.
- **`filters.exclude_languages: [de]`** : écarte les annonces en allemand, d'après l'intitulé (Praktikant/in, (m/w/d), Werkstudent, mots allemands…) et, quand elle est disponible, la langue de la description. Supprime la ligne pour les garder.
- Quand tu modifies les filtres, l'historique est refiltré au passage suivant. Quand tu modifies les recherches, le passage suivant remonte 30 jours en arrière pour rattraper.

## Pourquoi tu ne devrais pas être bloqué (et les limites)

Il n'existe pas de garantie à 100 %, ni ici ni ailleurs. Le système est conçu pour que le risque soit faible et que, si un blocage arrive, il reste sans conséquence.

| Mesure | Effet |
|---|---|
| API JSON officielles des ATS plutôt que du HTML | Ce sont des endpoints publics prévus pour être lus. C'est le cas le plus sûr. |
| 3 à 7 s aléatoires entre deux requêtes au même domaine, une seule à la fois | Pas de rafale, pas de rythme régulier détectable. |
| Respect des codes 429/503 et de `Retry-After`, backoff exponentiel | Le script ralentit quand le site le demande. |
| Coupe-circuit : sur un 403 ou après 3 échecs, le domaine est ignoré jusqu'au lendemain | Le script n'insiste jamais, alors que c'est l'insistance qui mène au bannissement. |
| `robots.txt` respecté pour toutes les pages de sites (requêtes simples et navigateur) | Reste dans les règles affichées par le site. |
| Sites carrières : quelques pages par société et par jour, images / polices / vidéos non chargées, méthode d'accès mémorisée | Charge négligeable pour chaque site, comparable à un visiteur. |
| JobSpy : 25 à 60 s entre les recherches, un site à la fois, sans descriptions LinkedIn | Volume faible, environ 50 requêtes LinkedIn par jour. |
| JobSpy : site désactivé pour la journée dès un signe de limitation, ou après 3 résultats vides d'affilée | Pas d'acharnement sur un site qui freine. |
| **Aucune connexion à ton compte LinkedIn** | Au pire c'est ton IP qui est freinée quelques heures, **jamais ton compte**. |
| Un passage par jour, à une heure aléatoire (`--jitter 45`) | Comportement proche d'une consultation humaine. |
| Verrou anti-double exécution, cache de la détection d'ATS | Pas de requêtes inutiles. |

Si LinkedIn bloque malgré tout, ce qui arrive parfois avec les IP de bureau ou de VPN partagées, le log l'indique (`linkedin signale une limitation`). Dans ce cas, réduis `results_wanted` ou le nombre de termes, ou ajoute un proxy résidentiel dans `jobspy.proxies`. Les sites carrières, eux, continuent de fonctionner.

Pour un usage personnel de recherche d'emploi, ce type de collecte est courant, mais les conditions d'utilisation de LinkedIn et d'Indeed l'interdisent formellement. Ne republie pas les données collectées.

## Planification quotidienne

**Windows (déjà en place)** : `PROGRAMMER_20H.bat` crée la tâche planifiée **« JobHunter »**, qui lance `run_daily.bat` tous les jours à **20:00** dans une fenêtre réduite. Le journal est écrit dans `logs\tache_quotidienne.log` et le rapport dans `output\`.
- Si le PC est éteint ou en veille à 20:00, la tâche démarre dès qu'il est rallumé.
- Elle ne tourne que si ta session Windows est ouverte (même verrouillée).
- Pour changer l'heure, modifie `20:00` dans `tools\installer_tache.ps1` et relance `PROGRAMMER_20H.bat`. Pour supprimer la tâche : Planificateur de tâches > « JobHunter » > Supprimer.

**macOS / Linux (cron)** : `crontab -e`, puis `0 20 * * * /chemin/vers/jobhunter/run_daily.sh`.

## Email des nouveautés (optionnel)

Copie `.env.example` en `.env` et remplis-le. Pour Gmail, il faut un **mot de passe d'application**, pas ton mot de passe habituel. Sans `.env`, le système se contente du fichier Excel.

## Structure

```
run.py                    point d'entrée (run / seed-seca)
config.yaml               entreprises, mots-clés, réglages anti-blocage
jobhunter/http.py         client HTTP poli (délais, backoff, coupe-circuit, robots.txt)
jobhunter/ats.py          connecteurs ATS (API) + détection des ATS et portails
jobhunter/browser.py      navigateur sans fenêtre : page carrière, JSON, liens, texte
jobhunter/careers.py      orchestration par société (API → navigateur → sitemap), en parallèle
jobhunter/structured.py   schema.org JobPosting (JSON-LD) et sitemaps XML
tools/dump_sites.py       capture des pages des sites en échec (DIAGNOSTIC.bat) pour améliorer l'extraction
jobhunter/seed.py         import de l'annuaire SECA
tools/                    liste de base des sociétés + générateur de firms.yaml
firms.yaml                les ~350 sociétés suivies
jobhunter/jobspy_source.py LinkedIn / Indeed via JobSpy
jobhunter/filters.py      pertinence investissement (FR/EN/DE/IT), Suisse, type de poste
jobhunter/store.py        SQLite : historique, nouveautés, dédoublonnage
jobhunter/report.py       Excel, CSV, email
data/jobs.sqlite          historique (créé au premier passage)
output/                   rapports
logs/                     un log par jour
```

## Non couvert

jobs.ch, jobup.ch et Swissfinancejobs n'ont pas d'API publique et interdisent le scraping. Le plus simple est d'y créer des **alertes email** avec les mêmes mots-clés.
