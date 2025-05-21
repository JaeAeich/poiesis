# Nextflow with Poiesis as Backend

[Nextflow](https://www.nextflow.io/) is a workflow management system designed
for running scientific data analysis pipelines.

Most importantly for our case:
[Nextflow supports GA4GH TES (Task Execution Service)](https://github.com/nextflow-io/nf-ga4gh)
as an execution backend. This means you can write workflows in Nextflow and
execute individual tasks using `Poiesis` as the TES backend—on Kubernetes.

This guide walks you through running a simple workflow using `Nextflow` with
`Poiesis`.

:::info 🧬 Nextflow Version
This guide was tested with:

```bash
Nextflow version 25.04.2 build 5947
```

Things might break or behave differently in other versions.
:::

## ⚙️ Configuring Nextflow to Use Poiesis

Nextflow supports TES backends via the
[`nf-ga4gh`](https://github.com/nextflow-io/nf-ga4gh) plugin.

Before we begin, make sure you’ve deployed `Poiesis` with `MinIO` (or configured
it to use external object storage). You can follow our [deployment guide here](/docs/app/docs/deploy/deploying-poiesis.md#step-2-add-object-storage-minio).

Here’s a minimal `nextflow.config` to connect with Poiesis:

```groovy
plugins {
  id 'nf-ga4gh'
}

process.executor = 'tes'
tes.endpoint = 'http://localhost:8000/ga4gh/tes'
tes.oauthToken = 'asdf'
```

:::info 🔐 Auth & Endpoints

- No need to add `/v1` to the endpoint; the plugin does that automagically.
- If your Poiesis deployment uses Keycloak, you’ll need a valid OAuth token here.
:::

## 🪣 Configuring S3/MinIO for Nextflow

Since Poiesis executes tasks remotely, your local files aren't directly
accessible once a task is launched. This means Nextflow needs to know how to
stash and fetch data via S3.

Let’s update the config to include AWS (S3) settings:

```groovy
plugins {
  id 'nf-ga4gh'
}

workDir = 's3://poiesis/nextflow'

aws {
  accessKey = 'minioUser123'
  secretKey = 'minioPassword123'
  client {
    endpoint = 'http://localhost:9000'
    s3PathStyleAccess = true
  }
}

process.executor = 'tes'
tes.endpoint = 'http://localhost:8000/ga4gh/tes'
tes.oauthToken = 'asdf'
```

:::info 🪣 Bucket Basics
If you're using the built-in MinIO from Poiesis, it creates a default bucket
named `poiesis`.

If you're using an external MinIO/S3 setup, make sure your `workDir` bucket
exists beforehand.
:::

## ✨ Running a Workflow – `SAY_HI`

Let’s start with a basic workflow called `SAY_HI`. Create a file named `main.nf`:

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
  names_ch = Channel.of('Alice', 'Bob', 'Charlie')
  greetings_ch = SAY_HI(names_ch)
  greetings_ch.view { "Received: $it" }
}
```

Run it:

```bash
nextflow run main.nf
```

🎉 Boom! You just got a hey from `Poiesis`:

```bash
N E X T F L O W  ~  version 25.04.2
Launching `main.nf` [irreverent_heyrovsky] DSL2 - revision: 20fa9be87e

executor >  tes [http://localhost:8000/ga4gh/tes] (3)
[a8/cfbbc9] SAY_HI (Greeting Bob)     | 3 of 3 ✔
Received: Hello Alice from the TES executor!
Received: Hello Charlie from the TES executor!
Received: Hello Bob from the TES executor!
```

## 📂 Workflow with Inputs from Object Storage

Let’s kick it up a notch. Suppose you’ve got a list of names stored in MinIO.
Here’s how to feed it into a workflow.

1. Create a file named `names.txt`:

    ```bash
    echo -e "Alice\nBob\nCharlie" > names.txt
    ```

2. Upload it to MinIO:

    ```bash
    mc cp ./names.txt minio/poiesis/nextflow/inputs/names.txt
    ```

3. Create a new workflow:

    ```groovy
    params.names_file = 's3://poiesis/nextflow/inputs/names.txt'

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
        names_file_ch = Channel.fromPath(params.names_file)

        name_lines_ch = SplitNames(names_file_ch)
                            .splitText()

        GreetName(name_lines_ch)
    }
    ```

4. Run it:

```bash
nextflow run main.nf
```

🎊 Voilà!

```bash
N E X T F L O W  ~  version 25.04.2
Launching `main.nf` [stoic_leibniz] DSL2 - revision: 8d92889497

executor >  tes [http://localhost:8000/ga4gh/tes] (5)
[61/850ead] SplitNames (1) | 1 of 1 ✔
[cb/f4c456] GreetName (2)  | 4 of 4 ✔
```
