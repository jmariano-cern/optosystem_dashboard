# Optosystem production testing dashboard

A dashboard for organizing and tracking optosystem production testing based on a SQLite backend.

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
