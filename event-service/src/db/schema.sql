CREATE TABLE IF NOT EXISTS events (
  id UUID PRIMARY KEY,
  manager_id INTEGER,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  start_at TIMESTAMPTZ NOT NULL,
  end_at TIMESTAMPTZ NOT NULL,
  status VARCHAR(20) NOT NULL CHECK (status IN ('DRAFT', 'PUBLISHED', 'RESCHEDULED', 'CANCELLED', 'COMPLETED')),
  venue_name TEXT NOT NULL,
  venue_address TEXT,
  venue_city TEXT,
  venue_country TEXT,
  published_at TIMESTAMPTZ,
  cancelled_at TIMESTAMPTZ,
  cancellation_reason TEXT,
  changed_by TEXT,
  changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE events
ADD COLUMN IF NOT EXISTS manager_id INTEGER;

CREATE TABLE IF NOT EXISTS pricing_tiers (
  id UUID PRIMARY KEY,
  event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  price NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
  currency CHAR(3) NOT NULL,
  description TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (event_id, code)
);

CREATE TABLE IF NOT EXISTS seat_sections (
  id UUID PRIMARY KEY,
  event_id UUID NOT NULL,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  pricing_tier_code TEXT NOT NULL,
  capacity INTEGER CHECK (capacity IS NULL OR capacity >= 0),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (event_id, code),
  CONSTRAINT fk_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
  CONSTRAINT fk_pricing_tier FOREIGN KEY (event_id, pricing_tier_code)
    REFERENCES pricing_tiers(event_id, code)
    ON UPDATE CASCADE
    ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS reschedule_history (
  id UUID PRIMARY KEY,
  event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  previous_start_at TIMESTAMPTZ NOT NULL,
  previous_end_at TIMESTAMPTZ NOT NULL,
  previous_venue_name TEXT NOT NULL,
  previous_venue_address TEXT,
  previous_venue_city TEXT,
  previous_venue_country TEXT,
  new_start_at TIMESTAMPTZ NOT NULL,
  new_end_at TIMESTAMPTZ NOT NULL,
  new_venue_name TEXT NOT NULL,
  new_venue_address TEXT,
  new_venue_city TEXT,
  new_venue_country TEXT,
  reason TEXT,
  changed_by TEXT,
  changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
CREATE INDEX IF NOT EXISTS idx_events_manager_id ON events(manager_id);
CREATE INDEX IF NOT EXISTS idx_events_start_at ON events(start_at);
CREATE INDEX IF NOT EXISTS idx_events_venue_name ON events(venue_name);
