#!/bin/sh
gunicorn --bind 0.0.0.0:3000 --workers 3 habits.wsgi:application