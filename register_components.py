import pprint
import itkdb
import datetime
from datetime import datetime
import logging
import traceback

def datetime_formatter():
    current_datetime = datetime.now() 
    date = current_datetime.date()
    time = current_datetime.time()
    datetime_right_format = str(date) + 'T' + str(time)[:-3] + 'Z'
    return datetime_right_format




def associate_component_private(client,child_id,parent_id):
    client.post("assembleComponent", json = {"parent": str(parent_id),
                                             "child":str(child_id)} )



def create_client(accesscode_1 = "", accesscode_2 = "", token = ""):
    if token != "":
        try:
            user = itkdb.core.UserBearer(bearer=token)
            client = itkdb.Client(user=user,use_eos=True)
            print("The client was created")
            return client
        except:
            traceback.print_exc()
            logging.warning("The client was not properly created")
    else:
        if accesscode_1 == "":
            accesscode_1 = input("Enter accesscode_1... \n")
            print("Access code 1 is : " + accesscode_1)
        if accesscode_2 == "":
            accesscode_2 = input("Enter accesscode_2...\n")
            print("Access code 2 is : " + accesscode_2)
        try:
            user = itkdb.core.User(access_code1=accesscode_1, access_code2=accesscode_2)
            client = itkdb.Client(user=user,use_eos=True)
            print("The client was created")
            return client
    
        except:
            traceback.print_exc()
            logging.warning("The client was not properly created")


if __name__ == "__main__":
    print("\n.\n.\n.\n")
    print("Starting...")
    print("\n.\n.\n.\n")
    print("Finished")


 