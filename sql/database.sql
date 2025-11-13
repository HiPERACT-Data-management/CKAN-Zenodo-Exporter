CREATE DATABASE IF NOT EXISTS zenodo_export CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'zenodo_user'@'localhost' IDENTIFIED BY 'STRONG-PASSWORD';
GRANT ALL PRIVILEGES ON zenodo_export.* TO 'zenodo_user'@'localhost';
FLUSH PRIVILEGES;

USE zenodo_export;

CREATE TABLE IF NOT EXISTS zenodo_transfers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(255) NOT NULL,
    file_path VARCHAR(1024) NOT NULL,
    filename VARCHAR(255) NOT NULL,
    deposition_id VARCHAR(50) NOT NULL,
    deposition_name VARCHAR(255),
    status ENUM('pending', 'in_progress', 'completed', 'failed') DEFAULT 'pending',
    zenodo_response TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
