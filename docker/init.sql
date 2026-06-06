-- Called by postgres entrypoint on first start.
-- Creates a second database for Airflow metadata alongside the pipeline DB.
CREATE DATABASE airflow;
GRANT ALL PRIVILEGES ON DATABASE airflow TO pipeline;
