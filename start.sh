#!/bin/bash

# Gunicorn ka istemaal karke webserver ko production mode me chalao
# Yeh webserver.py file ke andar se 'app' ko dhoondhega
gunicorn -w 4 -k uvicorn.workers.UvicornWorker webserver:app --bind 0.0.0.0:$PORT
