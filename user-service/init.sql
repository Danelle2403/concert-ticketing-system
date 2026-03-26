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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
