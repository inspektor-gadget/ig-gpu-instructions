#!/usr/bin/env bash
# Copyright (c) 2021 Francis Laniel <flaniel@linux.microsoft.com>
# SPDX-License-Identifier: MPL-2.0
set -e
set -o pipefail

LOCATION='centralus'
K8S_NAMESPACE='gpu-observability'

PYROSCOPE_PLS='pyroscope-pls'
PYROSCOPE_MPE='pyroscope-mpe'
PYROSCOPE_PORT='4040'

PROMETHEUS_PLS='prometheus-pls'
PROMETHEUS_MPE='prometheus-mpe'
PROMETHEUS_PORT='80'

BLOB_STORAGE_CONTAINER='pyroscope-blob-storage'
PYROSCOPE_IDENTITY='pyroscope-id'
PYROSCOPE_SERVICE_ACCOUNT='pyroscope-sa'
PYROSCOPE_FEDERATED_CREDS='pyroscope-federated-creds'

function create_service_url {
	local resource_group
	local aks_node_rg
	local grafana_name
	local pls_name
	local mpe_name
	local port
	local location

	if [ $# -lt 7 ]; then
		echo "${FUNCNAME[0]} needs 7 arguments: the resource_group, the aks_node_rg, the grafana_name, the pls_name, the mpe_name, the port and the location" 1>&2

		exit 1
	fi

	resource_group=$1
	aks_node_rg=$2
	grafana_name=$3
	pls_name=$4
	mpe_name=$5
	port=$6
	location=$7

	pls_id=$(az network private-link-service show -n $pls_name -g $aks_node_rg --query 'id' -o tsv)
	az grafana mpe create --workspace-name $grafana_name --resource-group $resource_group --name $mpe_name --private-link-resource-id $pls_id --location $location -o none

	# Let's wait to be sure the connection exists.
	sleep 60

	# WARNING This is fragile, as this is not documented by Microsoft. Though,
	# this protects against any race condition with someone creating another
	# connection under our feet.
	pls_connection_prefix="grafana-${grafana_name}"
	pls_connection_name=$(az network private-link-service show -n $pls_name -g $aks_node_rg --query "privateEndpointConnections[?privateLinkServiceConnectionState.status=='Pending' && starts_with(name, '${pls_connection_prefix}')].name | [0]" -o tsv)
	# We need to approve it from CLI. Indeed, setting
	# service.beta.kubernetes.io/azure-pls-auto-approval to a subscription ID will
	# not work because the MPE lives in an internal Microsoft subscription.
	# By using the mpe_id, we are sure to accept the connection corresponding to
	# this MPE, and not any connection.
	az network private-link-service connection update --name $pls_connection_name --service-name $pls_name --resource-group $aks_node_rg --connection-status Approved -o none

	# Refresh in order for the status of the connection to be propagated.
	az grafana mpe refresh --workspace-name $grafana_name --resource-group $resource_group -o none

	endpoint_ip=$(az grafana mpe show --workspace-name $grafana_name --resource-group $resource_group --name $mpe_name --query 'privateLinkServicePrivateIP' -o tsv)

	url="http://${endpoint_ip}:${port}"

	echo $url
}

resource_group=''
aks_cluster=''
grafana_name=''

while getopts "g:k:n:b:h" option; do
	case $option in
	n)
		resource_group=${OPTARG}
		;;
	k)
		aks_cluster=${OPTARG}
		;;
	g)
		grafana_name=${OPTARG}
		;;
	b)
		blob_storage_name=${OPTARG}
		;;
	h|\?)
		echo "Usage: $0 -n resource_group -g grafana_name -k aks_cluster_name -b blob_storage_name" 1>&2
		echo -e "\t-n: The resource group where to deploy. This is mandatory" 1>&2
		echo -e "\t-k: The aks cluster where to deploy. This is mandatory" 1>&2
		echo -e "\t-g: The azure managed grafana name. This is mandatory" 1>&2
		echo -e "\t-b: The azure blob storage name. This is mandatory" 1>&2
		echo -e "\t-h: Print this help message." 1>&2
		exit 1
		;;
	esac
done

if [ -z "$resource_group" ] || [ -z "$aks_cluster" ] || [ -z "$grafana_name" ] || [ -z "$blob_storage_name" ]; then
	echo "Error: -n, -k, -b and -g are all required" 1>&2
	exit 1
fi

az storage account create --name $blob_storage_name --resource-group $resource_group --location $LOCATION --sku Standard_ZRS --kind StorageV2 --min-tls-version TLS1_2 --allow-blob-public-access false -o none
az storage container create --name $BLOB_STORAGE_CONTAINER --account-name $blob_storage_name --auth-mode login -o none

# We will use federated credentials in order for Pyroscope to use Azure Blob Storage as backend.
az identity create --name $PYROSCOPE_IDENTITY --resource-group $resource_group --location $LOCATION -o none
identity_client_id=$(az identity show --name $PYROSCOPE_IDENTITY --resource-group $resource_group --query "clientId" -o tsv)

subscription_id=$(az account show --query id -o tsv)
# Restrict the scope as much as possible.
storage_scope="/subscriptions/${subscription_id}/resourceGroups/${resource_group}/providers/Microsoft.Storage/storageAccounts/${blob_storage_name}"
az role assignment create --assignee $identity_client_id --role "Storage Blob Data Contributor" --scope $storage_scope -o none

az aks update --name $aks_cluster --resource-group $resource_group --enable-oidc-issuer --enable-workload-identity -o none
oidc_issuer=$(az aks show --name $aks_cluster --resource-group $resource_group --query "oidcIssuerProfile.issuerUrl" -o tsv)

az identity federated-credential create --name $PYROSCOPE_FEDERATED_CREDS --identity-name $PYROSCOPE_IDENTITY --resource-group "$resource_group" --issuer $oidc_issuer --subject "system:serviceaccount:${K8S_NAMESPACE}:${PYROSCOPE_SERVICE_ACCOUNT}" --audiences "api://AzureADTokenExchange" -o none

pushd charts
helm repo update
helm dependency build
# Deploy IG + Pyroscope + Prometheus to the AKS cluster.
# The annotations on Pyroscope and Prometheus will automatically create private
# link services.
# We then use --set-string to customize Pyroscope to use Azure Blob Storage as backend:
# storage.azure.*: Mandatory parameters when using federated credentials.
# serviceAccount: Flags used to create the k8s ServiceAccount.
# azure.workload.identity/use: Mandatory to inject the good AKS environments
# variables in the pod, see:
# https://learn.microsoft.com/en-us/azure/aks/workload-identity-overview#pod-labels
helm upgrade --install gpu-observability . -n $K8S_NAMESPACE --reset-values --create-namespace -f values-micro-services.yaml -f values.yaml --set-string "pyroscope.pyroscope.structuredConfig.storage.azure.account_name=${blob_storage_name}" --set-string "pyroscope.pyroscope.structuredConfig.storage.azure.container_name=${BLOB_STORAGE_CONTAINER}" --set-string "pyroscope.pyroscope.serviceAccount.create=true" --set-string "pyroscope.pyroscope.serviceAccount.name=${PYROSCOPE_SERVICE_ACCOUNT}" --set-string "pyroscope.pyroscope.serviceAccount.annotations.azure\\.workload\\.identity/client-id=${identity_client_id}" --set-string "pyroscope.pyroscope.extraLabels.azure\\.workload\\.identity/use=true"
popd

# Deploy Grafana.
az grafana create -n $grafana_name -g $resource_group --location $LOCATION -o none

# Let's wait for private link services and Grafana to be ready.
sleep 60

aks_node_rg=$(az aks show -g $resource_group -n $aks_cluster --query 'nodeResourceGroup' -o tsv)

pyroscope_url=$(create_service_url $resource_group $aks_node_rg $grafana_name $PYROSCOPE_PLS $PYROSCOPE_MPE $PYROSCOPE_PORT $LOCATION)
pyroscope_ds_definition=$(cat <<EOF
{
	"name": "local-pyroscope",
	"uid": "local-pyroscope",
	"type": "grafana-pyroscope-datasource",
	"access": "proxy",
	"url": "${pyroscope_url}",
	"jsonData": {
		"keepCookies": ["pyroscope_git_session"]
	}
}
EOF
)
az grafana data-source create -n $grafana_name -g $resource_group --definition "$pyroscope_ds_definition" -o none

prometheus_url=$(create_service_url $resource_group $aks_node_rg $grafana_name $PROMETHEUS_PLS $PROMETHEUS_MPE $PROMETHEUS_PORT $LOCATION)
prometheus_ds_definition=$(cat <<EOF
{
	"name": "prometheus",
	"type": "prometheus",
	"uid": "prometheus",
	"access": "proxy",
	"url": "${prometheus_url}",
	"isDefault": true,
	"editable": false
}
EOF
)
az grafana data-source create -n $grafana_name -g $resource_group --definition "$prometheus_ds_definition" -o none

az grafana dashboard create -n $grafana_name -g $resource_group --definition "$(cat grafana-dashboard.json)" -o none

echo -e "Everything is ready, you can now access Grafana from: $(az grafana show -n $grafana_name -g $resource_group --query 'properties.endpoint' -o tsv)\nDo not forget to clean resources with:\naz grafana delete -n $grafana_name -g $resource_group --no-wait\naz storage account delete -n $blob_storage_name -g $resource_group --no-wait\naz identity delete -n $PYROSCOPE_IDENTITY -g $resource_group"
