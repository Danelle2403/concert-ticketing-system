CREATE TABLE IF NOT EXISTS events (
    eventId VARCHAR(50) PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    venue VARCHAR(120) NOT NULL,
    date VARCHAR(50) NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    genre VARCHAR(50) DEFAULT 'Live',
    defaultSeatCategory VARCHAR(50) DEFAULT 'CAT1',
    status ENUM('active', 'cancelled', 'deleted') DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

INSERT INTO events (eventId, name, venue, date, price, genre, defaultSeatCategory, status)
VALUES
  ('EVT1001', 'The Midnight World Tour', 'Marina Bay Sands, Singapore', '2026-08-15', 88.00, 'electronic', 'VIP', 'active'),
  ('EVT1002', 'Neon Bloom Live', 'Singapore Indoor Stadium', '2026-09-22', 98.00, 'pop', 'CAT1', 'active'),
  ('EVT1003', 'Wave Artist Live', 'Esplanade Theatre', '2026-10-10', 78.00, 'hiphop', 'CAT2', 'active')
ON DUPLICATE KEY UPDATE
  name = VALUES(name),
  venue = VALUES(venue),
  date = VALUES(date),
  price = VALUES(price),
  genre = VALUES(genre),
  defaultSeatCategory = VALUES(defaultSeatCategory),
  status = VALUES(status),
  updated_at = CURRENT_TIMESTAMP;
