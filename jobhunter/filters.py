"""Filtres : début de carrière × corporate finance / investissement × Suisse.

Une offre est retenue si :
  1. elle est en Suisse ;
  2. son intitulé n'est ni senior ni hors sujet (IT, RH, compliance, audit...) ;
  3. c'est un poste de début de carrière : stage (y c. summer / off-cycle,
     working student), graduate / trainee programme, analyst / junior,
     ou associate (option) ;
  4. elle relève d'un domaine visé : M&A / IB, private equity / VC,
     asset management... (dans l'intitulé, ou programme général d'une société
     de la liste confirmé par la description).
"""
from __future__ import annotations

import re
from datetime import datetime
import unicodedata


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower()).strip()


# ---------------------------------------------------------------------------
# Domaines (FR / EN / DE / IT, texte normalisé sans accents)
# ---------------------------------------------------------------------------
DOMAINS: list[tuple[str, re.Pattern]] = [
    ("M&A / Investment Banking", re.compile(
        r"\bm ?& ?a\b|\bm and a\b|\bmergers|\bacquisitions?\b|\bfusions?\b|"
        r"investment bank|\bibd?\b|corporate finance|finance d.entreprise|"
        r"transaction (services|advisory)|deal advisory|\bdeals?\b|"
        r"financial due diligence|\bvaluations?\b|evaluation d.entreprise|bewertung|"
        r"corporate development|restructuring|leveraged finance|acquisition finance|"
        r"\becm\b|\bdcm\b|capital markets|equity capital|debt capital|"
        r"marches des capitaux|kapitalmarkt|\bcoverage\b|unternehmensfinanz|"
        r"corporate banking|structured finance|project finance|debt advisory")),
    ("Private Equity / VC / Private Markets", re.compile(
        r"private (equity|markets?|debt|credit|assets|infrastructure)|"
        r"\bventure\b|\bvc\b|growth equity|\bbuy.?out|secondaries|co.?invest|"
        r"direct investment|fund of funds|infrastructure invest|real estate invest|"
        r"\bpe (analyst|associate|intern|team)|beteiligung")),
    ("Asset Management / Investments", re.compile(
        r"asset manage|gestion d.actifs|vermogensverwalt|kapitalanlage|"
        r"portfolio (manage|analy|construct)|\bportefeuille|fund manage|"
        r"investment (analy|manage|team|office|research|strateg|solution|specialist|intern|associate|banking)?|"
        r"\binvest(?!igat)|equity research|research analyst|buy.?side|"
        r"multi.?asset|fixed income|\bequities\b|hedge fund|asset allocation|"
        r"\bquant(itative)? (analy|research|invest)|\bfonds\b|\bfunds?\b|"
        r"\banlage|investimenti|gestione patrimoni")),
    ("Wealth Management / Private Banking", re.compile(
        r"wealth manage|gestion de fortune|gestion privee|private bank|"
        r"vermogensberat|relationship manager|client advis|conseiller clientele")),
]

# Signaux « finance » secondaires, utiles surtout dans la description
FINANCE_HINTS = re.compile(
    r"\bdcf\b|financial model|\blbo\b|\bvaluation|due diligence|pitch ?book|"
    r"\bcfa\b|bloomberg|capital iq|factset|\bm ?& ?a\b|private equity|"
    r"portfolio|asset management|investment|transaction")

# ---------------------------------------------------------------------------
# Niveau
# ---------------------------------------------------------------------------
INTERNSHIP = re.compile(
    r"\bintern(ship)?s?\b|\bstagiaire|"
    r"(?<!early )(?<!later )(?<!late )(?<!growth )(?<!seed )(?<!development )(?<!expansion )"
    r"\bstage\b(?! ?(\d|gate|manager|compan|invest|venture|fund|start))|"
    r"\bpraktik|\bwerkstudent|working student|\bstudent (job|assistant)|"
    r"summer (analyst|associate|intern|program)|\boff.?cycle|spring (week|insight)|"
    r"\binsight (week|day|program)|\btirocin|\bstagista|\bthesis\b|\bmaster.?arbeit|"
    r"memoire|\bv\.i\.e\b|\bvie (contract|intern|program|mission)")
GRADUATE = re.compile(
    r"\bgraduate\b|\btrainee|\brotation(al)?\b|\bberufseinsteiger|\beinstiegs?program|"
    r"jeune(s)? diplome|young (professional|talent)|career starter|"
    r"\b(analyst|talent|junior) program|\bgraduate program|early career|"
    r"\bentry.level\b|\bnachwuchs|\bdirect entry\b")
JUNIOR = re.compile(r"\bjunior\b|\bjr\.?\b|\banalyst\b|\banalyste\b|\banalist|\bconsultant\b|"
                    r"\bassistant (portfolio|fund|investment|relationship)")
ASSOCIATE = re.compile(r"\bassociate\b|\bassocie\b")

SENIOR = re.compile(
    r"\bsenior\b|\bsr\.?\b|\bdirector\b|\bdirecteur|\bdirektor|\bvice.president|\bvp\b|"
    r"\bavp\b|\bhead\b|\bresponsable\b|\bleiter|\blead\b|\bprincipal\b|\bpartner\b|"
    r"\bmanaging\b|\bchief\b|\bcio\b|\bcfo\b|\bexperienced\b|\bexpert\b|\bexecutive\b|"
    r"\b(\d{1,2}\+? ?(years|ans|jahre))|\bteam ?lead|\bsupervisor")
# « manager » est senior, sauf « assistant / junior ... manager » (géré par JUNIOR)
MANAGER = re.compile(r"\bmanager\b|\bgerant")

# Apprentissages suisses (CFC / KV / Lehre) : niveau secondaire, pas visés
APPRENTICE = re.compile(r"\bapprenti|\blernende|\blehrstelle|\blehre\b|\bkv\b|\bcfc\b|"
                        r"\bapprendista|\bberufsmatur")

# ---------------------------------------------------------------------------
# Suisse
# ---------------------------------------------------------------------------
SWISS = re.compile(
    r"\b(switzerland|suisse|schweiz|svizzera|svizra|swiss|ch)\b|"
    r"\b(geneve|geneva|genf|ginevra|zurich|zuerich|lausanne|basel|bale|basilea|bern|berne|"
    r"lugano|zug|luzern|lucerne|lucerna|st\.? ?gallen|saint.gall|neuchatel|fribourg|"
    r"sion|sitten|winterthur|nyon|vevey|montreux|morges|chur|schaffhausen|baar|pfaffikon|"
    r"aarau|olten|solothurn|thun|biel|bienne|yverdon|rolle|carouge|plan.les.ouates|"
    r"meyrin|vernier|lancy|cham|kusnacht|wollerau|freienbach|schindellegi|chiasso|bellinzona|"
    r"locarno|mendrisio|uster|dubendorf|opfikon|glattbrugg|wallisellen|kloten|"
    r"gland|eysins|vaud|valais|wallis|ticino|tessin|graubunden|grisons|"
    r"zollikon|thalwil|horgen|baden|rapperswil|jona|schwyz|altdorf|sarnen|stans|herisau|"
    r"frauenfeld|kreuzlingen|liestal|muttenz|pratteln|allschwil|riehen|emmen|kriens|rotkreuz|"
    r"steinhausen|hunenberg|kilchberg|ruschlikon|adliswil|horw|bulle|martigny|monthey|sierre|"
    r"delemont|la chaux.de.fonds|renens|ecublens|epalinges|pully|crissier|prilly|bussigny|"
    r"coppet|versoix|chene.bourg|thonex|onex|grand.saconnex|cointrin|allaman|aubonne|etoy|"
    r"st\.? ?moritz|davos|glarus|wadenswil|wetzikon|bulach|schlieren|dietikon|regensdorf|"
    r"rumlang|oerlikon|altstetten|manno|bioggio|paradiso|massagno|cadempino|agno|ruggell|"
    r"pfaeffikon|zurich.flughafen|zug.baar|lachen|kussnacht|risch|cham|hergiswil)\b|"
    # codes de canton non ambigus après une virgule (« Pfäffikon, SZ », « Baar, ZG »)
    r",\s*(zh|vd|zg|sz|bs|bl|lu|ti|sg|vs|gr|ag|so|tg|sh|nw|ow|ur|ju)\b")
NON_SWISS_GENEVA = re.compile(r"geneva,? (il|ny|oh|al|illinois|new york|ohio)\b|"
                              r"\b(usa|united states|united kingdom)\b|,\s*(us|uk)\s*$")


FOREIGN_IN_TITLE = re.compile(
    r"\b(singapore|london|hong kong|new york|dubai|abu dhabi|luxembourg|paris|frankfurt|munich|"
    r"munchen|berlin|hamburg|madrid|milan|milano|amsterdam|stockholm|tokyo|sydney|toronto|"
    r"san francisco|boston|chicago|mumbai|shanghai|beijing|doha|riyadh|tel aviv|monaco|jersey|"
    r"guernsey|vienna|wien|warsaw|lisbon|dublin|brussels|copenhagen|oslo|helsinki|bangkok|"
    r"mexico|sao paulo|uk|usa|united kingdom|united states|germany|france|italy|spain|asia|apac|"
    r"emea hub|americas)\b")


def is_swiss(location: str) -> bool:
    loc = norm(location)
    loc = loc + " " + loc.replace("ae", "a").replace("oe", "o").replace("ue", "u")
    if re.search(r"\b(switzerland|suisse|schweiz|svizzera)\b", loc):
        return True
    if not loc or NON_SWISS_GENEVA.search(loc):
        return False
    return bool(SWISS.search(loc))


# ---------------------------------------------------------------------------
LEVEL_INTERN = "Stage / Internship"
LEVEL_GRAD = "Graduate programme"
LEVEL_JUNIOR = "Analyst / Junior"
LEVEL_ASSOC = "Associate"


def level(title: str) -> str | None:
    """Niveau de début de carrière, ou None si senior / indéterminé."""
    t = norm(title)
    if APPRENTICE.search(t):
        return None
    early = INTERNSHIP.search(t) or GRADUATE.search(t)
    if SENIOR.search(t) and not early:
        return None
    if INTERNSHIP.search(t):
        return LEVEL_INTERN
    if GRADUATE.search(t):
        return LEVEL_GRAD
    if JUNIOR.search(t):
        return LEVEL_JUNIOR
    if MANAGER.search(t):
        return None
    if ASSOCIATE.search(t):
        return LEVEL_ASSOC
    return None


def domain(text: str) -> str | None:
    for name, rx in DOMAINS:
        if rx.search(text):
            return name
    return None


# ---------------------------------------------------------------------------
# Langue : écarter les annonces rédigées en allemand
# ---------------------------------------------------------------------------
GERMAN_TITLE = re.compile(
    r"\((m|w|d|x)\s*/\s*(m|w|d|x)(\s*/\s*(m|w|d|x))?\)|\b(m|w)/(w|m)/d\b|\(alle\)|"
    r"\w(:|\*|/-?)in(nen)?\b|\b(und|fur|mit|im|bei|zur|zum|der|die|das|des)\b|"
    r"\b(praktik\w*|werkstudent\w*|mitarbeiter\w*|berater\w*|kundenberat\w*|sachbearbeit\w*|"
    r"fachspezialist\w*|fachperson|fachfrau|fachmann|kauffrau|kaufmann|leiter\w*|stellvertret\w*|"
    r"teilzeit|vollzeit|lernende\w*|lehrstelle|vermogens\w*|anlage\w*|unternehmens\w*|"
    r"bereich|abteilung|spezialist\w*|assistenz|betreuer\w*|verantwortlich\w*|"
    r"einsteiger\w*|nachwuchs\w*|traineeprogramm|hochschul\w*|absolvent\w*|stelle)\b")
_DE = set("und der die das mit fur wir sie ist von zu auf eine ein einen den dem im bei unsere unser "
          "ihre ihr sind werden oder als auch nicht du dich dein deine uns sowie uber wie".split())
_EN = set("and the with for we you is of to on a an our your are will or as also not in at "
          "this that be from".split())
_FR = set("et le la les des du avec pour nous vous est de un une nos vos sont ou aussi pas dans "
          "au aux sur".split())


def is_german(title: str, description: str = "") -> bool:
    t = norm(title)
    # les noms de villes / sociétés en allemand ne comptent pas
    t = re.sub(r"\b(zurich|zuerich|basel|bern|zug|luzern|st\.? ?gallen|winterthur|"
               r"kantonalbank|ag|gmbh)\b", " ", t)
    if GERMAN_TITLE.search(t):
        return True
    words = re.findall(r"[a-z]+", norm(description)[:3000])
    if len(words) >= 40:
        de = sum(w in _DE for w in words)
        en = sum(w in _EN for w in words)
        fr = sum(w in _FR for w in words)
        return de > max(en, fr) and de >= 8
    return False


# Intitulés qui sont des rubriques de site, pas des postes (« Young Talents », « Early Careers @ X »)
NOT_A_JOB = re.compile(
    r"^((internship|graduate|trainee|talent|young talent|student)s? (program|programme)s?|"
    r"early careers?|young talents?|working students?|students|graduates|internships|careers?)"
    r"( @ .*| at .*| - .*)?$|^(read more|more)\b|analyst (coverage|recommendations?)")
BIO_LINE = re.compile(r"\b(at|chez|bei|@|formerly|previously|former)\b")
# Postes qui GÈRENT un programme (« Graduate Programme Manager », « Internship Coordinator »)
PROGRAM_STAFF = re.compile(
    r"\b(graduate|intern(ship)?s?|trainee|campus|early careers?|talent|student)\s+"
    r"((program(me)?|relations|acquisition|recruiting)\s+)?"
    r"(manager|coordinator|lead|recruiter|specialist|partner|advisor|officer|consultant|head)\b")
# Pages « équipe » : les fonctions des collaborateurs ressemblent à des intitulés de poste
TEAM_URL = re.compile(r"/(team|teams|our-team|people|our-people|leadership|management|board|"
                      r"partners|equipe|unser-team|mitarbeitende|about-us/team|who-we-are)(/|$|\?|#|\.html?)",
                      re.I)


def evaluate(job: dict, fcfg: dict, firm=False):
    """Renvoie l'offre enrichie (type, domain, score, tags) ou None si écartée.

    firm : bool (société de la liste « investissement ») ou dict
           {"investment_firm": bool, "domain": str | None} pour une société cible
           dont on connaît le métier (ex. un fonds de PE → domaine PE).
    """
    if isinstance(firm, dict):
        company_is_investment_firm = firm.get("investment_firm", True)
        firm_domain = firm.get("domain")
    else:
        company_is_investment_firm, firm_domain = bool(firm), None
    title = norm(job.get("title", ""))
    if not title or NOT_A_JOB.search(title) or PROGRAM_STAFF.search(title):
        return None
    if (job.get("source") or "").endswith("texte") and BIO_LINE.search(title):
        return None                       # ligne de biographie lue dans le texte d'une page
    src = job.get("source") or ""
    if (src.endswith(("texte", "liens", "aucune")) or src.startswith("site:navigateur")) \
            and TEAM_URL.search(job.get("url") or ""):
        return None                       # fonction d'un collaborateur sur la page « équipe »
    for bad in fcfg.get("exclude_title", []):
        if re.search(rf"\b{re.escape(norm(bad))}", title):
            return None
    if fcfg.get("swiss_only", True):
        loc = job.get("location", "")
        if not (is_swiss(loc) or (not loc and is_swiss(job.get("title", "")))):
            return None
    if FOREIGN_IN_TITLE.search(title) and not SWISS.search(title):
        return None                       # « ... – Tenity Singapore », « Analyst (London) »
    if "de" in fcfg.get("exclude_languages", []) and is_german(job["title"], job.get("description", "")):
        return None

    vt = (job.get("valid_through") or "")[:10]
    if re.fullmatch(r"\d{4}-\d\d-\d\d", vt) and vt < datetime.now().strftime("%Y-%m-%d"):
        return None                       # offre expirée (validThrough du JSON-LD)
    lvl = level(job["title"])
    if lvl is None and re.search(r"\bINTERN", (job.get("employment_type") or "").upper()):
        lvl = LEVEL_INTERN                # schema.org employmentType = INTERN
    if fcfg.get("early_career_only", True):
        if lvl is None:
            return None
        if lvl == LEVEL_ASSOC and not fcfg.get("include_associate", True):
            return None
    allowed_levels = fcfg.get("levels")
    if allowed_levels and lvl not in allowed_levels:
        return None

    desc = norm(job.get("description", ""))[:5000]
    dom = domain(title)
    score = 0
    if dom and firm_domain and dom == "Asset Management / Investments":
        dom = firm_domain        # « Investment Analyst » chez un fonds de PE → PE
    if dom:
        score += 5
    else:
        # Intitulé générique (« Summer Internship 2027 », « Graduate Programme »...) :
        # accepté s'il vient d'une société de la liste ou si la description est finance.
        # Le domaine n'est pas déduit de la description (trop de faux positifs) :
        # l'offre est étiquetée comme générique pour que tu tries toi-même.
        hints = len(set(FINANCE_HINTS.findall(desc)))
        if firm_domain and lvl:
            dom = firm_domain                 # ex. « Analyst » chez un fonds de PE
            score += 3
        elif company_is_investment_firm and lvl in (LEVEL_INTERN, LEVEL_GRAD):
            dom = "Programme général (société cible)"
            score += 2
        elif hints >= 3 and lvl in (LEVEL_INTERN, LEVEL_GRAD):
            dom = "Finance (d'après la description)"
            score += 1
        else:
            return None
    allowed_domains = fcfg.get("domains")
    if allowed_domains and not any(d.lower() in dom.lower() for d in allowed_domains):
        return None

    score += {LEVEL_INTERN: 3, LEVEL_GRAD: 3, LEVEL_JUNIOR: 2, LEVEL_ASSOC: 1}.get(lvl, 0)
    if company_is_investment_firm:
        score += 1
    if desc:
        score += min(2, len(set(FINANCE_HINTS.findall(desc))) // 2)
    if score < fcfg.get("min_score", 0):
        return None
    tags = sorted(set(m.group(0) for _, rx in DOMAINS for m in [rx.search(title)] if m))[:3]
    return {**job, "score": score, "type": lvl or "?", "domain": dom, "tags": ", ".join(tags)}
