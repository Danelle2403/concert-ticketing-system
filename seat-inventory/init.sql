CREATE TABLE IF NOT EXISTS seat_inventory (
    id INT AUTO_INCREMENT PRIMARY KEY,
    eventId VARCHAR(50) NOT NULL,
    seatCategory VARCHAR(50) NOT NULL,
    totalSeats INT NOT NULL,
    availableSeats INT NOT NULL,
    createdAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_event_category (eventId, seatCategory),
    CHECK (totalSeats >= 0),
    CHECK (availableSeats >= 0),
    CHECK (availableSeats <= totalSeats)
);

CREATE TABLE IF NOT EXISTS seat_holds (
    holdId VARCHAR(36) PRIMARY KEY,
    eventId VARCHAR(50) NOT NULL,
    seatCategory VARCHAR(50) NOT NULL,
    quantity INT NOT NULL,
    status ENUM('HELD', 'CONFIRMED', 'RELEASED', 'EXPIRED') NOT NULL,
    expiresAt DATETIME NOT NULL,
    confirmedAt DATETIME NULL,
    releasedAt DATETIME NULL,
    releaseReason VARCHAR(100) NULL,
    createdAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_holds_status_expires (status, expiresAt),
    INDEX idx_holds_event_category (eventId, seatCategory),
    CHECK (quantity > 0)
);

INSERT INTO seat_inventory (eventId, seatCategory, totalSeats, availableSeats)
VALUES
  ('EVT1001', 'VIP', 50, 50),
  ('EVT1001', 'CAT1', 120, 120),
  ('EVT1001', 'CAT2', 200, 200),
  ('EVT1002', 'VIP', 40, 40),
  ('EVT1002', 'CAT1', 150, 150),
  ('EVT1002', 'CAT2', 250, 250),
  ('1', 'VIP', 40, 40),
  ('1', 'STANDARD', 150, 149),
  ('2', 'VIP', 60, 59),
  ('789', 'VIP', 80, 80)
ON DUPLICATE KEY UPDATE
  totalSeats = VALUES(totalSeats),
  availableSeats = VALUES(availableSeats),
  updatedAt = CURRENT_TIMESTAMP;

INSERT INTO seat_holds
    (holdId, eventId, seatCategory, quantity, status, expiresAt, confirmedAt, releasedAt, releaseReason, createdAt, updatedAt)
VALUES
    ('11111111-1111-1111-1111-111111111111', '789', 'VIP', 1, 'RELEASED', '2026-03-27 05:47:46', '2026-03-27 05:42:46', '2026-03-27 21:25:49', 'REFUND', '2026-03-27 05:42:46', '2026-03-27 21:25:49'),
    ('22222222-2222-2222-2222-222222222222', '1', 'VIP', 1, 'RELEASED', '2026-03-27 21:20:59', '2026-03-27 21:15:59', '2026-03-27 21:26:14', 'ORDER_CANCELLED', '2026-03-27 21:15:59', '2026-03-27 21:26:14'),
    ('33333333-3333-3333-3333-333333333333', '1', 'STANDARD', 1, 'CONFIRMED', '2026-12-31 23:59:59', '2026-03-27 21:16:23', NULL, NULL, '2026-03-27 21:16:23', '2026-03-27 21:16:23'),
    ('44444444-4444-4444-4444-444444444444', '2', 'VIP', 1, 'CONFIRMED', '2026-12-31 23:59:59', '2026-03-27 21:16:49', NULL, NULL, '2026-03-27 21:16:49', '2026-03-27 21:16:49')
ON DUPLICATE KEY UPDATE
    eventId = VALUES(eventId),
    seatCategory = VALUES(seatCategory),
    quantity = VALUES(quantity),
    status = VALUES(status),
    expiresAt = VALUES(expiresAt),
    confirmedAt = VALUES(confirmedAt),
    releasedAt = VALUES(releasedAt),
    releaseReason = VALUES(releaseReason),
    updatedAt = VALUES(updatedAt);
