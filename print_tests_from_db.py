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

if __name__ == "__main__":
    with open("config/components.json") as f:
        components = json.load(f)
        
    client = create_client(accesscode_1="itkdb_BernLab_1", accesscode_2="itkdb_BernLab_2")

    print("Reading test_types from production database:")
    for component_type_name, component_type_data in components.items():
        print("  "+component_type_name)
        test_list = get_tests(client, component_type_data["db_name"], component_type_data["db_project"])
        print(json.dumps(test_list,indent=2))
