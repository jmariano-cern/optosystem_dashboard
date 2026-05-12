#!/bin/bash

DEFAULT_INTERVAL=30
INTERVAL=${1:-${DEFAULT_INTERVAL}}

echo "Creating crontab (requires sudo)"
sudo crontab -l > crontab_0
echo "####################################"
echo "## Previous crontab"
echo "####################################"
cat crontab_0
grep -v read_db.py crontab_0 > crontab_1
printf "*/${INTERVAL} * * * * /usr/bin/python3 $(realpath $(dirname "$0")/read_db.py)\n" > crontab_1
echo "####################################"
echo "## New crontab"
echo "####################################"
cat crontab_1
read -p "Install new crontab? (y/N) " -n 1 -r
echo    # (optional) move to a new line
if [[ $REPLY =~ ^[Yy]$ ]]
then
    sudo crontab crontab_1
fi
rm crontab_0
rm crontab_1
echo "####################################"
echo "## Current system crontab"
echo "####################################"
sudo crontab -l
