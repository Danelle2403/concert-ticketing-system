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
