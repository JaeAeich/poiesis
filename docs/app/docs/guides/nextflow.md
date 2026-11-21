---
description: Run Nextflow on Poiesis with the nf-ga4gh plugin - config, API key, S3 work directory and two complete example workflows.
---

# Nextflow end to end

[Nextflow](https://www.nextflow.io/) can dispatch process tasks through
a TES backend via the
[`nf-ga4gh`](https://github.com/nextflow-io/nf-ga4gh) plugin. Pointed
at Poiesis, each process becomes a TaskPod on Kubernetes.

This page was written against Nextflow `25.04.2`; authentication was
checked with `25.10.4` (`nf-ga4gh` 1.5.0).

## Minimal config

```groovy
plugins {
  id 'nf-ga4gh'
}

process.executor = 'tes'
tes.endpoint = 'http://localhost:8000/ga4gh/tes'
```

The plugin appends `/v1` to the endpoint, so point it at
`/ga4gh/tes` rather than `/ga4gh/tes/v1`.

With auth on (the default), add an [API key](../concepts/api-keys.md):

```groovy
tes.oauthToken = 'poi_k7H2pQ…'
```

An access token would expire during the run; see
[Workflow engines](./workflow-engines.md#nextflow).

## With S3 staging

Workflows that pass files between processes need an object store, since
the TaskPod can't see your local filesystem. The dev stack runs an
S3 store (SeaweedFS) in-cluster:

```groovy
plugins {
  id 'nf-ga4gh'
}

workDir = 's3://poiesis-test/nextflow'

aws {
  accessKey = 'admin'
  secretKey = 'password'
  client {
    endpoint = 'http://localhost:9000'
    s3PathStyleAccess = true
  }
}

process.executor = 'tes'
tes.endpoint = 'http://localhost:8000/ga4gh/tes'
```

Create the `workDir` bucket once before running anything. The
[Quickstart](../start/quickstart.md#s3-inputs-and-outputs)
shows how.

Recent Nextflow versions send the AWS SDK's default checksums, which
the dev store accepts. Older S3-compatible stores (SeaweedFS 3.x, for
one) reject them with `Content input stream does not support
mark/reset`; run Nextflow with `AWS_REQUEST_CHECKSUM_CALCULATION=when_required`
for those.

## A trivial workflow

`main.nf`:

```groovy
process SAY_HI {
  container 'ubuntu:latest'
  tag "Greeting ${person}"

  input:
  val person

  output:
  stdout

  script:
  """
  echo "Hello ${person} from the TES executor!"
  """
}

workflow {
  Channel.of('Alice', 'Bob', 'Charlie')
    | SAY_HI
    | view { "Received: $it" }
}
```

Port-forward Poiesis and the S3 store, then:

```bash
kubectl -n po port-forward svc/poiesis-api 8000:8000 &
kubectl -n deps port-forward svc/s3 9000:9000 &
nextflow run main.nf
```

Expected output:

```text
executor >  tes [http://localhost:8000/ga4gh/tes] (3)
[xx/xxxxxx] SAY_HI (Greeting Bob) | 3 of 3 ✔
Received: Hello Alice from the TES executor!
Received: Hello Bob from the TES executor!
Received: Hello Charlie from the TES executor!
```

## A workflow with inputs

Upload a file and reference it via `s3://`:

```bash
echo -e "Alice\nBob\nCharlie" > names.txt
AWS_ACCESS_KEY_ID=admin AWS_SECRET_ACCESS_KEY=password AWS_REGION=us-east-1 \
  aws --endpoint-url http://localhost:9000 \
  s3 cp ./names.txt s3://poiesis-test/nextflow/inputs/names.txt
```

```groovy
params.names_file = 's3://poiesis-test/nextflow/inputs/names.txt'

process SplitNames {
  container 'ubuntu:latest'

  input:
  path names_txt

  output:
  stdout

  script:
  """
  cat ${names_txt}
  """
}

process GreetName {
  container 'ubuntu:latest'

  input:
  val name

  output:
  stdout

  script:
  """
  echo "Greetings from ${name}, from TES executor."
  """
}

workflow {
  Channel.fromPath(params.names_file)
    | SplitNames
    | splitText
    | GreetName
}
```

Submit:

```bash
nextflow run main.nf
```
