-- Run this once in the Supabase SQL Editor to set up your schema.
-- Dashboard → SQL Editor → New Query → paste → Run

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id       BIGSERIAL   PRIMARY KEY,
    event_id        BIGINT      NOT NULL,
    seat_row        TEXT,
    seat_number     TEXT,
    seat_section    TEXT,
    is_valid        BOOLEAN     NOT NULL DEFAULT TRUE,
    issued_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    invalidated_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tickets_event_id ON tickets (event_id);
