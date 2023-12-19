#!/bin/sh

set -e

if [ "$DATABASE" = "sqlite" ] && [ "$LIVE" = "1" ]
then
    echo "Creating the database tables..."
    flask create_db
    echo "Tables created"
fi

service cron start
echo "cron service started" 

exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf