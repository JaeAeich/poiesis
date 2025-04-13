# Command Line Interface

The CLI for `Poiesis` extends beyond simple endpoint of the API. Using
[rich-click](https://github.com/ewels/rich-click) to provide a rich
experience. The CLI has a user friendly and "obvious" implementation of
subcommands.

::: info CLI docs
Instead of documenting each command the CLI has a help message that is displayed
when the user runs `poiesis <command> --help`.
:::

## Core services

Since each service has a single responsibility. The CLI for each service is also
single main command, ie `run`.

Check the usage of the run command.

```bash
poiesis <service-name> run --help
```

Eg.

```bash
poiesis texam run --help
```

## TES

The CLI experience of the TES service has been designed to be as simple as
possible.

```bash
poiesis task <create|list|get|cancel> --help
```

Their `--help` will give better information on the subcommands. The command
takes all the same inputs as the API, namely all the request parameter for the
endpoint and `authentication bearer token`.

::: info Auth
Read more about auth options on [Auth page](./auth).
:::
