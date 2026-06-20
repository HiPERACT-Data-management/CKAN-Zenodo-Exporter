# CKAN to Zenodo Exporter

**CKAN to Zenodo Exporter** is a web application that enables researchers and data managers to publish datasets from a [CKAN](https://ckan.org) data portal directly to [Zenodo](https://zenodo.org) — the open-access repository operated by CERN.

<p>
  <img src="docs/images/ckan_zenodo_flow.svg" alt="CKAN to Zenodo Exporter Diagram"/>
</p>

---

## Goal and Scope

Research institutions that run CKAN as their internal data management platform often need to make selected datasets publicly available in a citeable, DOI-backed repository. Zenodo is the natural target for this — it is free, trusted by the scientific community, and integrates well with the European Open Science Cloud (EOSC).

However, the manual workflow is tedious: download the file from CKAN, log in to Zenodo, fill in metadata, upload the file, and publish. For institutions with dozens or hundreds of resources, this is not sustainable.

**CKAN to Zenodo Exporter** bridges the two systems with a lightweight middleware that:

- Is triggered directly from the CKAN resource page with a single click
- Authenticates users through the institution's existing **Keycloak** SSO — no separate accounts needed
- Lets the user select an existing Zenodo deposition or create a new one with configurable metadata (title, description, upload type, access rights)
- Exports a single resource **or an entire CKAN dataset** (all resources at once) to a chosen deposition
- Offloads the actual file transfer to a **background worker** so the browser does not need to wait for potentially large uploads
- Retries failed transfers automatically with exponential backoff and notifies the user by email on completion or failure
- Provides a **Transfers** page with live status updates so users always know where their exports stand

The tool is designed for self-hosted institutional deployments. It assumes the CKAN file storage is accessible on the same filesystem as the exporter (either directly or via a network mount), which avoids re-downloading files through the CKAN API and keeps transfers fast.

---

## Architecture

```
CKAN portal  ──(click)──▶  Flask web app (server.py)
                                │
                         Keycloak SSO
                                │
                         RabbitMQ queue
                                │
                         Worker (worker.py)
                                │
                          Zenodo REST API
                                │
                         MariaDB (transfer log)
```

| Component | Role |
|---|---|
| **Flask + Waitress** | Web interface and REST API endpoints |
| **Keycloak OIDC** | Single sign-on — users authenticate with their institutional account |
| **RabbitMQ** | Decouples the web request from the upload; allows retries and backpressure |
| **Worker** | Consumes tasks from the queue; uploads files to Zenodo; sends notifications |
| **MariaDB** | Stores transfer records (status, retry count, response) for audit and display |

---

## Features

- **Single-resource export** — export any CKAN resource to an existing or new Zenodo deposition
- **Full-dataset export** — export all resources of a CKAN package to a single deposition in one click
- **New deposition creation** — set title, description, upload type, and access rights from the UI; values are pre-filled from the CKAN package metadata
- **Configurable upload type and access rights** — choose from all Zenodo-supported types (dataset, software, publication, image, …) and access rights (open, restricted, embargoed, closed) per export
- **Zenodo sandbox support** — toggle `use_sandbox = true` to test against `sandbox.zenodo.org` without affecting production records
- **Async transfer queue** — RabbitMQ-backed worker processes uploads in the background; the web UI is never blocked
- **Automatic retry with exponential backoff** — failed uploads are re-queued automatically (10 s → 20 s → 40 s … capped at 5 min); configurable maximum retry count
- **Retry button** — manually re-queue any failed transfer from the Transfers page (requires the API key to still be in session)
- **Live status polling** — the Transfers page polls `/api/transfer/<id>` every 5 seconds and updates status badges in place without a full page reload
- **Duplicate detection** — warns if the same resource + deposition combination already has an active or completed transfer
- **File size limit** — optional `max_file_size_mb` cap; exports over the limit are rejected before queuing
- **Email notifications** — optional SMTP notification to the exporting user on transfer completion or final failure
- **Keycloak SSO** — users log in with their institutional identity; username and email are carried through to transfer records
- **CSRF protection** — all state-changing requests are protected via Flask-WTF
- **Health endpoint** — `GET /health` returns JSON status for DB and RabbitMQ; suitable for load balancer probes and monitoring
- **Database migrations** — versioned SQL migration files applied by `migrate.py`; safe to re-run
- **Docker Compose** — one-command local or production deployment

---

## Requirements

- Python 3.10+
- RabbitMQ 3.x
- MySQL 8 or MariaDB 10.6+
- A running CKAN instance with API access
- A Zenodo account and API token
- A Keycloak realm configured with an OIDC client for this application
- CKAN file storage accessible on the local filesystem (direct mount or NFS)

---

## Quick Start with Docker Compose

The fastest way to run the full stack locally:

```bash
cp settings.ini.example settings.ini   # fill in your values
docker compose up --build
```

Services started:
- `rabbitmq` — message broker (management UI at http://localhost:15672)
- `db` — MariaDB database
- `migrate` — runs pending schema migrations on startup, then exits
- `server` — Flask web app on http://localhost:8090
- `worker` — background upload worker

CKAN resource storage must be bind-mounted into the `server` and `worker` containers via the `ckan_resources` volume defined in `docker-compose.yml`.

---

## Manual Installation

### 1. Create a Python virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Install RabbitMQ and MariaDB

```bash
sudo apt install rabbitmq-server mariadb-server
```

### 3. Set up the database

For a fresh install, run the bundled schema:

```bash
mysql -u root < sql/database.sql
```

For an existing installation, apply pending migrations:

```bash
python migrate.py
```

To check which migrations have been applied:

```bash
python migrate.py --status
```

### 4. Configure the application

Copy and edit `settings.ini`:

```ini
[app]
secret_key = <random secret>
log_file = /var/log/ckan-export.log
max_file_size_mb = 0        # 0 = unlimited
notify_on_completion = false

[ckan]
server = https://ckan.example.com
apikey = <ckan-api-key>
resources_path = /mnt/vol/ckan/default/resources
resources_usr_path = /mnt/vol/homes/{user}/ckan-pub
resources_usr_url = https://ckan.example.com:8443/~

[mysql]
host = localhost
user = zenodo_user
password = <password>
database = zenodo_export

[sso]
keycloak_server_url = https://keycloak.example.com
realm_name = myrealm
client_id = ckan-zenodo
client_secret = <client-secret>
redirect_uri = https://ckan.example.com:8090/callback

[rabbitmq]
host = localhost
queue = zenodo_upload
max_retries = 3

[zenodo]
api_url = https://zenodo.org/api/deposit/depositions
use_sandbox = false        # set true to test against sandbox.zenodo.org
upload_type = dataset
access_right = restricted

[smtp]
enabled = false
host = smtp.example.com
port = 587
use_tls = true
username =
password =
from_addr = noreply@example.com
```

### 5. Run the services

**Development:**

```bash
python server.py   # web app on port 8090
python worker.py   # background worker (separate terminal)
```

**Production (systemd):**

Create `/etc/systemd/system/ckan-export.service`:

```ini
[Unit]
Description=CKAN to Zenodo Exporter
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/ckan-export
ExecStart=/opt/ckan-export/venv/bin/python /opt/ckan-export/server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Create `/etc/systemd/system/zenodo-worker.service`:

```ini
[Unit]
Description=Zenodo Upload Worker
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/ckan-export
ExecStart=/opt/ckan-export/venv/bin/python /opt/ckan-export/worker.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now ckan-export.service zenodo-worker.service
```

---

## CKAN Integration

To add an **Export to Zenodo** link on the CKAN resource page, edit the resource item template:

```
/usr/lib/ckan/default/src/ckan/ckan/templates/package/snippets/resource_item.html
```

Add the following snippet inside the resource actions menu:

```html
{% if 'https://ckan.example.com' in res.url %}
  <li>
    <a class="dropdown-item" href="{{ 'https://ckan.example.com:8090/export?resource=' + res.id }}">
      <i class="fa fa-book"></i>
      {{ _('Export to Zenodo') }}
    </a>
  </li>
{% endif %}
```

Replace `ckan.example.com` with your actual CKAN hostname in both the condition and the href.

---

## How It Works

1. A user clicks **Export to Zenodo** on a CKAN resource page.
2. If not logged in, they are redirected to Keycloak and authenticated.
3. The exporter fetches the resource and package metadata from CKAN.
4. The user enters their Zenodo API key. The key is validated and stored server-side in the session — it is never transmitted again.
5. The user selects an existing Zenodo deposition or creates a new one with a title, description, upload type, and access rights.
6. The exporter checks that the file exists locally and is within the size limit, then creates a transfer record in the database and publishes a task to RabbitMQ.
7. The background worker picks up the task, uploads the file to Zenodo's storage bucket, and updates the transfer status.
8. If the upload fails, the worker retries with exponential backoff. After all retries are exhausted, the transfer is marked as failed and the user is notified by email (if configured).
9. The user can monitor progress on the **Transfers** page, which polls for live status updates, and manually retry failed transfers.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Home page |
| `GET` | `/export?resource=<uuid>` | Export page for a CKAN resource |
| `POST` | `/ajax` | AJAX handler for all export actions |
| `GET` | `/transfers` | Transfer history for the logged-in user |
| `GET` | `/api/transfer/<id>` | JSON status of a single transfer (for polling) |
| `GET` | `/health` | Liveness check — returns `{"status":"healthy"}` or `503` |
| `GET` | `/login` | Initiate Keycloak OIDC login |
| `GET` | `/callback` | Keycloak OAuth2 callback |
| `GET` | `/logout` | Clear session and log out |

### AJAX actions (`POST /ajax`)

| `action` | Description |
|---|---|
| `list_depositions` | Fetch and display the user's Zenodo depositions; stores API key in session |
| `export_to_zenodo` | Export a single resource to an existing deposition |
| `create_deposit_and_export` | Create a new deposition and export the resource into it |
| `export_package_to_zenodo` | Export all resources of a CKAN package to an existing deposition |
| `retry_transfer` | Re-queue a failed transfer |

---

## Project Structure

```
ckan-zenodo-exporter/
├── server.py               # Flask web application
├── worker.py               # RabbitMQ consumer — uploads files to Zenodo
├── ckan_zenodo.py          # Core business logic (file path resolution, DB, queue)
├── configs.py              # Configuration loader (settings.ini)
├── db.py                   # Connection pool (DBUtils PooledDB)
├── migrate.py              # Database migration runner
├── settings.ini            # Application configuration (not committed)
├── requirements.txt        # Production dependencies
├── requirements-dev.txt    # Development/test dependencies
├── Dockerfile              # Container image definition
├── docker-compose.yml      # Full stack (server, worker, RabbitMQ, MariaDB)
├── sql/
│   └── database.sql        # Schema for fresh installs
├── migrations/
│   ├── 001_initial_schema.sql
│   ├── 002_add_retry_count.sql
│   └── 003_add_resource_id_and_email.sql
├── static/                 # CSS, JS, images
├── templates/              # Jinja2 HTML templates
├── tests/
│   ├── conftest.py         # Shared fixtures and config patches
│   ├── test_ckan_zenodo.py
│   ├── test_server.py
│   └── test_worker.py
└── docs/
    └── images/
```

---

## Running Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

All tests use mocked external dependencies (CKAN API, Zenodo API, RabbitMQ, MariaDB) and run without any live services.

---

## User Manual

See the detailed step-by-step guide: [USER_MANUAL.md](USER_MANUAL.md)

---

## License

MIT License — see [LICENSE](LICENSE).

Copyright (c) 2023-2026 Marcin Lawenda, Poznan Supercomputing and Networking Center
