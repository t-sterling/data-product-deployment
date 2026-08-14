#!/usr/bin/env python3
"""One-shot Git-to-Argo reconciler for pinned data-product manifests."""
import hashlib
import json
import os
import re
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import yaml

NAMESPACE = os.getenv("ARGO_NAMESPACE", "argo")
ENVIRONMENT = os.getenv("ENVIRONMENT", "dev")
REPOSITORY = os.environ["DEPLOYMENT_REPOSITORY_URL"]
BRANCH = os.getenv("DEPLOYMENT_REPOSITORY_BRANCH", "main")
API = os.getenv("KUBERNETES_SERVICE_HOST")
PORT = os.getenv("KUBERNETES_SERVICE_PORT_HTTPS", "443")
TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
CA_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"


def clone_url():
    token = os.getenv("GIT_TOKEN")
    if token and REPOSITORY.startswith("https://"):
        return REPOSITORY.replace("https://", f"https://x-access-token:{token}@", 1)
    return REPOSITORY


def api(method, path, body=None):
    token = Path(TOKEN_PATH).read_text().strip()
    request = urllib.request.Request(
        f"https://{API}:{PORT}{path}",
        data=json.dumps(body).encode() if body else None,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    context = ssl.create_default_context(cafile=CA_PATH)
    with urllib.request.urlopen(request, context=context) as response:
        return json.load(response)


def valid_manifest(document, path):
    required = {"environment", "product", "version", "releaseStatus", "source", "artifact"}
    missing = required - set(document or {})
    if missing:
        raise ValueError(f"{path}: missing fields: {', '.join(sorted(missing))}")
    if document["environment"] != ENVIRONMENT:
        raise ValueError(f"{path}: environment must be {ENVIRONMENT}")
    if ENVIRONMENT != "dev" and document["releaseStatus"] != "release":
        raise ValueError(f"{path}: only released artifacts are allowed outside DEV")
    if document["releaseStatus"] not in {"candidate", "release"}:
        raise ValueError(f"{path}: invalid releaseStatus")
    if not str(document["artifact"].get("uri", "")).startswith("s3://"):
        raise ValueError(f"{path}: artifact.uri must be an s3 URI")
    if not re.fullmatch(r"[a-f0-9]{64}", str(document["artifact"].get("sha256", ""))):
        raise ValueError(f"{path}: artifact.sha256 must be lowercase SHA-256")


def workflow(document, digest):
    product = document["product"]
    safe_product = re.sub(r"[^a-z0-9-]", "-", product.lower())[:40].strip("-")
    parameters = {
        "environment": document["environment"],
        "product": product,
        "version": str(document["version"]),
        "release-status": document["releaseStatus"],
        "artifact-uri": document["artifact"]["uri"],
        "artifact-sha256": document["artifact"]["sha256"],
        "source-commit": document["source"]["commit"],
        "content-sha256": document["source"]["contentSha256"],
    }
    return {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Workflow",
        "metadata": {
            "generateName": f"deploy-{safe_product}-",
            "namespace": NAMESPACE,
            "labels": {"data-product": safe_product, "environment": ENVIRONMENT, "desired-state": digest},
            "annotations": {"data-products.example.io/desired-state": digest},
        },
        "spec": {
            "workflowTemplateRef": {"name": "deploy-data-product"},
            "arguments": {"parameters": [{"name": key, "value": value} for key, value in parameters.items()]},
        },
    }


def main():
    with tempfile.TemporaryDirectory() as directory:
        subprocess.run(["git", "clone", "--depth", "1", "--branch", BRANCH, clone_url(), directory], check=True)
        manifests = sorted(Path(directory, "environments", ENVIRONMENT, "products").glob("*.yml"))
        existing = api("GET", f"/apis/argoproj.io/v1alpha1/namespaces/{NAMESPACE}/workflows").get("items", [])
        observed = {item.get("metadata", {}).get("labels", {}).get("desired-state") for item in existing}
        for path in manifests:
            resource = yaml.safe_load(path.read_text())
            document = resource.get("spec", {}) if isinstance(resource, dict) else {}
            valid_manifest(document, path)
            digest = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()[:40]
            if digest in observed:
                print(f"unchanged: {document['product']} ({digest})")
                continue
            api("POST", f"/apis/argoproj.io/v1alpha1/namespaces/{NAMESPACE}/workflows", workflow(document, digest))
            print(f"submitted: {document['product']} ({digest})")


if __name__ == "__main__":
    main()
