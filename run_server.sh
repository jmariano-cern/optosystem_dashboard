#!/bin/bash

DEFAULT_PORT=5000
PORT=${1:-${DEFAULT_PORT}}

echo "Opening port ${PORT} in firewall (requires sudo)"
sudo firewall-cmd --zone=public --add-port=${PORT}/tcp
cd "$(dirname "$0")"
echo "Starting optoboard dashboard on http://$(hostname):${PORT}"
waitress-serve --host 0.0.0.0 --port ${PORT} app:app

# #!/bin/bash
# export FLASK_APP=app.py
# flask run --host=0.0.0.0 --port=5000
