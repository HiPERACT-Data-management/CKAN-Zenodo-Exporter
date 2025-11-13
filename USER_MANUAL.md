# 📘 CKAN to Zenodo — User Manual

This manual explains how to use the **CKAN to Zenodo Exporter** to transfer datasets from CKAN directly to your **Zenodo** account.

---

## 🧩 Overview

The **CKAN to Zenodo Exporter** allows CKAN users to export resources to Zenodo deposits directly from the CKAN web interface.  
Users can either create a **new deposition** on Zenodo or **upload to an existing one** using their personal Zenodo API key.

---

## 🪄 Prerequisites

Before using the exporter:

1. You must have an active **Zenodo account** → [https://zenodo.org](https://zenodo.org)
2. Obtain your **Zenodo API key**:
   - Go to **Account Settings → Applications**
   - Generate a **Personal Access Token**
   - Copy the key to use it in the exporter

---

## 🚀 Exporting a Resource

1. Open your dataset in **CKAN**  
   Example:  
   `https://ckan.example.com/dataset/my-dataset`

2. Under the desired resource, click **Explore → Export to ZENODO**

3. You will be redirected to the **CKAN to Zenodo Exporter** page.

4. On the exporter page:
   - Paste your **Zenodo API key**
   - Choose one of the following:
     - **Create a new deposition**, or  
     - **Upload to an existing deposition**

5. Click **Export to ZENODO** to start the transfer.

---

## 📦 Monitoring Transfers

Once the export starts, the transfer runs in the background.

To check transfer progress:
1. Go to the **Transfers** section in the exporter interface.
2. You will see:
   - Pending uploads  
   - Completed exports  
   - Any errors that occurred  

---

## ⚠️ Notes & Recommendations

- Large datasets may take several minutes to transfer, depending on Zenodo’s API response time.  
- Ensure your Zenodo API key has permission to upload files.  
- Do **not share** your API key — it grants full access to your Zenodo account.  
- If the transfer fails, review exporter logs or contact your CKAN administrator.

---

## 🔗 Useful Links

- [Zenodo](https://zenodo.org)  
- [Zenodo API Documentation](https://developers.zenodo.org/)  
- [CKAN Documentation](https://docs.ckan.org/)  

---

## 🧑‍💻 Support

If you encounter issues, contact your CKAN administrator or the maintainer of the **CKAN to Zenodo Exporter**.

---

*Version:* 1.0  
*Last updated:* October 2025
