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

def clean_component_list(componentList):
    return [component for component in componentList if component["state"] != "deleted"]

if __name__ == "__main__":
    with open("config/components.json") as f:
        components = json.load(f)
        
    client = create_client(accesscode_1="itkdb_BernLab_1", accesscode_2="itkdb_BernLab_2")
    
    print("Loading tests from production database:")
    for component_type_name, component_type_data in components.items():
        print("  "+component_type_name)
        component_list = get_components(client, component_type_data["db_name"], component_type_data["db_project"])
        component_list = clean_component_list(component_list)
        print(json.dumps(component_list[-1],indent=1))
