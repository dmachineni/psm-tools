#!/usr/bin/python3

from sys import api_version
import time
import os
import argparse 
from apigroups.client import configuration, api_client
from utils import workload_tools
from apigroups.client.api.monitoring_v1_api import MonitoringV1Api
from apigroups.client.api.cluster_v1_api import ClusterV1Api
from apigroups.client.api.objstore_v1_api import ObjstoreV1Api
from apigroups.client.model.monitoring_tech_support_request import MonitoringTechSupportRequest
from apigroups.client.model.api_object_meta import ApiObjectMeta
from apigroups.client.model.monitoring_tech_support_request_spec import MonitoringTechSupportRequestSpec
from apigroups.client.model.tech_support_request_spec_node_selector_spec import TechSupportRequestSpecNodeSelectorSpec
from utils.filesystem_utils import saveBinary
import warnings
import json 

warnings.simplefilter("ignore")

HOME = os.environ['HOME']

config = configuration.Configuration(
    psm_config_path=HOME+"/.psm/config.json",
    interactive_mode=True
)
config.verify_ssl = False

client = api_client.ApiClient(config)
monitoring_instance = MonitoringV1Api (client)
cluster_instance = ClusterV1Api (client) 
objstore_instance = ObjstoreV1Api (client)

parser = argparse.ArgumentParser()
parser.add_argument("-w", "--workloads", dest =  "workloads", metavar = '', required = True, help = 'name or UUIDs of Workloads')
parser.add_argument("-d", "--dir", dest = "dir", metavar = '', required = True, help = 'directory name to put tech support data into')
parser.add_argument("-n", "--requestName", dest =  "requestName", metavar = '', required = True, help = 'name of tech support request')
parser.add_argument("-t", "--tenant", dest =  "tenant", default="default", metavar = '', required = False, help = 'tenant name, if not specified: default')
parser.add_argument("-p", "--collectPSMNodes", dest =  "collectPSMNodes", default="True", metavar = '', required = False, help = 'user can specify whether or not they want tech support data for PSM nodes; default = True')
parser.add_argument("-v", "--verbose", dest =  "verbose", default="False", metavar = '', required = False, help = 'prints more debug information; default = False')

args = parser.parse_args()

#create a list of workloads from the workloads given by the user
workload_list = args.workloads.split(",")

#gets a list of DSCs and their information
dsc_info = cluster_instance.list_distributed_service_card()

node_names = set()

for workload in workload_list:
    #get DSC IDs from the getDscFromWorkload API using the given workloads by user 
    dsc_id_list = workload_tools.getDscFromWorkload(client, workload, forceName = True)

    #find DSC name via DSC ID and store it in the node_names set, any duplicate dscs will not be added
    if (len(dsc_id_list) == 0):
            print ("No DSC coresponding to workload: " + workload)
    else:  
        for dsc_id in dsc_id_list:
            for item in dsc_info["items"]:
                if item["spec"]["id"] == dsc_id:
                    node_names.add(item["meta"]["name"])
                    break

#adds PSM names to node_names set 
if (args.collectPSMNodes == "True"):
    cluster_response = cluster_instance.get_cluster()
    for psm_node in cluster_response.status.quorum_status.members:
        node_names.add(psm_node.name)

#converting a set into a list 
node_names = list(node_names) 
if (len(node_names) == 0):
    print("No PSM and DSC nodes corresponding to given workloads.")
else: 
    #body argument for add_tech_support request 
    body = MonitoringTechSupportRequest(
        meta=ApiObjectMeta (
            name= args.requestName
        ),
        spec=MonitoringTechSupportRequestSpec(
            node_selector=TechSupportRequestSpecNodeSelectorSpec(
                names = node_names
            ),
            skip_cores = (True)
        )
    )

    #creates a POST request for the tech_support
    monitoring_instance.add_tech_support_request(body)

    #waits until tech support data is ready
    for x in range(500):
        time.sleep(2)
        tech_support_response = monitoring_instance.get_tech_support_request(args.requestName)
        if tech_support_response.status.status == "completed":
            break

    #checks to make sure the tech support data has been retrieved. If not, prints a warning
    if tech_support_response.status.status != "completed":
        print ("Warning: unabled to retrieve tech support data for all nodes")
    else:
        #checks to see if tech support data was created for all controller nodes. If so, adds the controller node results' URIs to the uri_list
        os.makedirs(args.dir, exist_ok = True)
        URIs =[]
        for ctrlr_node_name, ctrlr_node in tech_support_response.status.ctrlr_node_results.items():
            if (args.verbose == True):
                print(ctrlr_node_name)
                print(ctrlr_node)
                print("")
            if ctrlr_node.status != "completed" and ctrlr_node.status != "Completed":
                    print ("Error in retrieving tech support data for the node: " + ctrlr_node_name)
            else:
                #puts tech support files for ctrlr_node_results into user's given file
                URIs.append(ctrlr_node.uri)
            
        #checks to see if tech support data was created for all dsc nodes. If so, adds the dsc node results' URIs to the uri_list
        for dsc_node_name, dsc_node in tech_support_response.status.dsc_results.items():
            if (args.verbose == True):
                print(dsc_node_name)
                print (dsc_node)
                print("")
            if dsc_node.status != "completed" and dsc_node.status != "Completed":
                    print ("Error in retrieving tech support data for the node: " + dsc_node_name)
            else:
                #puts tech support files for dsc_results into user's given file
                URIs.append(dsc_node.uri)

        for uri in URIs:
            uri_list = uri.split('/')       
            arg_file = uri_list[len(uri_list) - 1]
            if (args.verbose == True):
                print (arg_file)
                print("")
            response = objstore_instance.get_download_file(args.tenant,"techsupport", arg_file)             
            download_path = args.dir + "/"+uri_list[-1]
            saveBinary(download_path, response.data)