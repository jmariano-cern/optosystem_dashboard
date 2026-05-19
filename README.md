# Optosystem production testing dashboard

A dashboard for organizing and tracking optosystem production testing based on a SQLite backend.

## Quick start

1. ***Make sure that the firewall is open***. Run `sudo firewall-cmd --list-all`. Under `ports` you should see `[PORT]/tcp` where `[PORT]` is the port number on which you would like to serve the dashboard. If you do not see the port, open it by running `./open_firewall.sh [PORT]`.

2. ***Make sure that the database is set to auto-update***. Run `sudo crontab -l`. You should see a line like
```
*/30 * * * * /usr/bin/python3 /home/lhep/Current_users/joseph/optosystem_dashboard/read_db.py
```
If you don't see something like this, run './cron_add_read_db.sh'.

3. ***Start the server***. To check whether the server is already running, run `ps aux | grep waitress`. If you see a line like
```
iconda3/bin/python /home/lhep/miniconda3/bin/waitress-serve --host 0.0.0.0 --port 5001 app:app
```
this means that the server is already running. Verify that the port here (5001 in this example) is the one you intend. If you need to restart the server or change the port, see the 'Stop' section below. To start a new server instance in the background,run `nohup ./run_server.sh {PORT} &`.

## Configure

Configuration is managed by .json files in the `config` directory:
```
config
├── components.json
└── testers.json
```
`config/testers.cfg` contains a single dictionary with entries of the form
```
  "Joseph": { "color": "#4e79a7" },
```
where the `color` attribute defines the color to used for the tester in the dashboard.

`config/components.cfg` contains a single dictionary with entries of the form
```
  "Optoboard": {
    "goal": 1878,
    "color": "#ff7f0e",
    "active": true,
    "failure_modes": [
      "No optical signal",
      "Laser failure",
      "Clock failure"
    ]
  },
```
`goal` defines the total number of goal 'good' components to be produced. `color` defines the color to be used for the component in the dashboard. `active` defines whether the dashboard should treat the components as active or not. Active components are those which are currently undergoing testing. Inactive components include those which have not yet been received and those which have already met their goal. `failure_modes` gives a list of possible failure modes for each component.

## Init

Before the dashboard can be used, the database must be initialized:
```
python3 initdb.py
```
This will create database.db

Note that database.db is gitignored, so back it up separately.

## Run

Run the server from the top-level directory with
```
./run_server.sh [PORT]
```
where `[PORT]` is an optional argument for the port on which to serve the database (default is 5000).

To run the server in the background use
```
nohup ./run_server.sh [PORT] &
```

## Stop
To stop the server run
```
pkill -u ${USER} -e -f "waitress-serve --host 0.0.0.0 --port [PORT]"
pkill -u ${USER} -e -f run_server.sh
```
where `[PORT]` is the port that you specified in the 'Run' section, or 5000 if you did not specify a port.
