#!/usr/bin/python3

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
parser.add_argument("-r", "--requestName", dest =  "requestName", metavar = '', required = True, help = 'name of tech support request')
parser.add_argument("-t", "--tenant", dest =  "tenant", default= "default", metavar = '', required = False, help = 'tenant name, if not specified: default')
parser.add_argument("-c", "--collectPSMNodes", dest =  "collectPSMNodes", default= False, action = 'store_true', required = False, help = 'user can specify whether or not they want tech support data for PSM nodes; default = False')
parser.add_argument("-v", "--verbose", dest =  "verbose", default= False, action = 'store_true', required = False, help = 'prints more debug information; default = False')
parser.add_argument("-n", "--newRequest", dest =  "newRequest", default= False, action = 'store_true', required = False, help = 'user can specify whether or not they want to create POST request for tech support data; default = False')
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
    if len(dsc_id_list) == 0:
            print ("No DSC coresponding to workload: " + workload)
    else:  
        dsc_dict = {}
        for item in dsc_info.items:
            dsc_dict[item.spec.id] = item.meta.name
        for dsc_id in dsc_id_list:
            if dsc_id in dsc_dict:
                node_names.add(dsc_dict[dsc_id])

#adds PSM names to node_names set 
if args.collectPSMNodes:
    cluster_response = cluster_instance.get_cluster()
    for psm_node in cluster_response.status.quorum_status.members:
        node_names.add(psm_node.name)

#converting a set into a list 
node_names = list(node_names) 
if len(node_names) == 0:
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
            skip_cores = True
        )
    )

    #creates a POST request for the tech_support
    if args.newRequest:
        monitoring_instance.add_tech_support_request(body)

    #waits until tech support data is ready
    for x in range(500):
        if args.newRequest:
            time.sleep(2)
        tech_support_response = monitoring_instance.get_tech_support_request(args.requestName)
        if tech_support_response.status.status == "completed":
            break
        if not args.newRequest:
            time.sleep(2)

    #checks to make sure the tech support data has been retrieved. If not, prints a warning
    if tech_support_response.status.status != "completed":
        print ("Error: unable to retrieve tech support data for all nodes")
    else:
        os.makedirs(args.dir, exist_ok = True)
        URIs =[]

        #Checks to see if user wanted to collect PSM nodes. If no, skips collecting the tech support files.  
        #If yes, checks to see if tech support data was created for all controller nodes. If so, adds the controller node results' URIs to the uri_list. 
        if args.collectPSMNodes:
            for ctrlr_node_name, ctrlr_node in tech_support_response.status.ctrlr_node_results.items():
                if args.verbose:
                    print(ctrlr_node_name)
                    print(ctrlr_node)
                    print("")
                if ctrlr_node.status != "completed" and ctrlr_node.status != "Completed":
                    print ("Error: unable to retrieve tech support data for the PSM node: " + ctrlr_node_name)
                else:
                    URIs.append(ctrlr_node.uri)
            
        #checks to see if tech support data was created for all dsc nodes. If so, adds the dsc node results' URIs to the uri_list
        for dsc_node_name, dsc_node in tech_support_response.status.dsc_results.items():
            if args.verbose:
                print(dsc_node_name)
                print (dsc_node)
                print("")
            if dsc_node.status != "completed" and dsc_node.status != "Completed":
                    print ("Error: unable to retrieve tech support data for the DSC node: " + dsc_node_name)
            else:
                URIs.append(dsc_node.uri)

        #puts tech support files for DSC and PSM nodes into user's given directory 
        for uri in URIs:
            uri_list = uri.split('/')       
            arg_file = uri_list[len(uri_list) - 1]
            if args.verbose:
                print (arg_file)
                print("")
            response = objstore_instance.get_download_file(args.tenant,"techsupport", arg_file)             
            download_path = args.dir + "/"+uri_list[-1]
            saveBinary(download_path, response.data)