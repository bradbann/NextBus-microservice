#!/bin/bash
sh nextbus.sh
service cron start
/usr/bin/crontab /etc/cron.d/nextbus-cron
python3 nextbus.py
