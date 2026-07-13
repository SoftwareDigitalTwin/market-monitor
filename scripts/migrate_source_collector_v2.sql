-- Source Collector V2
-- MySQL 8+
-- No modifica ni elimina tablas existentes.

CREATE TABLE IF NOT EXISTS source_listings (
    id BIGINT NOT NULL AUTO_INCREMENT,
    source_id INT NOT NULL,
    listing_key VARCHAR(64) NOT NULL,
    external_id VARCHAR(200) NULL,
    canonical_url VARCHAR(1000) NOT NULL,

    status VARCHAR(30) NOT NULL DEFAULT 'active',
    missing_streak INT NOT NULL DEFAULT 0,
    reappearance_count INT NOT NULL DEFAULT 0,

    first_seen_date DATE NOT NULL,
    last_seen_date DATE NOT NULL,
    inactive_at DATE NULL,
    detail_last_scraped_date DATE NULL,

    last_seen_run_id INT NULL,
    latest_raw_listing_id INT NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uq_source_listing_key (source_id, listing_key),
    KEY ix_source_listing_status (source_id, status),
    KEY ix_source_listing_last_seen (source_id, last_seen_date),
    KEY ix_source_listing_external_id (source_id, external_id),
    KEY ix_source_listing_last_seen_run (source_id, last_seen_run_id),

    CONSTRAINT fk_source_listing_source
        FOREIGN KEY (source_id) REFERENCES data_sources(id),
    CONSTRAINT fk_source_listing_last_run
        FOREIGN KEY (last_seen_run_id) REFERENCES scraping_runs(id),
    CONSTRAINT fk_source_listing_latest_raw
        FOREIGN KEY (latest_raw_listing_id) REFERENCES raw_listings(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS source_listing_events (
    id BIGINT NOT NULL AUTO_INCREMENT,
    source_listing_id BIGINT NOT NULL,
    run_id INT NULL,
    event_type VARCHAR(40) NOT NULL,
    detected_date DATE NOT NULL,
    event_data JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    KEY ix_source_listing_event_listing (source_listing_id),
    KEY ix_source_listing_event_type_date (event_type, detected_date),

    CONSTRAINT fk_source_listing_event_listing
        FOREIGN KEY (source_listing_id) REFERENCES source_listings(id),
    CONSTRAINT fk_source_listing_event_run
        FOREIGN KEY (run_id) REFERENCES scraping_runs(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS source_scan_metrics (
    id BIGINT NOT NULL AUTO_INCREMENT,
    run_id INT NOT NULL,
    source_id INT NOT NULL,
    scan_date DATE NOT NULL,

    discovery_complete BOOLEAN NOT NULL DEFAULT FALSE,
    safety_passed BOOLEAN NOT NULL DEFAULT FALSE,
    stop_reason VARCHAR(200) NULL,

    baseline_active INT NOT NULL DEFAULT 0,
    seen_count INT NOT NULL DEFAULT 0,
    new_count INT NOT NULL DEFAULT 0,
    reappeared_count INT NOT NULL DEFAULT 0,
    missing_suspected_count INT NOT NULL DEFAULT 0,
    inactive_confirmed_count INT NOT NULL DEFAULT 0,
    detail_scraped_count INT NOT NULL DEFAULT 0,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uq_source_scan_metric_run (run_id),
    KEY ix_source_scan_metric_source_date (source_id, scan_date),

    CONSTRAINT fk_source_scan_metric_run
        FOREIGN KEY (run_id) REFERENCES scraping_runs(id),
    CONSTRAINT fk_source_scan_metric_source
        FOREIGN KEY (source_id) REFERENCES data_sources(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
