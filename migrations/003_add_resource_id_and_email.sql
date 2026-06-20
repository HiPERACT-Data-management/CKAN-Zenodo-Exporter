-- Store the CKAN resource_id for duplicate detection and user_email for notifications.
ALTER TABLE zenodo_transfers
    ADD COLUMN IF NOT EXISTS resource_id VARCHAR(100) NULL AFTER deposition_name,
    ADD COLUMN IF NOT EXISTS user_email VARCHAR(255) NULL AFTER username;
