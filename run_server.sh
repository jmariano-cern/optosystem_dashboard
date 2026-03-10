#!/bin/bash
cd "$(dirname "$0")"
waitress-serve --host 0.0.0.0 --port 5000 app:app
# #!/bin/bash
# export FLASK_APP=app.py
# flask run --host=0.0.0.0 --port=5000
