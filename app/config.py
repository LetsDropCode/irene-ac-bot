# app/config.py
from dotenv import load_dotenv
import logging
import os

load_dotenv()

logger = logging.getLogger(__name__)

VALID_ENVS = frozenset({"development", "test", "production"})
DEFAULT_ADMIN_NUMBERS: tuple[str, ...] = ()
DEFAULT_ATTENDANCE_REPORT_RECIPIENTS: tuple[str, ...] = ()


def _env_list(name: str, default: str = "", environ=None) -> tuple[str, ...]:
    environ = os.environ if environ is None else environ
    return tuple(
        item.strip()
        for item in environ.get(name, default).split(",")
        if item.strip()
    )

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET") or os.getenv("META_APP_SECRET")
# Kept for import-time compatibility. validate_configuration() requires an
# explicit ENV before a process can start.
ENV = os.getenv("ENV", "development").strip().lower()
PUBLIC_BASE_URL = (
    os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    or (f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}" if os.getenv("RAILWAY_PUBLIC_DOMAIN") else "")
)
JOB_RUNNER_TOKEN = os.getenv("JOB_RUNNER_TOKEN")
JOB_RUNNER_BATCH_SIZE = int(os.getenv("JOB_RUNNER_BATCH_SIZE", "10"))
ATTENDANCE_REPORT_RECIPIENTS = _env_list(
    "ATTENDANCE_REPORT_RECIPIENTS",
    ",".join(DEFAULT_ATTENDANCE_REPORT_RECIPIENTS),
)
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME") or os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL") or SMTP_USERNAME
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").strip().lower() not in {"0", "false", "no"}
WHATS_NEW_VERSION = os.getenv("WHATS_NEW_VERSION", "2026-06-shop-league-menu")
WHATS_NEW_MESSAGE = os.getenv(
    "WHATS_NEW_MESSAGE",
    (
        "✨ *What’s new at Irene AC TT*\n\n"
        "Your bot now does more than capture results:\n"
        "• View *My progress* for milestones, PBs and trends\n"
        "• Open *The Irene Shop* and *Irene League Standings* from the menu\n"
        "• Check your *profile* and update your details\n"
        "• See runner results and walker activity on the leaderboard\n\n"
        "Send *HELP* anytime to explore the menu."
    ),
)

ADMIN_NUMBERS = frozenset(
    _env_list(
        "ADMIN_NUMBERS",
        ",".join(DEFAULT_ADMIN_NUMBERS),
    )
)


def is_deployed_environment(environ=None) -> bool:
    """Identify hosted runtimes without treating the local test DB as hosted."""
    environ = os.environ if environ is None else environ
    database_url = environ.get("DATABASE_URL", "")
    if database_url.rstrip("/").endswith("/test"):
        return False
    return any(
        environ.get(name)
        for name in ("RAILWAY_ENVIRONMENT", "RAILWAY_PUBLIC_DOMAIN", "RENDER_SERVICE_ID")
    )


def validate_configuration(environ=None) -> None:
    """Fail closed for production and hosted non-test processes.

    Secrets are named in validation errors but never included by value.
    """
    environ = os.environ if environ is None else environ
    env = (environ.get("ENV") or "").strip().lower()
    if env not in VALID_ENVS:
        raise RuntimeError("ENV must be explicitly set to development, test, or production")

    deployed = is_deployed_environment(environ)
    strict = env == "production" or (deployed and env != "test")
    if not strict:
        return

    app_secret = environ.get("WHATSAPP_APP_SECRET") or environ.get("META_APP_SECRET")
    required = {
        "WHATSAPP_APP_SECRET or META_APP_SECRET": app_secret,
        "WHATSAPP_TOKEN": environ.get("WHATSAPP_TOKEN"),
        "PHONE_NUMBER_ID": environ.get("PHONE_NUMBER_ID"),
        "VERIFY_TOKEN": environ.get("VERIFY_TOKEN"),
        "JOB_RUNNER_TOKEN": environ.get("JOB_RUNNER_TOKEN"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError("Missing required secure configuration: " + ", ".join(missing))

    if not _env_list("ADMIN_NUMBERS", environ=environ):
        message = "ADMIN_NUMBERS is empty; no administrator can use protected admin operations"
        if env == "production":
            raise RuntimeError(message)
        logger.warning(message)
