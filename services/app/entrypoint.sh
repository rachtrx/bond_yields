#!/bin/sh

set -e

if [ "$DATABASE" = "postgres" ]
then
    echo "Waiting for postgres..."

    while ! pg_isready -h $SQL_HOST -p $SQL_PORT -q; do
      echo "Waiting for PostgreSQL to start..."
      sleep 1
  done

    echo "PostgreSQL started"
    echo "Creating the database tables..."
    flask create_db
    echo "Tables created"
fi

service cron start
echo "cron service started" 

exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf