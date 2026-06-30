"""
Tablas de equivalencias para normalización de datos del mercado vehicular.
Estas tablas mapean valores crudos comunes a valores estandarizados.
"""

# ─── MARCAS ──────────────────────────────────────────────────────────────────

BRAND_MAP = {
    # Toyota
    "toyota": "Toyota",
    "toyot": "Toyota",
    # Hyundai
    "hyundai": "Hyundai",
    "hundai": "Hyundai",
    "hiunday": "Hyundai",
    # Nissan
    "nissan": "Nissan",
    "nisan": "Nissan",
    # Honda
    "honda": "Honda",
    # Suzuki
    "suzuki": "Suzuki",
    "susuki": "Suzuki",
    # Mitsubishi
    "mitsubishi": "Mitsubishi",
    "mitsibushi": "Mitsubishi",
    "mitsubishi motors": "Mitsubishi",
    # Kia
    "kia": "Kia",
    "kia motors": "Kia",
    # Chevrolet
    "chevrolet": "Chevrolet",
    "chevy": "Chevrolet",
    "chev": "Chevrolet",
    # Ford
    "ford": "Ford",
    # Mazda
    "mazda": "Mazda",
    # BMW
    "bmw": "BMW",
    # Mercedes
    "mercedes-benz": "Mercedes-Benz",
    "mercedes benz": "Mercedes-Benz",
    "mercedes": "Mercedes-Benz",
    "mb": "Mercedes-Benz",
    # Volkswagen
    "volkswagen": "Volkswagen",
    "vw": "Volkswagen",
    "volks": "Volkswagen",
    # Subaru
    "subaru": "Subaru",
    # Jeep
    "jeep": "Jeep",
    # Dodge
    "dodge": "Dodge",
    # Ram
    "ram": "Ram",
    # Audi
    "audi": "Audi",
    # Lexus
    "lexus": "Lexus",
    # Volvo
    "volvo": "Volvo",
    # Isuzu
    "isuzu": "Isuzu",
    # Land Rover
    "land rover": "Land Rover",
    "landrover": "Land Rover",
    # Porsche
    "porsche": "Porsche",
    # Renault
    "renault": "Renault",
    # Peugeot
    "peugeot": "Peugeot",
    # Chery
    "chery": "Chery",
    # JAC
    "jac": "JAC",
    "jac motors": "JAC",
    # BAIC
    "baic": "BAIC",
    # BYD
    "byd": "BYD",
    # MG
    "mg": "MG",
    "mg motors": "MG",
    # Geely
    "geely": "Geely",
    # GWM / Great Wall
    "gwm": "GWM",
    "great wall": "GWM",
    "great wall motors": "GWM",
}

# ─── MODELOS (patrones comunes que requieren normalización) ──────────────────

MODEL_NORMALIZATION = {
    # Toyota
    "rav4": "RAV4",
    "rav-4": "RAV4",
    "rav 4": "RAV4",
    "land cruiser": "Land Cruiser",
    "landcruiser": "Land Cruiser",
    "hilux": "Hilux",
    "hi lux": "Hilux",
    "prado": "Prado",
    "land cruiser prado": "Prado",
    "4runner": "4Runner",
    "4 runner": "4Runner",
    "fortuner": "Fortuner",
    "corolla": "Corolla",
    "camry": "Camry",
    "yaris": "Yaris",
    "rush": "Rush",
    "c-hr": "C-HR",
    "chr": "C-HR",
    # Hyundai
    "tucson": "Tucson",
    "santa fe": "Santa Fe",
    "santafe": "Santa Fe",
    "creta": "Creta",
    "accent": "Accent",
    "elantra": "Elantra",
    "venue": "Venue",
    "kona": "Kona",
    "palisade": "Palisade",
    # Nissan
    "x-trail": "X-Trail",
    "xtrail": "X-Trail",
    "x trail": "X-Trail",
    "frontier": "Frontier",
    "kicks": "Kicks",
    "qashqai": "Qashqai",
    "sentra": "Sentra",
    "versa": "Versa",
    "pathfinder": "Pathfinder",
    "navara": "Navara",
    # Honda
    "cr-v": "CR-V",
    "crv": "CR-V",
    "hr-v": "HR-V",
    "hrv": "HR-V",
    "civic": "Civic",
    "fit": "Fit",
    "city": "City",
    # Suzuki
    "vitara": "Vitara",
    "grand vitara": "Grand Vitara",
    "jimny": "Jimny",
    "swift": "Swift",
    "s-cross": "S-Cross",
    "scross": "S-Cross",
    # Mitsubishi
    "outlander": "Outlander",
    "l200": "L200",
    "montero": "Montero",
    "montero sport": "Montero Sport",
    "asx": "ASX",
    "eclipse cross": "Eclipse Cross",
}

# ─── COMBUSTIBLE ─────────────────────────────────────────────────────────────

FUEL_MAP = {
    "gasolina": "gasolina",
    "gas": "gasolina",
    "gasoline": "gasolina",
    "petrol": "gasolina",
    "nafta": "gasolina",
    "diesel": "diesel",
    "diésel": "diesel",
    "turbo diesel": "diesel",
    "electrico": "electrico",
    "eléctrico": "electrico",
    "electric": "electrico",
    "ev": "electrico",
    "hibrido": "hibrido",
    "híbrido": "hibrido",
    "hybrid": "hibrido",
    "plug-in hybrid": "hibrido",
    "phev": "hibrido",
    "gas lp": "gas_lp",
    "glp": "gas_lp",
    "lpg": "gas_lp",
}

# ─── TRANSMISIÓN ─────────────────────────────────────────────────────────────

TRANSMISSION_MAP = {
    "automatica": "automatica",
    "automática": "automatica",
    "automatic": "automatica",
    "auto": "automatica",
    "at": "automatica",
    "tiptronic": "automatica",
    "manual": "manual",
    "standard": "manual",
    "mt": "manual",
    "mecanica": "manual",
    "mecánica": "manual",
    "cvt": "cvt",
    "continuamente variable": "cvt",
}

# ─── TRACCIÓN ────────────────────────────────────────────────────────────────

DRIVETRAIN_MAP = {
    "4x4": "4wd",
    "4wd": "4wd",
    "four wheel drive": "4wd",
    "4 wheel drive": "4wd",
    "awd": "awd",
    "all wheel drive": "awd",
    "all-wheel drive": "awd",
    "traccion integral": "awd",
    "tracción integral": "awd",
    "2wd": "fwd",
    "2x4": "fwd",
    "fwd": "fwd",
    "front wheel drive": "fwd",
    "traccion delantera": "fwd",
    "tracción delantera": "fwd",
    "rwd": "rwd",
    "rear wheel drive": "rwd",
    "traccion trasera": "rwd",
    "tracción trasera": "rwd",
}

# ─── ESTILO DE CARROCERÍA ───────────────────────────────────────────────────

BODY_STYLE_MAP = {
    "sedan": "sedan",
    "sedán": "sedan",
    "suv": "suv",
    "sport utility": "suv",
    "todoterreno": "suv",
    "pickup": "pickup",
    "pick-up": "pickup",
    "pick up": "pickup",
    "camioneta": "pickup",
    "doble cabina": "pickup",
    "hatchback": "hatchback",
    "hatch": "hatchback",
    "5 puertas": "hatchback",
    "coupe": "coupe",
    "coupé": "coupe",
    "deportivo": "coupe",
    "convertible": "convertible",
    "cabriolet": "convertible",
    "van": "van",
    "minivan": "minivan",
    "mini van": "minivan",
    "wagon": "wagon",
    "station wagon": "wagon",
    "rural": "wagon",
    "crossover": "crossover",
}

# ─── TIPO DE VENDEDOR ───────────────────────────────────────────────────────

SELLER_TYPE_MAP = {
    "particular": "particular",
    "privado": "particular",
    "dueño": "particular",
    "owner": "particular",
    "agencia": "agencia",
    "dealer": "agencia",
    "concesionario": "agencia",
    "concesionaria": "agencia",
    "automotora": "agencia",
    "lote": "comercializador",
    "comercializador": "comercializador",
    "comercializadora": "comercializador",
    "revendedor": "comercializador",
    "intermediario": "comercializador",
}

# ─── COLORES ─────────────────────────────────────────────────────────────────

COLOR_MAP = {
    "blanco": "Blanco",
    "white": "Blanco",
    "blanco perla": "Blanco",
    "blanco perlado": "Blanco",
    "negro": "Negro",
    "black": "Negro",
    "gris": "Gris",
    "grey": "Gris",
    "gray": "Gris",
    "plata": "Plata",
    "silver": "Plata",
    "plateado": "Plata",
    "rojo": "Rojo",
    "red": "Rojo",
    "azul": "Azul",
    "blue": "Azul",
    "verde": "Verde",
    "green": "Verde",
    "café": "Café",
    "brown": "Café",
    "marron": "Café",
    "marrón": "Café",
    "beige": "Beige",
    "dorado": "Dorado",
    "gold": "Dorado",
    "amarillo": "Amarillo",
    "yellow": "Amarillo",
    "naranja": "Naranja",
    "orange": "Naranja",
    "vino": "Vino",
    "burgundy": "Vino",
    "celeste": "Celeste",
    "champagne": "Champagne",
}
