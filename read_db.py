import os
from pprint import pprint
import json
import collections
import sqlite3

from register_components import *

def get_components(client, componentType, project):
    componentList = client.get("listComponents", json = {
        "filterMap": {
            "componentType": componentType,
            "project": project
        }
    }).data
    return componentList

def get_tests(client, componentType, project):
    testList = client.get("listTestTypesByComponentTypes", json = {
            "componentTypes": [componentType],
            "project": project
        
    }).data
    testList = [test["code"] for test in testList if test["state"] == "active"]
    return testList

def clean_component_list(componentList):
    return [component for component in componentList if component["state"] != "deleted"]

def get_component_data(client, serial_number):    
    response = client.get("getComponent", json = {
        "component": serial_number
    })
    test_data = {}
    production_component =  False
    for property in response["properties"]:
        if property["code"] == "PRODUCTION_COMPONENT":
            if property["value"]:
                production_component = True
    if not production_component:
        return (test_data, production_component)        
    for test_type in response["tests"]:
        test_data[test_type["code"]] = []
        for test_run in test_type["testRuns"]:
            test_data[test_type["code"]].append({})
            test_data[test_type["code"]][-1]["date"] = test_run["date"]
            test_data[test_type["code"]][-1]["passed"] = test_run["passed"]
        test_data[test_type["code"]] = sorted(test_data[test_type["code"]], reverse=False, key=lambda x: datetime.strptime(x["date"], '%Y-%m-%dT%H:%M:%S.%fZ'))
    return (test_data, production_component)
    
def get_test_summary(component_tests,test_list,multiple_tests_behavior="latest"):
    summary = {}
    for test in test_list:
        summary[test] = {}
        if not test in component_tests:
            summary[test]["status"] = "missing"
            summary[test]["date"] = ""
            continue
        summary[test]["date"] = component_tests[test][-1]["date"] # take date of latest test
        if multiple_tests_behavior == "latest":
            summary[test]["status"] = "passed" if component_tests[test][-1]["passed"] else "failed" # latest test passed
        elif multiple_tests_behavior == "or":
            summary[test]["status"] = "passed" if True in [ x["passed"] for x in component_tests[test] ] else "failed" # any test passed
        elif multiple_tests_behavior == "and":
            summary[test]["status"] = "failed" if False in [ x["passed"] for x in component_tests[test] ] else "passed" # all test passed
        else:
            print("WARNING: multiple_tests_behavior " + multiple_tests_behavior + " is unknown")
            summary[test]["status"] = "unknown"
    return summary

def get_component_summary(test_summary,component_type_name,components):
    summary = {}
    summary["status"] = "good"
    failed_tests = []
    summary["failure_mode"] = "none"
    summary["missing_tests"] = []
    dates = []
    for test in components[component_type_name]["required_tests"]:
        if test not in test_summary:
            print("WARNING: test " + test + " required for component " + component_type_name + ", but not associated to " + component_type_name + " in database")
            continue
        
        if test_summary[test]["status"] == "missing":
            summary["missing_tests"].append(test)
            if (components[component_type_name]["missing_test_behavior"] == "skip") and not (summary["status"] == "bad"):
                summary["status"] = "skip"
            elif components[component_type_name]["missing_test_behavior"] == "fail":
                summary["status"] = "bad"
                failed_tests.append(test)
            continue
        dates.append(test_summary[test]["date"])
        if test_summary[test]["status"] == "failed":
            summary["status"] = "bad"
            failed_tests.append(test)
    dates = sorted(dates, reverse=False, key=lambda x: datetime.strptime(x, '%Y-%m-%dT%H:%M:%S.%fZ'))
    if len(dates) > 0:
        summary["date"] = dates[-1] # take date of latest test
    else:
        summary["date"] = ""
    failed_tests.sort()
    if len(failed_tests) > 0:
        summary["failure_mode"] = '_'.join(failed_tests)
    return summary

def get_tester(timestamp,component_type_name,local_db_cursor):
    lunchtime = datetime.strptime('12:30', '%H:%M').time()
    date = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%fZ').date()
    time = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%fZ').time()
    shift = "morning" if (time < lunchtime) else "afternoon"
    local_db_cursor.execute("SELECT tester FROM shifts WHERE date = ? AND shift = ? AND component_type = ? ORDER BY date, shift, component_type",(date.isoformat(),shift,component_type_name))
    rows = local_db_cursor.fetchall()
    if (len(rows)>1):
        print("ERROR: returned multiple shifts")
        exit
    elif (len(rows)==0):
        return "Unknown"
    return "Unknown" if rows[0][0] == None else rows[0][0]
   
if __name__ == "__main__":
    with open("config/components.json") as f:
        components = json.load(f)
        
    client = create_client(accesscode_1="itkdb_BernLab_1", accesscode_2="itkdb_BernLab_2")
    
    logfile = open("log/tests_from_db.log","w")

    local_db = sqlite3.connect("database.db")
    local_db_cursor = local_db.cursor()

    tester = "Unknown"
    tests_to_insert = []
    print("Loading tests from production database:")
    for component_type_name, component_type_data in components.items():
        print("  "+component_type_name)
        logfile.write("######################################\n")
        logfile.write("######################################\n")
        logfile.write("######################################\n")
        logfile.write("##  "+component_type_name+"\n")
        logfile.write("######################################\n")
        logfile.write("######################################\n")
        logfile.write("######################################\n")
        component_list = get_components(client, component_type_data["db_name"], component_type_data["db_project"])
        component_list = clean_component_list(component_list)
        test_list = get_tests(client, component_type_data["db_name"], component_type_data["db_project"])
        for component in component_list:            
            logfile.write("######################################\n")
            logfile.write("  "+component["serialNumber"]+"\n")
            logfile.write("######################################\n")
            (component_tests,production_component) = get_component_data(client, component["serialNumber"])
            if not production_component:
                logfile.write("  Not production component -- skipping\n")
                continue
            print("    "+component["serialNumber"])
            logfile.write(json.dumps(component_tests,indent=1))
            test_summary = get_test_summary(component_tests, test_list, components[component_type_name]["multiple_tests_behavior"])
            logfile.write(json.dumps(test_summary,indent=1))
            component_summary = get_component_summary(test_summary,component_type_name,components)
            if component_summary["status"] == "skip":
                continue
            component_summary["tester"] = get_tester(component_summary["date"],component_type_name,local_db_cursor)
            logfile.write(json.dumps(component_summary,indent=1))
            tests_to_insert.append(
                (component_type_name, component["serialNumber"], tester, component_summary["status"], component_summary["failure_mode"], datetime.strptime(component_summary["date"], '%Y-%m-%dT%H:%M:%S.%fZ').isoformat())
            )
            logfile.write(json.dumps(tests_to_insert[-1],indent=1))
            
    print("Updating dashboard database:")
    print("  Deleting previous entries")
    local_db_cursor.execute("DELETE FROM tests")
    local_db.commit()
    print("  Loading new entries")
    logfile.write("######################################\n")
    logfile.write("######################################\n")
    logfile.write("######################################\n")
    logfile.write("##  DATABASE INSERT\n")
    logfile.write("######################################\n")
    logfile.write("######################################\n")
    logfile.write("######################################\n")
    logfile.write(json.dumps(tests_to_insert,indent=1))
    local_db_cursor.executemany("""
    INSERT INTO tests (component_type, serial_number, tester, status, failure_mode, timestamp)               
    VALUES (?, ?, ?, ?, ?, ?)                                                                                
""", tests_to_insert)
    local_db.commit()
    local_db.close()
    print("Done -- "+str(len(tests_to_insert))+" components loaded.")
