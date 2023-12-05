import os
import time
import redis
import json
import requests
import argparse
from kubernetes import client, config
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify
from threading import Thread
from waitress import serve

app = Flask(__name__)

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy"}), 200

def probe_server():
    serve(app, host='0.0.0.0', port=8080)

class LogParser:
    def __init__(self, kube_namespace):
        self.v1 = client.CoreV1Api()
        self.namespace = kube_namespace
        self.redis_client = redis.Redis(f"redis.{kube_namespace}.svc.cluster.local", port=6379, db=0)
        self.loki_endpoint = f"http://loki-gateway.{kube_namespace}.svc.cluster.local:80/loki/api/v1/push"

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

    def send_to_loki(self, log_line, pod, timestamp):
        try:
            log_entry = {
                "streams": [
                    {
                        "stream": {
                            "pod": pod.metadata.name,
                        },
                        "values": [
                            [f"{timestamp}", log_line]
                        ]
                    }
                ]
            }
            headers = {'Content-Type': 'application/json'}
            response = requests.post(self.loki_endpoint, data=json.dumps(log_entry), headers=headers)
            if response.status_code != 204:
                print(f"Failed to send log to Loki: {response.text}")
        except Exception as e:
            print(f"Error sending log to Loki: {e}")

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
            for line in logs.split('\n'):
                if line.strip():
                    print(line)
                    log_timestamp = int(time.time() * 1e9)
                    self.send_to_loki(line, pod, log_timestamp)

        self.redis_client.set(pod_key, str(time.time()))

    def run(self):
        while True:
            pods = self.get_pods().items
            with ThreadPoolExecutor() as executor:
                executor.map(self.process_pod, pods)
            time.sleep(5)
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
    log_parser = LogParser(kube_namespace=kube_namespace)

    flask_thread = Thread(target=probe_server)
    flask_thread.daemon = True
    flask_thread.start()

    log_parser.run()

if __name__ == "__main__":
    main()
