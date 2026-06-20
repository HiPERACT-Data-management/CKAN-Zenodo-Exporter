-- Initial schema: zenodo_transfers table
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
