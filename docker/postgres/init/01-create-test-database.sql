-- Runs once, when the database volume is first initialized (Postgres image
-- convention: scripts in /docker-entrypoint-initdb.d). Creates the separate
-- database the test suite uses; its name must end in "_test".
CREATE DATABASE repair_shop_test;
