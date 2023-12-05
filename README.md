# Kubernetes Loki Log Parser 

## Introduction

The repository contains log parser script that can be deployed on a Kubernetes or OpenShift cluster using Helm. The script collects logs from pods within a specified namespace and forwards them to a Loki gateway for aggregation and storage. It also interacts with a Redis server for timestamp records. It is a workaround solution that enables users without administrator privileges who can not deploy a Promtail Agent to ship logs to a Loki instance. 

## Prerequisites

- Kubernetes or OpenShift cluster with Loki and Redis deployments
- Helm 

## Installation

1. Clone the repository
```
git clone https://github.com/jakubzolkos/loki-parser
```
2. Modify the values.yaml file with your configuration
- **namespace**: the namespace on your cluster from which you want to scrape logs
```yaml
logParser:
  namespace: default
```
3. (OPTIONAL) Publish your own image. <br>
If you wish to make modification to the script, you will need to deploy your own Docker image. After changing the script, run:
```
docker build -t loki-parser .
docker tag loki-parser ghcr.io/<username>/<image_name>:<version_tag>
docker push ghcr.io/<username>/<image_name>:<version_tag>
```
Next, provide the URL of the image in the **values.yaml** file inside **templates** folder
```yaml
image:
  repository: image_name
```
4. Deploy with Helm
- Navigate to the loki-parser directory
```
cd loki-parser
```
- After logging in to your cluster, run this to deploy the chart
```
helm install --values values.yaml loki-parser .
```
