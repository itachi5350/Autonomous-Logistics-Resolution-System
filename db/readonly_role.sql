   DO $$
   BEGIN
       IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'logistics_ro') THEN
           CREATE ROLE logistics_ro LOGIN PASSWORD 'readonly_dev';
       END IF;
   END $$;

   GRANT USAGE ON SCHEMA public TO logistics_ro;
   GRANT SELECT ON customers, products, orders, shipments, inventory TO logistics_ro;
   ALTER ROLE logistics_ro SET statement_timeout = '5s';
   ALTER ROLE logistics_ro SET default_transaction_read_only = on;