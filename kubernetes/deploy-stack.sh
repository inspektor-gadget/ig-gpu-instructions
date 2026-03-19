#!/usr/bin/env bash
# Copyright (c) 2021 Francis Laniel <flaniel@linux.microsoft.com>
# SPDX-License-Identifier: MPL-2.0
set -e
set -o pipefail

LOCATION='centralus'
K8S_NAMESPACE='gpu-observability'

BLOB_STORAGE_CONTAINER='pyroscope-blob-storage'
PYROSCOPE_IDENTITY='pyroscope-id'
PYROSCOPE_SERVICE_ACCOUNT='pyroscope-sa'
PYROSCOPE_FEDERATED_CREDS='pyroscope-federated-creds'

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
		echo "Usage: $0 -n resource_group -k aks_cluster_name -b blob_storage_name" 1>&2
		echo -e "\t-n: The resource group where to deploy. This is mandatory" 1>&2
		echo -e "\t-k: The aks cluster where to deploy. This is mandatory" 1>&2
		echo -e "\t-b: The azure blob storage name. This is mandatory" 1>&2
		echo -e "\t-h: Print this help message." 1>&2
		exit 1
		;;
	esac
done

if [ -z "$resource_group" ] || [ -z "$aks_cluster" ] || [ -z "$blob_storage_name" ]; then
	echo "Error: -n, -k and -b are all required" 1>&2
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

echo -e "Everything is ready, you can now access Grafana from:\nkubectl -n gpu-observability port-forward svc/gpu-observability-grafana 3001:80\nDo not forget to clean resources with:\naaz storage account delete -n $blob_storage_name -g $resource_group --no-wait\naz identity delete -n $PYROSCOPE_IDENTITY -g $resource_group"
