-- Flyway migration (OceanBase / MySQL dialect). All DDL lives here, never in code.
-- A small JSON document store: one row per (collection, document id).

CREATE TABLE docs (
    coll        VARCHAR(64)  NOT NULL,
    doc_id      VARCHAR(200) NOT NULL,
    data        LONGTEXT     NOT NULL,
    updated_at  DATETIME(6)  NOT NULL,
    updated_by  VARCHAR(255) NULL,
    PRIMARY KEY (coll, doc_id)
) DEFAULT CHARSET=utf8mb4;

-- Revision counter per collection: bumped on every write so clients can poll cheaply.
CREATE TABLE coll_rev (
    coll  VARCHAR(64) NOT NULL,
    rev   BIGINT      NOT NULL DEFAULT 0,
    PRIMARY KEY (coll)
) DEFAULT CHARSET=utf8mb4;
