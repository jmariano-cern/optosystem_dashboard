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

def get_component_tests(client, serial_number):    
    response = client.get("getComponent", json = {
        "component": serial_number
    })
    test_data = {}
    for test_type in response["tests"]:
        test_data[test_type["code"]] = []
        for test_run in test_type["testRuns"]:
            test_data[test_type["code"]].append({})
            test_data[test_type["code"]][-1]["date"] = test_run["date"]
            test_data[test_type["code"]][-1]["passed"] = test_run["passed"]
        test_data[test_type["code"]] = sorted(test_data[test_type["code"]], reverse=False, key=lambda x: datetime.strptime(x["date"], '%Y-%m-%dT%H:%M:%S.%fZ'))
    return test_data
    
def get_test_summary(component_tests,test_list):
    summary = {}
    for test in test_list:
        summary[test] = {}
        if not test in component_tests:
            summary[test]["status"] = "missing"
            summary[test]["date"] = ""
            continue
        summary[test]["status"] = "passed" if True in [ x["passed"] for x in component_tests[test] ] else "failed" # any test passed
        summary[test]["date"] = component_tests[test][-1]["date"] # take date of latest test
    return summary

def get_component_summary(test_summary):
    summary = {}
    summary["status"] = "good"
    failed_tests = []
    summary["failure_mode"] = "none"
    #summary["missing_tests"] = []
    dates = []
    for test_name,test_data in test_summary.items():
        if test_data["status"] == "missing":
            summary["status"] = "missing_tests"
            #summary["status"] = "failed"
            #summary["missing_tests"].append(test_name)
            #summary["failure_mode"] = "missing_test"
            continue
        if test_data["status"] == "failed":
            summary["status"] = "bad"
            failed_tests.append(test_name)
        dates.append(test_data["date"])
    dates = sorted(dates, reverse=False, key=lambda x: datetime.strptime(x, '%Y-%m-%dT%H:%M:%S.%fZ'))
    if len(dates) > 0:
        summary["date"] = dates[-1] # take date of latest test
    else:
        summary["date"] = ""
    failed_tests.sort()
    if len(failed_tests) > 0:
        summary["failure_mode"] = '_'.join(failed_tests)
    return summary
    
if __name__ == "__main__":
    with open("config/components.json") as f:
        components = json.load(f)
        
    client = create_client(accesscode_1="itkdb_BernLab_1", accesscode_2="itkdb_BernLab_2")

    # component_types = [["BPOL12V", "CE"], ["OPTOBOX_POWERBOARD", "P"], ["OPTOBOX_CONNECTORBOARD", "P"],["OPTOBOARD", "P"]]
    # component_types = [["BPOL12V", "CE"]] # 233/245
    # component_types = [["OPTOBOX_POWERBOARD", "P"]] # 48/53
    # component_types = [["OPTOBOX_CONNECTORBOARD", "P"]] # 22/58
    # component_types = [["OPTOBOARD", "P"]] # 1/303
    # component_types = [["BPOL2V5", "CE"]] # 233/245

    tester = "Unknown"
    tests_to_insert = []
    print("Loading tests from production database:")
    for component_type_name, component_type_data in components.items():
        print("  "+component_type_name)
        component_list = get_components(client, component_type_data["db_name"], component_type_data["db_project"])
        component_list = clean_component_list(component_list)
        test_list = get_tests(client, component_type_data["db_name"], component_type_data["db_project"])
        for component in component_list:            
            print("    "+component["serialNumber"])
            component_tests = get_component_tests(client, component["serialNumber"])
            test_summary = get_test_summary(component_tests, test_list)
            component_summary = get_component_summary(test_summary)
            if component_summary["status"] == "missing_tests":
                continue
            tests_to_insert.append(
                (component_type_name, component["serialNumber"], tester, component_summary["status"], component_summary["failure_mode"], datetime.strptime(component_summary["date"], '%Y-%m-%dT%H:%M:%S.%fZ').isoformat())
            )
            
    print("Updating dashboard database:")
    conn = sqlite3.connect("database.db")
    cur = conn.cursor()
    print("  Deleting previous entries")
    cur.execute("DELETE FROM tests")
    conn.commit()
    print("  Loading new entries")
    cur.executemany("""                                                                                          
    INSERT INTO tests (component_type, serial_number, tester, status, failure_mode, timestamp)               
    VALUES (?, ?, ?, ?, ?, ?)                                                                                
""", tests_to_insert)
    conn.commit()
    conn.close()
    print("Done -- "+str(len(tests_to_insert))+" components loaded.")
    
    # for component_type, project in component_types:
    #     # total = 0
    #     # passed = 0
    #     print("Component type: ", component_type)
    #     component_list = get_components(client, component_type, project)
    #     component_list = clean_component_list(component_list)
    #     test_list = get_tests(client, component_type,project)
    #     for component in component_list:            
    #         component_tests = get_component_tests(client, component["serialNumber"])
    #         test_summary = get_test_summary(component_tests,test_list)
    #         component_summary = get_component_summary(test_summary)
    #         component_summary["serial_number"] = component["serialNumber"]
    #         component_summary[""] = component["serialNumber"]
    #         # print("\ncomponent with SN :" + component["serialNumber"])
    #         print(json.dumps(component_summary,indent=1))
    #     #     if component_summary["status"] == "passed":
    #     #         passed += 1
    #     #     if component_summary["status"] == "missing_tests":
    #     #         continue
    #     #     total += 1
    #     # print("  Passed: " + str(passed) + "/" + str(total))
    
