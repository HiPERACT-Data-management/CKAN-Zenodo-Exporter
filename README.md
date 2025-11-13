# CKAN to Zenodo Exporter

**CKAN to Zenodo Exporter** is a tool that automates the export of datasets from a **CKAN** instance to **Zenodo**.  
It uses Flask for the web interface, RabbitMQ for background task management, and MySQL (MariaDB) for storing export metadata.

<p>
  <img src="docs/images/ckan_zenodo_flow.svg" alt="CKAN to Zenodo Exporter Diagram"/>
</p>

---

## 🧩 Features

- Export CKAN datasets and metadata directly to Zenodo via API  
- Supports multiple users and resource paths  
- Keycloak SSO integration  
- RabbitMQ-based background queue for transfers  
- Backend built with Flask + Waitress  

---

## ⚙️ Requirements

- Python 3.8+
- RabbitMQ server
- MySQL or MariaDB
- Access to a CKAN instance with an API key
- Zenodo account with an active API token

---

## 🚀 Installation

### 1️⃣ Create a Python virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2️⃣ Install dependencies

Install required Python modules listed in `requirements.txt`:

```bash
pip install -r requirements.txt
```

**Main dependencies:**
- Flask  
- waitress  
- requests  
- ckanapi  
- pika  
- pymysql  

### 3️⃣ Install RabbitMQ and MariaDB

```bash
sudo apt install rabbitmq-server mariadb-server
```

Create the database and tables:

```bash
mysql -u root < exporter.sql
```

---

## ⚙️ Configuration

Edit the `settings.ini` file and fill in your configuration values:

```ini
[app]
secret_key=
log_file=

[ckan]
server=https://ckan.example.com
apikey=
resources_path=/mnt/vol/ckan/default/resources
resources_usr_path=/mnt/vol/homes/{user}/ckan-pub
resources_usr_url=https://ckan.example.com:8443/~

[mysql]
host = localhost
user = 
password = 
database = zenodo_export

[sso]
keycloak_server_url =
realm_name =
client_id =
client_secret =
redirect_uri = 

[rabbitmq]
host = localhost
queue = zenodo_upload

[zenodo]
api_url = https://zenodo.org/api/deposit/depositions
```

---

## 🧠 System Services

Create two systemd service files in `/etc/systemd/system/`.

### `ckan-export.service`

```ini
[Unit]
Description=CKAN to ZENODO Exporter Service
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

### `zenodo-worker.service`

```ini
[Unit]
Description=Zenodo Upload Worker Service
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

Enable and start both services:

```bash
sudo systemctl enable ckan-export.service zenodo-worker.service
sudo systemctl start ckan-export.service zenodo-worker.service
```

---

## 🧩 CKAN Integration

To add an **"Export to Zenodo"** option in CKAN, edit the file:

```
/usr/lib/ckan/default/src/ckan/ckan/templates/package/snippets/resource_item.html
```

Add the following snippet inside the resource menu:

```html
{% if 'https://ckan.example.com' in res.url %}
  <li>
    <a class="dropdown-item" href="{{ 'https://ckan.example.com:9443/export?resource=' + res.id }}">
      <i class="fa fa-book"></i>
      {{ _('Export to ZENODO') }}
    </a>
  </li>
{% endif %}
```

---

## 🧰 Project Structure

```
ckan-export/
├── server.py          # Flask server
├── worker.py          # Background worker handling Zenodo uploads
├── exporter.sql       # Database schema
├── settings.ini       # Application configuration
├── requirements.txt   # Dependencies
└── README.md          # Documentation
```

---

## 📖 User Manual

See the detailed user guide here: [USER_MANUAL.md](USER_MANUAL.md)

---

## 🧑‍💻 Authors

Developed by ** PSNC **  
📧 pdzierzak@man.poznan.pl, lawenda@man.poznan.pl  
🔗 PSNC https://psnc.pl

---

## 📄 License

This project is released under the **MIT License** (or specify another if preferred).

---

## 🧪 How It Works

1. The user selects a resource in CKAN.  
2. Clicking **Export to Zenodo** redirects to the exporter interface.  
3. The exporter queues the transfer task in RabbitMQ.  
4. The worker uploads the dataset to Zenodo using the API.  
5. The user receives a confirmation and link to the published record.

---

> 💡 **Tip:**  
> Add a `.env` file for local environment variables and a `.gitignore` file to avoid committing sensitive information.
