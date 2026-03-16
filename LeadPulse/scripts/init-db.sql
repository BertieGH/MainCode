-- Grant privileges for creating tenant databases
GRANT ALL PRIVILEGES ON *.* TO 'leadpulse'@'%' WITH GRANT OPTION;
FLUSH PRIVILEGES;

-- Seed subscription plans
USE leadpulse_app;

CREATE TABLE IF NOT EXISTS SubscriptionPlans (
    Id INT PRIMARY KEY AUTO_INCREMENT,
    Name VARCHAR(50) NOT NULL,
    MaxUsers INT NOT NULL,
    MaxSocialAccounts INT NOT NULL,
    MaxKeywords INT NOT NULL,
    MaxApiCallsPerDay INT NOT NULL,
    DedicatedDbServer BOOLEAN DEFAULT FALSE,
    PriceMonthly DECIMAL(10,2),
    IsActive BOOLEAN DEFAULT TRUE
);

INSERT INTO SubscriptionPlans (Name, MaxUsers, MaxSocialAccounts, MaxKeywords, MaxApiCallsPerDay, DedicatedDbServer, PriceMonthly) VALUES
('Starter', 2, 3, 10, 1000, FALSE, 49.00),
('Professional', 5, 5, 25, 5000, FALSE, 149.00),
('Enterprise', 999, 10, 9999, 25000, TRUE, 499.00);
