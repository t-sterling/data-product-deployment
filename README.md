# Data-product deployment

This is the deployment-team-owned GitOps repository for data-products. It is an independent Git repository from `data-product`: product teams own product content and artifact creation, while the deployment team owns environment desired state and Argo orchestration.

This repository does **not** own or build the applications that perform deployment operations. In a production implementation, jobs such as schema reconciliation, topic creation, Liquibase execution, service restarts, and verification are independently developed, versioned, secured, and published by their owning teams. The Argo templates here only compose those jobs and pass them pinned inputs.

## Repository responsibilities

This repository owns:

- the desired data-product version for each environment;
- immutable S3 artifact coordinates and checksums;
- Argo `WorkflowTemplate` composition and dependency ordering;
- environment admission rules;
- retries, concurrency, synchronization, and workflow parameters;
- promotion history through Git commits and pull requests.

This repository does not own:

- data-product source or version selection;
- Maven assembly or S3 publication;
- executable deployment-job implementations;
- container-image build pipelines for those jobs;
- environment-specific credentials or business logic.

## Layout

```text
.
|-- environments/
|   |-- dev/products/              Desired state for shared DEV
|   `-- prod/products/             Released products promoted to PROD
|-- argo/
|   |-- workflow-template.yml      Top-level data-product orchestration
|   |-- reconciler.yml             Prototype Git-to-Argo trigger resources
|   `-- templates/                 Reusable operation contracts
|       |-- validate-product.yml
|       |-- reconcile-config.yml
|       |-- reconcile-topics.yml
|       |-- reconcile-glue.yml
|       |-- run-liquibase.yml
|       |-- restart-services.yml
|       |-- verify-deployment.yml
|       `-- deployment-summary.yml
|-- installation/
|   `-- install-local-argo.sh       Idempotent Docker Desktop installer
`-- README.md
```

The `deployer/` and `reconciler/` images are foundational prototype utilities: one securely obtains and verifies the package, and the other turns Git desired state into Argo workflow submissions. They remain here until production-grade platform components replace them. They are not implementations of config, topics, Glue, Liquibase, restart, or verification operations; those jobs remain independently owned.

## Desired-state manifests

Each file under `environments/<environment>/products/` describes exactly one desired deployment. For example:

```yaml
apiVersion: platform.example.io/v1alpha1
kind: DataProductDeployment
metadata:
  name: orders
spec:
  environment: dev
  product: orders
  version: 1.4.0
  releaseStatus: candidate
  source:
    repository: t-sterling/data-product
    branch: feature/orders-change
    commit: 0123456789abcdef
    contentSha256: <source-tree-sha256>
  artifact:
    uri: s3://ts-data-products/data-products/candidates/orders/1.4.0/0123456789abcdef/orders-1.4.0.zip
    sha256: <zip-sha256>
```

Every deployment is pinned by S3 URI, ZIP checksum, source commit, and source-content digest. There is no `latest` alias.

Admission policy is deliberately asymmetric:

- DEV accepts `candidate` and `release` artifacts.
- Every higher environment accepts `release` artifacts only.
- Candidate artifacts are addressed by Git SHA and cannot be promoted outside DEV.

## Lifecycle

### Candidate deployment to DEV

1. A developer pushes a feature branch in the `data-product` repository.
2. CI identifies only the changed products and validates their version changes.
3. CI assembles each changed product into a ZIP.
4. CI publishes each immutable candidate to a SHA-addressed S3 key.
5. CI updates only those products' manifests under `environments/dev/products/`.
6. The Git change is observed by the GitOps trigger.
7. Argo submits `deploy-data-product` for each changed desired state.
8. Shared DEV converges to the most recently successful manifest update for that product.

Developers can repeat this cycle without creating a source pull request. Each push produces a new immutable candidate; DEV desired state simply points to the selected candidate.

### Release creation

1. The developer validates the candidate in DEV.
2. The exact tested content is submitted through a pull request to `main`.
3. Release CI verifies that the merged product tree matches the candidate recorded in DEV.
4. CI publishes the formal release under `releases/<product>/<version>/`.
5. CI changes the DEV manifest from `candidate` to the immutable `release` coordinate.

If the merged content differs from the DEV-tested candidate, release creation fails and a new candidate must pass through DEV.

### Promotion

Promotion does not rebuild or copy the product artifact. A pull request changes the target environment manifest to reference the same released S3 object and checksum. Review and merge of that Git change is the promotion approval and audit record.

```text
feature push
  -> immutable candidate in S3
  -> DEV manifest commit
  -> Argo deploys candidate to DEV

merge to main
  -> tested-content verification
  -> immutable release in S3
  -> DEV manifest uses release

promotion PR
  -> higher-environment manifest uses same release
  -> Argo deploys release to that environment
```

## Argo composition

`argo/workflow-template.yml` is the top-level workflow. It defines sequencing and calls the operation templates with `templateRef`:

```text
obtain and verify artifact
  -> validate-product
  -> reconcile-config
  -> reconcile-topics
  -> reconcile-glue
  -> run-liquibase
  -> restart-services
  -> verify-deployment
  -> deployment-summary
```

The files under `argo/templates/` define integration contracts. Their current Alpine commands are non-production skeletons imported from the templates already installed in the local `argo` namespace. As independently owned jobs become available, each template should reference an externally published image pinned by immutable version or digest.

Changing a job implementation should normally require changing only the relevant template's image reference and parameters, not changing product source or rebuilding product artifacts.

## Security and operational boundaries

- Workflow service accounts receive only the permissions required for their operation.
- Artifact access is read-only and limited to the data-product S3 prefix.
- Runtime credentials come from the target platform, not this Git repository.
- Container images are pinned; floating tags such as `latest` are not permitted.
- Higher-environment changes require pull-request review.
- A product/environment mutex prevents overlapping deployments of the same product.
- Checksums are verified before deployment operations begin.

## Installing the local prototype

Requirements are Docker Desktop Kubernetes, Argo Workflows in the `argo` namespace, AWS CLI v2, `kubectl`, and AWS credentials that can read the artifact prefix. The deployment repository is public in this prototype, so the reconciler does not require a Git token.

Check the active identities first:

```bash
kubectl config current-context
aws sts get-caller-identity
```

Install or update everything idempotently:

```bash
bash ./installation/install-local-argo.sh
```

The installer asks before changing the active cluster, exports the current AWS CLI session into the `data-product-s3-reader` Kubernetes Secret, and applies all templates, RBAC, service accounts, and the reconciliation CronWorkflow. Credentials are neither printed nor written to the repository. If the AWS session is temporary, rerun the installer after refreshing it. Options include `--profile <name>`, `--region <region>`, `--yes`, and `--skip-aws-secret`.

## Installing the orchestration resources manually

The checked-in resources can be parsed without changing the cluster:

```bash
kubectl create --dry-run=client --validate=false \
  -f argo/templates \
  -f argo/workflow-template.yml \
  -f argo/reconciler.yml \
  -o name
```

After external image references, Git access, artifact access, and service accounts have been configured for the target platform:

```bash
kubectl apply -f argo/templates/
kubectl apply -f argo/workflow-template.yml
kubectl apply -f argo/reconciler.yml
```

Applying these resources installs orchestration only. It must not implicitly create or build the independently owned deployment jobs.
