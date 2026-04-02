CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    role ENUM('fan', 'manager') DEFAULT 'fan',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_tickets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    userId INT NOT NULL,
    ticketId VARCHAR(50),
    eventId VARCHAR(50),
    eventName VARCHAR(100),
    venue VARCHAR(100),
    date VARCHAR(50),
    status ENUM('active', 'refunded', 'cancelled') DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_tickets_userId (userId),
    INDEX idx_user_tickets_eventId (eventId),
    INDEX idx_user_tickets_ticketId (ticketId)
);

CREATE TABLE IF NOT EXISTS managed_events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    managerId INT NOT NULL,
    eventId VARCHAR(50),
    name VARCHAR(100),
    venue VARCHAR(100),
    date VARCHAR(50),
    price DECIMAL(10,2),
    status ENUM('active', 'cancelled') DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_managed_events_managerId (managerId),
    INDEX idx_managed_events_eventId (eventId)
);

INSERT INTO users (id, name, email, role)
VALUES
  (1, 'Alice Fan', 'fan@example.com', 'fan'),
  (2, 'Noah Fan', 'fan2@example.com', 'fan'),
  (3, 'Chloe Fan', 'fan3@example.com', 'fan'),
  (99, 'Maya Manager', 'manager@example.com', 'manager'),
  (123, 'Legacy Fan', 'legacyfan@example.com', 'fan')
ON DUPLICATE KEY UPDATE
  name = VALUES(name),
  email = VALUES(email),
  role = VALUES(role);

INSERT INTO managed_events (managerId, eventId, name, venue, date, price, status)
VALUES
  (99, 'EVT1001', 'The Midnight World Tour', 'Marina Bay Sands, Singapore', '2026-08-15', 88.00, 'active'),
  (99, 'EVT1002', 'Neon Bloom Live', 'Singapore Indoor Stadium', '2026-09-22', 98.00, 'active'),
  (99, '1', 'Pulse Arena Nights', 'Capitol Theatre, Singapore', '2026-04-18', 80.00, 'active'),
  (99, '2', 'Skyline VIP Session', 'Singapore Indoor Stadium', '2026-05-02', 200.00, 'active'),
  (99, '789', 'Harbour Lights Reunion', 'The Star Theatre, Singapore', '2026-03-10', 150.00, 'cancelled')
;

INSERT INTO user_tickets (userId, ticketId, eventId, eventName, venue, date, status)
VALUES
  (123, '456', '789', 'Harbour Lights Reunion', 'The Star Theatre, Singapore', '2026-03-10', 'refunded'),
  (1, '1', '1', 'Pulse Arena Nights', 'Capitol Theatre, Singapore', '2026-04-18', 'cancelled'),
  (2, '2', '1', 'Pulse Arena Nights', 'Capitol Theatre, Singapore', '2026-04-18', 'active'),
  (3, '3', '2', 'Skyline VIP Session', 'Singapore Indoor Stadium', '2026-05-02', 'active')
;
