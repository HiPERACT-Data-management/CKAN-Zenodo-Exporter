# Installation Guide

This guide covers all deployment options for **CKAN to Zenodo Exporter**: Docker Compose (recommended), manual setup on a bare Linux server, and the database migration workflow.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Option A — Docker Compose](#option-a--docker-compose)
- [Option B — Manual Installation](#option-b--manual-installation)
  - [1. System packages](#1-system-packages)
  - [2. Python environment](#2-python-environment)
  - [3. Database setup](#3-database-setup)
  - [4. Configuration](#4-configuration)
  - [5. Running the services](#5-running-the-services)
  - [6. systemd service files](#6-systemd-service-files)
- [Database migrations](#database-migrations)
- [CKAN integration](#ckan-integration)
- [Keycloak configuration](#keycloak-configuration)
- [Reverse proxy (nginx)](#reverse-proxy-nginx)
- [Verifying the installation](#verifying-the-installation)

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | |
| RabbitMQ | 3.x | Durable queues required |
| MariaDB / MySQL | 10.6+ / 8.0+ | `utf8mb4` charset |
| CKAN | 2.9+ | API access + shared filesystem |
| Zenodo account | — | Personal Access Token required |
| Keycloak | 20+ | OIDC client configured |

The application assumes the CKAN resource file storage is **accessible on the local filesystem** of the machine running the exporter, either directly or via a network mount (NFS, CIFS). Files are read directly from disk — they are not downloaded through the CKAN API.

---

## Option A — Docker Compose

The fastest path to a running stack.

### 1. Clone the repository

```bash
git clone https://github.com/HiPERACT-Data-management/CKAN-Zenodo-Exporter.git
cd CKAN-Zenodo-Exporter
```

### 2. Configure

Copy and edit the configuration file:

```bash
cp settings.ini settings.ini.local   # optional — for local overrides
```

Edit `settings.ini` (see the [Configuration reference](#4-configuration) below).

### 3. Mount CKAN storage

Open `docker-compose.yml` and update the `ckan_resources` volume definition to point at the actual CKAN storage path on your host:

```yaml
volumes:
  ckan_resources:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /mnt/vol   # ← path on the Docker host
```

### 4. Start the stack

```bash
docker compose up --build -d
```

Services:

| Service | Port | Description |
|---|---|---|
| `rabbitmq` | 5672, 15672 | Message broker + management UI |
| `db` | 3306 | MariaDB database |
| `migrate` | — | Runs migrations on startup, then exits |
| `server` | 8090 | Flask web application |
| `worker` | — | Background upload worker |

### 5. Check status

```bash
docker compose ps
curl http://localhost:8090/health
```

Expected response:

```json
{"status": "healthy", "db": "ok", "rabbitmq": "ok"}
```

---

## Option B — Manual Installation

### 1. System packages

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip rabbitmq-server mariadb-server
```

Enable and start the services:

```bash
sudo systemctl enable --now rabbitmq-server mariadb
```

### 2. Python environment

```bash
git clone https://github.com/HiPERACT-Data-management/CKAN-Zenodo-Exporter.git
cd CKAN-Zenodo-Exporter

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Database setup

#### Fresh install

```bash
mysql -u root -p < sql/database.sql
```

`sql/database.sql` creates the `zenodo_export` database, the `zenodo_user` account, and all tables. Edit the file first to set a strong password for `zenodo_user`.

#### Existing installation

Run pending migrations instead:

```bash
python migrate.py
```

See [Database migrations](#database-migrations) for details.

### 4. Configuration

Edit `settings.ini`:

```ini
[app]
secret_key = <long-random-string>   # e.g. output of: python -c "import secrets; print(secrets.token_hex(32))"
log_file = /var/log/ckan-zenodo-export.log
max_file_size_mb = 0                # 0 = unlimited; positive integer = MB cap
notify_on_completion = false        # set true to send email on transfer completion/failure

[ckan]
server = https://ckan.example.com
apikey = <ckan-service-account-api-key>
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
client_id = ckan-zenodo-exporter
client_secret = <client-secret>
redirect_uri = https://ckan.example.com:8090/callback

[rabbitmq]
host = localhost
queue = zenodo_upload
max_retries = 3

[zenodo]
api_url = https://zenodo.org/api/deposit/depositions
use_sandbox = false       # true → use sandbox.zenodo.org for testing
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

**Configuration notes:**

- `resources_usr_path` — the `{user}` placeholder is automatically replaced at runtime with the username extracted from the resource URL. Example: `http://ckan.example.com/~johndoe/file.csv` → user = `johndoe`.
- `use_sandbox` — set to `true` to target `sandbox.zenodo.org`. All uploads go to the sandbox; use this for testing before enabling production exports.
- `max_file_size_mb = 0` disables the size check. Set a positive integer (e.g. `500`) to reject files larger than that many megabytes before queuing.
- `notify_on_completion` requires a valid `[smtp]` configuration.

### 5. Running the services

**Development / testing:**

```bash
# Terminal 1
source venv/bin/activate
python server.py

# Terminal 2
source venv/bin/activate
python worker.py
```

The web app listens on `http://0.0.0.0:8090`.

### 6. systemd service files

Create `/etc/systemd/system/ckan-zenodo-server.service`:

```ini
[Unit]
Description=CKAN to Zenodo Exporter — web server
After=network.target mariadb.service rabbitmq-server.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/ckan-zenodo-exporter
ExecStart=/opt/ckan-zenodo-exporter/venv/bin/python server.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Create `/etc/systemd/system/ckan-zenodo-worker.service`:

```ini
[Unit]
Description=CKAN to Zenodo Exporter — upload worker
After=network.target mariadb.service rabbitmq-server.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/ckan-zenodo-exporter
ExecStart=/opt/ckan-zenodo-exporter/venv/bin/python worker.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ckan-zenodo-server.service ckan-zenodo-worker.service
```

Check logs:

```bash
journalctl -u ckan-zenodo-server -f
journalctl -u ckan-zenodo-worker -f
```

---

## Database migrations

The `migrate.py` script tracks which SQL migrations have been applied in a `schema_migrations` table and applies pending ones in order.

```bash
# Show current migration status
python migrate.py --status

# Apply all pending migrations
python migrate.py
```

Migration files live in `migrations/` and are named `NNN_description.sql`. They are applied in lexicographic order. Re-running `migrate.py` on an already-migrated database is safe — applied migrations are skipped.

| File | Description |
|---|---|
| `001_initial_schema.sql` | Base `zenodo_transfers` table |
| `002_add_retry_count.sql` | Adds `retry_count` column |
| `003_add_resource_id_and_email.sql` | Adds `resource_id` and `user_email` columns |

---

## CKAN integration

Add an **Export to Zenodo** link to the CKAN resource page by editing the resource item template on your CKAN server:

```
/usr/lib/ckan/default/src/ckan/ckan/templates/package/snippets/resource_item.html
```

Add the following inside the resource actions dropdown (replace `ckan.example.com` with your actual hostnames):

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

Restart CKAN after editing the template (or reload the uWSGI workers):

```bash
sudo supervisorctl restart ckan-uwsgi:
```

---

## Keycloak configuration

In your Keycloak admin console, create an OIDC client for the exporter:

1. **Clients → Create** — set Client ID to the value you use for `client_id` in `settings.ini`
2. **Access Type:** `confidential`
3. **Valid Redirect URIs:** `https://ckan.example.com:8090/callback`
4. **Web Origins:** `https://ckan.example.com:8090`
5. Copy the **Secret** from the **Credentials** tab → paste into `client_secret` in `settings.ini`

The exporter requests the `openid profile email` scope. Ensure the `email` mapper is enabled in the client's scope configuration so that `userinfo` responses include the user's email address (used for transfer notifications).

---

## Reverse proxy (nginx)

To expose the exporter behind nginx on the standard HTTPS port:

```nginx
server {
    listen 443 ssl;
    server_name ckan.example.com;

    # ... ssl_certificate, ssl_certificate_key ...

    location /export {
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ajax {
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        client_max_body_size 0;
    }

    location /transfers {
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host $host;
    }

    location /health {
        proxy_pass http://127.0.0.1:8090;
    }
}
```

---

## Verifying the installation

```bash
# Health check
curl -s http://localhost:8090/health | python3 -m json.tool

# Expected
{
    "db": "ok",
    "rabbitmq": "ok",
    "status": "healthy"
}
```

If any component shows `"error: ..."`, check:
- `db` error → MariaDB is not running, credentials in `settings.ini` are wrong, or the `zenodo_export` database does not exist
- `rabbitmq` error → RabbitMQ is not running or the hostname in `settings.ini` is wrong
