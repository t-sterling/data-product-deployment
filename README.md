# Data-product deployment

This is the deployment-team-owned GitOps repository. It must be published as an independent repository; its temporary nesting beside the prototype source is only for local bootstrapping.

`environments/<environment>/products/<product>.yml` is desired state. Every artifact is pinned by S3 URI, ZIP SHA-256, source commit, and source-content digest. There is no `latest`. DEV accepts `candidate` or `release`; every other environment accepts only `release`.

The source repository updates DEV directly after publishing a candidate. Feature pushes therefore converge automatically to shared DEV (last successful push for a product wins). A merge is released only when its content digest matches the candidate currently recorded in DEV. Promotion to a higher environment is a PR that copies or updates the same released artifact coordinates in that environment directory.

## Bootstrap

1. Create a remote repository and push this directory as its own Git repository.
2. Replace `REPLACE_WITH_ORG` and `REPLACE_WITH_DEPLOYER_ROLE_ARN` in `argo/*.yml`.
3. Let `build-images.yml` publish the two images to GHCR, then make them readable by the cluster.
4. Give `data-product-deployer` read-only access to the artifact S3 prefix (IRSA is shown; use the local cluster's AWS credential mechanism for the prototype).
5. For a private Git repository, create the optional token secret:

   ```bash
   kubectl -n argo create secret generic deployment-repository-credentials --from-literal=token=<fine-grained-read-token>
   ```

6. Install the resources:

   ```bash
   kubectl apply -f argo/templates/
   kubectl apply -f argo/workflow-template.yml
   kubectl apply -f argo/reconciler.yml
   ```

The eight reference templates under `argo/templates/` were normalized from the live templates found in the local `argo` namespace. The main workflow now calls all of them through `templateRef`. Their component commands intentionally remain skeleton adapters. Artifact fetching, checksum verification, safe extraction, manifest normalization, desired-state validation, deduplication, and workflow submission are implemented.
