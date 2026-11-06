"""Registr nastavení: jediné místo, kde se definují volby aplikace.

DB (tabulka ``settings``) drží jen hodnoty. Typ, výchozí hodnota, popis, validace a skupina
žijí tady – UI nastavení se z registru generuje samo. Nová funkce = nový záznam, žádná migrace.
Nastavení s ``scope="user"`` může mít každý uživatel vlastní hodnotu (přepisuje globální).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SettingType = Literal["string", "text", "int", "float", "bool", "enum", "string_list", "secret"]
Scope = Literal["global", "user"]


@dataclass(frozen=True)
class SettingDef:
    key: str
    type: SettingType
    default: Any
    group: str
    label: str
    description: str = ""
    scope: Scope = "global"  # "user" = lze přepsat per uživatel
    choices: tuple[str, ...] = ()
    min: float | None = None
    max: float | None = None
    restart_required: bool = False
    admin_only: bool = True  # měnit globální hodnotu smí jen admin
    tags: tuple[str, ...] = field(default=())

    @property
    def is_secret(self) -> bool:
        return self.type == "secret"


def _d(*defs: SettingDef) -> dict[str, SettingDef]:
    return {d.key: d for d in defs}


GROUPS: dict[str, str] = {
    "general": "Obecné",
    "ui": "Vzhled a ovládání",
    "items": "Věci a umístění",
    "photos": "Fotografie",
    "search": "Vyhledávání",
    "ai": "AI asistent",
    "voice": "Hlas (STT / TTS)",
    "labels": "Štítky a tisk",
    "notifications": "Upozornění",
    "export": "Import a export",
    "mqtt": "MQTT",
    "api": "API a integrace",
    "backup": "Zálohy",
    "security": "Zabezpečení",
}

REGISTRY: dict[str, SettingDef] = _d(
    # --- Obecné
    SettingDef("general.household_name", "string", "Domov", "general", "Název domácnosti"),
    SettingDef(
        "general.language",
        "enum",
        "cs",
        "general",
        "Jazyk",
        choices=("cs", "en"),
        scope="user",
        admin_only=False,
    ),
    SettingDef(
        "general.timezone",
        "string",
        "Europe/Prague",
        "general",
        "Časová zóna",
        scope="user",
        admin_only=False,
    ),
    SettingDef("general.currency", "string", "CZK", "general", "Výchozí měna"),
    SettingDef(
        "general.date_format",
        "enum",
        "d. M. yyyy",
        "general",
        "Formát data",
        choices=("d. M. yyyy", "yyyy-MM-dd", "dd/MM/yyyy"),
        scope="user",
        admin_only=False,
    ),
    # --- UI
    SettingDef(
        "ui.theme",
        "enum",
        "auto",
        "ui",
        "Motiv",
        choices=("auto", "light", "dark"),
        scope="user",
        admin_only=False,
    ),
    SettingDef(
        "ui.density",
        "enum",
        "comfortable",
        "ui",
        "Hustota rozhraní",
        choices=("comfortable", "compact"),
        scope="user",
        admin_only=False,
    ),
    SettingDef(
        "ui.default_view",
        "enum",
        "table",
        "ui",
        "Výchozí pohled na věci",
        choices=("table", "cards"),
        scope="user",
        admin_only=False,
    ),
    SettingDef(
        "ui.page_size",
        "int",
        50,
        "ui",
        "Počet řádků na stránku",
        scope="user",
        min=10,
        max=500,
        admin_only=False,
    ),
    SettingDef(
        "ui.large_buttons",
        "bool",
        False,
        "ui",
        "Velká tlačítka (pro práci v rukavicích)",
        scope="user",
        admin_only=False,
    ),
    # --- Věci
    SettingDef("items.require_category", "bool", False, "items", "Vyžadovat kategorii u věci"),
    SettingDef(
        "items.require_location",
        "bool",
        False,
        "items",
        "Vyžadovat umístění u věci",
        description="Vypnuto = věc smí být „nezařazená“.",
    ),
    SettingDef("items.default_unit", "string", "ks", "items", "Výchozí jednotka"),
    SettingDef(
        "items.trash_retention_days",
        "int",
        90,
        "items",
        "Doba uchování v koši (dny)",
        min=0,
        max=3650,
    ),
    SettingDef(
        "items.duplicate_policy",
        "enum",
        "warn",
        "items",
        "Politika duplicit",
        choices=("allow", "warn", "block"),
        description="Co dělat při vytvoření věci s velmi podobným názvem.",
    ),
    SettingDef(
        "items.show_prices",
        "bool",
        True,
        "items",
        "Zobrazovat ceny a hodnoty",
        scope="user",
        admin_only=False,
    ),
    # --- Fotky
    SettingDef(
        "photos.max_dimension", "int", 2048, "photos", "Maximální rozměr (px)", min=512, max=8192
    ),
    SettingDef("photos.jpeg_quality", "int", 85, "photos", "Kvalita (1–100)", min=40, max=100),
    SettingDef("photos.keep_original", "bool", False, "photos", "Ukládat i originál"),
    SettingDef("photos.strip_gps", "bool", True, "photos", "Odstranit GPS z EXIF"),
    SettingDef(
        "photos.max_upload_mb",
        "int",
        25,
        "photos",
        "Maximální velikost nahrání (MB)",
        min=1,
        max=200,
    ),
    SettingDef(
        "photos.max_batch_files",
        "int",
        50,
        "photos",
        "Maximum souborů v jednom hromadném nahrání",
        min=1,
        max=500,
    ),
    SettingDef(
        "photos.max_megapixels",
        "int",
        64,
        "photos",
        "Maximální velikost obrázku (megapixely)",
        description="Ochrana proti „decompression bomb“: větší obrázky se odmítnou před dekódováním.",
        min=1,
        max=500,
    ),
    SettingDef(
        "photos.auto_analyze", "bool", False, "photos", "Po nahrání automaticky analyzovat AI"
    ),
    # --- Vyhledávání
    SettingDef(
        "search.fuzzy_threshold",
        "float",
        0.3,
        "search",
        "Práh podobnosti (překlepy)",
        min=0.05,
        max=0.95,
    ),
    SettingDef(
        "search.semantic_enabled", "bool", True, "search", "Sémantické hledání (embeddings)"
    ),
    SettingDef("search.max_results", "int", 50, "search", "Maximum výsledků", min=5, max=500),
    # --- AI
    SettingDef("ai.enabled", "bool", True, "ai", "AI asistent zapnut"),
    SettingDef(
        "ai.cloud_allowed",
        "bool",
        True,
        "ai",
        "Povolit odesílání do cloudu",
        description="Vypnuto = použijí se jen lokální providery.",
    ),
    SettingDef(
        "ai.provider_chat",
        "enum",
        "gemini",
        "ai",
        "Provider pro chat",
        choices=("gemini", "anthropic", "openai_compat", "ollama"),
    ),
    SettingDef(
        "ai.provider_vision",
        "enum",
        "gemini",
        "ai",
        "Provider pro čtení fotek",
        choices=("gemini", "anthropic", "openai_compat", "ollama"),
    ),
    SettingDef(
        "ai.provider_fallback",
        "enum",
        "none",
        "ai",
        "Záložní provider",
        choices=("none", "gemini", "anthropic", "openai_compat", "ollama"),
    ),
    SettingDef(
        "ai.model_chat",
        "string",
        "gemini-2.5-flash",
        "ai",
        "Model pro chat",
        description="Názvy modelů se mění – ověř v dokumentaci poskytovatele.",
    ),
    SettingDef("ai.model_vision", "string", "gemini-2.5-flash", "ai", "Model pro čtení fotek"),
    SettingDef("ai.model_embeddings", "string", "", "ai", "Model pro embeddings"),
    SettingDef("ai.gemini_api_key", "secret", "", "ai", "Gemini API klíč"),
    SettingDef("ai.anthropic_api_key", "secret", "", "ai", "Anthropic API klíč"),
    SettingDef("ai.openai_base_url", "string", "", "ai", "OpenAI-kompatibilní URL (např. Ollama)"),
    SettingDef("ai.openai_api_key", "secret", "", "ai", "OpenAI-kompatibilní API klíč"),
    SettingDef(
        "ai.trust_level",
        "enum",
        "ask",
        "ai",
        "Důvěra v AI změny",
        choices=("ask", "auto_small", "auto_all"),
        description="ask = vždy potvrdit; auto_small = drobnosti automaticky; auto_all = vše s možností vrátit.",
    ),
    SettingDef(
        "ai.bulk_threshold",
        "int",
        5,
        "ai",
        "Počet operací, od kterého je potvrzení povinné",
        min=1,
        max=100,
    ),
    SettingDef(
        "ai.system_prompt_extra",
        "text",
        "",
        "ai",
        "Vlastní pravidla domácnosti",
        description="Např. „Kabely patří do krabice Elektro.“",
    ),
    SettingDef(
        "ai.max_requests_per_minute",
        "int",
        10,
        "ai",
        "Limit požadavků za minutu (free tier)",
        min=1,
        max=600,
    ),
    SettingDef(
        "ai.max_requests_per_day", "int", 200, "ai", "Limit požadavků za den", min=1, max=100000
    ),
    SettingDef(
        "ai.monthly_budget_usd",
        "float",
        0.0,
        "ai",
        "Měsíční rozpočet (USD, 0 = bez placených volání)",
        min=0,
    ),
    SettingDef("ai.temperature", "float", 0.2, "ai", "Teplota", min=0, max=2),
    SettingDef("ai.history_days", "int", 90, "ai", "Uchování konverzací (dny)", min=0, max=3650),
    # --- Hlas
    SettingDef(
        "voice.stt_engine",
        "enum",
        "browser",
        "voice",
        "Engine pro rozpoznávání řeči",
        choices=("off", "browser", "faster_whisper", "cloud"),
        scope="user",
        admin_only=False,
    ),
    SettingDef("voice.stt_model", "string", "medium", "voice", "Model Whisper"),
    SettingDef(
        "voice.tts_engine",
        "enum",
        "browser",
        "voice",
        "Engine pro syntézu řeči",
        choices=("off", "browser", "piper", "cloud"),
        scope="user",
        admin_only=False,
    ),
    SettingDef(
        "voice.tts_voice",
        "string",
        "cs_CZ-jirka-medium",
        "voice",
        "Hlas",
        scope="user",
        admin_only=False,
    ),
    SettingDef(
        "voice.tts_speed",
        "float",
        1.0,
        "voice",
        "Rychlost řeči",
        scope="user",
        min=0.5,
        max=2.0,
        admin_only=False,
    ),
    SettingDef(
        "voice.speak_replies",
        "enum",
        "after_voice",
        "voice",
        "Kdy mluvit odpovědi",
        choices=("never", "after_voice", "always"),
        scope="user",
        admin_only=False,
    ),
    SettingDef("voice.vocabulary", "text", "", "voice", "Slovník domácnosti (pomáhá rozpoznávání)"),
    # --- Štítky
    SettingDef(
        "labels.code_style", "enum", "qr", "labels", "Typ kódu na štítku", choices=("qr", "code128")
    ),
    SettingDef(
        "labels.page_format",
        "enum",
        "A4_3x8",
        "labels",
        "Formát archu",
        choices=("A4_3x8", "A4_2x5", "A4_4x12"),
    ),
    SettingDef("labels.show_path", "bool", True, "labels", "Tisknout cestu umístění"),
    # --- Upozornění
    SettingDef(
        "notifications.warranty_days",
        "int",
        30,
        "notifications",
        "Upozornit na konec záruky (dní předem)",
        min=0,
        max=365,
    ),
    SettingDef(
        "notifications.expiry_days",
        "int",
        14,
        "notifications",
        "Upozornit na expiraci (dní předem)",
        min=0,
        max=365,
    ),
    SettingDef(
        "notifications.low_stock", "bool", True, "notifications", "Upozorňovat na nízkou zásobu"
    ),
    SettingDef("notifications.smtp_host", "string", "", "notifications", "SMTP server"),
    SettingDef(
        "notifications.smtp_port", "int", 587, "notifications", "SMTP port", min=1, max=65535
    ),
    SettingDef("notifications.smtp_user", "string", "", "notifications", "SMTP uživatel"),
    SettingDef("notifications.smtp_password", "secret", "", "notifications", "SMTP heslo"),
    # --- Export
    SettingDef(
        "export.csv_delimiter", "enum", ";", "export", "Oddělovač CSV", choices=(";", ",", "\t")
    ),
    SettingDef("export.csv_bom", "bool", True, "export", "UTF-8 s BOM (pro Excel)"),
    SettingDef("export.decimal_comma", "bool", True, "export", "Desetinná čárka"),
    # --- MQTT (zatím vypnuto – viz docs/00-rozhodnuti.md)
    SettingDef("mqtt.enabled", "bool", False, "mqtt", "MQTT zapnuto", restart_required=True),
    SettingDef("mqtt.host", "string", "", "mqtt", "Broker – adresa", restart_required=True),
    SettingDef(
        "mqtt.port", "int", 1883, "mqtt", "Broker – port", min=1, max=65535, restart_required=True
    ),
    SettingDef("mqtt.tls", "bool", False, "mqtt", "Použít TLS", restart_required=True),
    SettingDef("mqtt.username", "string", "", "mqtt", "Uživatel", restart_required=True),
    SettingDef("mqtt.password", "secret", "", "mqtt", "Heslo", restart_required=True),
    SettingDef("mqtt.prefix", "string", "domovnik", "mqtt", "Prefix topiců", restart_required=True),
    SettingDef("mqtt.retain_state", "bool", True, "mqtt", "Retained stavy"),
    SettingDef("mqtt.ha_discovery", "bool", True, "mqtt", "Home Assistant Discovery"),
    SettingDef("mqtt.accept_commands", "bool", False, "mqtt", "Přijímat příkazy přes MQTT"),
    # --- API
    SettingDef(
        "api.cors_origins", "string_list", [], "api", "Povolené CORS originy", restart_required=True
    ),
    SettingDef(
        "api.rate_limit_per_minute",
        "int",
        600,
        "api",
        "Rate limit (požadavků/min/token)",
        min=10,
        max=100000,
    ),
    SettingDef("api.mcp_enabled", "bool", False, "api", "MCP server zapnut"),
    SettingDef("api.webhooks_enabled", "bool", False, "api", "Webhooky zapnuty"),
    # --- Zálohy
    SettingDef("backup.enabled", "bool", True, "backup", "Aplikační zálohy (pg_dump)"),
    SettingDef("backup.schedule_cron", "string", "30 3 * * *", "backup", "Plán (cron)"),
    SettingDef(
        "backup.retention_days", "int", 14, "backup", "Uchovávat záloh (dny)", min=1, max=3650
    ),
    # --- Zabezpečení
    SettingDef(
        "security.session_hours",
        "int",
        720,
        "security",
        "Platnost přihlášení (hodiny)",
        min=1,
        max=8760,
    ),
    SettingDef(
        "security.min_password_length",
        "int",
        10,
        "security",
        "Minimální délka hesla",
        min=8,
        max=128,
    ),
    SettingDef(
        "security.allow_setup",
        "bool",
        True,
        "security",
        "Povolit úvodní nastavení, dokud neexistuje uživatel",
    ),
)
