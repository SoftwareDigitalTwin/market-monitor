-- Script para crear la base de datos y usuario en MySQL 8+
-- Ejecutar como administrador:
--   mysql -u root -p < setup_db.sql

CREATE DATABASE IF NOT EXISTS dtc_market
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'dtc_user'@'%' IDENTIFIED BY 'dtc_password';
CREATE USER IF NOT EXISTS 'dtc_user'@'localhost' IDENTIFIED BY 'dtc_password';

GRANT ALL PRIVILEGES ON dtc_market.* TO 'dtc_user'@'%';
GRANT ALL PRIVILEGES ON dtc_market.* TO 'dtc_user'@'localhost';
FLUSH PRIVILEGES;
