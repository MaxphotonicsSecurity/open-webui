\set ON_ERROR_STOP on

-- Run while connected to the postgres maintenance database as postgres.
-- CREATE DATABASE cannot run inside a transaction; \gexec executes it separately.
SELECT 'CREATE DATABASE openwebui OWNER postgres TEMPLATE template0'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'openwebui')
\gexec

\connect openwebui
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

SELECT current_database(), extname, extversion
FROM pg_extension
WHERE extname = 'vector';
