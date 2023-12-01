import os
import time
import redis
import json
import requests
import argparse
from kubernetes import client, config
from concurrent.futures import ThreadPoolExecutor

class LogParser:
    def __init__(self, kube_namespace, loki_host, loki_port, redis_host, redis_port):
        self.v1 = client.CoreV1Api()
        self.namespace = kube_namespace
        self.redis_client = redis.Redis(redis_host, port=redis_port, db=0)
        self.loki_endpoint = f"http://{loki_host}:{loki_port}/loki/api/v1/push"

    @staticmethod
    def write_health_check():
        with open('/tmp/health_check', 'w') as file:
            file.write(str(time.time()))

    def get_pods(self):
        return self.v1.list_namespaced_pod(namespace=self.namespace)

    def scrape_logs(self, pod, container_name=None, since_seconds=None):
        try:
            return self.v1.read_namespaced_pod_log(
                name=pod.metadata.name,
                namespace=pod.metadata.namespace,
                container=container_name,
                since_seconds=since_seconds
            )
        except Exception as e:
            print(f"Error getting logs for pod {pod.metadata.name}: {e}")
            return None

    def send_to_loki(self, logs, pod):
        try:
            log_entry = {
                "streams": [
                    {
                        "stream": {
                            "pod": pod.metadata.name,
                        },
                        "values": [
                            [f"{int(time.time() * 1e9)}", logs]
                        ]
                    }
                ]
            }
            headers = {'Content-Type': 'application/json'}
            response = requests.post(self.loki_endpoint, data=json.dumps(log_entry), headers=headers)
            if response.status_code != 204:
                print(f"Failed to send logs to Loki: {response.text}")
        except Exception as e:
            print(f"Error sending logs to Loki: {e}")

    def process_pod(self, pod):
        pod_key = f"{pod.metadata.namespace}:{pod.metadata.name}"
        last_log_time = self.redis_client.get(pod_key)
        since_seconds = None
        if last_log_time:
            try:
                last_log_timestamp = float(last_log_time.decode('utf-8'))
                since_seconds = int(time.time() - last_log_timestamp)
            except ValueError:
                print(f"Invalid timestamp for pod {pod.metadata.name} in Redis. Resetting timestamp.")
                self.redis_client.set(pod_key, str(time.time()))

        container_names = [container.name for container in pod.spec.containers]
        for container_name in container_names:
            logs = self.scrape_logs(pod, container_name, since_seconds)
            if logs:
                print(logs)
                self.send_to_loki(logs, pod)

        self.redis_client.set(pod_key, str(time.time()))

    def run(self):
        while True:
            pods = self.get_pods().items
            with ThreadPoolExecutor() as executor:
                logs = list(executor.map(self.process_pod, pods))
            self.write_health_check()
            time.sleep(15)


def main():
    parser = argparse.ArgumentParser(
        description="Kubernetes/OpenShift Log Parser"
    )

    parser.add_argument(
        "--namespace",
        "-n",
        required=False,
        help="The Kubernetes/OpenShift namespace where the application is running. Logs from pods in this namespace will be collected. (default: default)",
    )

    parser.add_argument(
        "--loki-host",
        "-lh",
        required=False,
        help="The HTTP route host for the Loki gateway on the cluster. Usually in the form of 'http://loki-gateway-NAMESPACE.PUBLIC_DOMAIN'. (default: localhost)",
    )

    parser.add_argument(
        "--loki-port",
        "-lp",
        required=False,
        help="The port of the Loki gateway service. (default: 80)",
    )

    parser.add_argument(
        "--redis-host",
        "-rh",
        required=False,
        help="The service hostname or IP address of the Redis server for maintaining timestamp records. Usually in the form of redis.NAMESPACE.svc.cluster.local (default: localhost).",
    )

    parser.add_argument(
        "--redis-port",
        "-rp",
        required=False,
        type=int,
        help="The port of the Redis server. (default: 6379).",
    )

    args = parser.parse_args()

    try:
        config.load_incluster_config()
    except config.config_exception.ConfigException:
        try:
            config.load_kube_config()
        except Exception as e:
            print(f"Failed to load kube config: {e}")
            exit(1)

    kube_namespace = args.namespace or os.getenv("KUBE_NAMESPACE", "default")
    loki_host = args.loki_host or os.getenv("LOKI_HOST", "localhost")
    loki_port = args.loki_port or int(os.getenv("LOKI_PORT", 80))
    redis_host = args.loki_host or os.getenv("REDIS_HOST", "localhost")
    redis_port = args.loki_port or int(os.getenv("REDIS_PORT", 6379))

    log_parser = LogParser(
        kube_namespace=kube_namespace,
        loki_host=loki_host,
        loki_port=loki_port,
        redis_host=redis_host,
        redis_port=redis_port,
    )

    log_parser.run()

if __name__ == "__main__":
    main()

