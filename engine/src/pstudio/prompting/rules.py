"""Proveedor `rules` (#15): pedido en español o inglés → EditPlan, con palabras clave.

Offline, determinista y rápido (< 1 ms por pedido): es el respaldo garantizado cuando el LLM no
está o falla. No "entiende" el idioma: reconoce temas (luz, contraste, color, recorte…), una
dirección (más/menos, más cálido/más frío) y una intensidad ("un poco", "mucho") por cláusula.

Cómo funciona:
1. Normaliza: minúsculas, sin tildes, espacios simples. Protege frases que llevan "y"/"and"
   ("blanco y negro") y parte el pedido en cláusulas por comas, "y", "and", "luego", "then"…
2. En cada cláusula: ¿hay negación ("no", "sin", "don't")? Entonces los temas que aparezcan
   quedan bloqueados (no se agregan, aunque otra cláusula los pida). Si no, cada tema detectado
   suma una "intención" con su dirección e intensidad.
3. Primero se miran los pedidos fuera del catálogo (quitar el fondo, borrar objetos,
   retocar piel, IA…) → `unsupported` con motivo y alternativa.
4. Las intenciones se combinan (dos pedidos de la misma op se suman, con tope), se ordenan
   en un orden de revelado fijo (geometría → luz → color → detalle → tamaño) y se arma una
   explicación corta en el idioma del pedido.
5. Si no se entendió nada, o falta un dato imprescindible (recortar sin proporción, enderezar
   sin grados), devuelve una sola pregunta concreta en `clarification`, sin ops.

Los valores son relativos y moderados (ver BASE): la idea es un primer paso razonable que el
usuario ajusta con los sliders, no adivinar el valor exacto.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from pstudio.prompting.provider import PlanRequest

# ------------------------------------------------------------------ texto
_PROTECT = {
    "blanco y negro": "blanco_y_negro",
    "black and white": "black_and_white",
    "black & white": "black_and_white",
    "b&w": "black_and_white",
    "b/n": "blanco_y_negro",
    "luces y sombras": "luces_y_sombras",
    "highlights and shadows": "luces_y_sombras",
    "shadows and highlights": "luces_y_sombras",
}
_SPLIT = re.compile(
    r"\s*(?:[,;.!?\n]|\by\b|\be\b|\band\b|\bthen\b|\bluego\b|\bdespues\b|\bademas\b|"
    r"\bplus\b|\balso\b|\btambien\b|\bpero\b|\bbut\b)\s*"
)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("×", "x").replace("’", "'")
    text = re.sub(r"\s+", " ", text).strip()
    for phrase, token in _PROTECT.items():
        text = text.replace(phrase, token)
    return text


def clauses(text: str) -> list[str]:
    return [c for c in _SPLIT.split(text) if c]


def _has(text: str, *patterns: str) -> bool:
    return any(re.search(p, text) for p in patterns)


ENGLISH_HINTS = (
    r"\bthe\b", r"\bmake\b", r"\bmore\b", r"\bless\b", r"\bplease\b", r"\bphoto\b",
    r"\bimage\b", r"\bit\b", r"\bwith\b", r"\bfor\b", r"\btoo\b", r"\bbit\b", r"\badd\b",
)  # fmt: skip
SPANISH_HINTS = (
    r"\bla\b", r"\bel\b", r"\bmas\b", r"\bmenos\b", r"\bfoto\b", r"\bimagen\b", r"\bun\b",
    r"\buna\b", r"\bcon\b", r"\bpara\b", r"\bmuy\b", r"\bpoco\b", r"\bque\b", r"\bde\b",
)  # fmt: skip


def language(text: str) -> str:
    en = sum(bool(re.search(p, text)) for p in ENGLISH_HINTS)
    es = sum(bool(re.search(p, text)) for p in SPANISH_HINTS)
    return "en" if en > es else "es"


# ------------------------------------------------------------------ intensidad y dirección
LOW = (r"\bun poc", r"\bpoquit", r"\bapenas\b", r"\blevement", r"\bligera", r"\bsutil",
       r"\bsuave(ment)?\b(?! (la|el|los|las) )", r"\bslight", r"\ba (little )?bit\b",
       r"\ba little\b", r"\bsubtl", r"\bgently\b", r"\bun toque\b", r"\btouch\b")  # fmt: skip
HIGH = (r"\bmuch[oa]\b", r"\bbastante\b", r"\bmuy\b", r"\bdemasiad", r"\bre ", r"\ba lot\b",
        r"\blots\b", r"\bmuch\b", r"\bvery\b", r"\breally\b", r"\bstrong", r"\bfuert",
        r"\bintens", r"\btoo\b", r"\bheav", r"\bextrem", r"\bway\b")  # fmt: skip
NEGATION = (r"\bno\b", r"\bsin\b", r"\bni\b", r"\bnunca\b", r"\bdon'?t\b", r"\bdo not\b",
            r"\bwithout\b", r"\bnot\b", r"\bnever\b", r"\bavoid", r"\bevit")  # fmt: skip
MORE = (r"\bmas\b", r"\bmore\b", r"\bsub[ie]", r"\baument", r"\bincreas", r"\bboost",
        r"\braise\b", r"\blevant", r"\babr[ie]", r"\bagreg", r"\bpon[eé]?\b", r"\badd\b",
        r"\benhanc", r"\bextra\b", r"\bresalt", r"\bpotenci", r"\bintensific",
        r"\blift")  # fmt: skip
UPSIDE_DOWN = (r"\bal reves\b", r"\bupside down\b", r"\bdar vuelta\b", r"\bdale vuelta\b",
               r"\bcabeza abajo\b", r"\bpatas (para )?arriba\b", r"\binvertida\b")  # fmt: skip
STATE = r"\b(se ven?|estan?|quedaron|quedo|queda|looks?|are|is|seem|parece)\b"
LOOK_WORDS = (r"\blook\b", r"\bestilo\b", r"\befecto\b", r"\btipo\b", r"\bvibe\b",
              r"\baesthetic\b", r"\bonda\b", r"\bstyle\b")  # fmt: skip
RESIZE_WORDS = (
    r"\b(achic|reduc|resiz|redimension|cambi\w* (el )?tamano|tamano|smaller|scale down|"
    r"downscal|agrand|enlarg|bigger)"
)
LESS = (r"\bmenos\b", r"\bless\b", r"\bbaj[aáeo]", r"\breduc", r"\bdisminu", r"\bdecreas",
        r"\blower\b", r"\bsac[aá]", r"\bquit", r"\bremove\b", r"\btone down\b", r"\bsuaviz",
        r"\bsoften", r"\brecuper", r"\brecover", r"\bcontrol", r"\bbaja\b")  # fmt: skip


def intensity(clause: str) -> float:
    if _has(clause, *LOW):
        return 0.5
    if _has(clause, *HIGH):
        return 2.0
    return 1.0


def direction(clause: str) -> int:
    """+1 más, −1 menos, 0 no dice."""
    less, more = _has(clause, *LESS), _has(clause, *MORE)
    if less and not more:
        return -1
    if more and not less:
        return 1
    return 0


# ------------------------------------------------------------------ fuera de catálogo
@dataclass(frozen=True)
class Unsupported:
    patterns: tuple[str, ...]
    request: dict[str, str]
    reason: dict[str, str]
    alternative: dict[str, str] | None = None


UNSUPPORTED = [
    Unsupported(
        (
            r"\b(script|codigo|code|python|javascript|programa|program|comando|command|"
            r"ejecut|execute|shell|terminal|powershell|bash|sql|macro|plugin)\w*",
        ),
        {"es": "escribir o ejecutar código", "en": "write or run code"},
        {
            "es": "por seguridad solo aplico operaciones del catálogo, nunca código",
            "en": "for safety I only apply catalog operations, never code",
        },
        {
            "es": "decime el efecto que buscás (por ejemplo, sepia) y lo armo con ajustes",
            "en": "tell me the look you want (e.g. sepia) and I'll build it from adjustments",
        },
    ),  # fmt: skip
    Unsupported(
        (
            r"\b(quit|sac|borr|elimin|remov|cambi|reemplaz|replac|chang|swap|delet|"
            r"transparen|recort|cut out|desenfoc|blur|pon\w* (un|otro)|add)\w*\b.*"
            r"\b(fondo|background|backdrop)\b",
            r"\b(fondo|background|backdrop)\b.*\b(transparente|transparent|distinto|"
            r"different|otro|another|nuevo|new)\b",
            r"\bsin fondo\b",
            r"\bno background\b",
        ),
        {"es": "cambiar o quitar el fondo", "en": "change or remove the background"},
        {
            "es": "requiere separar el sujeto con IA (llega en una versión futura)",
            "en": "needs AI subject segmentation (coming in a future version)",
        },
        {
            "es": "puedo oscurecer los bordes con una viñeta para destacar el sujeto",
            "en": "I can darken the edges with a vignette to make the subject stand out",
        },
    ),  # fmt: skip
    Unsupported(
        (
            r"\b(borr|elimin|quit|sac|remov|eras|delet|get rid)\w*\b.*\b(persona|gente|people|"
            r"person|man|woman|hombre|mujer|objeto|object|cable|poste|pole|wire|turista|tourist|"
            r"auto|car|basura|trash|logo|marca de agua|watermark|mancha|spot|texto|text)",
            r"\b(agreg|anad|pon[eé]?|sum|add|insert|put)\w*\b.*\b(persona|gente|people|person|"
            r"herman|amig|novi|esposa|esposo|mama|papa|abuel|hij[oa]|bebe|perro|gato|mascota|"
            r"brother|sister|friend|wife|husband|mom|dad|baby|dog|cat|pet|someone|alguien|"
            r"objeto|object|texto|text|logo|marca de agua|watermark|sticker|letras|caption|"
            r"titulo|title|firma|signature|sol\b|sun\b|luna|moon|nubes|clouds)",
        ),
        {"es": "agregar o borrar elementos de la foto", "en": "add or remove elements"},
        {
            "es": "el catálogo actual no edita el contenido de la foto (requiere relleno con IA)",
            "en": "the current catalog doesn't edit the photo's content (needs AI inpainting)",
        },
        None,
    ),  # fmt: skip
    Unsupported(
        (
            r"\bcielo\b.*\b(cambi|reemplaz|otro)",
            r"\b(cambi|reemplaz|pon)\w*\b.*\b(el |un |otro )?cielo\b.*\b(por|con|nuevo|azul)\b",
            r"\b(replace|swap|change)\b.*\bsky\b",
            r"\bsky replac",
        ),
        {"es": "reemplazar el cielo", "en": "replace the sky"},
        {"es": "requiere segmentación con IA", "en": "needs AI segmentation"},
        {
            "es": "puedo recuperar las altas luces para que el cielo tenga más detalle",
            "en": "I can recover the highlights to bring back detail in the sky",
        },
    ),  # fmt: skip
    Unsupported(
        (
            r"\b(piel|skin|arrugas|wrinkle|granos de la cara|acne|pimple|ojos rojos|red ?eye|"
            r"dientes|teeth|maquill|makeup|retoc|retouch|cara|face|rostro|adelgaz|slim|"
            r"blemish|ojeras)\b",
        ),
        {"es": "retoque de rostro o piel", "en": "face or skin retouching"},
        {
            "es": "el catálogo no tiene retoque local (requiere máscaras)",
            "en": "the catalog has no local retouching (needs masks)",
        },
        {
            "es": "puedo suavizar un poco el contraste o reducir el ruido de toda la foto",
            "en": "I can soften the overall contrast slightly or reduce noise",
        },
    ),  # fmt: skip
    Unsupported(
        (
            r"\b(upscal|super ?resol|aumentar (la )?resolucion|mas resolucion|more resolution|"
            r"higher resolution|mejorar (la )?calidad con ia|ai enhance|\bia\b|\bai\b)",
        ),
        {"es": "aumentar la resolución con IA", "en": "AI upscaling"},
        {
            "es": "el escalado con IA llega en una versión futura",
            "en": "AI upscaling is planned for a future version",
        },
        {
            "es": "puedo agrandarla con un resize clásico (Lanczos)",
            "en": "I can enlarge it with a classic (Lanczos) resize",
        },
    ),  # fmt: skip
    Unsupported(
        (
            r"\b(estilo|style|como si|like a|look like|parezca)\b.*\b(van gogh|picasso|monet|"
            r"anime|cartoon|caricatura|dibujo|drawing|pintura|painting|oleo|acuarela|"
            r"watercolor|ghibli|pixar|comic|sketch)",
            r"\b(van gogh|picasso|monet|anime|cartoon|ghibli|pixar|watercolor|acuarela|"
            r"oleo|sketch)\b",
        ),
        {"es": "transferencia de estilo artístico", "en": "artistic style transfer"},
        {"es": "requiere un modelo generativo", "en": "needs a generative model"},
        {
            "es": "puedo darle un look vintage o dramático con ajustes de color y contraste",
            "en": "I can give it a vintage or dramatic look with color and contrast",
        },
    ),  # fmt: skip
    Unsupported(
        (
            r"\b(desenfoc\w* (el )?fondo|blur (the )?background|bokeh|profundidad de campo|"
            r"depth of field|modo retrato|portrait mode)",
        ),
        {"es": "desenfocar el fondo", "en": "blur the background"},
        {"es": "requiere separar el sujeto del fondo", "en": "needs subject segmentation"},
        {
            "es": "puedo agregar una viñeta para llevar la mirada al centro",
            "en": "I can add a vignette to draw the eye to the center",
        },
    ),  # fmt: skip
    Unsupported(
        (
            r"\bperspectiv",
            r"\bkeystone\b",
            r"\blineas (verticales|que caen)",
            r"\bconverging lines",
        ),
        {"es": "corregir la perspectiva", "en": "correct perspective"},
        {
            "es": "la corrección de perspectiva llega en una versión futura",
            "en": "perspective correction is planned for a future version",
        },
        {"es": "puedo enderezar la foto si está inclinada", "en": "I can straighten a tilt"},
    ),  # fmt: skip
    Unsupported(
        (r"\b(espej|mirror|flip|voltea|invert\w* (horizontal|vertical))",),
        {"es": "espejar o voltear la imagen", "en": "mirror or flip the image"},
        {"es": "el catálogo todavía no tiene espejado", "en": "the catalog has no mirroring yet"},
        {
            "es": "si está cabeza abajo, puedo rotarla 180°",
            "en": "if it's upside down, I can rotate it 180°",
        },
    ),  # fmt: skip
    Unsupported(
        (r"\braw\b", r"\bdng\b", r"\bcr2\b", r"\bnef\b", r"\barw\b"),
        {"es": "revelado de archivos RAW", "en": "RAW development"},
        {
            "es": "el soporte de RAW llega en una versión futura",
            "en": "RAW support is planned for a future version",
        },
        None,
    ),  # fmt: skip
    Unsupported(
        (r"\b(grano de pelicula|film grain|agreg\w* grano|add (some )?grain|ruido artistic)",),
        {"es": "agregar grano de película", "en": "add film grain"},
        {
            "es": "el catálogo no tiene una op para agregar grano",
            "en": "the catalog has no op to add grain",
        },
        {
            "es": "puedo darle un look de película con colores y negros levantados",
            "en": "I can give it a film look with lifted blacks and softer colors",
        },
    ),  # fmt: skip
    Unsupported(
        (
            r"\b(curvas|curves|mascara|mask|hsl|tono por color|selective color|"
            r"color selectivo|split ?ton|dividir tonos)\b",
        ),
        {
            "es": "ajustes locales o por color (curvas, máscaras, HSL)",
            "en": "local or per-color adjustments (curves, masks, HSL)",
        },
        {"es": "llegan en una versión futura", "en": "planned for a future version"},
        None,
    ),  # fmt: skip
]


# ------------------------------------------------------------------ intenciones
@dataclass
class Intent:
    op: str
    params: dict
    topic: str  # para bloquear por negación y para la explicación


@dataclass
class Draft:
    intents: list[Intent] = field(default_factory=list)
    blocked: set[str] = field(default_factory=set)  # temas negados
    export: dict = field(default_factory=dict)
    unsupported: list[dict] = field(default_factory=list)
    clarification: str | None = None
    look: bool = False  # el pedido habla de un "look"/estilo (afecta "lavado", "matte")


BASE = {  # valor de una intención de intensidad 1 (antes de dirección)
    "exposure": 0.5,  # EV
    "contrast": 20,
    "highlights": 35,
    "shadows": 35,
    "whites": 20,
    "blacks": 20,
    "temperature": 25,
    "tint": 20,
    "saturation": 20,
    "vibrance": 25,
    "sharpen": 40,
    "denoise": 0.5,
    "vignette": 35,
}

# Tema → (patrones, dirección por defecto si la cláusula no dice "más/menos").
# El signo se multiplica por la dirección de la cláusula.
TOPICS: dict[str, tuple[tuple[str, ...], int]] = {
    "bright": (
        (
            r"\baclar",
            r"\bilumin",
            r"\bluminos",
            r"\bbrillo\b",
            r"\bbright",
            r"\bbrigth",  # typo frecuente ("brigther")
            r"\bbrite\b",
            r"\blighten",
            r"\blighter\b",
            r"\bexposicion\b(?!.*\bcorreg)",
            r"\bexposure\b",
            r"\bmas luz\b",
            r"\bmore light\b",
            r"\bluz\b",
        ),
        1,
    ),  # fmt: skip
    "dark": (
        (r"\boscur", r"\bdark", r"\bsubexpuest", r"\bunderexpos", r"\bdim\b", r"\bsombria\b"),
        1,
    ),  # fmt: skip
    "overexposed": (
        (
            r"\bquemad",
            r"\bsobreexpuest",
            r"\boverexpos",
            r"\bblown\b",
            r"\bdemasiado clara\b",
            r"\btoo bright\b",
            r"\bmuy clara\b",
        ),
        1,
    ),  # fmt: skip
    "contrast": ((r"\bcontrast", r"\bpunch", r"\bpop\b", r"\bfuerza\b"), 1),
    "flat": (
        (
            r"\bplana\b",
            r"\bflat\b",
            r"\blavad",
            r"\bwashed",
            r"\bmatte?\b",
            r"\bfaded\b",
            r"\bdesvaid",
        ),
        1,
    ),  # fmt: skip
    "highlights": (
        (
            r"\baltas luces\b",
            r"\bluces altas\b",
            r"\bhighlight",
            r"\breflejos\b",
            r"\bcielo\b",
            r"\bsky\b",
            r"\bzonas claras\b",
            r"\bbright areas\b",
        ),
        -1,
    ),  # fmt: skip
    "shadows": (
        (
            r"\bsombras?\b",
            r"\bshadow",
            r"\bzonas oscuras\b",
            r"\bdark areas\b",
            r"\bcontraluz\b",
            r"\bbacklit\b",
            r"\bbacklight",
        ),
        1,
    ),  # fmt: skip
    "luces_y_sombras": ((r"\bluces_y_sombras\b",), 1),
    "whites": (
        (
            r"\bblancos\b",
            r"\bwhites\b",
            r"\bpunto blanco\b",
            r"\bwhite point\b",
            r"\bfondo (bien |mas |muy |)blanco\b",
            r"\bwhiter? background\b",
            r"\bpure white\b",
            r"\bwhite background\b",
        ),
        1,
    ),  # fmt: skip
    "blacks": ((r"\bnegros\b", r"\bblacks\b", r"\bpunto negro\b", r"\bblack point\b"), 1),
    "warm": (
        (
            r"\bcalid",
            r"\bwarm",
            r"\bcalor\b",
            r"\batardecer\b",
            r"\bsunset\b",
            r"\bgolden\b",
            r"\bdorad",
            r"\bmas naranja\b",
        ),
        1,
    ),  # fmt: skip
    "cool": (
        (
            r"\bfri[oa]\b",
            r"\bfrio\b",
            r"\bcool",
            r"\bcold",
            r"\bazulad",
            r"\bmas azul\b",
            r"\bbluer\b",
            r"\bhelad",
        ),
        1,
    ),  # fmt: skip
    "yellow_cast": (
        (r"\bamarill", r"\byellow", r"\bnaranj", r"\borange\b", r"\btungsten", r"\bincandesc"),
        1,
    ),  # fmt: skip
    "blue_cast": (
        (
            r"\bdemasiado azul\b",
            r"\bmuy azul\b",
            r"\btoo blue\b",
            r"\bblue cast\b",
            r"\bblueish\b",
            r"\bbluish\b",
            r"\bdominante azul\b",
        ),
        1,
    ),  # fmt: skip
    "green_cast": (
        (r"\bverdos", r"\bgreen(ish)? (tint|cast)\b", r"\btoo green\b", r"\bdominante verde\b"),
        1,
    ),  # fmt: skip
    "magenta_cast": ((r"\bmagenta\b", r"\brosad", r"\bpinkish\b", r"\btoo pink\b"), 1),
    "fix_color": (
        (
            r"\bbalance de blancos\b",
            r"\bwhite balance\b",
            r"\bwb\b",
            r"\bcorreg\w* (el )?color",
            r"\bfix (the )?colou?rs?\b",
            r"\bcolor correct",
            r"\bcolores (raros|reales|naturales)\b",
            r"\bnatural colou?rs?\b",
            r"\btono raro\b",
            r"\bdominante\b",
            r"\bcolor cast\b",
        ),
        1,
    ),  # fmt: skip
    "saturation": (
        (
            r"\bsatur",
            r"\bcolores? mas vivos?\b",
            r"\bvivid",
            r"\bcolorid",
            r"\bcolorful\b",
            r"\bmas color\b",
            r"\bmore colou?r\b",
            r"\bcolores?\b",
            r"\bcolou?rs?\b",
        ),
        1,
    ),  # fmt: skip
    "desaturate": (
        (
            r"\bdesatur",
            r"\bapagad",
            r"\bmuted\b",
            r"\bpastel\b",
            r"\bmenos color\b",
            r"\bless colou?r\b",
        ),
        1,
    ),  # fmt: skip
    "vibrance": ((r"\bvibran", r"\bvida\b", r"\bvibrant\b"), 1),
    "bw": (
        (
            r"\bblanco_y_negro\b",
            r"\bblack_and_white\b",
            r"\bmonocrom",
            r"\bmonochrom",
            r"\bgrayscale\b",
            r"\bgreyscale\b",
            r"\bescala de grises\b",
            r"\bbyn\b",
            r"\bbn\b",
        ),
        1,
    ),  # fmt: skip
    "sharpen": (
        (
            r"\bnitid",
            r"\benfoc",
            r"\bsharp",
            r"\bcrisp",
            r"\bdefinid",
            r"\bdefinicion",
            r"\bdetalle",
            r"\bdetail",
            r"\bclarity\b",
            r"\bborros",
            r"\bblurry\b",
            r"\bdesenfocad",
            r"\bsoft focus\b",
        ),
        1,
    ),  # fmt: skip
    "denoise": (
        (
            r"\bruido",
            r"\bgrano\b",
            r"\bgranulad",
            r"\bnois",
            r"\bgrain",
            r"\bgrainy\b",
            r"\bpixelad",
            r"\bmanchitas\b",
        ),
        1,
    ),  # fmt: skip
    "vignette": (
        (
            r"\bvinet",
            r"\bvign?ett?",  # vignette, vignete (typo)
            r"\b(esquinas|bordes|corners|edges) (quedaron|quedan|estan|se ven|are|look)\w* "
            r"(oscur|dark)",
            r"\bbordes? oscur",
            r"\bdark(en)? (the )?(edges|"
            r"corners)",
            r"\boscurec\w* (los )?(bordes|esquinas)",
            r"\bcorners? darker",
        ),
        -1,
    ),  # fmt: skip
    "auto": (
        (
            r"\bmejor",
            r"\bimprov",
            r"\benhanc",
            r"\barregl",
            r"\bfix\b",
            r"\bautomatic",
            r"\bauto\b",
            r"\boptimiz",
            r"\bretoque general\b",
            r"\bmas linda\b",
            r"\bprettier\b",
            r"\blook better\b",
            r"\bnicer\b",
            r"\bpro\b",
            r"\bprofesional\b",
            r"\bprofessional\b",
        ),
        1,
    ),  # fmt: skip
    "vintage": (
        (
            r"\bvintage\b",
            r"\bretro\b",
            r"\bantigu",
            r"\bnostalg",
            r"\bold ?school\b",
            r"\banos 70\b",
            r"\b70s\b",
            r"\bsetentas\b",
        ),
        1,
    ),  # fmt: skip
    "film": (
        (
            r"\bpelicula\b",
            r"\bfilm\b",
            r"\banalog",
            r"\bkodak\b",
            r"\bfuji\b",
            r"\bcinemat",
            r"\bcine\b",
        ),
        1,
    ),  # fmt: skip
    "dramatic": (
        (r"\bdramat", r"\bmoody\b", r"\bepic", r"\bintensa\b", r"\bdark mood\b", r"\bmisterios"),
        1,
    ),  # fmt: skip
    "hdr": ((r"\bhdr\b",), 1),
    "sepia": ((r"\bsepia\b",), 1),
    "soft": ((r"\bsoñad", r"\bdreamy\b", r"\betere", r"\bairy\b", r"\bluminosa y suave\b"), 1),
}

# Tema → ops que bloquea una negación ("no toques los colores").
BLOCKS = {
    "saturation": {"saturation", "vibrance", "white_balance", "auto_white_balance"},
    "fix_color": {"white_balance", "auto_white_balance"},
    "warm": {"white_balance"}, "cool": {"white_balance"},
    "bright": {"exposure", "auto_exposure"}, "dark": {"exposure", "auto_exposure"},
    "contrast": {"contrast"}, "highlights": {"highlights"}, "shadows": {"shadows"},
    "whites": {"whites"}, "blacks": {"blacks"}, "vibrance": {"vibrance"},
    "sharpen": {"sharpen"}, "denoise": {"denoise"}, "vignette": {"vignette"},
    "crop": {"crop"}, "resize": {"resize"}, "rotate": {"rotate", "straighten"},
    "bw": {"saturation"},
}  # fmt: skip

NOT_A_TOPIC_CONTEXT = {
    # "luz" en "luz natural" o "mas luz al cielo" es luz; pero "luces del restaurante" es causa
    "bright": (r"\bluces del\b", r"\bpor las luces\b", r"\blights in\b"),
    # "las esquinas quedaron oscuras" es viñeta del lente, no una foto oscura
    "dark": (r"\b(esquinas|bordes|corners|edges)\b",),
    # "ver detalle en la sombra / en el cielo" pide sombras o altas luces, no nitidez
    "sharpen": (
        r"\b(detalle|detail)s? (en|in) (la |las |el |los |the )?(sombra|shadow|cielo|sky|"
        r"luces|highlight|zonas)",
    ),
}

ASPECT_WORDS: list[tuple[tuple[str, ...], str]] = [
    ((r"\bcuadrad", r"\bsquare\b", r"\b1:1\b", r"\b1 ?x ?1\b"), "1:1"),
    (
        (
            r"\bstor(y|ies)\b",
            r"\bhistori",
            r"\breels?\b",
            r"\btiktok\b",
            r"\bshorts\b",
            r"\bestado de whatsapp\b",
            r"\bwhatsapp status\b",
            r"\b9:16\b",
        ),
        "9:16",
    ),  # fmt: skip
    (
        (
            r"\bfeed\b",
            r"\bpost de instagram\b",
            r"\binstagram post\b",
            r"\b4:5\b",
            r"\bvertical de instagram\b",
            r"\binstagram vertical\b",
        ),
        "4:5",
    ),  # fmt: skip
    (
        (
            r"\bpanoram",
            r"\bwidescreen\b",
            r"\byoutube\b",
            r"\bminiatura\b",
            r"\bthumbnail\b",
            r"\bbanner\b",
            r"\bportada\b",
            r"\bcover photo\b",
            r"\b16:9\b",
            r"\bpantalla ancha\b",
        ),
        "16:9",
    ),  # fmt: skip
]
CROP_WORDS = (r"\brecort", r"\bcrop", r"\bencuadr", r"\breencuadr", r"\bcort[aá]\b",
              r"\bcortala\b", r"\bframe\b", r"\btrim\b")  # fmt: skip
RATIO = re.compile(r"\b(\d{1,2})\s*[:/x]\s*(\d{1,2})\b")
SIZE = re.compile(r"\b(\d{3,5})\s*(?:px)?\s*[x]\s*(\d{3,5})\b")
SIDE = re.compile(
    r"\b(\d{3,5})\s*(?:px|pixeles|pixels)?\s*(?:de\s+)?(ancho|wide|width|alto|high|tall|height|"
    r"lado largo|long side|long edge)\b|\b(ancho|width|alto|height|lado largo|long side)\s*"
    r"(?:de\s+|of\s+|=\s*|:\s*)?(\d{3,5})(?:\s*(?:px|pixeles|pixels))?\b"
)
DEGREES = re.compile(r"(-?\d{1,3}(?:[.,]\d)?)\s*(?:°|º|grados?|degrees?|deg)\b")


# ------------------------------------------------------------------ análisis de cláusulas
def _add(draft: Draft, op: str, topic: str, **params) -> None:
    draft.intents.append(Intent(op, params, topic))


def _amount(base: float, sign: int, k: float, limit: float = 100) -> float:
    return max(-limit, min(limit, sign * base * k))


def _topics(clause: str) -> list[str]:
    found = []
    for name, (patterns, _) in TOPICS.items():
        if _has(clause, *patterns):
            if name in NOT_A_TOPIC_CONTEXT and _has(clause, *NOT_A_TOPIC_CONTEXT[name]):
                continue
            found.append(name)
    # temas más específicos tapan a los generales
    if "bw" in found:
        found = [t for t in found if t not in ("saturation", "desaturate")]
    if {"yellow_cast", "blue_cast", "green_cast", "magenta_cast"} & set(found):
        found = [t for t in found if t != "saturation"]
    if "desaturate" in found:
        found = [t for t in found if t != "saturation"]
    if "luces_y_sombras" in found:
        found = [t for t in found if t not in ("highlights", "shadows")]
    if "overexposed" in found:
        found = [t for t in found if t != "bright"]
    if "vibrance" in found and "saturation" in found and not _has(clause, r"\bsatur"):
        found.remove("saturation")
    return found


def _geometry(clause: str, draft: Draft, negated: bool) -> None:
    lang_crop = _has(clause, *CROP_WORDS)
    size = SIZE.search(clause)
    if size and not negated:
        w, h = int(size.group(1)), int(size.group(2))
        _add(draft, "resize", "resize", width=w, height=h, fit="cover")
    side = SIDE.search(clause)
    if side and not size and not negated:
        num = int(side.group(1) or side.group(4))
        which = side.group(2) or side.group(3)
        if which in ("ancho", "wide", "width"):
            _add(draft, "resize", "resize", width=num)
        elif which in ("alto", "high", "tall", "height"):
            _add(draft, "resize", "resize", height=num)
        else:
            _add(draft, "resize", "resize", width=num, height=num)
    elif (
        not size
        and not negated
        and _has(clause, RESIZE_WORDS)
        and not _has(clause, r"\b(peso|weight|liviana|lighter file|mb|kb)\b")
    ):
        draft.clarification = draft.clarification or "size"

    aspect = None
    ratio = RATIO.search(clause)
    if ratio and not size:
        key = f"{int(ratio.group(1))}:{int(ratio.group(2))}"
        if key in ("1:1", "4:5", "5:4", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16"):
            aspect = key
    if aspect is None:
        for patterns, value in ASPECT_WORDS:
            if _has(clause, *patterns):
                aspect = value
                break
    if aspect is None and _has(clause, r"\binstagram\b", r"\binsta\b", r"\big\b"):
        aspect = "4:5"
    if aspect is None and _has(clause, r"\bvertical\b") and lang_crop:
        aspect = "4:5"
    if aspect is None and _has(clause, r"\bhorizontal\b") and lang_crop:
        aspect = "3:2"
    if negated:
        if lang_crop or aspect:
            draft.blocked.add("crop")
        return
    if aspect:
        anchor = "center" if _has(clause, r"\bcentr") else "subject_or_center"
        for word, anc in (("arriba", "top"), ("top", "top"), ("abajo", "bottom"),
                          ("bottom", "bottom")):  # fmt: skip
            if re.search(rf"\b{word}\b", clause):
                anchor = anc
        _add(draft, "crop", "crop", aspect_ratio=aspect, anchor=anchor)
    elif lang_crop:
        draft.clarification = draft.clarification or "crop"

    deg = DEGREES.search(clause)
    degrees = float(deg.group(1).replace(",", ".")) if deg else None
    if _has(clause, r"\benderez", r"\bstraighten", r"\btorcid", r"\bcrooked\b", r"\btilt",
            r"\binclinad", r"\bhorizonte\b", r"\bhorizon\b", r"\blevel\b", r"\bnivel"):  # fmt: skip
        if degrees is not None and abs(degrees) <= 45:
            sign = -1 if _has(clause, r"\bizquierda\b", r"\bleft\b", r"\bantihorari",
                              r"\bcounter") else 1  # fmt: skip
            _add(draft, "straighten", "rotate", degrees=sign * abs(degrees))
        else:
            draft.clarification = draft.clarification or "straighten"
    elif _has(clause, r"\brot[aáe]", r"\bgir[aáe]", r"\bturn\b", *UPSIDE_DOWN):
        if _has(clause, r"\b180\b", *UPSIDE_DOWN):
            value = 180.0
        else:
            value = abs(degrees) if degrees is not None else 90.0
        if _has(clause, r"\bizquierda\b", r"\bleft\b", r"\bantihorari", r"\bcounter"):
            value = -value
        if value in (180.0, -180.0) or abs(value) <= 180:
            _add(draft, "rotate", "rotate", degrees=value)


def _export(clause: str, draft: Draft, negated: bool) -> None:
    exp = draft.export
    if _has(clause, r"\b(gps|ubicacion|location|geoloc|coordenadas|privacidad|privacy)\b") and (
        negated or _has(clause, r"\b(sac|quit|borr|elimin|remov|strip|delet|hide|ocult)")
    ):
        exp["metadata"] = "strip_gps"
    if _has(clause, r"\b(metadatos|metadata|exif)\b") and (
        negated or _has(clause, r"\b(sac|quit|borr|elimin|remov|strip|delet|limpi|clean)")
    ):
        exp["metadata"] = "strip"
    if negated:
        # solo vale lo de antes de la negación ("export as png without location")
        clause = clause[: re.search("|".join(NEGATION), clause).start()]
    for fmt, patterns in (("png", (r"\bpng\b",)), ("webp", (r"\bwebp\b",)),
                          ("jpeg", (r"\bjpe?g\b",)), ("tiff", (r"\btiff?\b",))):  # fmt: skip
        if _has(clause, *patterns):
            exp["format"] = fmt
    q = re.search(r"\b(?:calidad|quality|q)\s*(?:de\s+|of\s+|=\s*|:\s*)?(\d{1,3})\b", clause)
    if q and 1 <= int(q.group(1)) <= 100:
        exp["quality"] = int(q.group(1))
    if _has(clause, r"\bpara (la )?web\b", r"\bfor (the )?web\b", r"\bweb\b",
            r"\bpagina\b", r"\bwebsite\b", r"\bblog\b"):  # fmt: skip
        exp.setdefault("preset", "web")
    square = any(i.op == "crop" and i.params.get("aspect_ratio") == "1:1" for i in draft.intents)
    if square and _has(clause, r"\bcatalogo\b", r"\bcatalog\b", r"\btienda\b", r"\bshop\b",
                       r"\becommerce\b", r"\bmercado ?libre\b", r"\bproduct"):  # fmt: skip
        exp.setdefault("preset", "catalog_square")
    if _has(clause, r"\bstor(y|ies)\b", r"\bhistori", r"\breels?\b", r"\btiktok\b"):
        exp.setdefault("preset", "story_9x16")
    elif _has(clause, r"\binstagram\b", r"\binsta\b", r"\bfeed\b"):
        exp.setdefault("preset", "social_vertical")
    if _has(clause, r"\b(maxima calidad|max(imum)? quality|alta calidad|high quality|"
            r"imprimir|print|impresion)\b"):  # fmt: skip
        exp.setdefault("preset", "high_quality")


def _tonal_and_color(clause: str, topics: list[str], draft: Draft, desc: dict) -> None:
    k = intensity(clause)
    d = direction(clause)
    sign = d or 1
    ev = desc.get("exposure_ev")
    for t in topics:
        if t == "bright":
            s = sign
            if d == 0 and _has(clause, r"\b(corregi|correct|fix|ajust|adjust)") and ev is not None:
                s = 1 if ev < 0 else -1
            if _has(clause, r"\bcorreg\w* (la )?exposicion\b", r"\bfix (the )?exposure\b",
                    r"\bexposicion correcta\b", r"\bproper exposure\b"):  # fmt: skip
                _add(draft, "auto_exposure", "bright", strength=1.0)
                continue
            _add(draft, "exposure", "bright", ev=round(_amount(BASE["exposure"], s, k, 2), 2))
        elif t == "dark":
            # "está oscura" (estado) → aclarar; "oscurecela"/"darker" (pedido) → oscurecer
            asks_darker = _has(clause, r"\boscurec", r"\bdarken\b", r"\bdarker\b",
                               r"\bmas oscur", r"\bmore dark")  # fmt: skip
            s = -1 if asks_darker else 1
            if d == -1 and not asks_darker:  # "menos oscura" → aclarar
                s = 1
            _add(draft, "exposure", "bright", ev=round(_amount(BASE["exposure"], s, k, 2), 2))
            if not asks_darker:
                _add(draft, "shadows", "shadows", amount=round(_amount(BASE["shadows"], 1, k)))
        elif t == "overexposed":
            _add(draft, "exposure", "bright", ev=round(_amount(BASE["exposure"], -1, k, 2), 2))
            _add(draft, "highlights", "highlights",
                 amount=round(_amount(BASE["highlights"], -1, k)))  # fmt: skip
        elif t == "contrast":
            _add(draft, "contrast", "contrast", amount=round(_amount(BASE["contrast"], sign, k)))
        elif t == "flat":
            # "está plana/lavada" (estado) → más contraste; "look matte/lavado" → menos
            wants_look = _has(clause, r"\blook\b", r"\befecto\b", r"\bestilo\b", r"\bdale\b",
                              r"\bmake it\b", r"\bhacela\b", r"\bponele\b")  # fmt: skip
            if wants_look or draft.look or d == 1 and _has(clause, r"\bmatte?\b", r"\bfaded\b"):
                _add(draft, "contrast", "contrast", amount=round(_amount(15, -1, k)))
                _add(draft, "blacks", "blacks", amount=round(_amount(25, 1, k)))
            else:
                _add(draft, "contrast", "contrast", amount=round(_amount(BASE["contrast"], 1, k)))
                _add(draft, "vibrance", "vibrance", amount=round(_amount(15, 1, k)))
        elif t == "highlights":
            # por defecto "recuperar" (bajar); "subí/más altas luces" → +
            s = 1 if d == 1 and not _has(clause, r"\brecuper", r"\brecover") else -1
            _add(draft, "highlights", "highlights", amount=round(_amount(BASE["highlights"], s, k)))
        elif t == "shadows":
            s = -1 if d == -1 or _has(clause, r"\bprofund", r"\bdeepen", r"\bmas oscuras\b",
                                         r"\bdarker shadows\b") else 1  # fmt: skip
            _add(draft, "shadows", "shadows", amount=round(_amount(BASE["shadows"], s, k)))
            if _has(clause, r"\bcontraluz\b", r"\bbacklit\b", r"\bbacklight"):
                _add(draft, "highlights", "highlights",
                     amount=round(_amount(BASE["highlights"], -1, k)))  # fmt: skip
        elif t == "luces_y_sombras":
            _add(
                draft, "highlights", "highlights", amount=round(_amount(BASE["highlights"], -1, k))
            )
            _add(draft, "shadows", "shadows", amount=round(_amount(BASE["shadows"], 1, k)))
        elif t == "whites":
            _add(draft, "whites", "whites", amount=round(_amount(BASE["whites"], sign, k)))
        elif t == "blacks":
            s = -1 if _has(clause, r"\bprofund", r"\bdeep", r"\bmas negros\b", r"\bricher\b",
                           r"\bmas intensos\b", r"\bhund", r"\baplast", r"\bcrush"
                           ) else sign  # fmt: skip
            _add(draft, "blacks", "blacks", amount=round(_amount(BASE["blacks"], s, k)))
        elif t in ("warm", "cool"):
            s = (1 if t == "warm" else -1) * (-1 if d == -1 else 1)
            _add(draft, "white_balance", "warm",
                 temperature_shift=round(_amount(BASE["temperature"], s, k)))  # fmt: skip
        elif t == "yellow_cast":
            if d == 1 and not _has(clause, r"\bdemasiad", r"\btoo\b", r"\bmuy\b"):
                _add(draft, "white_balance", "warm",
                     temperature_shift=round(_amount(BASE["temperature"], 1, k)))  # fmt: skip
            else:
                shift = round(_amount(BASE["temperature"], -1, max(k, 1.2)))
                _add(draft, "white_balance", "warm", temperature_shift=shift)
        elif t == "blue_cast":
            _add(draft, "white_balance", "warm",
                 temperature_shift=round(_amount(BASE["temperature"], 1, max(k, 1.2))))  # fmt: skip
        elif t == "green_cast":
            _add(draft, "white_balance", "warm", tint_shift=round(_amount(BASE["tint"], 1, k)))
        elif t == "magenta_cast":
            _add(draft, "white_balance", "warm", tint_shift=round(_amount(BASE["tint"], -1, k)))
        elif t == "fix_color":
            method = "white_patch" if _has(clause, r"\bblanc", r"\bwhite\b") else "gray_world"
            _add(draft, "auto_white_balance", "fix_color", method=method)
        elif t == "saturation":
            if d == 0 and not _has(clause, r"\bsatur", r"\bviv", r"\bcolorid", r"\bcolorful",
                                   r"\bmas color", r"\bmore colou?r"):  # fmt: skip
                continue  # "colores" sin pedir más ni menos: no es un pedido
            op = "saturation" if _has(clause, r"\bsatur") else "vibrance"
            _add(draft, op, "saturation", amount=round(_amount(BASE[op], sign, k)))
        elif t == "desaturate":
            # "los colores se ven apagados" describe un problema → más color;
            # "colores más apagados" / "desaturala" es el pedido → menos
            if _has(clause, STATE) and not _has(clause, r"\bdesatur", r"\bmas apagad"):
                _add(draft, "vibrance", "vibrance", amount=round(_amount(BASE["vibrance"], 1, k)))
            else:
                _add(draft, "saturation", "saturation", amount=round(_amount(30, -1, k)))
        elif t == "vibrance":
            _add(draft, "vibrance", "vibrance", amount=round(_amount(BASE["vibrance"], sign, k)))
        elif t == "bw":
            _add(draft, "saturation", "bw", amount=-100)
            _add(draft, "contrast", "contrast", amount=15)
        elif t == "sharpen":
            if _has(clause, r"\bsuaviz", r"\bsoften\b", r"\bmenos nitid", r"\bless sharp"):
                continue  # no hay op de suavizado global: lo cubre "soft"/contraste
            _add(draft, "sharpen", "sharpen",
                 amount=round(_amount(BASE["sharpen"], 1, k)), radius=1.0)  # fmt: skip
        elif t == "denoise":
            _add(draft, "denoise", "denoise", strength=round(_amount(BASE["denoise"], 1, k, 1), 2))
        elif t == "vignette":
            s = 1 if _has(clause, r"\bclar", r"\blight", r"\bbright", r"\bwhite") else -1
            # sacar la viñeta del lente / "las esquinas quedaron oscuras" → aclarar bordes
            if d == -1 or _has(clause, r"\bsac[aá]", r"\bquit", r"\bremove", r"\bcorreg",
                               r"\bfix\b", r"\belimin", r"\b(quedaron|quedan|estan|se ven|are|"
                               r"look)\w* (oscur|dark)"):  # fmt: skip
                s = 1
            if s:
                _add(draft, "vignette", "vignette", amount=round(_amount(BASE["vignette"], s, k)))
        elif t == "auto":
            if _has(clause, r"\bilumin", r"\bluz\b", r"\blight", r"\bexposicion\b",
                    r"\bexposure\b"):  # fmt: skip
                _add(draft, "auto_exposure", "bright", strength=1.0)
            elif _has(clause, r"\bcolor", r"\bcolour"):
                _add(draft, "auto_white_balance", "fix_color", method="gray_world")
            else:
                _add(draft, "auto_exposure", "bright", strength=1.0)
                _add(draft, "auto_white_balance", "fix_color", method="gray_world")
                _add(draft, "contrast", "contrast", amount=10)
                _add(draft, "vibrance", "vibrance", amount=15)
        elif t == "vintage":
            _add(draft, "white_balance", "warm", temperature_shift=round(_amount(30, 1, k)))
            _add(draft, "contrast", "contrast", amount=round(_amount(15, -1, k)))
            _add(draft, "saturation", "saturation", amount=round(_amount(20, -1, k)))
            _add(draft, "blacks", "blacks", amount=round(_amount(20, 1, k)))
            _add(draft, "vignette", "vignette", amount=round(_amount(30, -1, k)))
        elif t == "film":
            _add(draft, "blacks", "blacks", amount=round(_amount(25, 1, k)))
            _add(draft, "contrast", "contrast", amount=round(_amount(10, -1, k)))
            _add(draft, "saturation", "saturation", amount=round(_amount(15, -1, k)))
            _add(draft, "white_balance", "warm", temperature_shift=round(_amount(10, 1, k)))
        elif t == "dramatic":
            _add(draft, "contrast", "contrast", amount=round(_amount(35, 1, k)))
            _add(draft, "blacks", "blacks", amount=round(_amount(20, -1, k)))
            _add(draft, "highlights", "highlights", amount=round(_amount(25, -1, k)))
            _add(draft, "vignette", "vignette", amount=round(_amount(30, -1, k)))
        elif t == "hdr":
            _add(draft, "shadows", "shadows", amount=round(_amount(50, 1, k)))
            _add(draft, "highlights", "highlights", amount=round(_amount(50, -1, k)))
            _add(draft, "contrast", "contrast", amount=round(_amount(15, 1, k)))
            _add(draft, "vibrance", "vibrance", amount=round(_amount(25, 1, k)))
        elif t == "sepia":
            _add(draft, "saturation", "saturation", amount=round(_amount(70, -1, min(k, 1.3))))
            _add(draft, "white_balance", "warm", temperature_shift=round(_amount(45, 1, k)))
            _add(draft, "contrast", "contrast", amount=round(_amount(10, -1, k)))
        elif t == "soft":
            _add(draft, "contrast", "contrast", amount=round(_amount(20, -1, k)))
            _add(draft, "exposure", "bright", ev=round(_amount(0.3, 1, k, 2), 2))
            _add(draft, "highlights", "highlights", amount=round(_amount(15, 1, k)))


# ------------------------------------------------------------------ plan
ORDER = [
    "straighten", "rotate", "crop",
    "auto_exposure", "exposure", "auto_white_balance", "white_balance",
    "highlights", "shadows", "whites", "blacks", "contrast",
    "vibrance", "saturation", "denoise", "sharpen", "vignette", "resize",
]  # fmt: skip
SUMMABLE = {
    "exposure": ("ev", 2.0),
    "contrast": ("amount", 100), "highlights": ("amount", 100), "shadows": ("amount", 100),
    "whites": ("amount", 100), "blacks": ("amount", 100), "saturation": ("amount", 100),
    "vibrance": ("amount", 100), "vignette": ("amount", 100), "sharpen": ("amount", 100),
    "denoise": ("strength", 1.0),
}  # fmt: skip

DESCRIBE = {
    "es": {
        "auto_exposure": "ajusto la exposición automáticamente",
        "exposure": lambda p: (
            f"{'subo' if p['ev'] > 0 else 'bajo'} la exposición {abs(p['ev'])} EV"
        ),
        "auto_white_balance": "corrijo el balance de blancos automáticamente",
        "white_balance": lambda p: (
            "corrijo el color"
            if not p.get("temperature_shift")
            else f"la hago más {'cálida' if p['temperature_shift'] > 0 else 'fría'}"
        ),
        "contrast": lambda p: f"{'subo' if p['amount'] > 0 else 'bajo'} el contraste",
        "highlights": lambda p: (
            "recupero las altas luces" if p["amount"] < 0 else "subo las altas luces"
        ),
        "shadows": lambda p: f"{'abro' if p['amount'] > 0 else 'profundizo'} las sombras",
        "whites": lambda p: f"{'subo' if p['amount'] > 0 else 'bajo'} los blancos",
        "blacks": lambda p: f"{'levanto' if p['amount'] > 0 else 'profundizo'} los negros",
        "saturation": lambda p: (
            "la paso a blanco y negro"
            if p["amount"] <= -100
            else f"{'subo' if p['amount'] > 0 else 'bajo'} la saturación"
        ),
        "vibrance": lambda p: f"{'subo' if p['amount'] > 0 else 'bajo'} la intensidad del color",
        "sharpen": "aumento la nitidez",
        "denoise": "reduzco el ruido",
        "vignette": lambda p: f"{'oscurezco' if p['amount'] < 0 else 'aclaro'} los bordes",
        "crop": lambda p: f"recorto a {p['aspect_ratio']}",
        "rotate": lambda p: f"giro {p['degrees']:g}°",
        "straighten": lambda p: f"enderezo {p['degrees']:g}°",
        "resize": lambda p: (
            "cambio el tamaño a " + "×".join(str(p[k]) for k in ("width", "height") if p.get(k))
        ),
    },
    "en": {
        "auto_exposure": "auto-adjust the exposure",
        "exposure": lambda p: (
            f"{'raise' if p['ev'] > 0 else 'lower'} the exposure {abs(p['ev'])} EV"
        ),
        "auto_white_balance": "auto-correct the white balance",
        "white_balance": lambda p: (
            "correct the color"
            if not p.get("temperature_shift")
            else f"make it {'warmer' if p['temperature_shift'] > 0 else 'cooler'}"
        ),
        "contrast": lambda p: f"{'raise' if p['amount'] > 0 else 'lower'} the contrast",
        "highlights": lambda p: (
            "recover the highlights" if p["amount"] < 0 else "boost the highlights"
        ),
        "shadows": lambda p: f"{'open up' if p['amount'] > 0 else 'deepen'} the shadows",
        "whites": lambda p: f"{'raise' if p['amount'] > 0 else 'lower'} the whites",
        "blacks": lambda p: f"{'lift' if p['amount'] > 0 else 'deepen'} the blacks",
        "saturation": lambda p: (
            "convert it to black and white"
            if p["amount"] <= -100
            else f"{'raise' if p['amount'] > 0 else 'lower'} the saturation"
        ),
        "vibrance": lambda p: f"{'boost' if p['amount'] > 0 else 'reduce'} the vibrance",
        "sharpen": "sharpen it",
        "denoise": "reduce the noise",
        "vignette": lambda p: f"{'darken' if p['amount'] < 0 else 'lighten'} the edges",
        "crop": lambda p: f"crop to {p['aspect_ratio']}",
        "rotate": lambda p: f"rotate {p['degrees']:g}°",
        "straighten": lambda p: f"straighten {p['degrees']:g}°",
        "resize": lambda p: (
            "resize to " + "×".join(str(p[k]) for k in ("width", "height") if p.get(k))
        ),
    },
}
QUESTIONS = {
    "crop": {"es": "¿A qué proporción la recorto? (por ejemplo 1:1, 4:5, 16:9 o 9:16)",
             "en": "What aspect ratio should I crop to? (e.g. 1:1, 4:5, 16:9 or 9:16)"},
    "size": {"es": "¿A qué tamaño la llevo? (por ejemplo 1920 de ancho o 1080×1080)",
             "en": "What size should it be? (e.g. 1920 wide or 1080×1080)"},
    "straighten": {"es": "¿Cuántos grados está inclinada y hacia qué lado?",
                   "en": "How many degrees is it tilted, and which way?"},
    "nothing": {"es": "No entendí qué querés cambiar. ¿Querés ajustar la luz, el color, "
                      "recortarla o exportarla para algún uso?",
                "en": "I didn't understand what to change. Do you want to adjust light, "
                      "color, crop it or export it for something?"},
}  # fmt: skip


def _merge(intents: list[Intent], blocked_ops: set[str]) -> list[dict]:
    merged: dict[str, dict] = {}
    for it in intents:
        if it.op in blocked_ops:
            continue
        if it.op not in merged:
            merged[it.op] = {"op": it.op, **it.params}
            continue
        cur = merged[it.op]
        if it.op in SUMMABLE:
            key, limit = SUMMABLE[it.op]
            total = cur.get(key, 0) + it.params.get(key, 0)
            total = max(-limit, min(limit, total))
            cur[key] = round(total, 2) if isinstance(limit, float) else round(total)
        elif it.op == "white_balance":
            for key in ("temperature_shift", "tint_shift"):
                if key in it.params:
                    cur[key] = max(-100, min(100, cur.get(key, 0) + it.params[key]))
        else:
            cur.update(it.params)  # crop/resize/rotate: gana el último pedido
    if "exposure" in merged and "auto_exposure" in merged:
        del merged["auto_exposure"]  # pidió un sentido explícito: manda ese
    if (
        "white_balance" in merged
        and "auto_white_balance" in merged
        and merged["white_balance"].get("temperature_shift")
    ):
        del merged["auto_white_balance"]
    ops = []
    for name in ORDER:
        if name in merged:
            op = merged[name]
            if any(v == 0 for k, v in op.items() if k in ("ev", "amount", "strength")):
                continue
            ops.append(op)
    return ops


PROTECT_HIGHLIGHTS = re.compile(
    r"\b(sin|without|no|but not|pero sin)\s+(quemar|reventar|blow(ing)?( out)?|perder|"
    r"losing|lose|clip(ping)?)\b[^,]*"
)


def _protective(clause: str, draft: Draft) -> str:
    """ "sin quemar el cielo" / "without blowing out the sky" no niega: pide cuidar las altas
    luces. Se agrega esa intención y se saca la frase para que no bloquee el resto."""
    m = PROTECT_HIGHLIGHTS.search(clause)
    if not m:
        return clause
    _add(draft, "highlights", "highlights", amount=-25)
    return (clause[: m.start()] + clause[m.end() :]).strip()


def plan_from_rules(request: PlanRequest) -> dict:
    """El plan (dict) que proponen las reglas para un pedido."""
    text = normalize(request.prompt)
    lang = language(text)
    draft = Draft(look=_has(text, *LOOK_WORDS))

    for rule in UNSUPPORTED:
        if _has(text, *rule.patterns):
            item = {"request": rule.request[lang], "reason": rule.reason[lang]}
            if rule.alternative:
                item["alternative"] = rule.alternative[lang]
            draft.unsupported.append(item)

    for clause in clauses(text):
        clause = _protective(clause, draft)
        negated = _has(clause, *NEGATION)
        _geometry(clause, draft, negated)
        _export(clause, draft, negated)
        topics = _topics(clause)
        if negated:
            # "aclarala sin tocar los colores" / "no toques los colores, solo aclarala": lo
            # negado se bloquea; lo de antes de la negación y lo de después de "solo" se pide.
            neg = re.search("|".join(NEGATION), clause)
            before, rest = clause[: neg.start()], clause[neg.start() :]
            only = re.split(r"\bsolo\b|\bonly\b|\bjust\b|\bsino\b|\bbut\b", rest, maxsplit=1)
            for t in _topics(only[0]):
                draft.blocked.add(t)
            for part in (before, only[1] if len(only) == 2 else ""):
                if part.strip():
                    _tonal_and_color(part, _topics(part), draft, request.descriptors)
            continue
        _tonal_and_color(clause, topics, draft, request.descriptors)

    blocked_ops: set[str] = set()
    for t in draft.blocked:
        blocked_ops |= BLOCKS.get(t, {t})
    operations = _merge(draft.intents, blocked_ops)
    # Si todo lo pedido estaba fuera del catálogo, no se agregan ops "de relleno".
    plan: dict = {"operations": operations}
    if draft.unsupported:
        plan["unsupported"] = draft.unsupported
    export = {k: v for k, v in draft.export.items()}
    if export:
        plan["export"] = export

    if draft.clarification and not operations:
        plan["clarification"] = QUESTIONS[draft.clarification][lang]
    elif not operations and not draft.unsupported and not export:
        plan["clarification"] = QUESTIONS["nothing"][lang]
    elif draft.clarification and operations:
        # pidió algo concreto y algo ambiguo: hace lo concreto y pregunta lo otro
        plan["clarification"] = QUESTIONS[draft.clarification][lang]

    parts = []
    for op in operations:
        d = DESCRIBE[lang][op["op"]]
        parts.append(d(op) if callable(d) else d)
    if parts:
        text_out = ", ".join(parts)
        plan["explanation"] = text_out[0].upper() + text_out[1:] + "."
    return plan


class RulesProvider:
    name = "rules"

    def propose(self, request: PlanRequest, feedback: str | None = None) -> dict:
        return plan_from_rules(request)
