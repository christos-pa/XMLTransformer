import sys
import json
import zipfile
import shutil
import logging
import ssl
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime
import xml.etree.ElementTree as ET


# ==========================================================
# CONFIG LOADING (PyInstaller SAFE)
# ==========================================================

def get_tool_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


TOOL_DIR = get_tool_dir()
CONFIG_PATH = TOOL_DIR / "config.json"

if not CONFIG_PATH.exists():
    raise FileNotFoundError(f"config.json not found at: {CONFIG_PATH}")

CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

WATCH_DIR = Path(CONFIG["watch_dir"])
DONE_DIR_BASE = Path(CONFIG["done_dir"])
WORK_DIR_BASE = Path(CONFIG["work_dir"])
LOG_DIR_BASE = Path(CONFIG["log_dir"])

# Optional (recommended) so failures don’t get retried forever
FAILED_DIR_BASE = Path(CONFIG.get("failed_dir", str(WATCH_DIR / "failed")))

ZP = CONFIG["zatpark"]
BASE_URL = ZP["base_url"].rstrip("/")
HTTPS_AUTH = ZP["https_auth"]
SITE_CODE = ZP["site_code"]
ENFORCEMENT_TYPE = str(ZP["enforcement_type"])
TICKET_TYPE = ZP["ticket_type"]
BADGE_ID = ZP["badge_id"]
PRIMARY_CONTRAVENTION = str(ZP["primary_contravention"])

# SSL handling (you asked to disable verification)
DISABLE_SSL_VERIFY = bool(CONFIG.get("disable_ssl_verify", True))


# ==========================================================
# TIME-BASED FOLDER RESOLUTION (Year / Month)
# ==========================================================

def year_folder(base: Path) -> Path:
    return base / datetime.now().strftime("%Y")


def log_month_folder(base: Path) -> Path:
    dt = datetime.now()
    y = dt.strftime("%Y")
    m_num = dt.strftime("%m")
    m_name = dt.strftime("%B")  # February, March, etc.
    return base / y / f"{m_num}_{m_name}"


DONE_DIR = year_folder(DONE_DIR_BASE)
WORK_DIR = year_folder(WORK_DIR_BASE)
FAILED_DIR = year_folder(FAILED_DIR_BASE)
LOG_DIR = log_month_folder(LOG_DIR_BASE)

# Ensure folders exist
for d in [WATCH_DIR, DONE_DIR, WORK_DIR, FAILED_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ==========================================================
# LOGGING (monthly file)
# ==========================================================

LOG_FILE = LOG_DIR / "xml_transformer.log"
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

def log_start():
    logging.info("=== XMLTransformer (ZatPark) run started ===")

def log_finish(ok: int, fail: int):
    logging.info(f"=== XMLTransformer (ZatPark) run finished | ok={ok} fail={fail} ===")


# ==========================================================
# HELPERS
# ==========================================================

def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def unzip(zip_path: Path, extract_to: Path):
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_to)


def ssl_context():
    if DISABLE_SSL_VERIFY:
        return ssl._create_unverified_context()
    return ssl.create_default_context()


def parse_ddmmyyyy_hhmmss(s: str) -> datetime:
    # "17/12/2025 00:55:06"
    return datetime.strptime(s.strip(), "%d/%m/%Y %H:%M:%S")


def to_zp_datetime(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def safe_filename(s: str) -> str:
    return "".join(c for c in s if c.isalnum() or c in ("-", "_", ".", " ")).strip()


def post_zatpark_add_ticket(fields: dict) -> dict:
    url = f"{BASE_URL}/add_ticket"
    data = urllib.parse.urlencode(fields).encode("utf-8")

    req = urllib.request.Request(url, data=data)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("HTTPS_AUTH", HTTPS_AUTH)

    ctx = ssl_context()

    with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body)
        except Exception:
            raise RuntimeError(f"add_ticket returned non-JSON: {body[:500]}")


def post_zatpark_upload_attachment(ticket_no: str, vrm: str, file_path: Path, anpr_direction: str, anpr_type: str) -> dict:
    url = f"{BASE_URL}/upload_attachment"
    boundary = "----XMLTRANSFORMERBOUNDARY" + stamp()
    crlf = "\r\n"

    def part_text(name: str, value: str) -> bytes:
        return (
            f"--{boundary}{crlf}"
            f'Content-Disposition: form-data; name="{name}"{crlf}{crlf}'
            f"{value}{crlf}"
        ).encode("utf-8")

    def part_file(name: str, fp: Path) -> bytes:
        content = fp.read_bytes()
        filename = fp.name
        return (
            f"--{boundary}{crlf}"
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"{crlf}'
            f"Content-Type: application/octet-stream{crlf}{crlf}"
        ).encode("utf-8") + content + crlf.encode("utf-8")

    body = b"".join([
        part_text("ticket_no", ticket_no),
        part_text("vrm", vrm),
        part_text("anpr_direction", anpr_direction),
        part_text("anpr_type", anpr_type),
        part_file("attachment", file_path),
        f"--{boundary}--{crlf}".encode("utf-8"),
    ])

    req = urllib.request.Request(url, data=body)
    req.add_header("HTTPS_AUTH", HTTPS_AUTH)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

    ctx = ssl_context()

    with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
        txt = resp.read().decode("utf-8", errors="replace")
        try:
            return json.loads(txt)
        except Exception:
            return {"error": False, "status_code": 0, "message": "Upload OK", "raw": txt[:200]}


# ==========================================================
# INPUT DISCOVERY (single ZIP style)
# ==========================================================

def find_input_zips() -> list[Path]:
    zips = []
    for p in WATCH_DIR.iterdir():
        if p.is_file() and p.suffix.lower() == ".zip":
            zips.append(p)
    zips.sort(key=lambda x: x.stat().st_mtime)  # oldest-first
    return zips


# ==========================================================
# PROCESS ONE ZIP (multi-offence)
# ==========================================================

def process_single_zip(zip_path: Path, batch_id: str, idx: int):
    tag = f"{batch_id}_{idx:03d}"
    logging.info(f"--- Processing {tag}: {zip_path.name} ---")

    run_dir = WORK_DIR / f"run_{tag}"
    if run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    unzip(zip_path, run_dir)

    xml_files = list(run_dir.rglob("*.xml")) + list(run_dir.rglob("*.XML"))
    if not xml_files:
        raise RuntimeError("No XML found in ZIP")
    xml_file = xml_files[0]

    tree = ET.parse(xml_file)
    root = tree.getroot()

    offences = root.findall(".//offence")
    if not offences:
        raise RuntimeError("No <offence> nodes found in XML")

    image_index = {}
    for img in run_dir.rglob("*"):
        if img.is_file() and img.suffix.lower() in (".jpg", ".jpeg", ".png"):
            image_index[img.name] = img

    tickets_created = 0
    uploads_ok = 0
    uploads_missing = 0
    uploads_failed = 0

    for off_i, off in enumerate(offences, start=1):
        vrm = (off.get("vrm") or "").strip()
        if not vrm:
            logging.warning(f"Offence #{off_i} missing VRM - skipping")
            continue

        ent = off.find("entrance")
        ex = off.find("exit")
        if ent is None or ex is None:
            logging.warning(f"Offence #{off_i} missing entrance/exit - skipping vrm={vrm}")
            continue

        ent_ts = (ent.get("timestamp") or "").strip()
        ex_ts = (ex.get("timestamp") or "").strip()

        try:
            entry_dt = parse_ddmmyyyy_hhmmss(ent_ts)
            exit_dt = parse_ddmmyyyy_hhmmss(ex_ts)
        except Exception as e:
            logging.warning(f"Bad timestamp offence #{off_i} vrm={vrm}: {e}")
            continue

        entry_time = to_zp_datetime(entry_dt)
        exit_time = to_zp_datetime(exit_dt)

        form_fields = {
            "enforcement_type": ENFORCEMENT_TYPE,
            "type": TICKET_TYPE,
            "site_code": SITE_CODE,
            "contravention_datetime": exit_time,
            "issued_datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "observed_from_datetime": entry_time,
            "observed_to_datetime": exit_time,
            "vehicle_details[vrm]": vrm,
            "contraventions[primary]": PRIMARY_CONTRAVENTION,
            "badge_id": BADGE_ID,
        }

        add_resp = post_zatpark_add_ticket(form_fields)
        if add_resp.get("error"):
            raise RuntimeError(f"add_ticket failed for vrm={vrm}: {add_resp}")

        ticket_no = add_resp.get("ticket_no")
        tickets_created += 1
        logging.info(f"SUCCESS: ticket_no={ticket_no} vrm={vrm} (offence {off_i}/{len(offences)})")

        def upload_from_node(node, direction: str):
            nonlocal uploads_ok, uploads_missing, uploads_failed

            for attr in ("overview", "patch"):
                name = (node.get(attr) or "").strip()
                if not name:
                    continue

                fp = image_index.get(name)
                if not fp:
                    uploads_missing += 1
                    logging.warning(f"Missing image ticket={ticket_no} vrm={vrm}: {name}")
                    continue

                anpr_type = "O" if attr == "overview" else "P"

                try:
                    up = post_zatpark_upload_attachment(ticket_no, vrm, fp, direction, anpr_type)
                    if up.get("error") is True:
                        uploads_failed += 1
                        logging.warning(f"Upload failed ticket={ticket_no} image={name}: {up.get('message','unknown')}")
                    else:
                        uploads_ok += 1
                        logging.info(f"Uploaded: {name} ({direction}/{anpr_type})")
                except Exception as e:
                    uploads_failed += 1
                    logging.warning(f"Upload exception ticket={ticket_no} image={name}: {repr(e)}")

        upload_from_node(ent, "IN")
        upload_from_node(ex, "OUT")

    logging.info(
        f"ZIP summary: tickets_created={tickets_created}, uploads_ok={uploads_ok}, missing={uploads_missing}, failed={uploads_failed}"
    )

    dest = DONE_DIR / zip_path.name
    if dest.exists():
        dest = DONE_DIR / f"{zip_path.stem}_{tag}{zip_path.suffix}"
    shutil.move(str(zip_path), str(dest))
    logging.info(f"Moved ZIP to done: {dest}")

    # Cleanup work folder for this ZIP to avoid disk growth
    shutil.rmtree(run_dir, ignore_errors=True)


# ==========================================================
# MAIN
# ==========================================================

def main():
    log_start()

    zips = find_input_zips()
    if not zips:
        logging.info("No ZIPs found.")
        log_finish(ok=0, fail=0)
        return

    batch_id = stamp()
    logging.info(f"ZIPs found: {len(zips)} | Batch ID: {batch_id}")

    ok = 0
    fail = 0

    for i, zp in enumerate(zips, start=1):
        try:
            process_single_zip(zp, batch_id, i)
            ok += 1
        except Exception as e:
            fail += 1
            logging.exception(f"FAILED ZIP {i}: {zp.name} | {repr(e)}")
            try:
                failed_name = f"{zp.stem}_FAILED_{batch_id}_{i:03d}{zp.suffix}"
                dest = FAILED_DIR / safe_filename(failed_name)
                shutil.move(str(zp), str(dest))
                logging.info(f"Moved ZIP to failed: {dest}")
            except Exception:
                pass

    log_finish(ok=ok, fail=fail)


if __name__ == "__main__":
    main()
