-- Example schema for a simple ticketing table
CREATE TABLE IF NOT EXISTS Tickets (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Title TEXT NOT NULL,
    Description TEXT,
    CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
    Status TEXT DEFAULT 'Open'
);

INSERT INTO Tickets (Title, Description, Status) VALUES ('Sample ticket', 'This is a seed ticket', 'Open');
