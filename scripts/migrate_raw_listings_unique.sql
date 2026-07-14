-- Compact raw_listings into one row per source/listing_key.
-- MySQL 8+
--
-- Keeps the latest row by (capture_date, id), updates source_listings to point
-- to that row, removes old photo metadata if the legacy listing_images table
-- exists, then adds a unique index without capture_date.

SET @view_history_exists = (
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'source_listings'
      AND column_name = 'view_history'
);

SET @add_view_history_sql = IF(
    @view_history_exists = 0,
    'ALTER TABLE source_listings ADD COLUMN view_history JSON NULL AFTER last_seen_date',
    'SELECT ''source_listings.view_history already exists'' AS info'
);
PREPARE add_view_history_stmt FROM @add_view_history_sql;
EXECUTE add_view_history_stmt;
DEALLOCATE PREPARE add_view_history_stmt;

CREATE TEMPORARY TABLE source_listing_view_history AS
SELECT
    source_id,
    listing_key,
    JSON_OBJECTAGG(capture_date, views) AS view_history
FROM (
    SELECT
        source_id,
        listing_key,
        capture_date,
        COUNT(*) AS views
    FROM raw_listings
    GROUP BY source_id, listing_key, capture_date
) daily_views
GROUP BY source_id, listing_key;

UPDATE source_listings sl
JOIN source_listing_view_history history
  ON history.source_id = sl.source_id
 AND history.listing_key = sl.listing_key
SET sl.view_history = history.view_history;

CREATE TEMPORARY TABLE raw_listing_keep_ids AS
SELECT keep_rows.id AS keep_id, keep_rows.source_id, keep_rows.listing_key
FROM raw_listings keep_rows
JOIN (
    SELECT source_id, listing_key, MAX(CONCAT(capture_date, '#', LPAD(id, 20, '0'))) AS keep_token
    FROM raw_listings
    GROUP BY source_id, listing_key
) latest
  ON latest.source_id = keep_rows.source_id
 AND latest.listing_key = keep_rows.listing_key
 AND latest.keep_token = CONCAT(keep_rows.capture_date, '#', LPAD(keep_rows.id, 20, '0'));

CREATE TEMPORARY TABLE raw_listing_delete_ids AS
SELECT rl.id
FROM raw_listings rl
LEFT JOIN raw_listing_keep_ids keep_ids ON keep_ids.keep_id = rl.id
WHERE keep_ids.keep_id IS NULL;

UPDATE source_listings sl
JOIN raw_listing_keep_ids keep_ids
  ON keep_ids.source_id = sl.source_id
 AND keep_ids.listing_key = sl.listing_key
SET sl.latest_raw_listing_id = keep_ids.keep_id,
    sl.detail_last_scraped_date = COALESCE(sl.detail_last_scraped_date, sl.last_seen_date);

SET @listing_images_exists = (
    SELECT COUNT(*)
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = 'listing_images'
);

SET @delete_listing_images_sql = IF(
    @listing_images_exists > 0,
    'DELETE li FROM listing_images li JOIN raw_listing_delete_ids d ON d.id = li.raw_listing_id',
    'SELECT ''legacy listing_images table not present'' AS info'
);
PREPARE delete_listing_images_stmt FROM @delete_listing_images_sql;
EXECUTE delete_listing_images_stmt;
DEALLOCATE PREPARE delete_listing_images_stmt;

DELETE rl
FROM raw_listings rl
JOIN raw_listing_delete_ids d ON d.id = rl.id;

SET @raw_unique_exists = (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'raw_listings'
      AND index_name = 'uq_raw_source_listing_key'
);

SET @add_raw_unique_sql = IF(
    @raw_unique_exists = 0,
    'ALTER TABLE raw_listings ADD UNIQUE INDEX uq_raw_source_listing_key (source_id, listing_key)',
    'SELECT ''uq_raw_source_listing_key already exists'' AS info'
);
PREPARE add_raw_unique_stmt FROM @add_raw_unique_sql;
EXECUTE add_raw_unique_stmt;
DEALLOCATE PREPARE add_raw_unique_stmt;

SELECT
    ds.name AS source,
    COUNT(*) AS raw_unique_rows
FROM raw_listings rl
JOIN data_sources ds ON ds.id = rl.source_id
GROUP BY ds.name
ORDER BY ds.name;
