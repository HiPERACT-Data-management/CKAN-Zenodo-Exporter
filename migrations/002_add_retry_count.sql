-- Track how many times an upload has been retried
ALTER TABLE zenodo_transfers
    ADD COLUMN IF NOT EXISTS retry_count INT NOT NULL DEFAULT 0;
