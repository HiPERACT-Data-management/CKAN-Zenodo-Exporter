# User Guide

This guide explains how to use the **CKAN to Zenodo Exporter** to publish datasets from a CKAN data portal to Zenodo.

---

## Table of Contents

- [Overview](#overview)
- [Before you start](#before-you-start)
- [Logging in](#logging-in)
- [Exporting a single resource](#exporting-a-single-resource)
  - [Option 1 — Export to an existing deposition](#option-1--export-to-an-existing-deposition)
  - [Option 2 — Create a new deposition](#option-2--create-a-new-deposition)
- [Exporting an entire dataset](#exporting-an-entire-dataset)
- [Monitoring transfers](#monitoring-transfers)
- [Retrying a failed transfer](#retrying-a-failed-transfer)
- [Email notifications](#email-notifications)
- [Frequently asked questions](#frequently-asked-questions)

---

## Overview

The exporter connects your institutional CKAN portal to your Zenodo account. Instead of downloading files from CKAN and uploading them manually to Zenodo, you can trigger the transfer directly from the CKAN resource page with a single click.

Transfers run in the background — you do not have to keep the browser open. You can check the status at any time on the **Transfers** page, which refreshes automatically every few seconds.

---

## Before you start

You need:

1. **An active Zenodo account** — register at [https://zenodo.org](https://zenodo.org)
2. **A Zenodo Personal Access Token** with upload permissions:
   - Log in to Zenodo
   - Go to **Account → Applications → Personal access tokens**
   - Click **New token**
   - Give it a name (e.g. `ckan-export`)
   - Under **Scopes**, check `deposit:actions` and `deposit:write`
   - Click **Create** and copy the token — you will not be able to see it again
3. **Institutional login credentials** for Keycloak SSO (the same username and password you use for your CKAN portal)

---

## Logging in

The exporter uses your institution's **Single Sign-On (SSO)** via Keycloak. When you visit the exporter for the first time (or after your session expires), you are automatically redirected to the login page.

Enter your institutional credentials and you will be redirected back to the exporter. Your login session is shared with CKAN — you do not need a separate password.

---

## Exporting a single resource

### Step 1 — Navigate to a resource in CKAN

Open your dataset in CKAN and find the resource you want to export. Under the resource, click **Explore → Export to Zenodo**.

You will be redirected to the exporter interface, which shows the resource name and pre-fills the title and description from the CKAN dataset metadata.

### Step 2 — Enter your Zenodo API key

Paste your **Zenodo Personal Access Token** into the **Zenodo API key** field.

> Your key is stored in your browser session on the server only — it is never saved to a database or logged. It stays valid until you close your browser or your session expires (typically 1 hour).

Click either **Select deposition** or **Create deposition** depending on whether you want to add the file to an existing Zenodo record or create a new one.

---

### Option 1 — Export to an existing deposition

1. Click **Select deposition**. The exporter fetches your depositions from Zenodo and shows them in a dropdown list.
2. Select the deposition you want to add the file to.
3. Click **Export this resource**.

The transfer is queued and you will see a confirmation message. Go to the **Transfers** page to track progress.

---

### Option 2 — Create a new deposition

1. Click **Create deposition**. The exporter pre-fills the title and description fields from the CKAN dataset.
2. Edit the **Deposition title** and **Deposition description** as needed.
3. Choose the **Upload type** — for example: Dataset, Software, Publication, Image.
4. Choose the **Access right**:
   - **Restricted** — only you can see and download the file on Zenodo (default)
   - **Open** — publicly visible and downloadable
   - **Embargoed** — open after a specified date
   - **Closed** — not downloadable even after publication
5. Click **Create deposition & export**.

The exporter creates the Zenodo deposition, then queues the file upload. You will see a confirmation message. Go to the **Transfers** page to track progress.

> If the resource file cannot be found on the server, the newly created deposition is automatically deleted to avoid leaving an empty record on Zenodo.

---

## Exporting an entire dataset

If you want to export **all resources** of a CKAN dataset to a single Zenodo deposition at once:

1. Open the export interface for any resource in the dataset.
2. Enter your Zenodo API key and click **Select deposition**.
3. Select the target deposition from the dropdown.
4. Click **Export all resources in dataset**.

The exporter fetches all resources in the CKAN package and queues an upload task for each one. The result message tells you how many files were queued, how many were skipped (already exported), and whether any errors occurred.

> Resources that have already been successfully exported to the same deposition are automatically skipped to avoid duplicates.

---

## Monitoring transfers

Go to **Transfers** (link in the top navigation bar) to see all your past and current transfers.

The table shows:

| Column | Description |
|---|---|
| File name | Name of the exported resource file |
| Deposition name | Title of the Zenodo deposition |
| Status | Current transfer state (see below) |
| Retry # | Number of automatic retry attempts so far |
| Created at | When the transfer was queued |
| Updated at | Last status change time |

### Transfer statuses

| Status | Meaning |
|---|---|
| `pending` | Queued, waiting for the worker to pick it up |
| `in_progress` | Worker is currently uploading the file to Zenodo |
| `completed` | File successfully uploaded to Zenodo |
| `failed` | All retry attempts exhausted; upload did not succeed |

The page **auto-refreshes** every 5 seconds for any transfer in `pending` or `in_progress` state. You do not need to reload the page manually.

---

## Retrying a failed transfer

If a transfer shows `failed` status, a **Retry** button appears in the action column.

Before clicking **Retry**, make sure you have entered your Zenodo API key in the current browser session (go to the export page and click **Select deposition** or **Create deposition** with your key). The retry reuses the stored session key.

Click **Retry** — the transfer is reset and re-queued. The status changes to `pending` and the upload restarts from the beginning.

> If your browser session has expired and the API key is no longer stored, you will see a "Session expired" message. Navigate back to the export page, re-enter your key, and then retry.

---

## Email notifications

If your administrator has enabled email notifications, you will automatically receive an email at the address registered in your institutional account when:

- A transfer **completes successfully**
- A transfer **fails** after all automatic retries are exhausted

No configuration is needed on your end — notifications use the email address from your SSO profile.

---

## Frequently asked questions

**How long does a transfer take?**
It depends on the file size and Zenodo's API availability. Small files (a few MB) typically complete within seconds. Large files (hundreds of MB to GB) may take several minutes. The upload runs in the background — you do not need to keep the browser open.

**What happens if the upload fails?**
The worker automatically retries up to the configured maximum (default: 3 retries). The delay between retries increases each time (10 s → 20 s → 40 s …). If all retries fail, the transfer is marked as `failed` and you can retry it manually from the Transfers page.

**Can I export the same file twice?**
If you try to export the same resource to the same deposition and a non-failed transfer already exists for that combination, the exporter warns you and does not create a duplicate. If the previous transfer failed, you can use the **Retry** button or start a new export.

**Will my Zenodo API key be stored?**
No. The key is held only in your server-side session for the duration of your browser session (up to 1 hour). It is never written to the database or log files.

**Can I publish (submit) the Zenodo deposition through the exporter?**
Not at this time. The exporter uploads files and sets metadata, but the final publication step (clicking **Publish** on Zenodo) must be done manually on zenodo.org. This is intentional — it gives you the opportunity to review the metadata and add co-authors or funding information before making the record public.

**What is the Zenodo sandbox?**
The sandbox (`sandbox.zenodo.org`) is a test environment provided by Zenodo. Uploads there do not affect your production Zenodo account and are periodically wiped. Your administrator can enable sandbox mode for testing. If sandbox mode is active, a notice should appear from your administrator.

**Who do I contact if something goes wrong?**
Contact your CKAN / data management administrator. They can check the transfer logs and the exporter's health endpoint for diagnostic information.
