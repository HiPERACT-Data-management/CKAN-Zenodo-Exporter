# Developer Guide

This guide covers the internal architecture, module responsibilities, data flow, extension points, testing strategy, and contribution workflow for **CKAN to Zenodo Exporter**.

---

## Table of Contents

- [Architecture overview](#architecture-overview)
- [Module reference](#module-reference)
  - [server.py](#serverpy)
  - [ckan_zenodo.py](#ckan_zenodopy)
  - [worker.py](#workerpy)
  - [configs.py](#configspy)
  - [db.py](#dbpy)
  - [migrate.py](#migratepy)
- [Data flow](#data-flow)
- [Database schema](#database-schema)
- [Configuration reference](#configuration-reference)
- [Exception hierarchy](#exception-hierarchy)
- [API reference](#api-reference)
- [Security model](#security-model)
- [Testing](#testing)
- [Adding a migration](#adding-a-migration)
- [Adding a new AJAX action](#adding-a-new-ajax-action)
- [Extending the worker](#extending-the-worker)
- [Running locally without Keycloak](#running-locally-without-keycloak)
- [Coding conventions](#coding-conventions)

---

## Architecture overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser                                                        │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  CKAN portal   ─── "Export to Zenodo" link ──▶            │ │
│  │  export.html   ─── AJAX ──▶ /ajax (Flask)                 │ │
│  │  transfers.html ── GET  ──▶ /api/transfer/<id> (polling)  │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
         │                              │
    Keycloak SSO                Flask + Waitress (server.py)
                                        │
                              ckan_zenodo.py (business logic)
                               ┌────────┴────────┐
                           CKAN API          RabbitMQ queue
                                                  │
                                          worker.py (consumer)
                                           ┌──────┴──────┐
                                       Zenodo API     MariaDB
                                                    (transfer log)
```

The application is split into three long-running processes:

| Process | File | Role |
|---|---|---|
| Web server | `server.py` | Handles HTTP requests; validates input; writes to DB and queue |
| Upload worker | `worker.py` | Consumes queue messages; uploads files to Zenodo; retries on failure |
| (one-shot) | `migrate.py` | Applies pending database schema migrations |

All three share `ckan_zenodo.py` (business logic), `configs.py` (configuration), and `db.py` (connection pool).

---

## Module reference

### server.py

The Flask web application. Served in production by **Waitress** (a pure-Python WSGI server that handles threading internally).

**Responsibilities:**
- Routing and session management
- Keycloak OIDC callback and token exchange
- CSRF protection (Flask-WTF, `CSRFProtect`)
- Input validation for all user-supplied values
- Calling `ckan_zenodo` functions and mapping exceptions to user-facing messages
- Rendering Jinja2 templates
- Providing the `/health` and `/api/transfer/<id>` JSON endpoints

**Key design decisions:**

*CSRF*: `CSRFProtect(app)` enforces token validation on all non-GET requests. The CSRF token is injected into a `<meta>` tag in `base.html` and picked up by `$.ajaxSetup` in `functions.js`, which sets the `X-CSRFToken` header on every AJAX POST. The `/health` and `/api/transfer/<id>` endpoints are explicitly exempted via `@csrf.exempt` because they are GET requests consumed by monitoring tools and the polling loop.

*Session-based API key*: The Zenodo API key is stored in `session['zenodo_apikey']` after the user enters it once (in `list_depositions`). Subsequent AJAX actions read the key from the session rather than asking the client to re-send it. This avoids the key appearing in POST bodies in server logs.

*Input validation*: Four helpers guard all user-supplied identifiers:
- `_valid_api_key(value)` — non-empty, no whitespace, ≤ 200 chars
- `_valid_uuid(value)` — valid UUID (CKAN resource IDs)
- `_valid_deposition_id(value)` — positive integer string (Zenodo deposition IDs)
- `_valid_package_id(value)` — alphanumeric + `-_`, 1–100 chars

*Module-level `serve()` guard*: `serve(app, ...)` is only called inside `if __name__ == '__main__':` so that importing `server` in tests does not bind the port.

---

### ckan_zenodo.py

All business logic. Imported by both `server.py` and `worker.py` (indirectly, for shared exception types).

**Functions:**

| Function | Description |
|---|---|
| `get_file_path(resource_id, url)` | Resolves a CKAN resource URL to a local filesystem path. Handles two storage layouts: default CKAN resource store (`/resources/abc/def/...`) and user home directories (`/homes/{user}/...`). The `{user}` placeholder in `resources_usr_path` is expanded at runtime. |
| `check_duplicate_transfer(resource_id, deposition_id)` | Queries `zenodo_transfers` for a non-failed record with the same `resource_id` + `deposition_id`. Raises `DuplicateTransfer` if found. Only matches records where `resource_id IS NOT NULL` (records created before migration 003 are ignored). |
| `get_deposition_name(zenodo_apikey, deposition_id)` | Calls `GET /api/deposit/depositions/<id>` and returns the deposition title. |
| `insert_transfer_record(username, file_path, filename, deposition_id, deposition_name, resource_id, user_email)` | Inserts a `pending` row into `zenodo_transfers`. Returns the new `id`. |
| `send_upload_task(username, file_path, zenodo_token, deposition_id, deposition_name, filename, transfer_id, user_email)` | Publishes a JSON message to the RabbitMQ queue. The message includes all fields needed by the worker, including `user_email` for notifications. |
| `export_to_zenodo(zenodo_apikey, resource_id, filename, res_url, deposition_id)` | Orchestrates a single-resource export to an existing deposition: duplicate check → name lookup → file existence → size check → DB insert → queue. |
| `create_deposit_and_export(zenodo_apikey, resource_id, filename, res_url, deposition_name, deposition_desc, upload_type, access_right)` | Creates a new Zenodo deposition then exports a resource into it. Deletes the newly-created deposition if the resource file is not found (orphan cleanup). `upload_type` and `access_right` override config defaults when provided. |
| `get_ckan_resource(resource_id)` | Fetches a CKAN resource record via `ckanapi.RemoteCKAN`. |
| `get_ckan_package(package_id)` | Fetches a CKAN package record (includes `resources` list). |
| `get_depositions(zenodo_apikey)` | Lists all Zenodo depositions for the given API key. |
| `get_transfer_by_id(transfer_id, username)` | Returns a single transfer row, verified against `username`. Returns `None` if not found or owned by another user. |
| `reset_transfer_for_retry(transfer_id)` | Sets `status = 'pending'`, `retry_count = 0`, `zenodo_response = ''` for a transfer record. |
| `get_transfers_for_user(username)` | Returns all transfers for a user, ordered newest first. |

**Flask session dependency**: `export_to_zenodo` and `create_deposit_and_export` read `session['user']` to get the username and email. This ties them to the Flask request context. When calling these from tests, patch `ckan_zenodo.session` directly (see `conftest.py`).

---

### worker.py

The RabbitMQ consumer. Runs as a separate long-lived process.

**Message format** (JSON):

```json
{
  "username": "jsmith",
  "file_path": "/mnt/vol/ckan/resources/abc/def/...",
  "filename": "dataset.csv",
  "zenodo_token": "<api-key>",
  "deposition_id": "12345",
  "deposition_name": "My Dataset",
  "transfer_id": 42,
  "user_email": "jsmith@example.com",
  "retry_count": 0
}
```

**Retry logic:**

```
attempt = retry_count + 1
if upload fails AND retry_count < max_retries:
    delay = min(2 ** retry_count * 10, 300)   # 10s, 20s, 40s, … cap 300s
    sleep(delay)
    re-publish message with retry_count + 1
    update DB: status = 'pending', zenodo_response = "Retry N/M: <error>"
else:
    update DB: status = 'failed'
    send_email_notification(user_email, ...)

# always:
ch.basic_ack(delivery_tag=method.delivery_tag)
```

The final `basic_ack` is in a `finally` block so the message is always removed from the queue, even if the status update itself fails. Errors in `update_transfer_status` and `send_email_notification` are caught and logged without re-raising.

**`send_email_notification(to_addr, subject, body)`**: No-op when `smtp.enabled = false` or `to_addr` is empty. All SMTP errors are caught and logged — a broken SMTP configuration never causes the worker to crash or fail an ACK.

**`upload_to_zenodo(file_path, filename, zenodo_token, deposition_id)`**: Two-step upload:
1. `GET /api/deposit/depositions/<id>` — fetch the bucket URL from `response.json()['links']['bucket']`
2. `PUT <bucket_url>/<filename>` — stream the file from disk

Both calls use `.raise_for_status()`. If either raises `HTTPError`, the exception propagates to `callback()` which handles retries.

---

### configs.py

Loads `settings.ini` once at module import time into the module-level `_config` object. All getter functions return plain dicts.

**Getter functions:**

| Function | Section | Keys returned |
|---|---|---|
| `get_db_config()` | `[mysql]` | `host`, `user`, `password`, `database` |
| `get_ckan_config()` | `[ckan]` | `server`, `apikey`, `resources_path`, `resources_usr_path`, `resources_usr_url` |
| `get_sso_config()` | `[sso]` | `keycloak_server_url`, `realm_name`, `client_id`, `client_secret`, `redirect_uri` |
| `get_rabbitmq_config()` | `[rabbitmq]` | `host`, `queue`, `max_retries` |
| `get_zenodo_config()` | `[zenodo]` | `api_url` (sandbox-aware), `use_sandbox`, `upload_type`, `access_right` |
| `get_app_config()` | `[app]` | `secret_key`, `log_file`, `max_file_size_mb`, `notify_on_completion` |
| `get_smtp_config()` | `[smtp]` | `enabled`, `host`, `port`, `use_tls`, `username`, `password`, `from_addr` |

**Sandbox URL substitution**: `get_zenodo_config()` checks `use_sandbox` and replaces `zenodo.org` with `sandbox.zenodo.org` in `api_url` if it is `true`. This affects both the server (deposition creation) and the worker (bucket URL fetch and file upload).

**Testing**: In tests, all getter functions are patched at the session level via `pytest_configure` in `conftest.py` before any module-level import code runs. This is necessary because `server.py` and `worker.py` call config getters at module load time.

---

### db.py

Thin wrapper around `DBUtils.PooledDB`. Initialises a single connection pool lazily on first use.

```python
_pool = None

def _get_pool():
    global _pool
    if _pool is None:
        _pool = PooledDB(creator=pymysql, maxconnections=10, mincached=1,
                         maxcached=5, blocking=True, **configs.get_db_config())
    return _pool

def get_connection():
    return _get_pool().connection()
```

All callers follow the pattern:

```python
connection = db.get_connection()
try:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
    connection.commit()
finally:
    connection.close()   # returns connection to the pool, does not close the socket
```

`connection.close()` on a pooled connection returns it to the pool rather than closing the underlying socket. This is safe to call from both the web worker threads (`server.py`) and the single-threaded `worker.py`.

---

### migrate.py

Standalone script that applies versioned SQL migrations.

**Workflow:**
1. Connect to the database using `configs.get_db_config()`
2. Create `schema_migrations (version VARCHAR(255) PRIMARY KEY, applied_at TIMESTAMP)` if it does not exist
3. Read all `*.sql` files from the `migrations/` directory in lexicographic order
4. For each file, check whether its name (without `.sql`) is already recorded in `schema_migrations`
5. If not applied, execute the file's SQL and insert the version record

**Usage:**

```bash
python migrate.py           # apply pending migrations
python migrate.py --status  # show applied/pending status without executing
```

---

## Data flow

### Single-resource export

```
User clicks "Export this resource"
  │
  ▼
POST /ajax { action: export_to_zenodo, ckan_resource_id, deposition_id }
  │
  ├─ validate inputs (_valid_uuid, _valid_deposition_id)
  ├─ read zenodo_apikey from session
  │
  ▼
ckan_zenodo.export_to_zenodo()
  ├─ check_duplicate_transfer(resource_id, deposition_id)  → DuplicateTransfer?
  ├─ get_deposition_name(apikey, deposition_id)            → Zenodo GET
  ├─ get_file_path(resource_id, url)                       → local path
  ├─ os.path.exists(file_path)                             → ResourceFileNotFound?
  ├─ _check_file_size(file_path)                           → FileTooLarge?
  ├─ insert_transfer_record(...)                           → MariaDB INSERT → transfer_id
  └─ send_upload_task(...)                                 → RabbitMQ PUBLISH
  │
  ▼
worker.callback()
  ├─ update_transfer_status(transfer_id, 'in_progress')
  ├─ upload_to_zenodo(file_path, filename, token, dep_id)
  │    ├─ GET /api/deposit/depositions/<id>  → bucket_url
  │    └─ PUT <bucket_url>/<filename>        → stream file
  ├─ update_transfer_status(transfer_id, 'completed', response)
  ├─ send_email_notification(user_email, ...)
  └─ ch.basic_ack()
```

### Retry flow

```
worker.callback() — upload fails
  │
  ├─ retry_count < max_retries?
  │    YES:
  │    ├─ time.sleep(min(2^retry_count * 10, 300))
  │    ├─ re-publish message with retry_count + 1
  │    ├─ update_transfer_status(transfer_id, 'pending', "Retry N/M: <err>", retry_count+1)
  │    └─ ch.basic_ack()
  │
  └─ NO (exhausted):
       ├─ update_transfer_status(transfer_id, 'failed', str(e), retry_count)
       ├─ send_email_notification(user_email, "Transfer failed: ...")
       └─ ch.basic_ack()
```

---

## Database schema

```sql
CREATE TABLE zenodo_transfers (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(255) NOT NULL,
    user_email      VARCHAR(255) NULL,
    file_path       VARCHAR(1024) NOT NULL,
    filename        VARCHAR(255) NOT NULL,
    deposition_id   VARCHAR(50) NOT NULL,
    deposition_name VARCHAR(255),
    resource_id     VARCHAR(100) NULL,
    status          ENUM('pending','in_progress','completed','failed') DEFAULT 'pending',
    zenodo_response TEXT,
    retry_count     INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

| Column | Purpose |
|---|---|
| `username` | CKAN / Keycloak username of the exporting user |
| `user_email` | Email for notifications (from SSO profile at time of export) |
| `file_path` | Absolute path to the file on the server filesystem |
| `filename` | Display name / target filename on Zenodo |
| `deposition_id` | Zenodo deposition ID (integer, stored as string) |
| `deposition_name` | Zenodo deposition title at time of export |
| `resource_id` | CKAN resource UUID — used for duplicate detection |
| `status` | Current transfer state |
| `zenodo_response` | Raw Zenodo API response body or error message |
| `retry_count` | Number of upload attempts made so far |
| `created_at` | When the transfer was queued |
| `updated_at` | Last status change (auto-updated by MariaDB) |

---

## Exception hierarchy

```
Exception
├── ResourceFileNotFound   — CKAN resource file not found on the local filesystem
├── FileTooLarge           — file exceeds max_file_size_mb
├── DuplicateTransfer      — non-failed transfer already exists for resource+deposition
└── ZenodoAPIError         — Zenodo returned an unexpected HTTP status
      └── .status_code     — the HTTP status code from Zenodo
```

All four are defined in `ckan_zenodo.py` and imported by `server.py` for routing to user-facing messages.

---

## API reference

### Web endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/` | — | Home page |
| `GET` | `/export?resource=<uuid>` | Session | Export UI for a CKAN resource |
| `POST` | `/ajax` | Session + CSRF | All export actions (see below) |
| `GET` | `/transfers` | Session | Transfer history page |
| `GET` | `/api/transfer/<int:id>` | Session | Transfer status as JSON |
| `GET` | `/health` | — | Liveness check (JSON) |
| `GET` | `/login` | — | Redirect to Keycloak |
| `GET` | `/callback` | — | Keycloak OIDC callback |
| `GET` | `/logout` | — | Clear session |

### AJAX actions (`POST /ajax`)

All actions require the `action` field in the POST body. Actions other than `list_depositions` also require `session['zenodo_apikey']` to be set.

| `action` | Required fields | Description |
|---|---|---|
| `list_depositions` | `zenodo_apikey` | Validate and store API key; return depositions HTML fragment |
| `export_to_zenodo` | `ckan_resource_id`, `deposition_id` | Export single resource to existing deposition |
| `create_deposit_and_export` | `ckan_resource_id`, `deposit_name`, `deposit_desc`, `upload_type`*, `access_right`* | Create new deposition and export |
| `export_package_to_zenodo` | `package_id`, `deposition_id` | Export all resources in a CKAN package |
| `retry_transfer` | `transfer_id` | Re-queue a failed transfer |

\* optional; defaults to config values if omitted

### `/api/transfer/<id>` response

```json
{
  "id": 42,
  "status": "completed",
  "retry_count": 1,
  "updated_at": "2026-06-21 14:30:00"
}
```

### `/health` response

```json
{"status": "healthy", "db": "ok", "rabbitmq": "ok"}
```

Returns HTTP 200 when healthy, 503 when any component is unreachable.

---

## Security model

| Concern | Mitigation |
|---|---|
| CSRF | Flask-WTF `CSRFProtect`; token in `<meta>` tag; JS sets `X-CSRFToken` header |
| Zenodo API key exposure | Stored in server-side session only; never in DB or logs |
| Input injection | UUID/digit/regex validation on all user-supplied identifiers before use in SQL or API calls; parameterised SQL queries throughout |
| XSS | Jinja2 autoescaping enabled on all templates; no `{% autoescape false %}` |
| Insecure direct object reference | `get_transfer_by_id` enforces `AND username = %s`; users cannot access other users' transfers |
| File path traversal | `get_file_path` constructs paths from trusted config values + resource ID/URL components, not raw user input |
| Secrets in config | `settings.ini` is gitignored; Docker Compose mounts it as a read-only volume |

---

## Testing

### Setup

```bash
pip install -r requirements-dev.txt
```

### Running the suite

```bash
python -m pytest tests/ -v
```

No live services required. All external dependencies (DB, RabbitMQ, CKAN, Zenodo) are mocked.

### Test organisation

| File | Coverage |
|---|---|
| `tests/conftest.py` | Shared fixtures; session-level config patches |
| `tests/test_ckan_zenodo.py` | Business logic: file path resolution, duplicate detection, DB functions, export orchestration |
| `tests/test_server.py` | Flask routes and AJAX actions: validation, error handling, health endpoint, transfer status API |
| `tests/test_worker.py` | RabbitMQ callback: status updates, retry logic, backoff timing, ACK guarantees |

### Config patching strategy

`server.py` and `worker.py` call config getters at **module import time** (to set up Flask app config, logging, etc.). Standard fixtures cannot patch before this happens.

The solution is to use the `pytest_configure` hook in `conftest.py`:

```python
_patches = [
    patch('configs.get_db_config', return_value=DB_CONFIG),
    patch('configs.get_app_config', return_value=APP_CONFIG),
    # ...
]

def pytest_configure(config):
    for p in _patches:
        p.start()

def pytest_unconfigure(config):
    for p in _patches:
        p.stop()
```

This ensures patches are active before any test module triggers an import of `server` or `worker`.

### Session mocking

`export_to_zenodo` and `create_deposit_and_export` read from Flask's `session` object. In tests, patch `ckan_zenodo.session` directly:

```python
@pytest.fixture
def mock_session():
    fake_session = {'user': {'username': 'testuser', 'email': 'testuser@test.com', ...}}
    with patch('ckan_zenodo.session', fake_session):
        yield fake_session['user']
```

Do not use Flask's test request context for this — direct patching is simpler and more reliable.

### DB connection mocking

```python
@pytest.fixture
def mock_db_connection():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    with patch('db.get_connection', return_value=mock_conn):
        yield mock_conn, mock_cursor
```

Use `mock_cursor.execute.call_args[0]` to inspect SQL and parameters.

---

## Adding a migration

1. Create a new file in `migrations/` following the naming convention `NNN_description.sql` where `NNN` is the next sequential number (zero-padded to 3 digits).

2. Write idempotent SQL. Use `IF NOT EXISTS`, `IF EXISTS`, `ADD COLUMN IF NOT EXISTS`, etc.:

   ```sql
   ALTER TABLE zenodo_transfers
       ADD COLUMN IF NOT EXISTS new_column VARCHAR(255) NULL;
   ```

3. Update `sql/database.sql` to include the new column/table in the `CREATE TABLE` statement so that fresh installs get the complete schema without running migrations.

4. Run `python migrate.py --status` to verify it appears as pending, then `python migrate.py` to apply it.

---

## Adding a new AJAX action

1. **`ckan_zenodo.py`** — add the business logic function with appropriate exception types.

2. **`server.py`** — add an `elif action == "my_action":` block in the `ajax()` view:

   ```python
   elif action == "my_action":
       # 1. Check session
       if 'user' not in session:
           return render_template('result.html', message="Not authenticated.", back_button=False)

       # 2. Validate inputs
       my_param = request.form.get('my_param', '').strip()
       if not my_param:
           return render_template('result.html', message="Parameter required.", back_button=True)

       # 3. Call business logic
       try:
           ckan_zenodo.my_function(my_param)
           return render_template('result.html', message="Success.", back_button=True)
       except ckan_zenodo.SomeError as e:
           return render_template('result.html', message=str(e), back_button=True)
       except Exception as e:
           logging.error(f"Unexpected error in my_action: {e}")
           return render_template('result.html', message="An unexpected error occurred.", back_button=True)
   ```

3. **`static/functions.js`** — add the client-side AJAX call:

   ```javascript
   function my_action() {
       showProgress();
       $.ajax({
           type: "POST",
           url: "ajax",
           data: { action: "my_action", my_param: $('#my_input').val() },
           success: function(data) { $("#output").html(data); hideProgress(); },
           error: function() {
               $("#output").html('<div style="color:red;">An error occurred.</div>');
               hideProgress();
           },
           dataType: 'text'
       });
   }
   ```

4. **`tests/test_server.py`** — add tests for the success path and all validation/error branches.

---

## Extending the worker

To perform additional work after a successful upload (e.g. publish the Zenodo deposition, update a CKAN field, send a webhook):

1. Add the logic inside `worker.py`'s `callback()` function after the `update_transfer_status(transfer_id, 'completed', ...)` call.
2. Wrap it in a `try/except` so errors do not prevent the `basic_ack` from running:

   ```python
   response = upload_to_zenodo(...)
   update_transfer_status(transfer_id, 'completed', response, retry_count)

   try:
       publish_to_zenodo(task['zenodo_token'], task['deposition_id'])
   except Exception as e:
       logging.error(f"Could not publish deposition {task['deposition_id']}: {e}")
   ```

3. Add a corresponding config key if the behaviour should be toggleable.

---

## Running locally without Keycloak

For development, you can bypass SSO by temporarily adding a fake session in the Flask shell or by patching the login flow:

```python
# In a test script or Flask shell
with app.test_request_context():
    from flask import session
    session['user'] = {
        'username': 'devuser',
        'email': 'dev@example.com',
        'given_name': 'Dev',
        'family_name': 'User',
    }
```

Alternatively, add a development-only route:

```python
if app.config.get('TESTING') or os.environ.get('DEV_LOGIN'):
    @app.route('/dev-login')
    def dev_login():
        session['user'] = {'username': 'devuser', 'email': 'dev@example.com',
                           'given_name': 'Dev', 'family_name': 'User'}
        return redirect(url_for('home'))
```

**Never enable this in production.**

---

## Coding conventions

- **No module-level side effects** that depend on external services. Config loading (`configs.py`) is acceptable; DB connections and RabbitMQ connections must be lazy.
- **All SQL uses parameterised queries** — no string formatting of user data into SQL.
- **All external HTTP calls** (`requests.get/post/put/delete`) use `.raise_for_status()` so errors surface as `HTTPError` exceptions that callers can catch.
- **Comments only for non-obvious WHY**, not WHAT. Function names and type hints are the documentation.
- **Tests for every new AJAX action** — at least: success path, session-expired path, and each validation branch.
- **Migrations are idempotent** — use `IF NOT EXISTS` / `IF EXISTS` DDL variants.
- **`settings.ini` is gitignored** — never commit credentials or environment-specific paths.
