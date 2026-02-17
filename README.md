# XMLTransformer (ZatPark)

A Windows/Python automation tool that processes enforcement ZIP files containing source XML + ANPR images, then creates tickets in ZatPark via HTTPS and uploads the related images as attachments.

This project is designed as a simple file-driven pipeline:
drop a ZIP into a watch folder → tool processes it → uploads to ZatPark → moves ZIP to archive.

---

## What it does

- Scans a configured **watch folder** for `.zip` files (oldest first)
- Extracts ZIP contents into a work folder
- Parses the first XML found in the ZIP and iterates through all `<offence>` nodes
- For each offence:
  - reads `vrm`, `entrance timestamp`, `exit timestamp`
  - calls ZatPark `/add_ticket` to create a ticket
  - uploads related images referenced by XML (`overview` + `patch`) for:
    - entrance (IN)
    - exit (OUT)
- Moves processed ZIPs to a **Done** folder (year-based)
- Moves failed ZIPs to a **Failed** folder (year-based)
- Writes logs to a **monthly log folder** structure

---

## Included files in this repo

Typical folder contents:

- `XMLTransformer.exe` – standalone build (PyInstaller)
- `XMLTransformer_zatpark.py` – source code
- `config.json` – runtime configuration
- `RUN_NOW.bat` – convenience runner
- `INSTALL.bat` / `UNINSTALL.bat` – local install helpers

---

## Folder & log structure

The tool automatically creates folders if missing:

- `watch_dir`
- `work_dir/<YEAR>/run_<batch>`
- `done_dir/<YEAR>/`
- `failed_dir/<YEAR>/` (optional, defaults to `<watch_dir>/failed`)
- `log_dir/<YEAR>/<MM>_<MonthName>/xml_transformer.log`

---

## Configuration

The tool loads `config.json` from the same directory as the EXE (PyInstaller-safe) or script.

Example `config.json` shape:

```json
{
  "watch_dir": "C:\\XMLTransformer\\watch",
  "done_dir": "C:\\XMLTransformer\\done",
  "work_dir": "C:\\XMLTransformer\\work",
  "log_dir": "C:\\XMLTransformer\\logs",
  "failed_dir": "C:\\XMLTransformer\\failed",
  "disable_ssl_verify": true,
  "zatpark": {
    "base_url": "https://example/api",
    "https_auth": "YOUR_HEADER_TOKEN",
    "site_code": "XXXX",
    "enforcement_type": "1",
    "ticket_type": "PCN",
    "badge_id": "123",
    "primary_contravention": "24721"
  }
}
